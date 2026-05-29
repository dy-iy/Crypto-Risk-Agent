from __future__ import annotations

from app.agents.chat_agent.schemas import DecisionResult, SignalScanResult, ValidationSuggestion
from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP, RISK_SCENARIO_MAP


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


def build_fast_exit_decision() -> DecisionResult:
    return DecisionResult(
        risk_score=10,
        pre_cap_score=10,
        risk_level="低风险",
        risk_status="low_risk",
        primary_scenario="S0_GENERAL_UNKNOWN",
        confidence=0.75,
        reason_codes=["weak_rule_signal", "fast_exit"],
    )


def _status_from_score(score: int, confidence: float, reasons: list[str]) -> str:
    if "weak_rule_signal" in reasons:
        return "low_risk"
    if any(reason in reasons for reason in ["already_resolved", "mitigated_without_loss", "resolved_or_repaired"]):
        return "resolved_or_mitigated"
    if score <= 20:
        return "low_risk"
    if confidence < 0.45:
        return "insufficient_evidence"
    if "high_risk_floor_signal" in reasons and confidence < 0.65:
        return "potential_risk"
    if score >= 61:
        return "confirmed_risk"
    return "potential_risk"


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


def _high_risk_floor_candidates(signal_scan: SignalScanResult, risk_types: set[str] | None = None) -> list[dict[str, object]]:
    raw_candidates = signal_scan.debug.get("high_risk_floor_signals", [])
    if not isinstance(raw_candidates, list):
        return []
    candidates = [
        item
        for item in raw_candidates
        if isinstance(item, dict)
        and (risk_types is None or str(item.get("risk_type") or "") in risk_types)
        and int(_branch_value(item, "floor", 0)) > 0
    ]
    return sorted(
        candidates,
        key=lambda item: (int(_branch_value(item, "floor", 0)), int(_branch_value(item, "score_100", 0))),
        reverse=True,
    )


def _floor_signal_id(signal: dict[str, object]) -> str:
    risk_type = str(signal.get("risk_type") or "")
    floor = int(_branch_value(signal, "floor", 0))
    return f"high_risk_floor:{risk_type}:{floor}"


def decide_from_branches(
    signal_scan: SignalScanResult,
    validation: ValidationSuggestion | None = None,
) -> DecisionResult:
    branches = signal_scan.debug.get("risk_type_branches", [])
    if not isinstance(branches, list):
        branches = []

    established = [
        branch
        for branch in branches
        if isinstance(branch, dict) and branch.get("established") and int(_branch_value(branch, "branch_score", 0)) > 0
    ]
    if not established:
        floor_candidates = _high_risk_floor_candidates(signal_scan)
        if floor_candidates:
            floor_signal = floor_candidates[0]
            primary_type = str(floor_signal.get("risk_type") or "")
            score = int(_branch_value(floor_signal, "floor", 65))
            signal_scan.debug["branch_score_merge"] = {
                "primary_risk_type": primary_type,
                "primary_risk_name": RISK_NAME_MAP.get(primary_type, "综合风险"),
                "primary_branch_score": 0,
                "secondary_bonus": 0,
                "final_score": score,
                "secondary_risk_types": [],
                "high_risk_floors": floor_candidates,
                "formula": "strong high-risk signal floor applied when branch evidence was under-established",
            }
            return DecisionResult(
                risk_score=score,
                pre_cap_score=score,
                risk_level=risk_level_from_score(score),
                risk_status="potential_risk",
                primary_scenario=RISK_SCENARIO_MAP.get(primary_type, "S0_GENERAL_UNKNOWN"),
                confidence=0.55,
                reason_codes=[
                    "no_established_risk_type_branch",
                    "high_risk_floor_signal",
                    _floor_signal_id(floor_signal),
                ],
                score_floors_applied=[_floor_signal_id(floor_signal)],
            )
        return DecisionResult(
            risk_score=10,
            pre_cap_score=10,
            risk_level="低风险",
            risk_status="low_risk",
            primary_scenario="S0_GENERAL_UNKNOWN",
            confidence=0.65,
            reason_codes=["no_established_risk_type_branch"],
        )

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

    if validation and validation.action == "raise_floor" and validation.score_floor is not None and score < validation.score_floor:
        score = validation.score_floor
        floors.append(f"validator:{validation.score_floor}")
        reason_codes.append("validator_raise_floor")

    branch_types = {str(branch.get("risk_type") or "") for branch in established if isinstance(branch, dict)}
    floor_candidates = _high_risk_floor_candidates(signal_scan, branch_types)
    for floor_signal in floor_candidates:
        floor = int(_branch_value(floor_signal, "floor", 0))
        if score < floor:
            score = floor
            floors.append(_floor_signal_id(floor_signal))
            reason_codes.append("high_risk_floor_signal")
            reason_codes.append(_floor_signal_id(floor_signal))
            break
    pre_cap_score = max(pre_cap_score, score)

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
    if any(item.startswith("high_risk_floor:") for item in floors):
        confidence = max(confidence, 0.55)

    score = max(0, min(100, int(round(score))))
    branch_score_merge = {
        "primary_risk_type": primary_type,
        "primary_risk_name": RISK_NAME_MAP.get(primary_type, "综合风险"),
        "primary_branch_score": primary_score,
        "secondary_bonus": secondary_bonus,
        "final_score": score,
        "secondary_risk_types": [str(branch.get("risk_type") or "") for branch in secondary_branches],
        "high_risk_floors": floor_candidates,
        "insufficient_evidence_types": [
            str(branch.get("risk_type") or "")
            for branch in branches
            if isinstance(branch, dict)
            and (int(_branch_value(branch, "evidence_strength", 0)) < 40 or float(_branch_value(branch, "confidence", 0.0)) < 0.45)
        ],
        "formula": "final=max(strong_high_risk_floor, min(100, strongest_established_branch + capped_secondary_bonus)); caps may still reduce mitigated or false-positive contexts",
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


decide = decide_from_branches
