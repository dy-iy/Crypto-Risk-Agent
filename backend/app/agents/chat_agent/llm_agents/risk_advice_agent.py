from __future__ import annotations

from app.agents.chat_agent.prompts import build_advice_prompt
from app.llm import call_llm_json


def _compact(value: object, max_chars: int = 140) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _clamp_score(value: object, default: int = 0) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(0, min(100, number))


def _is_weak_context(context: dict[str, object]) -> bool:
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    return bool(context.get("is_weak_risk")) or score <= 20 or not bool(context.get("has_established_risk"))


def _entity_list(context: dict[str, object], *keys: str) -> list[str]:
    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    if not isinstance(entities, dict):
        return []

    values: list[str] = []
    for key in keys:
        raw_items = entities.get(key)
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            text = str(item or "").strip()
            if text and text not in values:
                values.append(text)
    return values[:6]


def _score_breakdown_from_context(context: dict[str, object]) -> dict[str, int]:
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = _clamp_score(decision.get("risk_score") if isinstance(decision, dict) else 0)
    try:
        confidence_raw = float(decision.get("confidence", 0) if isinstance(decision, dict) else 0)
    except (TypeError, ValueError):
        confidence_raw = 0
    confidence = _clamp_score(confidence_raw * 100)
    established = context.get("established_risk_type_branches")
    branches = established if isinstance(established, list) else []
    evidence_values = [
        _clamp_score(branch.get("evidence_strength"))
        for branch in branches
        if isinstance(branch, dict) and branch.get("evidence_strength") is not None
    ]
    evidence_strength = max(evidence_values) if evidence_values else confidence
    impact = context.get("impact_analysis") if isinstance(context.get("impact_analysis"), dict) else {}
    impact_items = []
    if isinstance(impact, dict):
        for key in ("affected_assets", "affected_platforms", "affected_users", "impact_channels"):
            value = impact.get(key)
            if isinstance(value, list):
                impact_items.extend(item for item in value if str(item or "").strip())
    impact_scope = min(100, max(score if impact_items else score // 2, len(impact_items) * 12))
    status = str(decision.get("risk_status") or "") if isinstance(decision, dict) else ""
    urgency = score if status not in {"resolved_or_mitigated", "low_risk"} else min(score, 35)
    reversibility = 20 if status == "resolved_or_mitigated" else max(10, min(95, score - 5 if score >= 60 else score // 2))
    if _is_weak_context(context):
        return {
            "severity": min(score, 20),
            "evidence_strength": min(evidence_strength, 35),
            "impact_scope": min(impact_scope, 20),
            "urgency": min(urgency, 20),
            "reversibility": min(reversibility, 25),
        }
    return {
        "severity": score,
        "evidence_strength": evidence_strength,
        "impact_scope": impact_scope,
        "urgency": urgency,
        "reversibility": reversibility,
    }


def _normalize_score_breakdown(raw: object, context: dict[str, object]) -> dict[str, int]:
    fallback = _score_breakdown_from_context(context)
    if not isinstance(raw, dict):
        return fallback
    return {
        "severity": _clamp_score(raw.get("severity"), fallback["severity"]),
        "evidence_strength": _clamp_score(raw.get("evidence_strength"), fallback["evidence_strength"]),
        "impact_scope": _clamp_score(raw.get("impact_scope"), fallback["impact_scope"]),
        "urgency": _clamp_score(raw.get("urgency"), fallback["urgency"]),
        "reversibility": _clamp_score(raw.get("reversibility"), fallback["reversibility"]),
    }


def _weak_risk_advice(context: dict[str, object], source: str = "weak_risk_guard") -> dict[str, object]:
    assets = _entity_list(context, "coins", "tokens")
    platforms = _entity_list(context, "exchanges", "chains", "projects")
    monitoring_items = [f"{asset} 后续行情与公告" for asset in assets[:3]]
    monitoring_items.extend(f"{platform} 状态更新" for platform in platforms[:3])
    if not monitoring_items:
        monitoring_items = ["官方公告", "链上异常", "交易所状态页"]

    return {
        "priority": "low",
        "recommended_actions": [
            "保留低风险监测状态",
            "等待官方或链上证据再升级",
            "仅围绕原文对象持续观察",
        ],
        "monitoring_items": monitoring_items[:6],
        "verification_needed": ["是否存在官方确认", "是否出现可量化损失", "是否影响用户资产"],
        "do_not_do": ["不要基于弱信号扩大处置范围", "不要给交易方向建议"],
        "score_breakdown": _score_breakdown_from_context(context),
        "score_breakdown_reason": "弱风险或未成立风险分支，仅保留低风险监测，影响范围和紧急度按保守低值处理。",
        "source": source,
    }


def _fallback_advice(context: dict[str, object], reason: str) -> dict[str, object]:
    if _is_weak_context(context):
        output = _weak_risk_advice(context, "fallback_weak_risk_guard")
        output["reason"] = reason
        return output

    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    priority = "urgent" if score >= 76 else "high" if score >= 61 else "medium" if score >= 41 else "low"
    return {
        "priority": priority,
        "recommended_actions": [
            "核验官方公告和链上证据",
            "降低未核实事件的操作暴露",
            "跟踪事件后续处置进展",
        ],
        "monitoring_items": ["官方公告", "链上资金流向", "交易所状态页"],
        "verification_needed": ["事件时间线", "影响范围", "是否已有缓解措施"],
        "do_not_do": ["不要基于单条消息做交易决策"],
        "score_breakdown": _score_breakdown_from_context(context),
        "score_breakdown_reason": "LLM 不可用，按最终风险分、证据置信度和影响对象数量生成兜底评分拆解。",
        "source": "fallback",
        "reason": reason,
    }


def generate_risk_advice(context: dict[str, object]) -> dict[str, object]:
    if _is_weak_context(context):
        return _weak_risk_advice(context)

    result = call_llm_json(build_advice_prompt(context), temperature=0.0)
    if result.get("_llm_error"):
        return _fallback_advice(context, str(result["_llm_error"]))
    priority = str(result.get("priority") or "medium")
    if priority not in {"low", "medium", "high", "urgent"}:
        priority = "medium"
    return {
        "priority": priority,
        "score_breakdown": _normalize_score_breakdown(result.get("score_breakdown"), context),
        "score_breakdown_reason": _compact(result.get("score_breakdown_reason"), 100),
        "recommended_actions": [_compact(item, 45) for item in list(result.get("recommended_actions") or [])[:6]],
        "monitoring_items": [_compact(item, 45) for item in list(result.get("monitoring_items") or [])[:6]],
        "verification_needed": [_compact(item, 45) for item in list(result.get("verification_needed") or [])[:6]],
        "do_not_do": [_compact(item, 45) for item in list(result.get("do_not_do") or [])[:4]],
        "source": "llm",
    }
