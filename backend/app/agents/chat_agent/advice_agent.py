from app.llm import call_llm_json
from app.prompts.advice_prompt import build_advice_prompt
from app.state import CryptoRiskState


BANNED_TERMS = ["买入", "卖出", "做空", "梭哈"]
PRIORITIES = {"none", "low", "medium", "high"}
ACTION_TYPES = {"none", "monitoring", "verification", "risk_reduction", "urgent_response"}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _sanitize_advice(items: list[str]) -> list[str]:
    return [item for item in items if not any(term in item for term in BANNED_TERMS)]


def advice_agent(state: CryptoRiskState) -> CryptoRiskState:
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
        "confirmed_facts": state.get("confirmed_facts", []),
        "risk_signals": state.get("risk_signals", []),
        "uncertainty_points": state.get("uncertainty_points", []),
        "verified_claims": state.get("verified_claims", []),
        "overclaiming_risks": state.get("overclaiming_risks", []),
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
        "severity_score": state.get("severity_score", 0),
        "confidence_score": state.get("confidence_score", 0),
        "urgency_score": state.get("urgency_score", 0),
        "contagion_score": state.get("contagion_score", 0),
        "calibrated_result": state.get("calibrated_result", {}),
        "confidence": state.get("score_confidence", "low"),
    }
    impact_result = {
        "impact": state.get("impact", []),
        "impact_scope": state.get("impact_scope", ""),
        "impact_severity": state.get("impact_severity", ""),
        "affected_entities": state.get("affected_entities", []),
        "affected_assets": state.get("affected_assets", []),
        "systemic_risk": state.get("systemic_risk", ""),
        "user_asset_risk": state.get("user_asset_risk", ""),
    }
    llm_result = call_llm_json(
        build_advice_prompt(
            state.get("raw_text", state.get("original_text", "")),
            triage_result,
            evidence_result,
            classification_result,
            score_result,
            impact_result,
        )
    )

    advice = _sanitize_advice(_string_list(llm_result.get("advice")))
    status = state.get("risk_status", "uncertain")
    if not advice:
        if status in {"no_risk", "potential_risk", "uncertain", "resolved_risk"}:
            advice = ["继续核验信息来源，关注官方公告、核心开发者或权威研究机构的后续说明。"]
        else:
            advice = ["优先核实官方公告、链上交易和资金流向，再评估是否需要降低相关风险暴露。"]

    priority = str(llm_result.get("priority") or ("low" if status in {"potential_risk", "uncertain", "resolved_risk"} else "medium"))
    if priority not in PRIORITIES:
        priority = "low"
    action_type = str(llm_result.get("action_type") or ("monitoring" if priority in {"none", "low"} else "verification"))
    if action_type not in ACTION_TYPES:
        action_type = "monitoring"

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["advice_agent"] = llm_result
    return {
        **state,
        "advice": advice[:7],
        "priority": priority,
        "action_type": action_type,
        "raw_agent_outputs": raw_outputs,
    }
