from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult


def evaluate_s0(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, evidence
    max_signal = max(signal_scan.scenario_scores.values(), default=0.0)
    if max_signal < 0.12:
        return ScenarioEvaluation(
            scenario="S0_GENERAL_UNKNOWN",
            is_applicable=True,
            scenario_score=10,
            confidence=0.75,
            severity="low",
            reason_codes=["weak_rule_signal", "no_specific_scenario_confirmed"],
            missing_evidence=["缺少明确攻击、提现异常、监管执法、脱锚或清算事实"],
        )
    return ScenarioEvaluation(
        scenario="S0_GENERAL_UNKNOWN",
        is_applicable=True,
        scenario_score=28,
        confidence=0.45,
        severity="low_medium",
        reason_codes=["fallback_general_risk"],
        missing_evidence=["具体风险场景证据不足"],
    )
