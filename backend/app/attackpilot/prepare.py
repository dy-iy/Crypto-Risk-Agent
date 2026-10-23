"""Prepare packaged runtime assets without starting any service.

Usage: python -m app.attackpilot.prepare --archive ARCHIVE --credentials --compilers --export-seed --import-seed
       python -m app.attackpilot.prepare --compiler-version v0.8.23+commit.f704f362
"""
import argparse
import ast
from collections import defaultdict
from datetime import datetime, timedelta
import io
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
import zipfile

from .demo_catalog import RETIRED_DEMO_TASK_IDS

PACKAGE = Path(__file__).resolve().parent
BACKEND = PACKAGE.parents[1]
SOLC_SOURCES = (
    "https://binaries.soliditylang.org/linux-amd64/",
    "https://raw.githubusercontent.com/ethereum/solc-bin/gh-pages/linux-amd64/",
)
SOLC_VERSION = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\+commit\.([0-9a-f]{8}))?")
SOLC_MAX_BYTES = 64 * 1024 * 1024


def _download_compiler_asset(url, output, max_bytes):
    """Bound both bytes and elapsed time; all URLs originate in the official mirrors."""
    deadline = time.monotonic() + 120
    request = Request(url, headers={"User-Agent": "AttackPilot-compiler-prepare/1"})
    with urlopen(request, timeout=30) as response:
        if not any(response.geturl().startswith(source) for source in SOLC_SOURCES):
            raise ValueError("Compiler download redirected outside the official mirrors")
        size = response.headers.get("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > max_bytes):
            raise ValueError("Compiler download exceeds the size limit")
        total = 0
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Compiler download exceeded 120 seconds")
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("Compiler download exceeds the size limit")
            output.write(chunk)


def _compiler_build(manifest, requested_version):
    match = SOLC_VERSION.fullmatch(requested_version)
    if match is None:
        raise ValueError("Use a stable Solidity version such as 0.8.23 or v0.8.23+commit.f704f362")
    version = ".".join(match.group(1, 2, 3))
    commit = match[4]
    release_path = manifest.get("releases", {}).get(version)
    candidates = []
    for build in manifest.get("builds", []):
        if build.get("version") != version or build.get("prerelease"):
            continue
        long_version = build.get("longVersion", "")
        exact = re.fullmatch(re.escape(version) + r"\+commit\.([0-9a-f]{8})", long_version)
        if not exact or (commit and exact[1] != commit):
            continue
        path = build.get("path")
        if not commit and path != release_path:
            continue
        if path != f"solc-linux-amd64-v{long_version}" or build.get("build") != f"commit.{exact[1]}":
            raise ValueError("Official compiler manifest has inconsistent build metadata")
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", build.get("sha256", "")):
            raise ValueError("Official compiler manifest is missing a valid SHA256 checksum")
        candidates.append(build)
    if len(candidates) != 1:
        raise ValueError(f"No unique official stable compiler matches {requested_version}")
    return candidates[0]


def _compiler_sha256(path):
    if path.stat().st_size > SOLC_MAX_BYTES:
        raise ValueError("Compiler file exceeds the size limit")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_compiler_version(path, long_version):
    result = subprocess.run([str(path), "--version"], check=True, capture_output=True,
                            text=True, timeout=15)
    match = re.search(r"^Version:\s+(\S+)", result.stdout, flags=re.MULTILINE)
    if not match or match[1] != f"{long_version}.Linux.g++":
        raise ValueError(f"Compiler executable did not report expected version {long_version}")


def install_compiler(requested_version, destination):
    """Explicit, repeatable installation; never called automatically by task execution."""
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise ValueError("Compiler installation currently supports Linux x86_64 only")
    if not SOLC_VERSION.fullmatch(requested_version):
        raise ValueError("Use a stable Solidity version such as 0.8.23 or v0.8.23+commit.f704f362")
    manifest = None
    failures = []
    for source in SOLC_SOURCES:
        try:
            content = io.BytesIO()
            _download_compiler_asset(source + "list.json", content, 4 * 1024 * 1024)
            manifest = json.loads(content.getvalue())
            if not isinstance(manifest, dict) or not isinstance(manifest.get("builds"), list):
                raise ValueError("Invalid official compiler manifest")
            break
        except (OSError, URLError, ValueError) as exc:
            failures.append(f"{source}: {exc}")
            manifest = None
    if manifest is None:
        raise RuntimeError("Unable to fetch official compiler manifest: " + "; ".join(failures))
    build = _compiler_build(manifest, requested_version)
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / build["path"]
    expected_sha256 = build["sha256"][2:].lower()
    if target.is_file() and _compiler_sha256(target) == expected_sha256:
        target.chmod(0o755)
        _verify_compiler_version(target, build["longVersion"])
        return {"path": str(target), "version": build["longVersion"], "sha256": expected_sha256, "installed": False}
    failures = []
    for source in SOLC_SOURCES:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".solc-download-", dir=destination, delete=False) as output:
                temporary = Path(output.name)
                _download_compiler_asset(source + build["path"], output, SOLC_MAX_BYTES)
                output.flush()
                os.fsync(output.fileno())
            if _compiler_sha256(temporary) != expected_sha256:
                raise ValueError("Compiler SHA256 checksum does not match the official manifest")
            temporary.chmod(0o755)
            _verify_compiler_version(temporary, build["longVersion"])
            os.replace(temporary, target)
            return {"path": str(target), "version": build["longVersion"], "sha256": expected_sha256, "installed": True}
        except (OSError, URLError, ValueError, subprocess.SubprocessError) as exc:
            failures.append(f"{source}: {exc}")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise RuntimeError("Unable to install verified compiler: " + "; ".join(failures))

