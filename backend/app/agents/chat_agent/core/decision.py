from __future__ import annotations

from app.agents.chat_agent.schemas import (
    DecisionResult,
    EvaluationSummary,
    ScenarioEvaluation,
    SignalScanResult,
    ValidationSuggestion,
)


STRONG_EVIDENCE_REASONS = {
    "exploit_occurred",
    "loss_usd",
    "user_fund_affected",
    "withdrawal_suspended",
    "trading_halted",
    "enforcement_action",
    "penalty_or_freeze",
    "block_production_stopped",
    "funds_at_risk",
    "depeg_mentioned",
    "reserve_issue",
    "redemption_suspended",
    "liquidity_stress_mentioned",
    "rug_pull_or_exit",
    "funds_removed",
    "user_loss_confirmed",
}


def risk_level_from_score(score: int) -> str:
    if score >= 91:
        return "极高风险"
    if score >= 76:
        return "高风险"
    if score >= 61:
        return "中高风险"
    if score >= 41:
        return "中风险"
    if score >= 21:
        return "轻微风险"
    return "低风险"


def _status_from_score(score: int, confidence: float, reasons: list[str]) -> str:
    if "weak_rule_signal" in reasons:
        return "low_risk"
    if any(reason in reasons for reason in ["already_resolved", "mitigated_without_loss", "resolved_or_repaired"]):
        return "resolved_or_mitigated"
    if score <= 20:
        return "low_risk"
    if confidence < 0.45:
        return "insufficient_evidence"
    if score >= 61:
        return "confirmed_risk"
    return "potential_risk"


def _decide_from_evaluations(
    signal_scan: SignalScanResult,
    evaluations: list[ScenarioEvaluation],
    validation: ValidationSuggestion | None = None,
) -> DecisionResult:
    applicable = [item for item in evaluations if item.is_applicable]
    if not applicable:
        applicable = [item for item in evaluations if item.scenario == "S0_GENERAL_UNKNOWN"] or evaluations

    non_general = [item for item in applicable if item.scenario != "S0_GENERAL_UNKNOWN"]
    primary_pool = non_general or applicable
    primary = max(primary_pool, key=lambda item: (item.scenario_score, item.confidence))
    secondary = [
        item.scenario
        for item in sorted(applicable, key=lambda item: item.scenario_score, reverse=True)
        if item.scenario != primary.scenario and item.scenario_score >= 35
    ][:3]

    score = primary.scenario_score
    reason_codes = list(primary.reason_codes)
    confidence = primary.confidence
    caps: list[str] = []
    hard_caps: list[str] = []
    soft_caps: list[str] = []
    cap_conflicts: list[str] = []
    floors: list[str] = []

    bonus = min(10, sum(4 for item in applicable if item.scenario != primary.scenario and item.scenario_score >= 45))
    if bonus:
        score = min(100, score + bonus)
        reason_codes.append("secondary_risk_bonus")

    for evaluation in applicable:
        if evaluation.score_floor is not None and score < evaluation.score_floor:
            score = evaluation.score_floor
            floors.append(f"{evaluation.scenario}:{evaluation.score_floor}")

    if validation:
        if validation.action == "raise_floor" and validation.score_floor is not None and score < validation.score_floor:
            score = validation.score_floor
            floors.append(f"validator:{validation.score_floor}")
            reason_codes.append("validator_raise_floor")

    pre_cap_score = max(0, min(100, int(round(score))))

    for evaluation in applicable:
        if evaluation.score_cap is not None and score > evaluation.score_cap:
            score = evaluation.score_cap
            cap_id = f"{evaluation.scenario}:{evaluation.score_cap}"
            caps.append(cap_id)
            hard_caps.append(cap_id)

    if validation:
        if validation.action == "cap_score" and validation.score_cap is not None and score > validation.score_cap:
            score = validation.score_cap
            cap_id = f"validator:{validation.score_cap}"
            caps.append(cap_id)
            hard_caps.append(cap_id)
            reason_codes.append("validator_cap_score")

    has_strong_evidence = bool(floors) or any(reason in STRONG_EVIDENCE_REASONS for reason in reason_codes)
    for cap_signal in signal_scan.cap_signals:
        if cap_signal.score_cap is not None and score > cap_signal.score_cap:
            cap_id = f"{cap_signal.type}:{cap_signal.score_cap}"
            if cap_signal.cap_type == "hard_cap":
                score = cap_signal.score_cap
                caps.append(cap_id)
                hard_caps.append(cap_id)
                if cap_signal.type not in reason_codes:
                    reason_codes.append(cap_signal.type)
                continue
            if has_strong_evidence:
                cap_conflicts.append(cap_id)
                continue
            score = cap_signal.score_cap
            caps.append(cap_id)
            soft_caps.append(cap_id)
            if cap_signal.type not in reason_codes:
                reason_codes.append(cap_signal.type)

    if primary.missing_evidence:
        confidence = min(confidence, 0.65)
        if score >= 41 and confidence < 0.45:
            reason_codes.append("insufficient_evidence")

    score = max(0, min(100, int(round(score))))
    return DecisionResult(
        risk_score=score,
        pre_cap_score=pre_cap_score,
        risk_level=risk_level_from_score(score),
        risk_status=_status_from_score(score, confidence, reason_codes),  # type: ignore[arg-type]
        primary_scenario=primary.scenario,
        secondary_scenarios=secondary,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        reason_codes=list(dict.fromkeys(reason_codes)),
        score_caps_applied=caps,
        hard_caps_applied=hard_caps,
        soft_caps_applied=soft_caps,
        cap_conflicts=cap_conflicts,
        score_floors_applied=floors,
    )


def decide_from_summary(
    signal_scan: SignalScanResult,
    evaluation_summary: EvaluationSummary,
    validation: ValidationSuggestion | None = None,
) -> DecisionResult:
    return _decide_from_evaluations(signal_scan, evaluation_summary.merged_evaluations, validation)


def decide(
    signal_scan: SignalScanResult,
    evaluations: list[ScenarioEvaluation],
    validation: ValidationSuggestion | None = None,
) -> DecisionResult:
    return _decide_from_evaluations(signal_scan, evaluations, validation)
