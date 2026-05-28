from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing


def evaluate_s4(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S4_INFRASTRUCTURE_FAILURE")
    score = 0
    reasons: list[str] = []
    cap: int | None = None

    if is_confirmed(fields, "network_outage"):
        score = max(score, 66)
        reasons.append("network_outage")
    if is_confirmed(fields, "block_production_stopped"):
        score = max(score, 72)
        reasons.append("block_production_stopped")
    if is_confirmed(fields, "oracle_failure"):
        score = max(score, 68)
        reasons.append("oracle_failure")
    if is_confirmed(fields, "bridge_paused"):
        score = max(score, 58)
        reasons.append("bridge_paused")
    if is_confirmed(fields, "rpc_or_node_failure"):
        score = max(score, 52)
        reasons.append("rpc_or_node_failure")
    if is_confirmed(fields, "user_transactions_affected"):
        score += 8
        reasons.append("user_transactions_affected")
    if is_confirmed(fields, "funds_at_risk"):
        score += 10
        reasons.append("funds_at_risk")
    if is_confirmed(fields, "already_resolved"):
        score = max(score - 25, 20)
        cap = 45
        reasons.append("already_resolved")

    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S4_INFRASTRUCTURE_FAILURE",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.78 if score >= 60 else 0.55 if reasons else 0.0,
        severity="high" if score >= 76 else "medium_high" if score >= 61 else "medium" if score >= 41 else "low",
        score_cap=cap,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["affected_chain_or_protocol", "user_transactions_affected", "funds_at_risk"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
