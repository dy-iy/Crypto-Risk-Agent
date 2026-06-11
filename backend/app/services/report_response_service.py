from __future__ import annotations

import copy
import os
from typing import Any


INTERNAL_REPORT_FIELDS = {
    "debug",
    "raw_agent_outputs",
    "merged_result",
    "calibrated_result",
    "structured_review_result",
}


def public_report_debug_enabled() -> bool:
    return os.getenv("ALLOW_PUBLIC_REPORT_DEBUG", "").strip() == "1"


def sanitize_risk_report_for_public_api(report: dict[str, Any]) -> dict[str, Any]:
    if public_report_debug_enabled():
        return copy.deepcopy(report)

    sanitized = copy.deepcopy(report)
    for field in INTERNAL_REPORT_FIELDS:
        sanitized.pop(field, None)
    return sanitized
