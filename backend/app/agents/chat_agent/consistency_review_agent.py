from app.llm import call_llm_json
from app.prompts.review_prompt import build_review_prompt
from app.state import CryptoRiskState


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_score(score: int, low: int, high: int) -> int:
    return max(low, min(high, score))


def _apply_basic_revisions(state: CryptoRiskState, issues: list[str]) -> CryptoRiskState:
    status = state.get("risk_status", "uncertain")
    evidence_quality = state.get("evidence_quality", "none")
    score = int(state.get("risk_score", 0))
    next_score = score
    from app.agents.chat_agent.score_agent import _event_score_floor, risk_level_from_score

    event_floor = _event_score_floor(state)

    if event_floor and score < event_floor:
        issues.append(f"重大已确认风险事件评分低于校准下限 {event_floor}，已上调评分。")
        next_score = event_floor

    if status == "no_risk" and next_score > 10:
        issues.append("risk_status 为 no_risk，但评分高于 10，已下调评分。")
        next_score = 10
    if status == "potential_risk" and next_score > 35 and not event_floor:
        issues.append("risk_status 为 potential_risk，但评分高于推荐区间，已下调到 35。")
        next_score = 35
    if evidence_quality == "none" and next_score > 45 and not event_floor:
        issues.append("evidence_quality 为 none，但评分偏高，已下调到 45。")
        next_score = min(next_score, 45)

    if next_score != score:
        return {**state, "risk_score": _clamp_score(next_score, 0, 100), "risk_level": risk_level_from_score(next_score)}
    return state


def consistency_review_agent(state: CryptoRiskState) -> CryptoRiskState:
    triage_result = {
        "risk_status": state.get("risk_status", "uncertain"),
        "risk_summary": state.get("risk_summary", ""),
        "risk_signals": state.get("risk_signals", []),
        "non_risk_factors": state.get("non_risk_factors", []),
        "confidence": state.get("triage_confidence", "low"),
    }
    evidence_result = {
        "supporting_evidence": state.get("supporting_evidence", []),
        "counter_evidence": state.get("counter_evidence", []),
        "missing_info": state.get("missing_info", []),
        "evidence_quality": state.get("evidence_quality", "none"),
    }
    classification_result = {
        "primary_category": state.get("primary_category"),
        "secondary_categories": state.get("secondary_categories", []),
        "classification_reason": state.get("classification_reason", ""),
        "classification_confidence": state.get("classification_confidence", "low"),
    }
    score_result = {
        "risk_score": state.get("risk_score", 0),
        "risk_level": state.get("risk_level", "低风险"),
        "score_reason": state.get("score_reason", ""),
        "score_factors": state.get("score_factors", {}),
        "confidence": state.get("score_confidence", "low"),
    }
    impact_result = {
        "impact": state.get("impact", []),
        "impact_scope": state.get("impact_scope", ""),
        "impact_severity": state.get("impact_severity", ""),
    }
    advice_result = {
        "advice": state.get("advice", []),
        "priority": state.get("priority", ""),
        "action_type": state.get("action_type", ""),
    }
    llm_result = call_llm_json(
        build_review_prompt(
            state.get("raw_text", state.get("original_text", "")),
            triage_result,
            evidence_result,
            classification_result,
            score_result,
            impact_result,
            advice_result,
        )
    )

    issues = _string_list(llm_result.get("issues"))
    suggestions = _string_list(llm_result.get("revision_suggestions"))
    revised_state = _apply_basic_revisions(state, issues)
    has_conflict = bool(llm_result.get("has_conflict", False)) or bool(issues)

    raw_outputs = revised_state.get("raw_agent_outputs", {})
    raw_outputs["consistency_review_agent"] = llm_result
    return {
        **revised_state,
        "has_conflict": has_conflict,
        "review_issues": issues,
        "revision_suggestions": suggestions,
        "raw_agent_outputs": raw_outputs,
    }
