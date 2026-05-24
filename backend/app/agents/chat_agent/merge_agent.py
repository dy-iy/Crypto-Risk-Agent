from app.state import CryptoRiskState


def merge_results(state: CryptoRiskState) -> CryptoRiskState:
    merged_result = {
        "scoring": {
            "severity_score": state.get("severity_score", 0),
            "confidence_score": state.get("confidence_score", 0),
            "urgency_score": state.get("urgency_score", 0),
            "contagion_score": state.get("contagion_score", 0),
            "final_risk_score": state.get("final_risk_score", state.get("risk_score", 0)),
            "risk_level": state.get("risk_level", "低风险"),
            "score_reason": state.get("score_reason", ""),
            "score_factors": state.get("score_factors", {}),
        },
        "classification": {
            "primary_category": state.get("primary_category"),
            "secondary_categories": state.get("secondary_categories", []),
            "risk_categories": state.get("risk_categories", []),
            "classification_reason": state.get("classification_reason", ""),
            "classification_confidence": state.get("classification_confidence", "low"),
        },
        "impact": {
            "affected_entities": state.get("affected_entities", []),
            "affected_assets": state.get("affected_assets", []),
            "loss_estimate": state.get("loss_estimate", ""),
            "impact_scope": state.get("impact_scope", ""),
            "impact_severity": state.get("impact_severity", ""),
            "systemic_risk": state.get("systemic_risk", ""),
            "user_asset_risk": state.get("user_asset_risk", ""),
            "impact": state.get("impact", []),
        },
        "uncertainty": {
            "verified_claims": state.get("verified_claims", []),
            "unverified_claims": state.get("unverified_claims", []),
            "official_explanation": state.get("official_explanation", []),
            "missing_information": state.get("missing_information", []),
            "overclaiming_risks": state.get("overclaiming_risks", []),
        },
    }
    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["merge_results"] = merged_result
    return {
        **state,
        "merged_result": merged_result,
        "raw_agent_outputs": raw_outputs,
    }
