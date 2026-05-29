from __future__ import annotations

from app.agents.chat_agent.schemas import (
    DecisionResult,
    EvaluationSummary,
    ScenarioEvaluation,
    SignalScanResult,
    ValidationSuggestion,
)
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_SCENARIO_MAP


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


def _branch_value(branch: dict[str, object], key: str, default=0):
    return branch.get(key, default)


def _eligible_secondary_bonus(branch: dict[str, object]) -> int:
    if not branch.get("established"):
        return 0
    confidence = float(_branch_value(branch, "confidence", 0.0))
    evidence_strength = int(_branch_value(branch, "evidence_strength", 0))
    if confidence < 0.45 or evidence_strength < 40:
        return 0
    score = int(_branch_value(branch, "branch_score", 0))
    if score >= 76:
        return 6
    if score >= 61:
        return 5
    if score >= 41:
        return 3
    return 1


def _decide_from_risk_type_branches(
    signal_scan: SignalScanResult,
    branches: list[dict[str, object]],
    validation: ValidationSuggestion | None = None,
) -> DecisionResult | None:
    established = [
        branch
        for branch in branches
        if branch.get("established") and int(_branch_value(branch, "branch_score", 0)) > 0
    ]
    if not established:
        return None

    ranked = sorted(
        established,
        key=lambda item: (
            int(_branch_value(item, "branch_score", 0)),
            int(_branch_value(item, "evidence_strength", 0)),
            float(_branch_value(item, "confidence", 0.0)),
        ),
        reverse=True,
    )
    primary = ranked[0]
    primary_type = str(primary.get("risk_type") or "")
    primary_scenario = RISK_SCENARIO_MAP.get(primary_type, "S0_GENERAL_UNKNOWN")
    primary_score = int(_branch_value(primary, "branch_score", 0))
    secondary_branches = ranked[1:]
    secondary_bonus = min(12, sum(_eligible_secondary_bonus(branch) for branch in secondary_branches))
    score = min(100, primary_score + secondary_bonus)
    pre_cap_score = score
    reason_codes = [
        "risk_type_branch_merge",
        f"primary_risk_type:{primary_type}",
    ]
    if secondary_bonus:
        reason_codes.append("secondary_risk_bonus")

    caps: list[str] = []
    hard_caps: list[str] = []
    soft_caps: list[str] = []
    cap_conflicts: list[str] = []
    floors: list[str] = []

    if validation:
        if validation.action == "raise_floor" and validation.score_floor is not None and score < validation.score_floor:
            score = validation.score_floor
            floors.append(f"validator:{validation.score_floor}")
            reason_codes.append("validator_raise_floor")

    has_strong_evidence = int(_branch_value(primary, "evidence_strength", 0)) >= 70 and float(_branch_value(primary, "confidence", 0.0)) >= 0.65
    for cap_signal in signal_scan.cap_signals:
        if cap_signal.score_cap is not None and score > cap_signal.score_cap:
            cap_id = f"{cap_signal.type}:{cap_signal.score_cap}"
            if cap_signal.cap_type == "hard_cap":
                score = cap_signal.score_cap
                caps.append(cap_id)
                hard_caps.append(cap_id)
                reason_codes.append(cap_signal.type)
                continue
            if has_strong_evidence:
                cap_conflicts.append(cap_id)
                continue
            score = cap_signal.score_cap
            caps.append(cap_id)
            soft_caps.append(cap_id)
            reason_codes.append(cap_signal.type)

    if validation and validation.action == "cap_score" and validation.score_cap is not None and score > validation.score_cap:
        score = validation.score_cap
        cap_id = f"validator:{validation.score_cap}"
        caps.append(cap_id)
        hard_caps.append(cap_id)
        reason_codes.append("validator_cap_score")

    secondary_scenarios: list[str] = []
    for branch in secondary_branches:
        risk_type = str(branch.get("risk_type") or "")
        scenario = RISK_SCENARIO_MAP.get(risk_type)
        if scenario and scenario != primary_scenario and scenario not in secondary_scenarios:
            secondary_scenarios.append(scenario)

    confidence = float(_branch_value(primary, "confidence", 0.0))
    if int(_branch_value(primary, "evidence_strength", 0)) < 40:
        confidence = min(confidence, 0.42)
        reason_codes.append("primary_branch_evidence_weak")

    score = max(0, min(100, int(round(score))))
    branch_score_merge = {
        "primary_risk_type": primary_type,
        "primary_risk_name": RISK_NAME_MAP.get(primary_type, "综合风险"),
        "primary_branch_score": primary_score,
        "secondary_bonus": secondary_bonus,
        "final_score": score,
        "secondary_risk_types": [str(branch.get("risk_type") or "") for branch in secondary_branches],
        "insufficient_evidence_types": [
            str(branch.get("risk_type") or "")
            for branch in branches
            if int(_branch_value(branch, "evidence_strength", 0)) < 40 or float(_branch_value(branch, "confidence", 0.0)) < 0.45
        ],
        "formula": "final=min(100, strongest_established_branch + capped_secondary_bonus); weak evidence branches receive reduced branch_score and no bonus",
    }
    signal_scan.debug["branch_score_merge"] = branch_score_merge

    return DecisionResult(
        risk_score=score,
        pre_cap_score=pre_cap_score,
        risk_level=risk_level_from_score(score),
        risk_status=_status_from_score(score, confidence, reason_codes),  # type: ignore[arg-type]
        primary_scenario=primary_scenario,
        secondary_scenarios=secondary_scenarios[:3],  # type: ignore[arg-type]
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
    branches = signal_scan.debug.get("risk_type_branches", [])
    if isinstance(branches, list) and branches:
        decision = _decide_from_risk_type_branches(signal_scan, branches, validation)
        if decision is not None:
            return decision
    return _decide_from_evaluations(signal_scan, evaluation_summary.merged_evaluations, validation)


def decide(
    signal_scan: SignalScanResult,
    evaluations: list[ScenarioEvaluation],
    validation: ValidationSuggestion | None = None,
) -> DecisionResult:
    return _decide_from_evaluations(signal_scan, evaluations, validation)
