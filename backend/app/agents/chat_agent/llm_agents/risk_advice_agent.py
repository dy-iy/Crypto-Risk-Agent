from __future__ import annotations

from app.agents.chat_agent.prompts import build_advice_prompt
from app.llm import call_llm_json


def _compact(value: object, max_chars: int = 140) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _is_weak_context(context: dict[str, object]) -> bool:
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    return bool(context.get("is_weak_risk")) or score <= 20 or not bool(context.get("has_established_risk"))


def _weak_risk_advice(context: dict[str, object], source: str = "weak_risk_guard") -> dict[str, object]:
    del context
    return {
        "priority": "low",
        "recommended_actions": [
            "保留低风险监测状态",
            "等待官方或链上证据再升级",
            "不要推断具体受影响对象",
        ],
        "monitoring_items": ["官方公告", "链上异常", "交易所状态页"],
        "verification_needed": ["是否存在官方确认", "是否出现可量化损失", "是否影响用户资产"],
        "do_not_do": ["不要基于弱信号扩大处置范围", "不要给交易方向建议"],
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
        "recommended_actions": [_compact(item, 45) for item in list(result.get("recommended_actions") or [])[:6]],
        "monitoring_items": [_compact(item, 45) for item in list(result.get("monitoring_items") or [])[:6]],
        "verification_needed": [_compact(item, 45) for item in list(result.get("verification_needed") or [])[:6]],
        "do_not_do": [_compact(item, 45) for item in list(result.get("do_not_do") or [])[:4]],
        "source": "llm",
    }
