"""Durable task/log/event store. Every public read is scoped at the API boundary."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from . import settings

TERMINAL = {"completed", "failed", "cancelled"}

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connection():
    settings.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.DATABASE_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY, owner_id TEXT, is_demo INTEGER NOT NULL DEFAULT 0,
            dapp_name TEXT NOT NULL, status TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, completed_at TEXT, final_report TEXT, result TEXT,
            error TEXT, payload TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL DEFAULT 'live'
        );
        CREATE INDEX IF NOT EXISTS ap_task_owner ON tasks(owner_id, created_at);
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            log_id TEXT NOT NULL, agent TEXT, level TEXT, message_type TEXT,
            message TEXT, full_content TEXT, timestamp TEXT, is_truncated INTEGER,
            UNIQUE(task_id, log_id)
        );
        CREATE INDEX IF NOT EXISTS ap_log_task ON logs(task_id, id);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ap_event_task ON events(task_id, id);
    """)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

def _task(row) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("result", "payload"):
        try:
            result[key] = json.loads(result[key]) if result[key] else None
        except (TypeError, ValueError):
            result[key] = None
    result["is_demo"] = bool(result["is_demo"])
    result["archived"] = bool(result["archived"])
    result["enabled_modules"] = (result.get("payload") or {}).get("enabled_modules", [])
    result["duration"] = None
    if result.get("completed_at"):
        try:
            result["duration"] = max(0, (datetime.fromisoformat(result["completed_at"]) - datetime.fromisoformat(result["created_at"])).total_seconds())
        except (TypeError, ValueError):
            pass
    return result

def public_task(task: dict) -> dict:
    return {key: value for key, value in task.items() if key not in {"owner_id", "payload"}}

def get_task(task_id: str) -> dict | None:
    with connection() as db:
        return _task(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

def can_read(task: dict | None, owner_id: str | None) -> bool:
    return bool(task and (task["is_demo"] or owner_id and task["owner_id"] == owner_id))

def list_tasks(owner_id: str | None, include_archived=False) -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM tasks WHERE (is_demo=1 OR owner_id=?) AND (? OR archived=0) ORDER BY created_at DESC", (owner_id, include_archived)).fetchall()
        return [_task(row) for row in rows]

def _event(db, task_id: str, payload: dict) -> None:
    db.execute("INSERT INTO events(task_id,payload) VALUES (?,?)", (task_id, json.dumps(payload, ensure_ascii=False)))

def create_task(owner_id: str, payload: dict) -> dict:
    task_id = str(uuid.uuid4())
    with connection() as db:
        db.execute("INSERT INTO tasks(task_id,owner_id,dapp_name,status,created_at,payload) VALUES (?,?,?,'pending',?,?)", (task_id, owner_id, payload["name"], now(), json.dumps(payload, ensure_ascii=False)))
        task = _task(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())
        _event(db, task_id, {"type": "TASK_STATUS", **public_task(task)})
    return task

def transition(task_id: str, status: str, *, result=None, error: str | None = None) -> bool:
    if isinstance(result, str):
        result = {"report": result}
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row or row["is_demo"] or row["status"] in TERMINAL:
            return False
        if status == "running" and row["status"] != "pending":
            return False
        report = result if isinstance(result, str) else (result or {}).get("report") if isinstance(result, dict) else None
        db.execute("UPDATE tasks SET status=?,completed_at=?,final_report=?,result=?,error=? WHERE task_id=?", (status, now() if status in TERMINAL else None, report, json.dumps(result, ensure_ascii=False) if result is not None else None, error, task_id))
        task = _task(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())
        _event(db, task_id, {"type": "TASK_FINAL" if status in TERMINAL else "TASK_STATUS", **public_task(task)})
        return True

def append_log(task_id: str, entry: dict) -> None:
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        task = db.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not task or task["status"] in TERMINAL:
            return
        content = str(entry.get("message") or "")
        log_id = entry.get("log_id") or str(uuid.uuid4())
        timestamp = entry.get("timestamp") or now()
        cursor = db.execute("INSERT OR IGNORE INTO logs(task_id,log_id,agent,level,message_type,message,full_content,timestamp,is_truncated) VALUES (?,?,?,?,?,?,?,?,?)", (task_id, log_id, entry.get("agent", "Workflow"), entry.get("level", "info"), entry.get("message_type", "text"), content[:1000], content, timestamp, len(content) > 1000))
        if cursor.rowcount:
            _event(db, task_id, {**entry, "type": "LOG", "task_id": task_id, "log_id": log_id, "persisted_id": cursor.lastrowid, "message": content[:1000], "is_truncated": len(content) > 1000, "timestamp": timestamp})

def log_page(task_id: str, limit=200, before_id=None, after_id=None) -> dict:
    query, args = "SELECT * FROM logs WHERE task_id=?", [task_id]
    if before_id is not None:
        query += " AND id<?"; args.append(before_id)
    if after_id is not None:
        query += " AND id>?"; args.append(after_id)
    query += " ORDER BY id " + ("ASC" if after_id is not None else "DESC") + " LIMIT ?"
    args.append(limit + 1)
    with connection() as db:
        rows = db.execute(query, args).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    if after_id is None:
        rows = list(reversed(rows))
    events = [{**{key: row[key] for key in ("task_id", "log_id", "agent", "level", "message_type", "message", "timestamp")}, "type": "LOG", "persisted_id": row["id"], "is_truncated": bool(row["is_truncated"])} for row in rows]
    return {"task_id": task_id, "events": events, "has_more": has_more, "next_before_id": rows[0]["id"] if rows else None, "next_after_id": rows[-1]["id"] if rows else after_id}

def full_log(task_id: str, log_id: str) -> str | None:
    with connection() as db:
        row = db.execute("SELECT full_content,message FROM logs WHERE task_id=? AND log_id=?", (task_id, log_id)).fetchone()
        return (row["full_content"] or row["message"] or "") if row else None

def events_after(task_id: str, event_id: int, limit=200) -> list[dict]:
    with connection() as db:
        return [{"id": row["id"], "payload": json.loads(row["payload"])} for row in db.execute("SELECT id,payload FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT ?", (task_id, event_id, limit))]

def unfinished() -> list[dict]:
    with connection() as db:
        return [_task(row) for row in db.execute("SELECT * FROM tasks WHERE is_demo=0 AND status IN ('pending','running') ORDER BY created_at")]

def archive(task_id: str, archived: bool) -> None:
    with connection() as db:
        db.execute("UPDATE tasks SET archived=? WHERE task_id=?", (archived, task_id))

def delete_task(task_id: str) -> None:
    with connection() as db:
        db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))

