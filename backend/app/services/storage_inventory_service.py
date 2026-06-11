from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services import (
    analysis_report_service,
    auth_service,
    daily_report_store,
    portfolio_watchlist_store,
    task_audit_service,
)
from app.services.sim_engine import sim_engine
from app.services import sim_engine as sim_engine_service

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() and path.is_file() else 0


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(DATA_DIR.parent.parent.parent))
    except ValueError:
        return str(path)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def _sqlite_inventory(name: str, path: Path, tables: list[str]) -> dict[str, Any]:
    inventory: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": _file_size(path),
        "tables": {table: 0 for table in tables},
    }
    if not path.exists():
        return inventory

    try:
        uri = f"file:{path}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            for table in tables:
                if not _table_exists(conn, table):
                    continue
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                inventory["tables"][table] = int(count or 0)
    except sqlite3.Error as exc:
        inventory["error"] = str(exc)
    return inventory


def _daily_report_inventory(path: Path) -> dict[str, Any]:
    user_dirs = [item for item in path.iterdir() if item.is_dir()] if path.exists() else []
    report_files = [
        item
        for item in path.rglob("*.json")
        if item.is_file() and item.name != "index.json"
    ] if path.exists() else []
    index_files = [
        item
        for item in path.rglob("index.json")
        if item.is_file()
    ] if path.exists() else []
    return {
        "name": "daily_reports",
        "path": str(path),
        "exists": path.exists(),
        "user_dirs": len(user_dirs),
        "report_files": len(report_files),
        "index_files": len(index_files),
        "size_bytes": sum(_file_size(item) for item in report_files + index_files),
    }


def _json_file_inventory(name: str, path: Path) -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": _file_size(path),
    }


def _invalid_json_backups(path: Path | None = None) -> list[Path]:
    resolved_path = path or DATA_DIR
    if not resolved_path.exists():
        return []
    return sorted(item for item in resolved_path.glob("*.invalid.*.bak") if item.is_file())


def _invalid_json_backup_inventory(path: Path | None = None) -> dict[str, Any]:
    resolved_path = path or DATA_DIR
    files = _invalid_json_backups(resolved_path)
    return {
        "name": "invalid_json_backups",
        "path": str(resolved_path),
        "exists": bool(files),
        "file_count": len(files),
        "size_bytes": sum(_file_size(item) for item in files),
        "files": [
            {
                "name": item.name,
                "path": str(item),
                "display_path": _display_path(item),
                "size_bytes": _file_size(item),
            }
            for item in files[:100]
        ],
    }


def _backup_item(
    *,
    name: str,
    kind: str,
    path: Path,
    backup_required: bool,
    note: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "path": str(path),
        "display_path": _display_path(path),
        "exists": path.exists(),
        "size_bytes": _file_size(path),
        "backup_required": backup_required,
        "note": note,
    }


def _sqlite_backup_items(name: str, path: Path, note: str) -> list[dict[str, Any]]:
    items = [
        _backup_item(
            name=name,
            kind="sqlite",
            path=path,
            backup_required=True,
            note=note,
        )
    ]
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            items.append(
                _backup_item(
                    name=f"{name}{suffix}",
                    kind="sqlite_sidecar",
                    path=sidecar,
                    backup_required=True,
                    note="SQLite 事务日志 sidecar，在线备份时需要与主库一起保存。",
                )
            )
    return items


def _directory_backup_items(name: str, path: Path, note: str, *, max_files: int = 5000) -> list[dict[str, Any]]:
    if not path.exists():
        return [
            _backup_item(
                name=name,
                kind="directory",
                path=path,
                backup_required=True,
                note=note,
            )
        ]
    files = [item for item in path.rglob("*") if item.is_file()]
    items = [
        _backup_item(
            name=name,
            kind="directory",
            path=path,
            backup_required=True,
            note=f"{note} 当前包含 {len(files)} 个文件。",
        )
    ]
    for item in sorted(files)[:max_files]:
        items.append(
            _backup_item(
                name=f"{name}:{item.relative_to(path)}",
                kind="directory_file",
                path=item,
                backup_required=True,
                note="目录内运行时文件。",
            )
        )
    if len(files) > max_files:
        items.append(
            {
                "name": f"{name}:truncated",
                "kind": "truncated",
                "path": str(path),
                "display_path": _display_path(path),
                "exists": True,
                "size_bytes": 0,
                "backup_required": True,
                "note": f"目录文件超过 {max_files} 个，清单已截断；备份时仍需保存完整目录。",
            }
        )
    return items


def _invalid_json_backup_items() -> list[dict[str, Any]]:
    return [
        _backup_item(
            name=f"invalid_json_backup:{path.name}",
            kind="runtime_json_invalid_backup",
            path=path,
            backup_required=True,
            note="运行态 JSON 损坏隔离备份；用于排障或人工恢复。",
        )
        for path in _invalid_json_backups()
    ]


