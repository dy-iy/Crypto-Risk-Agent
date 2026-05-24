from app.state import CryptoRiskState


def _default_summary(state: CryptoRiskState) -> str:
    if state.get("risk_status") == "no_risk":
        return "暂未从输入文本中发现明显加密货币风险信号。"

    categories = state.get("risk_categories", [])
    score = state.get("risk_score", 0)
    level = state.get("risk_level", "低风险")
    status = state.get("risk_status", "uncertain")
    category_text = "、".join(categories) if categories else state.get("primary_category") or "综合风险"
    return f"风险状态为 {status}，主要类别为{category_text}，综合风险评分为 {score}，风险等级为{level}。"


def _impact_to_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, dict):
            target = str(item.get("target", "")).strip()
            description = str(item.get("description", "")).strip()
            text = f"{target}：{description}" if target and description else target or description
            if text:
                output.append(text)
        elif str(item).strip():
            output.append(str(item).strip())
    return output


def report_agent(state: CryptoRiskState) -> CryptoRiskState:
    summary = str(state.get("risk_explanation") or _default_summary(state))
    impact = state.get("impact", [])
    advice = state.get("advice", [])

    if state.get("risk_status") == "no_risk":
        impact = []
        advice = ["继续核实信息来源，关注后续官方公告和链上数据变化。"]

    raw_outputs = state.get("raw_agent_outputs", {})
    raw_outputs["final_response_agent"] = {
        "summary": summary,
        "impact": impact,
        "advice": advice,
    }

    final_report = {
        "summary": summary,
        "input_type": state.get("input_type", "unknown"),
        "has_risk": state.get("risk_status") not in {"no_risk"},
        "risk_status": state.get("risk_status", "uncertain"),
        "risk_score": int(state.get("risk_score", 0)),
        "final_risk_score": int(state.get("final_risk_score", state.get("risk_score", 0))),
        "risk_level": state.get("risk_level", "低风险"),
        "risk_categories": state.get("risk_categories", []),
        "primary_category": state.get("primary_category"),
        "secondary_categories": state.get("secondary_categories", []),
        "classification_reason": state.get("classification_reason", ""),
        "classification_confidence": state.get("classification_confidence", "low"),
        "risk_signals": state.get("risk_signals", []),
        "non_risk_factors": state.get("non_risk_factors", []),
        "triage_confidence": state.get("triage_confidence", "low"),
        "entities": state.get("entities", {}),
        "keyword_refs": state.get("keyword_refs", []),
        "source_hint": state.get("source_hint", ""),
        "supporting_evidence": state.get("supporting_evidence", []),
        "counter_evidence": state.get("counter_evidence", []),
        "missing_info": state.get("missing_info", []),
        "confirmed_facts": state.get("confirmed_facts", []),
        "uncertainty_points": state.get("uncertainty_points", []),
        "evidence_items": state.get("evidence_items", []),
        "evidence_quality": state.get("evidence_quality", "none"),
        "evidence": state.get("evidence", []),
        "severity_score": state.get("severity_score", 0),
        "confidence_score": state.get("confidence_score", 0),
        "urgency_score": state.get("urgency_score", 0),
        "contagion_score": state.get("contagion_score", 0),
        "score_breakdown": state.get("score_breakdown", {}),
        "score_reason": state.get("score_reason", ""),
        "score_factors": state.get("score_factors", {}),
        "score_confidence": state.get("score_confidence", "low"),
        "impact": _impact_to_strings(impact),
        "structured_impact": state.get("impact", []),
        "impact_scope": state.get("impact_scope", ""),
        "impact_severity": state.get("impact_severity", ""),
        "affected_entities": state.get("affected_entities", []),
        "affected_assets": state.get("affected_assets", []),
        "loss_estimate": state.get("loss_estimate", ""),
        "systemic_risk": state.get("systemic_risk", ""),
        "user_asset_risk": state.get("user_asset_risk", ""),
        "verified_claims": state.get("verified_claims", []),
        "unverified_claims": state.get("unverified_claims", []),
        "official_explanation": state.get("official_explanation", []),
        "missing_information": state.get("missing_information", []),
        "overclaiming_risks": state.get("overclaiming_risks", []),
        "advice": [str(item) for item in advice],
        "priority": state.get("priority", ""),
        "action_type": state.get("action_type", ""),
        "has_conflict": state.get("has_conflict", False),
        "review_issues": state.get("review_issues", []),
        "revision_suggestions": state.get("revision_suggestions", []),
        "calibration_rules": state.get("calibration_rules", []),
        "risk_explanation": state.get("risk_explanation", ""),
        "merged_result": state.get("merged_result", {}),
        "calibrated_result": state.get("calibrated_result", {}),
        "raw_agent_outputs": raw_outputs,
    }

    return {
        **state,
        "impact": final_report["impact"],
        "advice": final_report["advice"],
        "final_report": final_report,
        "raw_agent_outputs": raw_outputs,
    }
