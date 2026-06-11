from __future__ import annotations

import hashlib
from typing import Any

from app.services.task_audit_service import record_task_event


def _short_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]


def _safe_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    chat_agent_result = report.get("chat_agent_result")
    if not isinstance(chat_agent_result, dict):
        chat_agent_result = {}
    evidence_graph = report.get("evidence_graph")
    decision_trace = report.get("decision_trace")
    scenario_assessments = report.get("scenario_assessments")
    return {
        "risk_score": int(report.get("risk_score") or 0),
        "risk_level": str(report.get("risk_level") or ""),
        "risk_type": str(report.get("risk_type") or ""),
        "primary_scenario": str(chat_agent_result.get("primary_scenario") or ""),
        "report_mode": str(chat_agent_result.get("report_mode") or ""),
        "evidence_graph_count": len(evidence_graph) if isinstance(evidence_graph, list) else 0,
        "decision_trace_count": len(decision_trace) if isinstance(decision_trace, list) else 0,
        "scenario_assessment_count": len(scenario_assessments) if isinstance(scenario_assessments, list) else 0,
        "fallback_count": int(chat_agent_result.get("fallback_count") or 0),
        "llm_call_count": int(chat_agent_result.get("llm_call_count") or 0),
    }


def _analysis_payload(
    *,
    input_text: str,
    duration_ms: float,
    endpoint: str,
    streaming: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "endpoint": endpoint,
        "streaming": streaming,
        "duration_ms": round(float(duration_ms), 1),
        "input_chars": len(input_text or ""),
        "input_sha256_16": _short_hash(input_text),
    }
    if extra:
        payload.update(extra)
    return payload


def record_chat_analysis_success(
    *,
    job_id: str,
    input_text: str,
    report: dict[str, Any],
    duration_ms: float,
    endpoint: str,
    streaming: bool = False,
    user_id: str = "",
) -> None:
    summary = _safe_report_summary(report)
    record_task_event(
        job_kind="chat_analysis",
        job_id=job_id,
        event_type="analysis_run",
        status="success",
        stage="completed",
        message=f"Chat analysis completed with score {summary['risk_score']}",
        user_id=user_id,
        payload=_analysis_payload(
            input_text=input_text,
            duration_ms=duration_ms,
            endpoint=endpoint,
            streaming=streaming,
            extra=summary,
        ),
    )


def record_chat_analysis_error(
    *,
    job_id: str,
    input_text: str,
    error: Exception | str,
    duration_ms: float,
    endpoint: str,
    streaming: bool = False,
    user_id: str = "",
) -> None:
    record_task_event(
        job_kind="chat_analysis",
        job_id=job_id,
        event_type="analysis_run",
        status="error",
        stage="failed",
        message="Chat analysis failed",
        user_id=user_id,
        payload=_analysis_payload(
            input_text=input_text,
            duration_ms=duration_ms,
            endpoint=endpoint,
            streaming=streaming,
            extra={"error_type": type(error).__name__, "error": str(error)[:300]},
        ),
    )


def record_risk_assistant_success(
    *,
    job_id: str,
    question: str,
    duration_ms: float,
    endpoint: str,
    streaming: bool = False,
    user_id: str = "",
    answer_chars: int = 0,
) -> None:
    record_task_event(
        job_kind="risk_assistant",
        job_id=job_id,
        event_type="assistant_run",
        status="success",
        stage="completed",
        message="Risk assistant completed",
        user_id=user_id,
        payload=_analysis_payload(
            input_text=question,
            duration_ms=duration_ms,
            endpoint=endpoint,
            streaming=streaming,
            extra={"answer_chars": max(0, int(answer_chars or 0))},
        ),
    )


def record_risk_assistant_error(
    *,
    job_id: str,
    question: str,
    error: Exception | str,
    duration_ms: float,
    endpoint: str,
    streaming: bool = False,
    user_id: str = "",
) -> None:
    record_task_event(
        job_kind="risk_assistant",
        job_id=job_id,
        event_type="assistant_run",
        status="error",
        stage="failed",
        message="Risk assistant failed",
        user_id=user_id,
        payload=_analysis_payload(
            input_text=question,
            duration_ms=duration_ms,
            endpoint=endpoint,
            streaming=streaming,
            extra={"error_type": type(error).__name__, "error": str(error)[:300]},
        ),
    )
