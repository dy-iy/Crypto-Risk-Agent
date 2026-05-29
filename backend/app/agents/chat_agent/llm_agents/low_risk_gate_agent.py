from __future__ import annotations

from typing import Any

from app.agents.chat_agent.core.scenario_router import select_active_scenarios
from app.agents.chat_agent.prompts import build_low_risk_gate_prompt
from app.agents.chat_agent.schemas import RiskCaseInput, Signal, SignalScanResult
from app.agents.chat_agent.tools.risk_scanner import (
    RISK_NAME_MAP,
    RISK_SCENARIO_MAP,
    SIGNAL_TYPES,
)
from app.llm import call_llm_json


def _clamp_score(value: object) -> int:
    try:
        score = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, score))


def _normalize_risk_type(value: object) -> str:
    text = str(value or "").strip()
    if text in RISK_NAME_MAP:
        return text
    for risk_type, risk_name in RISK_NAME_MAP.items():
        if text == risk_name:
            return risk_type
    return ""


def _normalize_added_types(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[str] = []
    for item in raw_value:
        if isinstance(item, dict):
            risk_type = _normalize_risk_type(item.get("risk_type") or item.get("type") or item.get("risk_name"))
        else:
            risk_type = _normalize_risk_type(item)
        if risk_type and risk_type not in normalized:
            normalized.append(risk_type)
    return normalized


def _normalize_scores(raw_value: object, added_types: list[str]) -> dict[str, int]:
    scores: dict[str, int] = {}
    if isinstance(raw_value, dict):
        for key, value in raw_value.items():
            risk_type = _normalize_risk_type(key)
            if risk_type:
                scores[risk_type] = _clamp_score(value)
    elif isinstance(raw_value, list):
        for item in raw_value:
            if not isinstance(item, dict):
                continue
            risk_type = _normalize_risk_type(item.get("risk_type") or item.get("type") or item.get("risk_name"))
            if risk_type:
                scores[risk_type] = _clamp_score(item.get("risk_score") or item.get("score"))

    for risk_type in added_types:
        scores.setdefault(risk_type, 41)
    return scores


def review_low_risk_route(case_input: RiskCaseInput, signal_scan: SignalScanResult) -> tuple[SignalScanResult, dict[str, Any], list[str]]:
    raw_result = call_llm_json(build_low_risk_gate_prompt(case_input, signal_scan), temperature=0.0)
    if raw_result.get("_llm_error"):
        gate = {
            "source": "llm_error_fallback",
            "low_risk_confirmed": True,
            "escalate_to_high_risk": False,
            "added_risk_types": [],
            "corrected_scores": {},
            "reason": str(raw_result["_llm_error"]),
            "raw_llm_output": raw_result,
        }
        updated_debug = {**signal_scan.debug, "low_risk_gate": gate}
        return signal_scan.model_copy(update={"debug": updated_debug}), gate, []

    added_types = _normalize_added_types(raw_result.get("added_risk_types"))
    corrected_scores = _normalize_scores(raw_result.get("corrected_scores"), added_types)
    primary_type = _normalize_risk_type(raw_result.get("reviewed_primary_risk_type"))
    reviewed_score = _clamp_score(raw_result.get("reviewed_risk_score"))
    if primary_type and reviewed_score > 0:
        corrected_scores[primary_type] = max(corrected_scores.get(primary_type, 0), reviewed_score)

    escalate = bool(raw_result.get("escalate_to_high_risk"))
    if corrected_scores:
        for risk_type, score in corrected_scores.items():
            if risk_type in {
                "score_hack",
                "score_fraud",
                "score_outage",
                "score_stablecoin",
                "score_solvency",
                "score_team",
                "score_infra",
            } and score > 0:
                escalate = True
            if risk_type in {
                "score_whale",
                "score_volatility",
                "score_macro",
                "score_liquidation",
                "score_regulatory",
            } and score > 40:
                escalate = True

    raw_scores = dict(signal_scan.raw_rule_scores)
    scenario_scores = dict(signal_scan.scenario_scores)
    positive_signals = list(signal_scan.positive_signals)
    for risk_type, score_100 in corrected_scores.items():
        score = round(score_100 / 100, 4)
        raw_scores[risk_type] = max(float(raw_scores.get(risk_type, 0.0)), score)
        scenario = RISK_SCENARIO_MAP[risk_type]
        scenario_scores[scenario] = max(float(scenario_scores.get(scenario, 0.0)), score)
        positive_signals.append(
            Signal(
                type=SIGNAL_TYPES.get(risk_type, risk_type),
                strength=score,
                scenario_hint=scenario,
                reason=f"low_risk_gate:{RISK_NAME_MAP[risk_type]}",
            )
        )

    gate = {
        "source": "llm",
        "low_risk_confirmed": bool(raw_result.get("low_risk_confirmed")) and not escalate,
        "escalate_to_high_risk": escalate,
        "reviewed_primary_risk_type": primary_type,
        "reviewed_risk_score": reviewed_score,
        "added_risk_types": added_types,
        "corrected_scores": corrected_scores,
        "reason": str(raw_result.get("reason") or ""),
        "raw_llm_output": raw_result,
    }
    updated_debug = {**signal_scan.debug, "low_risk_gate": gate}
    updated_scan = signal_scan.model_copy(
        update={
            "positive_signals": positive_signals,
            "scenario_scores": scenario_scores,
            "raw_rule_scores": raw_scores,
            "debug": updated_debug,
            "fast_exit_allowed": not escalate,
            "suggested_top_k": max(signal_scan.suggested_top_k, 2 if escalate else signal_scan.suggested_top_k),
        }
    )
    active_scenarios = select_active_scenarios(updated_scan) if escalate else []
    return updated_scan, gate, active_scenarios