def archive_member(archive, suffix):
    return next(info for info in archive.infolist() if info.filename.endswith(suffix))

def migrate_credentials(archive):
    source = archive.read(archive_member(archive, "/backend/settings.py")).decode("utf-8-sig")
    mapping = {"JSONRPCS": "ATTACKPILOT_RPC_URLS", "SCAN_APIKEYS": "ATTACKPILOT_SCAN_URLS", "WEB3_PROVIDER": "ATTACKPILOT_WEB3_PROVIDER", "TENDERLY_API_KEY": "ATTACKPILOT_TENDERLY_API_KEY", "ACCOUNT_SLUG": "ATTACKPILOT_TENDERLY_ACCOUNT", "PROJECT_SLUG": "ATTACKPILOT_TENDERLY_PROJECT"}
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in mapping:
            values[mapping[node.targets[0].id]] = ast.literal_eval(node.value)
    target = BACKEND / ".env"
    old = target.read_text() if target.exists() else ""
    existing = {line.split("=", 1)[0].strip() for line in old.splitlines() if "=" in line and not line.lstrip().startswith("#")}
    lines = []
    for key, value in values.items():
        if key not in existing:
            encoded = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
            lines.append(f"{key}='" + encoded.replace("'", "\\'") + "'")
    if "DEEPSEEK_API_KEY" not in existing:
        lines.append("DEEPSEEK_API_KEY=")
    if lines:
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write("\n# AttackPilot imported chain configuration\n" + "\n".join(lines) + "\n")
        target.chmod(0o600)

def copy_value(value):
    if value == r"\N": return None
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
    return re.sub(r"\\([0-7]{1,3}|.)", lambda match: chr(int(match[1], 8)) if match[1].isdigit() else escapes.get(match[1], match[1]), value)

def copy_tables(sql):
    tables = defaultdict(list); table = None; columns = []
    for line in sql.splitlines():
        match = re.match(r'COPY public\.(task_runs|task_logs) \((.*?)\) FROM stdin;', line)
        if match:
            table = match[1]; columns = [column.strip().strip('"') for column in match[2].split(",")]
        elif line == r"\.": table = None
        elif table:
            values = line.split("\t")
            if len(values) != len(columns): raise ValueError("Malformed archive COPY row")
            tables[table].append(dict(zip(columns, map(copy_value, values))))
    return tables

def redis_log_values(archive):
    data = archive.read(archive_member(archive, "/deployment/demo-data/attackpilot-redis-data.tar.gz"))
    result = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.endswith(".aof"): continue
            stream = tar.extractfile(member)
            if stream is None: continue
            while header := stream.readline():
                if not header.startswith(b"*"): raise ValueError("Unsupported AOF record")
                args = []
                for _ in range(int(header[1:])):
                    size = stream.readline()
                    if not size.startswith(b"$"): raise ValueError("Unsupported AOF bulk value")
                    args.append(stream.read(int(size[1:]))); stream.read(2)
                command = args[0].upper()
                if command in (b"SET", b"SETEX", b"PSETEX") and args[1].startswith(b"log:"):
                    content = args[2] if command == b"SET" else args[3]
                    result[args[1][4:].decode()] = content.decode("utf-8", errors="replace")
    return result

