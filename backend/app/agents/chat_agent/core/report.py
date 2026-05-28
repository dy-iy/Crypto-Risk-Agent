from __future__ import annotations

from app.agents.chat_agent.schemas import RiskCaseResult, ScenarioEvaluation


SCENARIO_CATEGORY_MAP = {
    "S0_GENERAL_UNKNOWN": "综合风险",
    "S1_ATTACK_EXPLOIT": "链上漏洞 / 攻击风险",
    "S2_EXCHANGE_ABNORMALITY": "交易所与系统运维风险",
    "S3_STABLECOIN_RESERVE": "稳定币异常风险",
    "S4_INFRASTRUCTURE_FAILURE": "基础设施 / 协议层异常风险",
    "S5_REGULATORY_ENFORCEMENT": "监管与法律风险",
    "S6_MARKET_LIQUIDATION": "爆仓 / 清算风险",
    "S7_FRAUD_GOVERNANCE": "诈骗 / 跑路 / Rug Pull 风险",
    "S8_WHALE_ONCHAIN_FLOW": "大额转账 / 巨鲸行为风险",
}


def _confidence_label(confidence: float) -> str:
    if confidence >= 0.75:
        return "高"
    if confidence >= 0.5:
        return "中"
    return "低"


def _summary(result: RiskCaseResult) -> str:
    decision = result.decision
    category = SCENARIO_CATEGORY_MAP.get(decision.primary_scenario, "综合风险")
    if decision.risk_status == "low_risk":
        return "未发现明确高危加密资产风险事件，当前文本更适合低风险监测。"
    if decision.risk_status == "insufficient_evidence":
        return f"文本存在{category}相关信号，但关键证据不足，暂不宜直接判定为已确认高风险。"
    if decision.risk_status == "resolved_or_mitigated":
        return f"文本涉及{category}，但包含已恢复、已修复或缓和证据，风险被限制。"
    return f"文本触发{category}场景，风险评分为 {decision.risk_score}/100，等级为{decision.risk_level}。"


