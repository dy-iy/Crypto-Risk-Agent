from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.runtime_json_store import load_runtime_json_or_quarantine, write_runtime_json_atomic


SUBSCRIPTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "daily_report_subscriptions.json"
_subscriptions_lock = Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_store() -> dict[str, dict[str, Any]]:
    raw = load_runtime_json_or_quarantine(SUBSCRIPTIONS_PATH)
    if not isinstance(raw, dict):
        return {}
    output: dict[str, dict[str, Any]] = {}
    for user_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        output[str(user_id)] = {
            "enabled": bool(value.get("enabled")),
            "updated_at": str(value.get("updated_at") or ""),
        }
    return output


def _write_store(store: dict[str, dict[str, Any]]) -> None:
    write_runtime_json_atomic(SUBSCRIPTIONS_PATH, store)


def get_daily_report_subscription(user_id: str) -> dict[str, Any]:
    with _subscriptions_lock:
        store = _load_store()
        record = store.get(user_id, {})
    return {
        "user_id": user_id,
        "enabled": bool(record.get("enabled")),
        "updated_at": str(record.get("updated_at") or ""),
    }


def set_daily_report_subscription(user_id: str, enabled: bool) -> dict[str, Any]:
    now = _now_text()
    with _subscriptions_lock:
        store = _load_store()
        store[user_id] = {
            "enabled": bool(enabled),
            "updated_at": now,
        }
        _write_store(store)
    return {
        "user_id": user_id,
        "enabled": bool(enabled),
        "updated_at": now,
    }


def list_daily_report_subscriptions() -> list[dict[str, Any]]:
    with _subscriptions_lock:
        store = _load_store()
    return [
        {
            "user_id": user_id,
            "enabled": bool(record.get("enabled")),
            "updated_at": str(record.get("updated_at") or ""),
        }
        for user_id, record in sorted(store.items())
    ]


def list_subscribed_daily_report_user_ids() -> list[str]:
    return [
        item["user_id"]
        for item in list_daily_report_subscriptions()
        if item["enabled"]
    ]


def delete_daily_report_subscription(user_id: str) -> int:
    with _subscriptions_lock:
        store = _load_store()
        existed = user_id in store
        if existed:
            store.pop(user_id, None)
            _write_store(store)
    return 1 if existed else 0
