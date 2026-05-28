from __future__ import annotations

from app.agents.chat_agent.schemas import EvidenceExtractionResult, RiskCaseInput, ScenarioEvaluation, SignalScanResult
from app.agents.chat_agent.scenario_evaluators.utils import clamp, confirmed_evidence, is_confirmed, missing


def evaluate_s5(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    evidence: EvidenceExtractionResult,
) -> ScenarioEvaluation:
    del case_input, signal_scan
    fields = evidence.by_scenario("S5_REGULATORY_ENFORCEMENT")
    reasons: list[str] = []
    score = 0
    cap: int | None = None

    has_regulator = is_confirmed(fields, "regulator")
    has_target = is_confirmed(fields, "target_entity")
    has_action = is_confirmed(fields, "enforcement_action") or is_confirmed(fields, "lawsuit_or_charge")
    if has_regulator:
        reasons.append("regulator")
    if has_target:
        reasons.append("target_entity")
    if has_action:
        reasons.append("enforcement_action")
    if has_regulator and has_target and has_action:
        score = 72
    elif has_action:
        score = 48

    if is_confirmed(fields, "penalty_or_freeze"):
        score += 10
        reasons.append("penalty_or_freeze")
    if is_confirmed(fields, "is_policy_discussion_only"):
        score = max(score, 18)
        cap = 30
        reasons.append("policy_discussion_only")
    if is_confirmed(fields, "is_positive_regulatory_clarity"):
        score = max(score, 12)
        cap = min(cap or 20, 20)
        reasons.append("positive_regulatory_clarity")

    score = clamp(score)
    if cap is not None:
        score = min(score, cap)

    return ScenarioEvaluation(
        scenario="S5_REGULATORY_ENFORCEMENT",
        is_applicable=bool(reasons) and score > 0,
        scenario_score=score,
        confidence=0.78 if has_regulator and has_target and has_action else 0.45 if reasons else 0.0,
        severity="high" if score >= 76 else "medium_high" if score >= 61 else "medium" if score >= 41 else "low",
        score_cap=cap,
        reason_codes=reasons,
        missing_evidence=missing(fields, ["regulator", "target_entity", "enforcement_action"]),
        evidence_summary=confirmed_evidence(fields, list(fields.keys())),
    )
