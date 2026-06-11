from __future__ import annotations


PUBLIC_AGENT_ERROR_DETAIL = "Agent workflow failed. Please retry later."
PUBLIC_RISK_ASSISTANT_ERROR_DETAIL = "Risk assistant failed. Please retry later."
PUBLIC_NEWS_UPDATE_ERROR_DETAIL = "News update failed. Please retry later."
PUBLIC_INTERNAL_ERROR_DETAIL = "Internal server error. Please retry later."


def public_error_payload(detail: str, job_id: str | None = None) -> dict[str, str]:
    payload = {"detail": detail}
    if job_id:
        payload["job_id"] = job_id
    return payload
