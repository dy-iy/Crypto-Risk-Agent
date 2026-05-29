from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

from app.agents.chat_agent.core.decision import build_fast_exit_decision, decide_from_branches
from app.agents.chat_agent.core.orchestrator import choose_route
from app.agents.chat_agent.core.report import build_report
from app.agents.chat_agent.core.validator import need_validation, validate_conflicts
from app.agents.chat_agent.llm_agents import (
    analyze_risk_type_branches,
    review_low_risk_route,
    run_final_context_agents,
)
from app.agents.chat_agent.schemas import (
    AnalysisPath,
    DecisionResult,
    EvidenceExtractionResult,
    OrchestrationDecision,
    RiskCaseInput,
    RiskCaseResult,
    ScenarioId,
    SignalScanResult,
    ValidationSuggestion,
)
from app.agents.chat_agent.tools import normalize_input, scan_fast_signals


class RiskCaseState(TypedDict):
    message: str
    case_input: NotRequired[RiskCaseInput]
    signal_scan: NotRequired[SignalScanResult]
    orchestration: NotRequired[OrchestrationDecision]
    orchestration_path: NotRequired[AnalysisPath]
    active_scenarios: NotRequired[list[ScenarioId]]
    initial_validation_hint: NotRequired[bool]
    evidence: NotRequired[EvidenceExtractionResult]
    risk_type_branches: NotRequired[list[dict[str, object]]]
    decision: NotRequired[DecisionResult]
    validation: NotRequired[ValidationSuggestion | None]
    final_context_agents: NotRequired[dict[str, object]]
    report: NotRequired[dict[str, object]]
    report_mode: NotRequired[str]
    low_risk_gate: NotRequired[dict[str, object]]
    errors: NotRequired[list[str]]
    needs_validation: NotRequired[bool]


def _errors(state: RiskCaseState) -> list[str]:
    return list(state.get("errors", []))


def normalize_input_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "case_input": normalize_input(state["message"]),
        "errors": _errors(state),
    }


def fast_signal_scan_node(state: RiskCaseState) -> RiskCaseState:
    case_input = state["case_input"]
    return {
        **state,
        "signal_scan": scan_fast_signals(case_input.content),
    }


def adaptive_router_node(state: RiskCaseState) -> RiskCaseState:
    orchestration = choose_route(state["signal_scan"])
    return {
        **state,
        "orchestration": orchestration,
        "orchestration_path": orchestration.path,
        "active_scenarios": orchestration.active_scenarios,
        "initial_validation_hint": orchestration.initial_validation_hint,
        "needs_validation": False,
    }


def fast_exit_decision_node(state: RiskCaseState) -> RiskCaseState:
    evidence = EvidenceExtractionResult(extraction_mode="fast_exit")
    decision = build_fast_exit_decision()
    return {
        **state,
        "evidence": evidence,
        "decision": decision,
        "validation": None,
        "report_mode": "fast_exit",
    }


def risk_type_branch_analysis_node(state: RiskCaseState) -> RiskCaseState:
    signal_scan, evidence, branches = analyze_risk_type_branches(
        state["case_input"],
        state["signal_scan"],
    )
    return {
        **state,
        "signal_scan": signal_scan,
        "evidence": evidence,
        "risk_type_branches": branches,
    }


def deterministic_decision_engine_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "decision": decide_from_branches(state["signal_scan"]),
    }


def validation_gate_node(state: RiskCaseState) -> RiskCaseState:
    decision = state["decision"]
    return {
        **state,
        "needs_validation": bool(state.get("initial_validation_hint")) or need_validation(decision),
    }


def conflict_validator_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "validation": validate_conflicts(state["decision"], state["evidence"]),
    }


def apply_validation_decision_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "decision": decide_from_branches(state["signal_scan"], state.get("validation")),
        "needs_validation": False,
    }


def final_context_agents_node(state: RiskCaseState) -> RiskCaseState:
    final_outputs = run_final_context_agents(
        state["case_input"],
        state["signal_scan"],
        state["decision"],
    )
    signal_scan = state["signal_scan"].model_copy(
        update={
            "debug": {
                **state["signal_scan"].debug,
                "final_context_agents": final_outputs,
            }
        }
    )
    return {
        **state,
        "signal_scan": signal_scan,
        "final_context_agents": final_outputs,
    }


def report_generator_node(state: RiskCaseState) -> RiskCaseState:
    report_mode = str(state.get("report_mode") or "full_case")
    result = RiskCaseResult(
        case_input=state["case_input"],
        signal_scan=state["signal_scan"],
        orchestration=state["orchestration"],
        evidence=state.get("evidence", EvidenceExtractionResult()),
        decision=state["decision"],
        validation=state.get("validation"),
    )
    report = build_report(result)
    report["report_mode"] = report_mode
    chat_agent_result = report.get("chat_agent_result")
    if isinstance(chat_agent_result, dict):
        chat_agent_result["report_mode"] = report_mode
    return {**state, "report": report, "report_mode": report_mode}


adaptive_orchestrator_node = adaptive_router_node
decision_engine_node = deterministic_decision_engine_node


def low_risk_gate_node(state: RiskCaseState) -> RiskCaseState:
    signal_scan, gate, active_scenarios = review_low_risk_route(state["case_input"], state["signal_scan"])
    if gate.get("escalate_to_high_risk"):
        orchestration = state["orchestration"].model_copy(
            update={
                "path": "deep_analysis",
                "needs_llm": True,
                "initial_validation_hint": True,
                "active_scenarios": active_scenarios,
                "reason_codes": list(
                    dict.fromkeys(
                        state["orchestration"].reason_codes
                        + ["low_risk_gate_escalated"]
                        + [f"low_risk_gate_added:{risk_type}" for risk_type in gate.get("added_risk_types", [])]
                    )
                ),
            }
        )
        return {
            **state,
            "signal_scan": signal_scan,
            "low_risk_gate": gate,
            "orchestration": orchestration,
            "orchestration_path": "deep_analysis",
            "active_scenarios": active_scenarios,
            "initial_validation_hint": True,
        }
    return {
        **state,
        "signal_scan": signal_scan,
        "low_risk_gate": gate,
        "orchestration_path": "fast_exit",
    }
