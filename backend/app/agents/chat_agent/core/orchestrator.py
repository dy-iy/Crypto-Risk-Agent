from __future__ import annotations

from app.agents.chat_agent.core.scenario_router import select_active_scenarios
from app.agents.chat_agent.schemas import OrchestrationDecision, SignalScanResult


HIGH_RISK_SCENARIOS = {
    "S1_ATTACK_EXPLOIT",
    "S2_EXCHANGE_ABNORMALITY",
    "S3_STABLECOIN_RESERVE",
    "S5_REGULATORY_ENFORCEMENT",
}


def choose_route(signal_scan: SignalScanResult) -> OrchestrationDecision:
    if signal_scan.fast_exit_allowed:
        return OrchestrationDecision(
            path="fast_exit",
            needs_llm=False,
            reason_codes=["weak_rule_signal", "no_high_risk_scenario_detected"],
            active_scenarios=[],
        )

    active_scenarios = select_active_scenarios(signal_scan)
    max_score = max(signal_scan.scenario_scores.values(), default=0.0)
    has_high_risk_hint = any(
        scenario in HIGH_RISK_SCENARIOS and score >= 0.5
        for scenario, score in signal_scan.scenario_scores.items()
    )
    has_cap_conflict = bool(signal_scan.cap_signals and max_score >= 0.5)
    reason_codes = ["candidate_scenarios_detected"]
    if has_high_risk_hint:
        reason_codes.append("initial_high_risk_signal")
    if has_cap_conflict:
        reason_codes.append("initial_rule_evidence_conflict")

    return OrchestrationDecision(
        path="deep_analysis",
        needs_llm=True,
        needs_validation=False,
        initial_validation_hint=has_high_risk_hint or has_cap_conflict,
        active_scenarios=active_scenarios,
        reason_codes=reason_codes,
    )


def choose_path(signal_scan: SignalScanResult) -> OrchestrationDecision:
    return choose_route(signal_scan)