def prune_invalid_json_backups(retention_days: int = 30) -> dict[str, Any]:
    safe_days = max(1, min(3650, int(retention_days or 30)))
    cutoff = datetime.now(timezone.utc) - timedelta(days=safe_days)
    deleted_files: list[dict[str, Any]] = []
    deleted_bytes = 0

    for path in _invalid_json_backups():
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if modified_at >= cutoff:
            continue
        size = _file_size(path)
        try:
            path.unlink()
        except OSError:
            continue
        deleted_files.append(
            {
                "name": path.name,
                "display_path": _display_path(path),
                "size_bytes": size,
                "modified_at": modified_at.isoformat(),
            }
        )
        deleted_bytes += size

    remaining = _invalid_json_backup_inventory()
    return {
        "deleted_files": len(deleted_files),
        "deleted_bytes": deleted_bytes,
        "remaining_files": remaining["file_count"],
        "remaining_bytes": remaining["size_bytes"],
        "retention_days": safe_days,
        "deleted": deleted_files[:50],
    }


def build_backup_manifest() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    items.extend(_sqlite_backup_items("auth", auth_service.AUTH_DB_PATH, "账号、登录会话和收藏数据。"))
    items.extend(
        _sqlite_backup_items(
            "analysis_reports",
            analysis_report_service.REPORT_DB_PATH,
            "用户保存的 Agent 分析报告。",
        )
    )
    items.extend(
        _sqlite_backup_items(
            "portfolio",
            portfolio_watchlist_store.PORTFOLIO_DB_PATH,
            "用户自选资产、持仓和迁移元数据。",
        )
    )
    items.extend(_sqlite_backup_items("task_audit", task_audit_service.TASK_AUDIT_DB_PATH, "任务审计和账号安全事件。"))
    items.extend(
        _directory_backup_items(
            "daily_reports",
            daily_report_store.DAILY_REPORTS_DIR,
            "用户资产日报 JSON 文件目录。",
        )
    )
    for name in ("sim_accounts.json", "portfolio_state.json", "portfolio_refresh_jobs.json", "update_jobs.json"):
        path = DATA_DIR / name
        items.append(
            _backup_item(
                name=name,
                kind="json",
                path=path,
                backup_required=path.exists(),
                note="兼容期运行态 JSON 文件；存在时建议随备份保存。",
            )
        )
    items.extend(_invalid_json_backup_items())

    existing_required = [item for item in items if item.get("backup_required") and item.get("exists")]
    missing_expected = [
        {"name": item["name"], "display_path": item["display_path"]}
        for item in items
        if item.get("backup_required") and not item.get("exists") and item.get("kind") in {"sqlite", "directory"}
    ]
    sidecars = [item for item in items if item.get("kind") == "sqlite_sidecar"]
    warnings: list[str] = []
    if missing_expected:
        warnings.append("部分运行时数据尚未创建；首次使用对应功能后会自动生成。")
    if sidecars:
        warnings.append("检测到 SQLite WAL/SHM sidecar；在线备份时需要同时保存主库和 sidecar，或先停写再备份。")
    if any(item.get("kind") == "runtime_json_invalid_backup" for item in items):
        warnings.append("检测到运行态 JSON 损坏隔离备份；建议排查来源，并在确认不再需要后手动清理。")
    if not existing_required:
        warnings.append("当前未发现已创建的持久化运行时数据，可能仍处于全新环境。")

    return {
        "generated_at": _now_iso(),
        "root": str(DATA_DIR),
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in existing_required),
        "target_count": len(existing_required),
        "items": items,
        "missing_expected_targets": missing_expected,
        "warnings": warnings,
    }


def build_storage_inventory() -> dict[str, Any]:
    invalid_json_backup_inventory = _invalid_json_backup_inventory()
    datastores = [
        _sqlite_inventory(
            "auth",
            auth_service.AUTH_DB_PATH,
            ["users", "sessions", "favorites"],
        ),
        _sqlite_inventory(
            "analysis_reports",
            analysis_report_service.REPORT_DB_PATH,
            ["analysis_reports"],
        ),
        _sqlite_inventory(
            "portfolio",
            portfolio_watchlist_store.PORTFOLIO_DB_PATH,
            ["portfolio_watchlist", "portfolio_metadata"],
        ),
        _sqlite_inventory(
            "task_audit",
            task_audit_service.TASK_AUDIT_DB_PATH,
            ["task_events"],
        ),
        _daily_report_inventory(daily_report_store.DAILY_REPORTS_DIR),
        _json_file_inventory("sim_accounts", sim_engine_service.SIM_ACCOUNTS_PATH),
        invalid_json_backup_inventory,
    ]
    total_size = sum(int(item.get("size_bytes") or 0) for item in datastores)
    sqlite_errors = [
        {"name": item["name"], "error": item["error"]}
        for item in datastores
        if item.get("error")
    ]
    return {
        "generated_at": _now_iso(),
        "total_size_bytes": total_size,
        "datastores": datastores,
        "sqlite_errors": sqlite_errors,
        "runtime": {
            "sim_accounts": sim_engine.account_count(),
            "invalid_json_backups": invalid_json_backup_inventory["file_count"],
        },
    }
