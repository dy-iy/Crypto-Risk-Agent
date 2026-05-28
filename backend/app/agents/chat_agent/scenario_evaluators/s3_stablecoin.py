from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing


def evaluate_s3(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S3_STABLECOIN_RESERVE")
    reasons: list[str] = []
    score = 0
    if is_confirmed(fields, "depeg_mentioned"):
        score = 58
        reasons.append("depeg_mentioned")
    if is_confirmed(fields, "reserve_issue"):
        score += 18
        reasons.append("reserve_issue")
    if is_confirmed(fields, "redemption_suspended"):
        score += 18
        reasons.append("redemption_suspended")
    if is_confirmed(fields, "issuer_statement"):
        score -= 8
        reasons.append("issuer_statement")

    score = clamp(score)
    return ScenarioEvaluation(
        scenario="S3_STABLECOIN_RESERVE",
        is_applicable=bool(reasons),
        scenario_score=score,
        confidence=0.72 if score >= 70 else 0.55 if reasons else 0.0,
        severity="high" if score >= 76 else "medium" if score >= 41 else "low",
        reason_codes=reasons,
        missing_evidence=missing(fields, ["depeg_price", "reserve_issue", "redemption_suspended"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
