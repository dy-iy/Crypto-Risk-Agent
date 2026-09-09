"""Prepare packaged runtime assets without starting any service.

Usage: python -m app.attackpilot.prepare --archive ARCHIVE --credentials --compilers --export-seed --import-seed
"""
import argparse
import ast
from collections import defaultdict
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import zipfile

PACKAGE = Path(__file__).resolve().parent
BACKEND = PACKAGE.parents[1]

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
        lines.extend(["DEEPSEEK_API_KEY=", "DEEPSEEK_MODEL=deepseek-v4-pro"])
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
    payload = redact({"version": 1, "source": "AttackPilot supplied archive", "tasks": tasks, "logs": dict(logs), "unmatched_logs": unmatched})
    target = PACKAGE / "data/demo-seed.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"tasks": len(tasks), "logs": sum(map(len, logs.values())), "unmatched_logs": unmatched}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--credentials", action="store_true")
    parser.add_argument("--compilers", action="store_true")
    parser.add_argument("--export-seed", action="store_true")
    parser.add_argument("--import-seed", action="store_true")
    args = parser.parse_args()
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
