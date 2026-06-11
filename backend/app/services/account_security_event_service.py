from __future__ import annotations

import hashlib
from uuid import uuid4

from app.services.task_audit_service import record_task_event


def security_identifier_hash(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] if normalized else ""


def record_account_security_event(
    *,
    user_id: str,
    event_type: str,
    stage: str,
    message: str,
    status: str = "success",
    payload: dict[str, object] | None = None,
) -> None:
    record_task_event(
        job_kind="account_security",
        job_id=f"account-security-{uuid4().hex}",
        event_type=event_type,
        status=status,
        stage=stage,
        message=message,
        user_id=user_id,
        payload=payload or {},
    )
