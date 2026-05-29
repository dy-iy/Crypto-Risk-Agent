from __future__ import annotations

import json
from typing import Any

from app.agents.chat_agent.core.scenario_router import select_active_scenarios
from app.agents.chat_agent.schemas import RiskCaseInput, Signal, SignalScanResult
from app.agents.chat_agent.tools.risk_scanner import (
    RISK_NAME_MAP,
    RISK_SCENARIO_MAP,
    RISK_TYPE_ORDER,
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


def _build_prompt(case_input: RiskCaseInput, signal_scan: SignalScanResult) -> str:
    risk_type_stats = signal_scan.debug.get("risk_type_stats", [])
    high_risk_route = signal_scan.debug.get("high_risk_route", {})
    payload = {
        "text": case_input.content or case_input.raw_text,
        "input_type": case_input.input_type,
        "entities": case_input.entities,
        "current_route": "low_risk_path",
        "current_risk_score": max(
            (int(round(float(score) * 100)) for score in signal_scan.raw_rule_scores.values()),
            default=0,
        ),
        "route_rule": {
            "direct_high_risk": [
                "score_hack",
                "score_fraud",
                "score_outage",
                "score_stablecoin",
                "score_solvency",
                "score_team",
                "score_infra",
            ],
            "threshold_high_risk": [
                "score_whale",
                "score_volatility",
                "score_macro",
                "score_liquidation",
                "score_regulatory",
            ],
            "threshold_condition": "score > 40 才进入高风险 path",
        },
        "risk_type_stats": risk_type_stats,
        "raw_rule_scores": signal_scan.raw_rule_scores,
        "high_risk_route": high_risk_route,
    }
    allowed_types = "\n".join(f"- {risk_type}: {risk_name}" for risk_type, risk_name in RISK_NAME_MAP.items())
    compact_payload = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""
你是低风险路段的反思门控 Agent。你的任务是审核规则扫描器是否把文本错误地放入低风险 path。

只允许使用以下 12 类 risk_type：
{allowed_types}

审核要求：
1. 结合原文、当前 risk_type 和 risk_score，判断“继续低风险 path”是否合理。
2. 如果文本明确命中 direct_high_risk 组中的任一风险类型，即使规则分很低，也应输出 escalate_to_high_risk=true。
3. 如果文本命中 threshold_high_risk 组，且你认为真实风险分应大于 40，应输出 escalate_to_high_risk=true。
4. 如果规则漏掉了 risk_type，请在 added_risk_types 中补充，并在 corrected_scores 中给出 0-100 的修正分。
5. 不要因为普通行情、观点、传闻、无损失维护、内部归集而轻易升级。
6. 必须严格输出 JSON，不要输出 Markdown。

JSON 格式：
{{
  "low_risk_confirmed": true,
  "escalate_to_high_risk": false,
  "reviewed_primary_risk_type": "score_whale",
  "reviewed_risk_score": 35,
  "added_risk_types": [],
  "corrected_scores": {{}},
  "reason": "一句话说明审核理由"
}}

待审核输入：
{compact_payload}
""".strip()


def review_low_risk_route(case_input: RiskCaseInput, signal_scan: SignalScanResult) -> tuple[SignalScanResult, dict[str, Any], list[str]]:
    raw_result = call_llm_json(_build_prompt(case_input, signal_scan), temperature=0.0)
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
