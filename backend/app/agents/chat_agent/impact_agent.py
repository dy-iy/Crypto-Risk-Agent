from app.llm import call_llm_json
from app.prompts.impact_prompt import build_impact_prompt
from app.state import CryptoRiskState


IMPACT_SCOPES = {"none", "short_term", "long_term", "protocol", "market", "systemic"}
IMPACT_SEVERITIES = {"none", "low", "medium", "high"}


def _impact_list(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    output: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        description = str(item.get("description", "")).strip()
        if target or description:
            output.append({"target": target or "待确认对象", "description": description})
    return output[:6]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _bounded_level(value: object, default: str = "low") -> str:
    level = str(value or default)
    return level if level in IMPACT_SEVERITIES else default


def impact_agent(state: CryptoRiskState) -> CryptoRiskState:
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
        "evidence_items": state.get("evidence_items", []),
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
    llm_result = call_llm_json(
        build_impact_prompt(
            state.get("raw_text", state.get("original_text", "")),
            triage_result,
            evidence_result,
            classification_result,
            score_result,
        )
    )

    impact = _impact_list(llm_result.get("impact"))
    status = state.get("risk_status", "uncertain")
    if not impact and status in {"potential_risk", "uncertain"}:
        impact = [{"target": "风险认知", "description": "原文仅支持有限或潜在影响，短期直接金融冲击不足以确认。"}]
    elif not impact and status == "no_risk":
        impact = []

    impact_scope = str(llm_result.get("impact_scope") or ("none" if status == "no_risk" else "long_term"))
    if impact_scope not in IMPACT_SCOPES:
        impact_scope = "long_term"
    impact_severity = str(llm_result.get("impact_severity") or ("none" if status == "no_risk" else "low"))
    if impact_severity not in IMPACT_SEVERITIES:
        impact_severity = "low"

    affected_entities = _string_list(llm_result.get("affected_entities"))
    affected_assets = _string_list(llm_result.get("affected_assets"))
    entities = state.get("entities", {})
    if not affected_assets and isinstance(entities, dict):
        affected_assets = [*entities.get("tokens", []), *entities.get("chains", [])][:8]
    if not affected_entities and isinstance(entities, dict):
        affected_entities = [*entities.get("exchanges", []), *entities.get("projects", [])][:8]
    loss_estimate = str(llm_result.get("loss_estimate") or "")
    systemic_risk = _bounded_level(llm_result.get("systemic_risk"), "none" if status == "no_risk" else "low")
    user_asset_risk = _bounded_level(llm_result.get("user_asset_risk"), "none" if status == "no_risk" else "low")

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["impact_agent"] = llm_result
    return {
        **state,
        "impact": impact,
        "impact_scope": impact_scope,
        "impact_severity": impact_severity,
        "affected_entities": affected_entities,
        "affected_assets": affected_assets,
        "loss_estimate": loss_estimate,
        "systemic_risk": systemic_risk,
        "user_asset_risk": user_asset_risk,
        "raw_agent_outputs": raw_outputs,
    }
