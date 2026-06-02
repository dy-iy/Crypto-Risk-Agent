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


def _normalize_risk_types(raw_value: object) -> list[str]:
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


def _merge_risk_types(*groups: object) -> list[str]:
    merged: list[str] = []
    for group in groups:
        values = group if isinstance(group, list) else [group]
        for value in values:
            risk_type = _normalize_risk_type(value)
            if risk_type and risk_type not in merged:
                merged.append(risk_type)
    return merged


def _rebuild_scenario_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    scenario_scores: dict[str, float] = {}
    for risk_type, score in raw_scores.items():
        scenario = RISK_SCENARIO_MAP.get(risk_type)
        if not scenario:
            continue
        scenario_scores[scenario] = max(float(scenario_scores.get(scenario, 0.0)), float(score))
    return scenario_scores


def review_low_risk_route(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    current_path: str = "fast_exit",
) -> tuple[SignalScanResult, dict[str, Any], list[str]]:
    prompt_route = "low_risk_path" if current_path == "fast_exit" else "deep_analysis_path"
    raw_result = call_llm_json(build_low_risk_gate_prompt(case_input, signal_scan, prompt_route), temperature=0.0)
    if raw_result.get("_llm_error"):
        gate = {
            "source": "llm_error_fallback",
            "low_risk_confirmed": True,
            "escalate_to_high_risk": False,
            "confirmed_risk_types": [],
            "added_risk_types": [],
            "suppressed_risk_types": [],
            "corrected_scores": {},
            "reason": str(raw_result["_llm_error"]),
            "raw_llm_output": raw_result,
        }
        updated_debug = {**signal_scan.debug, "low_risk_gate": gate}
        return signal_scan.model_copy(update={"debug": updated_debug}), gate, []

    confirmed_types = _normalize_risk_types(raw_result.get("confirmed_risk_types"))
    added_types = _normalize_risk_types(raw_result.get("added_risk_types"))
    suppressed_types = _normalize_risk_types(raw_result.get("suppressed_risk_types"))
    default_score_types = list(
        dict.fromkeys(
            added_types
            + [
                risk_type
                for risk_type in confirmed_types
                if float(signal_scan.raw_rule_scores.get(risk_type, 0.0)) <= 0
            ]
        )
    )
    corrected_scores = _normalize_scores(raw_result.get("corrected_scores"), default_score_types)
    for risk_type in suppressed_types:
        corrected_scores.setdefault(risk_type, 0)
    primary_type = _normalize_risk_type(raw_result.get("reviewed_primary_risk_type"))
    reviewed_score = _clamp_score(raw_result.get("reviewed_risk_score"))
    if primary_type and reviewed_score > 0:
        corrected_scores[primary_type] = max(corrected_scores.get(primary_type, 0), reviewed_score)
    handoff_types = _merge_risk_types(
        confirmed_types,
        added_types,
        primary_type if primary_type and reviewed_score > 0 else "",
        [
            risk_type
            for risk_type, score in corrected_scores.items()
            if score > 0 and risk_type not in suppressed_types
        ],
    )

    escalate = bool(raw_result.get("escalate_to_high_risk"))
    for risk_type in confirmed_types:
        if risk_type in suppressed_types:
            continue
        if risk_type in {
            "score_hack",
            "score_fraud",
            "score_outage",
            "score_stablecoin",
            "score_solvency",
            "score_team",
            "score_infra",
        }:
            escalate = True
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
    positive_signals = list(signal_scan.positive_signals)
    suppressed_signal_types = {SIGNAL_TYPES.get(risk_type, risk_type) for risk_type in suppressed_types}
    if suppressed_signal_types:
        positive_signals = [
            signal
            for signal in positive_signals
            if signal.type not in suppressed_signal_types
        ]
    for risk_type, score_100 in corrected_scores.items():
        score = round(score_100 / 100, 4)
        if risk_type in suppressed_types:
            raw_scores[risk_type] = min(float(raw_scores.get(risk_type, 0.0)), score)
            continue
        raw_scores[risk_type] = max(float(raw_scores.get(risk_type, 0.0)), score)
        scenario = RISK_SCENARIO_MAP[risk_type]
        positive_signals.append(
            Signal(
                type=SIGNAL_TYPES.get(risk_type, risk_type),
                strength=score,
                scenario_hint=scenario,
                reason=f"low_risk_gate:{RISK_NAME_MAP[risk_type]}",
            )
        )
    scenario_scores = _rebuild_scenario_scores(raw_scores)

    gate = {
        "source": "llm",
        "low_risk_confirmed": bool(raw_result.get("low_risk_confirmed")) and not escalate,
        "escalate_to_high_risk": escalate,
        "confirmed_risk_types": confirmed_types,
        "reviewed_primary_risk_type": primary_type,
        "reviewed_risk_score": reviewed_score,
        "added_risk_types": added_types,
        "suppressed_risk_types": suppressed_types,
        "handoff_risk_types": handoff_types,
        "corrected_scores": corrected_scores,
        "reason": str(raw_result.get("reason") or ""),
        "raw_llm_output": raw_result,
    }
    high_risk_route = dict(signal_scan.debug.get("high_risk_route", {}))
    if escalate and handoff_types:
        existing_triggered = high_risk_route.get("triggered_types", [])
        triggered_types = _merge_risk_types(existing_triggered if isinstance(existing_triggered, list) else [], handoff_types)
        high_risk_route.update(
            {
                "triggered": True,
                "triggered_types": triggered_types,
                "low_risk_gate_hits": handoff_types,
                "rule": f"{high_risk_route.get('rule') or 'rule_route'}+low_risk_gate_handoff",
            }
        )
    updated_debug = {
        **signal_scan.debug,
        "high_risk_route": high_risk_route,
        "low_risk_gate": gate,
        "low_risk_gate_handoff": {
            "risk_types": handoff_types if escalate else [],
            "source": "low_risk_gate",
            "reason": gate["reason"],
        },
    }
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
