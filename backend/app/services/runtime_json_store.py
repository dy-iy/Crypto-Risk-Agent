from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _invalid_backup_path(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base_name = f"{path.name}.invalid.{timestamp}.bak"
    candidate = path.with_name(base_name)
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{base_name}.{counter}")
        counter += 1
    return candidate


def quarantine_invalid_json(path: Path) -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        backup_path = _invalid_backup_path(path)
        path.replace(backup_path)
        return backup_path
    except OSError:
        return None


def load_runtime_json_or_quarantine(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        quarantine_invalid_json(path)
        return None


def write_runtime_json_atomic(path: Path, payload: Any) -> bool:
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as file:
            temp_path = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        temp_path.replace(path)
        return True
    except (OSError, ValueError, TypeError):
        logging.getLogger(__name__).exception("Failed to persist runtime JSON: %s", path.name)
        return False
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
