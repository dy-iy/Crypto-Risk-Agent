from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.runtime_json_store import load_runtime_json_or_quarantine, write_runtime_json_atomic


FEISHU_BINDINGS_PATH = Path(__file__).resolve().parents[1] / "data" / "feishu_bindings.json"
FEISHU_OAUTH_STATES_PATH = Path(__file__).resolve().parents[1] / "data" / "feishu_oauth_states.json"
OAUTH_STATE_TTL_MINUTES = 10

_bindings_lock = Lock()
_states_lock = Lock()


def _now() -> datetime:
    return datetime.now()


def _now_text() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _load_bindings() -> dict[str, dict[str, Any]]:
    raw = load_runtime_json_or_quarantine(FEISHU_BINDINGS_PATH)
    if not isinstance(raw, dict):
        return {}
    bindings: dict[str, dict[str, Any]] = {}
    for user_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        bindings[str(user_id)] = {
            "user_id": str(value.get("user_id") or user_id),
            "open_id": str(value.get("open_id") or ""),
            "union_id": str(value.get("union_id") or ""),
            "tenant_key": str(value.get("tenant_key") or ""),
            "name": str(value.get("name") or ""),
            "avatar_url": str(value.get("avatar_url") or ""),
            "enabled": bool(value.get("enabled", True)),
            "bound_at": str(value.get("bound_at") or ""),
            "updated_at": str(value.get("updated_at") or ""),
        }
    return bindings


def _write_bindings(bindings: dict[str, dict[str, Any]]) -> None:
    write_runtime_json_atomic(FEISHU_BINDINGS_PATH, bindings)


def _public_binding(record: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if not record:
        return {
            "user_id": user_id,
            "bound": False,
            "enabled": False,
            "name": "",
            "avatar_url": "",
            "bound_at": "",
            "updated_at": "",
        }
    return {
        "user_id": user_id,
        "bound": bool(record.get("open_id")),
        "enabled": bool(record.get("enabled")),
        "name": str(record.get("name") or ""),
        "avatar_url": str(record.get("avatar_url") or ""),
        "bound_at": str(record.get("bound_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
    }


def get_feishu_binding(user_id: str) -> dict[str, Any] | None:
    with _bindings_lock:
        return _load_bindings().get(user_id)


def get_public_feishu_binding(user_id: str) -> dict[str, Any]:
    return _public_binding(get_feishu_binding(user_id), user_id)


def list_public_feishu_bindings() -> list[dict[str, Any]]:
    with _bindings_lock:
        bindings = _load_bindings()
    return [_public_binding(record, user_id) for user_id, record in sorted(bindings.items())]


def upsert_feishu_binding(user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    now = _now_text()
    record = {
        "user_id": user_id,
        "open_id": str(profile.get("open_id") or ""),
        "union_id": str(profile.get("union_id") or ""),
        "tenant_key": str(profile.get("tenant_key") or ""),
        "name": str(profile.get("name") or profile.get("en_name") or profile.get("nickname") or ""),
        "avatar_url": str(profile.get("avatar_url") or profile.get("avatar_thumb") or ""),
        "enabled": True,
        "bound_at": now,
        "updated_at": now,
    }
    if not record["open_id"]:
        raise ValueError("missing_feishu_open_id")
    with _bindings_lock:
        bindings = _load_bindings()
        existing = bindings.get(user_id)
        if existing and existing.get("bound_at"):
            record["bound_at"] = str(existing.get("bound_at"))
        bindings[user_id] = record
        _write_bindings(bindings)
    return _public_binding(record, user_id)


def set_feishu_binding_enabled(user_id: str, enabled: bool) -> dict[str, Any]:
    with _bindings_lock:
        bindings = _load_bindings()
        record = bindings.get(user_id)
        if not record:
            return _public_binding(None, user_id)
        record["enabled"] = bool(enabled)
        record["updated_at"] = _now_text()
        bindings[user_id] = record
        _write_bindings(bindings)
    return _public_binding(record, user_id)


def delete_feishu_binding(user_id: str) -> int:
    with _bindings_lock:
        bindings = _load_bindings()
        existed = user_id in bindings
        if existed:
            bindings.pop(user_id, None)
            _write_bindings(bindings)
    return 1 if existed else 0


def _load_states() -> dict[str, dict[str, Any]]:
    raw = load_runtime_json_or_quarantine(FEISHU_OAUTH_STATES_PATH)
    if not isinstance(raw, dict):
        return {}
    states: dict[str, dict[str, Any]] = {}
    for state, value in raw.items():
        if not isinstance(value, dict):
            continue
        states[str(state)] = {
            "state": str(value.get("state") or state),
            "user_id": str(value.get("user_id") or ""),
            "expires_at": str(value.get("expires_at") or ""),
            "created_at": str(value.get("created_at") or ""),
        }
    return states


def _write_states(states: dict[str, dict[str, Any]]) -> None:
    write_runtime_json_atomic(FEISHU_OAUTH_STATES_PATH, states)


def _prune_expired_states(states: dict[str, dict[str, Any]], now: datetime | None = None) -> dict[str, dict[str, Any]]:
    current = now or _now()
    return {
        state: record
        for state, record in states.items()
        if (expires_at := _parse_time(record.get("expires_at"))) and expires_at > current
    }


def create_feishu_oauth_state(user_id: str) -> str:
    state = secrets.token_urlsafe(32)
    now = _now()
    record = {
        "state": state,
        "user_id": user_id,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "expires_at": (now + timedelta(minutes=OAUTH_STATE_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _states_lock:
        states = _prune_expired_states(_load_states(), now)
        states[state] = record
        _write_states(states)
    return state


def consume_feishu_oauth_state(state: str, user_id: str) -> bool:
    with _states_lock:
        states = _prune_expired_states(_load_states())
        record = states.pop(state, None)
        _write_states(states)
    if not record:
        return False
    return str(record.get("user_id") or "") == user_id
