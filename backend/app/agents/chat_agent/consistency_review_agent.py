from app.llm import call_llm_json
from app.prompts.review_prompt import build_review_prompt
from app.state import CryptoRiskState


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp_score(score: int, low: int, high: int) -> int:
    return max(low, min(high, score))


def _rule_review_issues(state: CryptoRiskState) -> list[str]:
    issues: list[str] = []
    from app.agents.chat_agent.score_agent import _event_score_floor, risk_level_from_score

    status = state.get("risk_status", "uncertain")
    evidence_quality = state.get("evidence_quality", "none")
    score = int(state.get("risk_score", 0))
    event_floor = _event_score_floor(state)

    if event_floor and score < event_floor:
        issues.append(f"高危信号明显但评分偏低：当前 risk_score={score}，规则下限={event_floor}。")

    if status == "no_risk" and score > 10:
        issues.append("risk_status 为 no_risk，但 risk_score 高于 10。")
    if status == "potential_risk" and score > 35 and not event_floor:
        issues.append("risk_status 为 potential_risk，但 risk_score 高于推荐区间。")
    if evidence_quality == "none" and score > 45 and not event_floor:
        issues.append("evidence_quality 为 none，但 risk_score 偏高。")

    level = state.get("risk_level", "")
    expected_level = risk_level_from_score(score)
    if level and level != expected_level:
        issues.append(f"risk_level 与 risk_score 不一致：当前等级={level}，按分数应为={expected_level}。")
    return issues


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

    issues = list(dict.fromkeys([*_rule_review_issues(state), *_string_list(llm_result.get("issues"))]))
    suggestions = _string_list(llm_result.get("revision_suggestions"))
    has_conflict = bool(llm_result.get("has_conflict", False)) or bool(issues)
    structured_review_result = {
        "has_conflict": has_conflict,
        "issues": issues,
        "revision_suggestions": suggestions,
        "score_overridden": False,
    }

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["consistency_review_agent"] = {
        "llm_result": llm_result,
        "structured_review_result": structured_review_result,
    }
    return {
        **state,
        "has_conflict": has_conflict,
        "review_issues": issues,
        "revision_suggestions": suggestions,
        "structured_review_result": structured_review_result,
        "raw_agent_outputs": raw_outputs,
    }
