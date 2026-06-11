from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TASK_AUDIT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "task_audit.sqlite3"
DEFAULT_AUDIT_WINDOW_HOURS = 24
DEFAULT_AUDIT_RETENTION_DAYS = 30
DEFAULT_AUDIT_MAX_EVENTS = 20_000


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@contextmanager
def _connect():
    TASK_AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(TASK_AUDIT_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_kind TEXT NOT NULL,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            message TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_job ON task_events(job_kind, job_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_created ON task_events(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_user ON task_events(user_id, id)")


def record_task_event(
    *,
    job_kind: str,
    job_id: str,
    event_type: str,
    status: str,
    stage: str,
    message: str,
    user_id: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    safe_payload = payload or {}
    try:
        payload_json = json.dumps(safe_payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload_json = json.dumps({"serialization_error": True}, ensure_ascii=False)
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO task_events (
                    job_kind, job_id, event_type, status, stage, message,
                    user_id, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(job_kind),
                    str(job_id),
                    str(event_type),
                    str(status),
                    str(stage),
                    str(message),
                    str(user_id or ""),
                    payload_json,
                    _now_text(),
                ),
            )
    except sqlite3.Error:
        return


def list_task_events(
    *,
    job_kind: str | None = None,
    job_id: str | None = None,
    user_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if job_kind:
        clauses.append("job_kind = ?")
        params.append(job_kind)
    if job_id:
        clauses.append("job_id = ?")
        params.append(job_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(500, int(limit)))
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, job_kind, job_id, event_type, status, stage, message,
                   user_id, payload_json, created_at
            FROM task_events
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            [*params, safe_limit],
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        output.append(
            {
                "id": row["id"],
                "job_kind": row["job_kind"],
                "job_id": row["job_id"],
                "event_type": row["event_type"],
                "status": row["status"],
                "stage": row["stage"],
                "message": row["message"],
                "user_id": row["user_id"],
                "payload": payload if isinstance(payload, dict) else {},
                "created_at": row["created_at"],
            }
        )
    return output


def list_account_security_events(user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(100, int(limit)))
    allowed_kinds = ("account_security", "account_export", "account_delete")
    placeholders = ",".join("?" for _item in allowed_kinds)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, job_kind, job_id, event_type, status, stage, message,
                   user_id, payload_json, created_at
            FROM task_events
            WHERE user_id = ? AND job_kind IN ({placeholders})
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, *allowed_kinds, safe_limit),
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        output.append(
            {
                "id": row["id"],
                "job_kind": row["job_kind"],
                "job_id": row["job_id"],
                "event_type": row["event_type"],
                "status": row["status"],
                "stage": row["stage"],
                "message": row["message"],
                "user_id": row["user_id"],
                "payload": payload if isinstance(payload, dict) else {},
                "created_at": row["created_at"],
            }
        )
    return output


def delete_task_events_for_user(user_id: str) -> int:
    if not str(user_id or "").strip():
        return 0
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM task_events WHERE user_id = ?", (str(user_id),))
    return max(0, int(cursor.rowcount or 0))


def task_audit_summary() -> dict[str, Any]:
    with _connect() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        recent_errors = int(
            conn.execute(
                "SELECT COUNT(*) FROM task_events WHERE status = 'error' AND id > ?",
                (max(0, total - 200),),
            ).fetchone()[0]
        )
        latest = conn.execute(
            """
            SELECT job_kind, job_id, status, stage, message, created_at
            FROM task_events
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return {
        "total_events": total,
        "recent_error_events": recent_errors,
        "latest_event": dict(latest) if latest else None,
    }


def task_audit_metrics(window_hours: int = DEFAULT_AUDIT_WINDOW_HOURS) -> dict[str, Any]:
    safe_window = max(1, min(24 * 30, int(window_hours or DEFAULT_AUDIT_WINDOW_HOURS)))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=safe_window)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        total_events = int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        window_total = int(
            conn.execute("SELECT COUNT(*) FROM task_events WHERE created_at >= ?", (cutoff,)).fetchone()[0]
        )
        rows = conn.execute(
            """
            SELECT job_kind, status, COUNT(*) AS count
            FROM task_events
            WHERE created_at >= ?
            GROUP BY job_kind, status
            ORDER BY job_kind ASC, status ASC
            """,
            (cutoff,),
        ).fetchall()
        latest_rows = conn.execute(
            """
            SELECT job_kind, job_id, status, stage, message, created_at
            FROM task_events
            WHERE id IN (
                SELECT MAX(id)
                FROM task_events
                GROUP BY job_kind
            )
            ORDER BY job_kind ASC
            """
        ).fetchall()

    by_kind: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_kind = str(row["job_kind"])
        status = str(row["status"] or "unknown")
        count = int(row["count"] or 0)
        stats = by_kind.setdefault(
            job_kind,
            {
                "job_kind": job_kind,
                "total": 0,
                "success": 0,
                "error": 0,
                "queued": 0,
                "running": 0,
                "other": 0,
                "error_rate": 0.0,
                "latest_event": None,
            },
        )
        stats["total"] += count
        if status in {"success", "error", "queued", "running"}:
            stats[status] += count
        else:
            stats["other"] += count

    for row in latest_rows:
        job_kind = str(row["job_kind"])
        stats = by_kind.setdefault(
            job_kind,
            {
                "job_kind": job_kind,
                "total": 0,
                "success": 0,
                "error": 0,
                "queued": 0,
                "running": 0,
                "other": 0,
                "error_rate": 0.0,
                "latest_event": None,
            },
        )
        stats["latest_event"] = {
            "job_id": row["job_id"],
            "status": row["status"],
            "stage": row["stage"],
            "message": row["message"],
            "created_at": row["created_at"],
        }

    for stats in by_kind.values():
        stats["error_rate"] = round(stats["error"] / max(1, stats["total"]), 3)

    return {
        "window_hours": safe_window,
        "total_events": total_events,
        "window_events": window_total,
        "by_kind": sorted(by_kind.values(), key=lambda item: item["job_kind"]),
        "retention": {
            "retention_days": _env_int("TASK_AUDIT_RETENTION_DAYS", DEFAULT_AUDIT_RETENTION_DAYS, minimum=1, maximum=3650),
            "max_events": _env_int("TASK_AUDIT_MAX_EVENTS", DEFAULT_AUDIT_MAX_EVENTS, minimum=100, maximum=2_000_000),
        },
    }


def prune_task_audit_events(
    *,
    retention_days: int | None = None,
    max_events: int | None = None,
) -> dict[str, int]:
    default_days = _env_int("TASK_AUDIT_RETENTION_DAYS", DEFAULT_AUDIT_RETENTION_DAYS, minimum=1, maximum=3650)
    default_max = _env_int("TASK_AUDIT_MAX_EVENTS", DEFAULT_AUDIT_MAX_EVENTS, minimum=100, maximum=2_000_000)
    safe_days = max(1, min(3650, int(retention_days if retention_days is not None else default_days)))
    safe_max = max(1, min(2_000_000, int(max_events if max_events is not None else default_max)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=safe_days)).strftime("%Y-%m-%d %H:%M:%S")
    with _connect() as conn:
        by_age = conn.execute("DELETE FROM task_events WHERE created_at < ?", (cutoff,)).rowcount
        total = int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
        by_count = 0
        if total > safe_max:
            threshold_row = conn.execute(
                """
                SELECT id
                FROM task_events
                ORDER BY id DESC
                LIMIT 1 OFFSET ?
                """,
                (safe_max - 1,),
            ).fetchone()
            if threshold_row:
                by_count = conn.execute("DELETE FROM task_events WHERE id < ?", (threshold_row["id"],)).rowcount
        remaining = int(conn.execute("SELECT COUNT(*) FROM task_events").fetchone()[0])
    return {
        "deleted_by_age": max(0, int(by_age or 0)),
        "deleted_by_count": max(0, int(by_count or 0)),
        "remaining_events": remaining,
    }
