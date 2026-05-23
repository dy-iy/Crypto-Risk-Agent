from app.llm import call_llm_json
from app.prompts.score_prompt import build_score_prompt
from app.state import CryptoRiskState


BREAKDOWN_KEYS = ["severity", "evidence_strength", "impact_scope", "urgency", "reversibility"]


def risk_level_from_score(score: int) -> str:
    if score <= 20:
        return "低风险"
    if score <= 40:
        return "轻微风险"
    if score <= 60:
        return "中风险"
    if score <= 80:
        return "高风险"
    return "极高风险"


def _clamp_score(value: object, default: int = 0) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))


def _fallback_score(state: CryptoRiskState) -> tuple[int, dict[str, int]]:
    categories = state.get("risk_categories", [])
    evidence = state.get("evidence", [])
    signals = state.get("risk_signals", [])

    base = 35
    base += min(len(categories), 4) * 8
    base += min(len(evidence), 4) * 5
    base += min(len(signals), 6) * 3

    text = state.get("cleaned_text", "").lower()
    if any(word in text for word in ["被盗", "hack", "exploit", "跑路", "rug", "暂停提现", "无法提现"]):
        base += 15
    if any(word in text for word in ["脱锚", "depeg", "清算", "爆仓", "储备不足"]):
        base += 10

    score = _clamp_score(base)
    breakdown = {
        "severity": _clamp_score(score + 5),
        "evidence_strength": _clamp_score(55 + len(evidence) * 8),
        "impact_scope": _clamp_score(45 + len(categories) * 10),
        "urgency": _clamp_score(score),
        "reversibility": _clamp_score(score - 5),
    }
    return score, breakdown


def score_agent(state: CryptoRiskState) -> CryptoRiskState:
    prompt = build_score_prompt(
        state.get("cleaned_text", ""),
        state.get("risk_categories", []),
        state.get("evidence", []),
    )
    llm_result = call_llm_json(prompt)

    score, fallback_breakdown = _fallback_score(state)
    risk_score = _clamp_score(llm_result.get("risk_score"), score)
    risk_level = str(llm_result.get("risk_level") or risk_level_from_score(risk_score))

    breakdown_value = llm_result.get("score_breakdown", {})
    if not isinstance(breakdown_value, dict):
        breakdown_value = {}

    score_breakdown = {
        key: _clamp_score(breakdown_value.get(key), fallback_breakdown[key])
        for key in BREAKDOWN_KEYS
    }

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["score_agent"] = llm_result

    return {
        **state,
        "risk_score": risk_score,
        "risk_level": risk_level_from_score(risk_score) if risk_level not in {"低风险", "轻微风险", "中风险", "高风险", "极高风险"} else risk_level,
        "score_breakdown": score_breakdown,
        "raw_agent_outputs": raw_outputs,
    }
