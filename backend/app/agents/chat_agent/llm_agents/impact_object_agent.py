from __future__ import annotations

from app.agents.chat_agent.prompts import build_impact_prompt
from app.llm import call_llm_json


def _compact(value: object, max_chars: int = 140) -> str:
    return " ".join(str(value or "").split())[:max_chars]


def _is_weak_context(context: dict[str, object]) -> bool:
    decision = context.get("decision") if isinstance(context.get("decision"), dict) else {}
    score = int(decision.get("risk_score") or 0) if isinstance(decision, dict) else 0
    return bool(context.get("is_weak_risk")) or score <= 20 or not bool(context.get("has_established_risk"))


def _weak_risk_impact(context: dict[str, object], source: str = "weak_risk_guard") -> dict[str, object]:
    del context
    return {
        "affected_assets": [],
        "affected_platforms": [],
        "affected_users": [],
        "impact_channels": ["持续监测", "信息核验"],
        "impact_summary": "未确认具体受影响资产、平台或用户群体，当前仅建议持续监测。",
        "uncertainty": ["缺少已成立风险分支，不能推断具体影响对象"],
        "source": source,
    }


def _fallback_impact(context: dict[str, object], reason: str) -> dict[str, object]:
    if _is_weak_context(context):
        output = _weak_risk_impact(context, "fallback_weak_risk_guard")
        output["uncertainty"].append(reason)
        return output

    entities = context.get("entities") if isinstance(context.get("entities"), dict) else {}
    assets = []
    platforms = []
    if isinstance(entities, dict):
        assets = list(entities.get("coins") or entities.get("tokens") or [])[:6]
        platforms = list(entities.get("exchanges") or [])[:6]
    return {
        "affected_assets": assets,
        "affected_platforms": platforms,
        "affected_users": ["相关资产持有者", "相关平台用户"],
        "impact_channels": ["市场情绪", "流动性变化"],
        "impact_summary": _compact("LLM 不可用，基于实体和风险分支生成保守影响对象。"),
        "uncertainty": [reason],
        "source": "fallback",
    }


def analyze_impact_objects(context: dict[str, object]) -> dict[str, object]:
    if _is_weak_context(context):
        return _weak_risk_impact(context)

    result = call_llm_json(build_impact_prompt(context), temperature=0.0)
    if result.get("_llm_error"):
        return _fallback_impact(context, str(result["_llm_error"]))
    return {
        "affected_assets": list(result.get("affected_assets") or [])[:8],
        "affected_platforms": list(result.get("affected_platforms") or [])[:8],
        "affected_users": list(result.get("affected_users") or [])[:8],
        "impact_channels": list(result.get("impact_channels") or [])[:8],
        "impact_summary": _compact(result.get("impact_summary")),
        "uncertainty": list(result.get("uncertainty") or [])[:6],
        "source": "llm",
    }
