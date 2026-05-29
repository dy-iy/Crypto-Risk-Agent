from __future__ import annotations

import re
from typing import Any

from app.agents.chat_agent.schemas import EvidenceFieldResult


def is_confirmed(fields: dict[str, EvidenceFieldResult], field: str) -> bool:
    item = fields.get(field)
    if not item or item.status != "confirmed":
        return False
    if isinstance(item.value, bool):
        return item.value
    return str(item.value).strip().lower() not in {"", "false", "none", "null", "0"}


def numeric_value(fields: dict[str, EvidenceFieldResult], field: str) -> float:
    item = fields.get(field)
    if not item:
        return 0.0
    value: Any = item.value
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value or ""))
    if not match:
        return 0.0
    return float(match.group(1))