def _evidence_items(evaluations: list[ScenarioEvaluation]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for evaluation in evaluations:
        category = SCENARIO_CATEGORY_MAP.get(evaluation.scenario, "综合风险")
        for text in evaluation.evidence_summary:
            items.append(
                {
                    "risk_category": category,
                    "evidence_text": text,
                    "explanation": ",".join(evaluation.reason_codes[:3]) or "evidence_contract",
                }
            )
    return items[:8]


def _impact(decision_score: int, category: str) -> list[str]:
    if decision_score <= 20:
        return ["当前缺少明确风险事件证据，主要影响是持续监测和信息核验。"]
    if "交易所" in category:
        return ["可能影响用户提现、充值、交易可用性和平台流动性信心。"]
    if "链上漏洞" in category:
        return ["可能影响协议资金池、用户资产安全和相关代币市场信心。"]
    if "监管" in category:
        return ["可能影响目标实体合规状态、服务可用性和相关资产交易情绪。"]
    if "稳定币" in category:
        return ["可能影响稳定币锚定、赎回预期和 DeFi 交易对流动性。"]
    if "基础设施" in category:
        return ["可能影响链上交易确认、协议可用性、跨链/预言机依赖和用户操作连续性。"]
    if "诈骗" in category or "治理" in category:
        return ["可能导致用户授权、钱包资产或项目流动性受损，并引发社区信任下降。"]
    if "巨鲸" in category:
        return ["可能影响短期市场情绪、交易所流动性和潜在抛压预期。"]
    if "清算" in category or "行情" in category:
        return ["可能放大短期波动、杠杆清算和市场流动性压力。"]
    return ["可能影响相关项目、资产或市场参与者的风险预期。"]


def _advice(decision_score: int, status: str) -> list[str]:
    if status in {"low_risk", "false_positive_suppressed"}:
        return ["继续跟踪官方公告和链上数据，暂不基于单条文本做高风险处置。"]
    if status == "insufficient_evidence":
        return ["补充官方公告、链上交易哈希、交易所状态页或监管文件后再升级判断。"]
    if decision_score >= 76:
        return ["优先核验官方公告、链上资金流向和影响范围，必要时降低相关平台或资产风险暴露。"]
    return ["持续监控事件进展，重点核验缺失证据和反向缓和信息。"]


def build_report(result: RiskCaseResult) -> dict[str, object]:
    decision = result.decision
    category = SCENARIO_CATEGORY_MAP.get(decision.primary_scenario, "综合风险")
    categories = [category]
    for scenario in decision.secondary_scenarios:
        next_category = SCENARIO_CATEGORY_MAP.get(scenario, "综合风险")
        if next_category not in categories:
            categories.append(next_category)

    confidence_score = int(round(decision.confidence * 100))
    severity = decision.risk_score
    chat_agent_result = {
        "engine": "CryptoRisk Evidence-Contracted Case Engine",
        "primary_scenario": decision.primary_scenario,
        "secondary_scenarios": decision.secondary_scenarios,
        "confidence": decision.confidence,
        "orchestration_path": result.orchestration.path,
        "pre_cap_score": decision.pre_cap_score,
        "extraction_mode": result.evidence.extraction_mode,
        "llm_call_count": result.evidence.llm_call_count,
        "fallback_count": result.evidence.fallback_count,
        "json_parse_error_count": result.evidence.json_parse_error_count,
        "validation": result.validation.model_dump() if result.validation else None,
    }
    report = {
        "summary": _summary(result),
        "input_type": result.case_input.input_type,
        "has_risk": decision.risk_status not in {"low_risk", "false_positive_suppressed"},
        "risk_status": decision.risk_status,
        "risk_score": decision.risk_score,
        "final_risk_score": decision.risk_score,
        "risk_level": decision.risk_level,
        "confidence_score": confidence_score,
        "confidence_level": _confidence_label(decision.confidence),
        "risk_categories": categories,
        "primary_category": category,
        "secondary_categories": categories[1:],
        "risk_signals": decision.reason_codes,
        "non_risk_factors": [signal.reason for signal in result.signal_scan.cap_signals if signal.reason],
        "evidence": _evidence_items(result.evaluations),
        "score_breakdown": {
            "severity": severity,
            "evidence_strength": confidence_score,
            "impact_scope": min(100, severity + 5 if severity >= 61 else severity),
            "urgency": severity if severity >= 41 else max(10, severity - 5),
            "reversibility": max(0, 100 - severity),
        },
        "impact": _impact(decision.risk_score, category),
        "advice": _advice(decision.risk_score, decision.risk_status),
        "missing_info": sorted({missing for item in result.evaluations for missing in item.missing_evidence})[:8],
        "uncertainty_points": result.evidence.extraction_errors,
        "score_reason": "；".join(decision.reason_codes),
        "calibration_rules": decision.score_caps_applied + decision.score_floors_applied,
        "chat_agent_result": chat_agent_result,
        "debug": {
            "signal_scan": result.signal_scan.model_dump(),
            "decision": result.decision.model_dump(),
            "scenario_evaluations": [item.model_dump() for item in result.evaluations],
            "evidence_extraction": {
                "mode": result.evidence.extraction_mode,
                "llm_call_count": result.evidence.llm_call_count,
                "fallback_count": result.evidence.fallback_count,
                "json_parse_error_count": result.evidence.json_parse_error_count,
                "errors": result.evidence.extraction_errors,
            },
            "evidence_errors": result.evidence.extraction_errors,
        },
    }
    if not report["evidence"]:
        report["evidence"] = [
            {
                "risk_category": category,
                "evidence_text": "当前文本未提供可确认关键字段的原文证据。",
                "explanation": "insufficient_evidence",
            }
        ]
    return report
