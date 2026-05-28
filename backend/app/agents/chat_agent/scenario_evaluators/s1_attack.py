from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, is_denied, missing, numeric_value


def evaluate_s1(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S1_ATTACK_EXPLOIT")
    score = 0
    reasons: list[str] = []
    cap: int | None = None
    floor: int | None = None

    exploit = is_confirmed(fields, "exploit_occurred")
    loss_usd = numeric_value(fields, "loss_usd")
    user_fund = is_confirmed(fields, "user_fund_affected")
    attack_vector = is_confirmed(fields, "attack_vector")
    research_only = is_confirmed(fields, "is_security_research_only")
    historical = is_confirmed(fields, "is_historical_event")
    mitigated = is_confirmed(fields, "mitigation_status")
    no_official = is_denied(fields, "official_confirmation")

    if exploit:
        score = 62
        reasons.append("exploit_occurred")
    if attack_vector:
        score = max(score, 58)
        reasons.append("attack_vector")
    if loss_usd:
        score = max(score, 72)
        reasons.append("loss_usd")
        if loss_usd >= 100_000_000:
            floor = 82
        elif loss_usd >= 10_000_000:
            floor = 76
    if user_fund:
        score += 8
        reasons.append("user_fund_affected")

    if research_only:
        score = max(score, 25)
        cap = 45
        reasons.append("security_research_only")
    if historical:
        cap = min(cap or 45, 45)
        reasons.append("historical_event")
    if mitigated and not loss_usd:
        cap = min(cap or 40, 40)
        reasons.append("mitigated_without_loss")
    if no_official and not loss_usd:
        cap = min(cap or 50, 50)
        reasons.append("official_confirmation_denied")

    if not reasons:
        score = 0

    score = clamp(max(score, floor or 0))
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S1_ATTACK_EXPLOIT",
        is_applicable=bool(reasons),
        scenario_score=score,
        confidence=0.82 if exploit and (loss_usd or user_fund) else 0.55 if reasons else 0.0,
        severity="high" if score >= 76 else "medium" if score >= 45 else "low",
        score_cap=cap,
        score_floor=floor,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["exploit_occurred", "loss_usd", "user_fund_affected"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