def export_seed(archive):
    from .privacy import redact
    with tempfile.TemporaryDirectory(prefix="attackpilot-import-") as temp:
        dump = Path(temp) / "source.dump"
        dump.write_bytes(archive.read(archive_member(archive, "/deployment/demo-data/attackpilot-postgres.dump")))
        sql = subprocess.run(["pg_restore", "--data-only", "--no-owner", "--no-privileges", "--file=-", str(dump)], check=True, capture_output=True).stdout.decode("utf-8")
    tables = copy_tables(sql); redis = redis_log_values(archive); logs = defaultdict(list)
    tasks = tables["task_runs"]
    valid_ids = {task["task_id"] for task in tasks}
    # Older logs were tagged by DApp name; associate only when unambiguous.
    by_name = defaultdict(list)
    for task in tasks:
        by_name[task["dapp_name"]].append(task["task_id"])
        task["archived"] = task.get("archived") == "t"
    unmatched = 0
    for log in tables["task_logs"]:
        task_id = log["task_id"]
        if task_id not in valid_ids:
            candidates = by_name.get(task_id, [])
            if len(candidates) != 1:
                timestamp = datetime.fromisoformat(log["timestamp"])
                candidates = [task["task_id"] for task in tasks if task["task_id"] in candidates
                              and task.get("completed_at")
                              and datetime.fromisoformat(task["created_at"]) - timedelta(seconds=2) <= timestamp
                              <= datetime.fromisoformat(task["completed_at"]) + timedelta(seconds=2)]
                if len(candidates) != 1:
                    unmatched += 1; continue
                log["association"] = "unique_case_and_time_window"
            task_id = candidates[0]
        log["task_id"] = task_id
        log["full_content"] = log.get("full_content") or redis.get(log["log_id"]) or log.get("message") or ""
        logs[task_id].append(log)
    # Associate old name-only logs before retiring records, so they cannot move to another run.
    tasks = [task for task in tasks if task["task_id"] not in RETIRED_DEMO_TASK_IDS]
    logs = {task_id: entries for task_id, entries in logs.items() if task_id not in RETIRED_DEMO_TASK_IDS}
    payload = redact({"version": 1, "source": "AttackPilot supplied archive", "tasks": tasks, "logs": logs, "unmatched_logs": unmatched})
    target = PACKAGE / "data/demo-seed.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"tasks": len(tasks), "logs": sum(map(len, logs.values())), "unmatched_logs": unmatched}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--credentials", action="store_true")
    parser.add_argument("--compilers", action="store_true")
    parser.add_argument("--compiler-version", action="append", default=[], metavar="VERSION",
                        help="Install an exact official stable solc version (repeatable; archive not required)")
    parser.add_argument("--export-seed", action="store_true")
    parser.add_argument("--import-seed", action="store_true")
    args = parser.parse_args()
    if args.compiler_version:
        from . import settings
        for version in args.compiler_version:
            try:
                print(json.dumps(install_compiler(version, settings.COMPILER_ROOT)))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                parser.exit(1, f"Compiler installation failed: {exc}\n")
    if args.credentials or args.compilers or args.export_seed:
        if not args.archive: parser.error("--archive is required")
        with zipfile.ZipFile(args.archive) as archive:
            if args.credentials: migrate_credentials(archive)
            from . import settings
            if args.compilers:
                settings.COMPILER_ROOT.mkdir(parents=True, exist_ok=True)
                for member in archive.infolist():
                    if "/backend/compiler/solc-linux-amd64-" in member.filename and not member.is_dir():
                        target = settings.COMPILER_ROOT / Path(member.filename).name
                        if not target.exists():
                            with archive.open(member) as source, target.open("wb") as output:
                                import shutil
                                shutil.copyfileobj(source, output)
                        target.chmod(0o755)
            if args.export_seed: print(json.dumps(export_seed(archive)))
    if args.import_seed:
        from . import store
        seed = json.loads((PACKAGE / "data/demo-seed.json").read_text())
        print(json.dumps(store.import_seed(seed)))
        for task_id, logs in seed.get("logs", {}).items():
            task = store.get_task(task_id)
            if not task or not task["is_demo"]: continue
            grouped = defaultdict(list)
            for log in logs:
                agent = re.sub(r"[^a-zA-Z0-9_-]", "_", log.get("agent") or "Workflow")
                grouped[agent].append(f"{log.get('timestamp', '')}\n{log.get('full_content') or log.get('message') or ''}\n")
            destination = store.task_dir(task_id) / "agent-logs"
            destination.mkdir(parents=True, exist_ok=True)
            for agent, contents in grouped.items():
                (destination / f"{agent}.log").write_text("\n".join(contents))

if __name__ == "__main__": main()
