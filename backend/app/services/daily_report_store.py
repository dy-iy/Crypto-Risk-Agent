from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


DAILY_REPORTS_DIR = Path(__file__).resolve().parents[1] / "data" / "daily_reports"
MAX_REPORTS_PER_USER = 30

_store_lock = Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_user_id(user_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "_", str(user_id or "demo_user"))
    return normalized[:96] or "demo_user"


def _user_dir(user_id: str) -> Path:
    return DAILY_REPORTS_DIR / _safe_user_id(user_id)


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "index.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_index(user_id: str) -> dict[str, Any]:
    index = _read_json(_index_path(user_id)) or {}
    reports = index.get("reports")
    if not isinstance(reports, list):
        reports = []
    return {"reports": [item for item in reports if isinstance(item, dict)]}


def _report_filename(report_id: str) -> str:
    return f"{report_id}.json"


def save_daily_report(user_id: str, report: dict[str, Any]) -> dict[str, Any]:
    now = _now_text()
    normalized_range = str(report.get("range") or report.get("date") or "24h")
    report_id = f"{normalized_range}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    saved_report = {
        **report,
        "report_id": report_id,
        "created_at": now,
        "generation_date": now[:10],
        "saved_at": now,
    }
    record = {
        "report_id": report_id,
        "range": normalized_range,
        "created_at": now,
        "generation_date": now[:10],
        "headline": str(saved_report.get("headline") or ""),
        "alert_level": str(saved_report.get("alert_level") or ""),
        "personal_risk_score": int(saved_report.get("personal_risk_score") or 0),
        "user_assets_count": int(saved_report.get("user_assets_count") or 0),
        "asset_report_count": len(saved_report.get("asset_reports") or []),
        "path": _report_filename(report_id),
    }

    with _store_lock:
        user_dir = _user_dir(user_id)
        _write_json(user_dir / record["path"], saved_report)
        index = _load_index(user_id)
        reports = [
            item
            for item in index["reports"]
            if str(item.get("report_id") or "") != report_id
        ]
        reports.insert(0, record)
        index["reports"] = reports[:MAX_REPORTS_PER_USER]
        _write_json(_index_path(user_id), index)

    return saved_report


def get_latest_daily_report(user_id: str, date_filter: str | None = None) -> dict[str, Any] | None:
    normalized_range = date_filter if date_filter in {"24h", "7d"} else None
    with _store_lock:
        index = _load_index(user_id)
        for item in index["reports"]:
            if normalized_range and str(item.get("range") or "") != normalized_range:
                continue
            path = _user_dir(user_id) / str(item.get("path") or "")
            report = _read_json(path)
            if report:
                return report
    return None


def list_daily_reports(user_id: str, date_filter: str | None = None) -> list[dict[str, Any]]:
    normalized_range = date_filter if date_filter in {"24h", "7d"} else None
    with _store_lock:
        reports = _load_index(user_id)["reports"]
    return [
        item
        for item in reports
        if not normalized_range or str(item.get("range") or "") == normalized_range
    ]
