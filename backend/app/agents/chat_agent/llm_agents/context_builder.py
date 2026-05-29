from __future__ import annotations

from app.agents.chat_agent.schemas import DecisionResult, RiskCaseInput, SignalScanResult


def build_final_context(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    decision: DecisionResult,
) -> dict[str, object]:
    branches = signal_scan.debug.get("risk_type_branches", [])
    established_branches = [
        branch
        for branch in branches
        if isinstance(branch, dict) and branch.get("established")
    ] if isinstance(branches, list) else []
    return {
        "raw_text": case_input.raw_text,
        "input_type": case_input.input_type,
        "entities": case_input.entities,
        "decision": decision.model_dump(),
        "is_weak_risk": decision.risk_score <= 20 or decision.risk_status == "low_risk",
        "has_established_risk": bool(established_branches),
        "raw_rule_scores": signal_scan.raw_rule_scores,
        "risk_type_stats": signal_scan.debug.get("risk_type_stats", []),
        "risk_type_branches": branches,
        "established_risk_type_branches": established_branches,
        "branch_score_merge": signal_scan.debug.get("branch_score_merge", {}),
        "low_risk_gate": signal_scan.debug.get("low_risk_gate", {}),
        "cap_signals": [signal.model_dump() for signal in signal_scan.cap_signals],
    }
