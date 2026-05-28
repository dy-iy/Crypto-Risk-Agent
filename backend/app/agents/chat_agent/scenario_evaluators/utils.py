from __future__ import annotations

import re
from typing import Any

from app.agents.chat_agent.schemas import EvidenceFieldResult


def is_confirmed(fields: dict[str, EvidenceFieldResult], field: str) -> bool:
    item = fields.get(field)
    if not item:
        return False
    if item.status != "confirmed":
        return False
    if isinstance(item.value, bool):
        return item.value
    return str(item.value).strip().lower() not in {"", "false", "none", "null", "0"}


def is_denied(fields: dict[str, EvidenceFieldResult], field: str) -> bool:
    item = fields.get(field)
    return bool(item and item.status == "denied")


def text_value(fields: dict[str, EvidenceFieldResult], field: str) -> str:
    item = fields.get(field)
    if not item or item.value is None:
        return ""
    return str(item.value)


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


def confirmed_evidence(fields: dict[str, EvidenceFieldResult], names: list[str]) -> list[str]:
    output: list[str] = []
    for name in names:
        item = fields.get(name)
        if item and item.status == "confirmed" and item.evidence_text:
            output.append(item.evidence_text)
    return list(dict.fromkeys(output))[:5]


def missing(fields: dict[str, EvidenceFieldResult], names: list[str]) -> list[str]:
    return [name for name in names if fields.get(name) is None or fields[name].status == "missing"]


def clamp(score: int) -> int:
    return max(0, min(100, score))
