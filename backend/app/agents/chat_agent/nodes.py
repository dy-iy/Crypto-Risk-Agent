from __future__ import annotations

from typing import TypedDict

from typing_extensions import NotRequired

from app.agents.chat_agent.contracts import build_contracts
from app.agents.chat_agent.core.decision import decide_from_summary
from app.agents.chat_agent.core.orchestrator import choose_route
from app.agents.chat_agent.core.report import build_report
from app.agents.chat_agent.core.scenario_router import build_hypotheses
from app.agents.chat_agent.core.summary import (
    build_evaluation_summary,
    build_fast_exit_decision,
    build_fast_exit_evaluation,
)
from app.agents.chat_agent.core.validator import need_validation, validate_conflicts
from app.agents.chat_agent.scenario_evaluators import evaluate_scenarios
from app.agents.chat_agent.schemas import (
    AnalysisPath,
    DecisionResult,
    EvidenceContract,
    EvidenceExtractionResult,
    EvaluationSummary,
    OrchestrationDecision,
    RiskCaseInput,
    RiskCaseResult,
    ScenarioEvaluation,
    ScenarioHypothesis,
    ScenarioId,
    SignalScanResult,
    ValidationSuggestion,
)
from app.agents.chat_agent.tools import extract_evidence, normalize_input, scan_fast_signals


class RiskCaseState(TypedDict):
    message: str
    case_input: NotRequired[RiskCaseInput]
    signal_scan: NotRequired[SignalScanResult]
    orchestration: NotRequired[OrchestrationDecision]
    orchestration_path: NotRequired[AnalysisPath]
    active_scenarios: NotRequired[list[ScenarioId]]
    initial_validation_hint: NotRequired[bool]
    hypotheses: NotRequired[list[ScenarioHypothesis]]
    contracts: NotRequired[list[EvidenceContract]]
    evidence: NotRequired[EvidenceExtractionResult]
    evaluations: NotRequired[list[ScenarioEvaluation]]
    merged_evaluations: NotRequired[list[ScenarioEvaluation]]
    evaluation_summary: NotRequired[EvaluationSummary]
    decision: NotRequired[DecisionResult]
    validation: NotRequired[ValidationSuggestion | None]
    report: NotRequired[dict[str, object]]
    report_mode: NotRequired[str]
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


def fast_exit_report_node(state: RiskCaseState) -> RiskCaseState:
    evaluations = [build_fast_exit_evaluation()]
    evidence = EvidenceExtractionResult(extraction_mode="fast_exit")
    decision = build_fast_exit_decision()
    result = RiskCaseResult(
        case_input=state["case_input"],
        signal_scan=state["signal_scan"],
        orchestration=state["orchestration"],
        hypotheses=[],
        contracts=[],
        evidence=evidence,
        evaluations=evaluations,
        decision=decision,
        validation=None,
    )
    report = build_report(result)
    report["report_mode"] = "fast_exit"
    chat_agent_result = report.get("chat_agent_result")
    if isinstance(chat_agent_result, dict):
        chat_agent_result["report_mode"] = "fast_exit"
    return {
        **state,
        "evaluations": evaluations,
        "merged_evaluations": evaluations,
        "evaluation_summary": build_evaluation_summary(evaluations),
        "evidence": evidence,
        "decision": decision,
        "validation": None,
        "report": report,
        "report_mode": "fast_exit",
    }


def build_scenario_contracts_node(state: RiskCaseState) -> RiskCaseState:
    active_scenarios = state.get("active_scenarios") or state["orchestration"].active_scenarios
    hypotheses = build_hypotheses(active_scenarios)
    return {
        **state,
        "active_scenarios": active_scenarios,
        "hypotheses": hypotheses,
        "contracts": build_contracts(hypotheses),
    }


def targeted_evidence_extractor_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "evidence": extract_evidence(state["case_input"], state.get("contracts", [])),
    }


def parallel_scenario_evaluators_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "evaluations": evaluate_scenarios(
            state["case_input"],
            state["signal_scan"],
            state["evidence"],
            state.get("hypotheses", []),
        ),
    }


def merge_evaluation_results_node(state: RiskCaseState) -> RiskCaseState:
    evaluation_summary = build_evaluation_summary(state.get("evaluations", []))
    return {
        **state,
        "merged_evaluations": evaluation_summary.merged_evaluations,
        "evaluation_summary": evaluation_summary,
    }


def deterministic_decision_engine_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "decision": decide_from_summary(state["signal_scan"], state["evaluation_summary"]),
    }


def validation_gate_node(state: RiskCaseState) -> RiskCaseState:
    decision = state["decision"]
    evaluation_summary = state["evaluation_summary"]
    return {
        **state,
        "needs_validation": bool(state.get("initial_validation_hint"))
        or need_validation(decision, evaluation_summary.merged_evaluations),
    }


def conflict_validator_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "validation": validate_conflicts(state["decision"], state["evidence"]),
    }


def apply_validation_decision_node(state: RiskCaseState) -> RiskCaseState:
    return {
        **state,
        "decision": decide_from_summary(state["signal_scan"], state["evaluation_summary"], state.get("validation")),
        "needs_validation": False,
    }


def report_generator_node(state: RiskCaseState) -> RiskCaseState:
    result = RiskCaseResult(
        case_input=state["case_input"],
        signal_scan=state["signal_scan"],
        orchestration=state["orchestration"],
        hypotheses=state.get("hypotheses", []),
        contracts=state.get("contracts", []),
        evidence=state.get("evidence", EvidenceExtractionResult()),
        evaluations=state.get("merged_evaluations", state.get("evaluations", [])),
        decision=state["decision"],
        validation=state.get("validation"),
    )
    report = build_report(result)
    report["report_mode"] = "full_case"
    chat_agent_result = report.get("chat_agent_result")
    if isinstance(chat_agent_result, dict):
        chat_agent_result["report_mode"] = "full_case"
    return {**state, "report": report, "report_mode": "full_case"}


adaptive_orchestrator_node = adaptive_router_node
scenario_router_and_contracts_node = build_scenario_contracts_node
decision_engine_node = deterministic_decision_engine_node