def task_dir(task_id: str) -> Path:
    # IDs come from validated persisted records, never from a user-supplied filename.
    canonical = str(uuid.UUID(task_id))
    return settings.RUNTIME_ROOT / "tasks" / canonical

def import_seed(seed: dict) -> dict:
    added = 0
    with connection() as db:
        for task in seed.get("tasks", []):
            task_id = str(uuid.UUID(task["task_id"]))
            status = task["status"] if task["status"] in TERMINAL else "failed"
            result = task.get("result")
            if isinstance(result, str):
                try: result = json.loads(result)
                except ValueError: result = {"report": result}
            cur = db.execute("INSERT OR IGNORE INTO tasks(task_id,is_demo,dapp_name,status,archived,created_at,completed_at,final_report,result,error,source) VALUES (?,1,?,?,?,?,?,?,?,?, 'archive')", (task_id, task["dapp_name"], status, bool(task.get("archived")), task["created_at"], task.get("completed_at"), task.get("final_report"), json.dumps(result, ensure_ascii=False), task.get("error")))
            existing = db.execute("SELECT is_demo,source FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not existing["is_demo"] or existing["source"] != "archive":
                continue
            added += cur.rowcount
            for entry in seed.get("logs", {}).get(task_id, []):
                content = entry.get("full_content") or entry.get("message") or ""
                db.execute("INSERT OR IGNORE INTO logs(task_id,log_id,agent,level,message_type,message,full_content,timestamp,is_truncated) VALUES (?,?,?,?,?,?,?,?,?)", (task_id, entry["log_id"], entry.get("agent"), entry.get("level"), entry.get("message_type"), content[:1000], content, entry.get("timestamp"), len(content) > 1000))
    return {"imported_tasks": added}

def export_user(owner_id: str) -> dict:
    tasks = [task for task in list_tasks(owner_id, True) if not task["is_demo"] and task["owner_id"] == owner_id]
    with connection() as db:
        logs = [dict(row) for row in db.execute("SELECT logs.* FROM logs JOIN tasks USING(task_id) WHERE tasks.owner_id=? AND tasks.is_demo=0", (owner_id,))]
        events = [{**dict(row), "payload": json.loads(row["payload"])} for row in db.execute("SELECT events.* FROM events JOIN tasks USING(task_id) WHERE tasks.owner_id=? AND tasks.is_demo=0", (owner_id,))]
    return {"tasks": [public_task(task) for task in tasks], "logs": logs, "events": events}
