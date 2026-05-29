from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agents.chat_agent.nodes import (
    RiskCaseState,
    adaptive_router_node,
    apply_validation_decision_node,
    build_scenario_contracts_node,
    conflict_validator_node,
    deterministic_decision_engine_node,
    fast_exit_report_node,
    fast_signal_scan_node,
    final_context_agents_node,
    low_risk_gate_node,
    merge_evaluation_results_node,
    normalize_input_node,
    parallel_scenario_evaluators_node,
    report_generator_node,
    targeted_evidence_extractor_node,
    validation_gate_node,
)
from app.state import CryptoRiskState


def _route_after_adaptive_router(state: RiskCaseState) -> Literal["fast_exit", "deep_analysis"]:
    return "fast_exit" if state.get("orchestration_path") == "fast_exit" else "deep_analysis"


def _route_after_low_risk_gate(state: RiskCaseState) -> Literal["fast_exit", "deep_analysis"]:
    return "fast_exit" if state.get("orchestration_path") == "fast_exit" else "deep_analysis"


def _route_after_validation_gate(state: RiskCaseState) -> Literal["need_validation", "no_validation"]:
    return "need_validation" if state.get("needs_validation") else "no_validation"


@lru_cache(maxsize=1)
def get_compiled_chat_graph():
    graph = StateGraph(RiskCaseState)
    graph.add_node("normalize_input", normalize_input_node)
    graph.add_node("fast_signal_scan", fast_signal_scan_node)
    graph.add_node("adaptive_router", adaptive_router_node)
    graph.add_node("low_risk_gate", low_risk_gate_node)
    graph.add_node("fast_exit_report", fast_exit_report_node)
    graph.add_node("build_scenario_contracts", build_scenario_contracts_node)
    graph.add_node("targeted_evidence_extractor", targeted_evidence_extractor_node)
    graph.add_node("parallel_scenario_evaluators", parallel_scenario_evaluators_node)
    graph.add_node("merge_evaluation_results", merge_evaluation_results_node)
    graph.add_node("deterministic_decision_engine", deterministic_decision_engine_node)
    graph.add_node("validation_gate", validation_gate_node)
    graph.add_node("conflict_validator", conflict_validator_node)
    graph.add_node("apply_validation_decision", apply_validation_decision_node)
    graph.add_node("final_context_agents", final_context_agents_node)
    graph.add_node("report_generator", report_generator_node)

    graph.add_edge(START, "normalize_input")
    graph.add_edge("normalize_input", "fast_signal_scan")
    graph.add_edge("fast_signal_scan", "adaptive_router")
    graph.add_conditional_edges(
        "adaptive_router",
        _route_after_adaptive_router,
        {
            "fast_exit": "low_risk_gate",
            "deep_analysis": "build_scenario_contracts",
        },
    )
    graph.add_conditional_edges(
        "low_risk_gate",
        _route_after_low_risk_gate,
        {
            "fast_exit": "fast_exit_report",
            "deep_analysis": "build_scenario_contracts",
        },
    )
    graph.add_edge("fast_exit_report", END)
    graph.add_edge("build_scenario_contracts", "targeted_evidence_extractor")
    graph.add_edge("targeted_evidence_extractor", "parallel_scenario_evaluators")
    graph.add_edge("parallel_scenario_evaluators", "merge_evaluation_results")
    graph.add_edge("merge_evaluation_results", "deterministic_decision_engine")
    graph.add_edge("deterministic_decision_engine", "validation_gate")
    graph.add_conditional_edges(
        "validation_gate",
        _route_after_validation_gate,
        {
            "need_validation": "conflict_validator",
            "no_validation": "final_context_agents",
        },
    )
    graph.add_edge("conflict_validator", "apply_validation_decision")
    graph.add_edge("apply_validation_decision", "final_context_agents")
    graph.add_edge("final_context_agents", "report_generator")
    graph.add_edge("report_generator", END)
    return graph.compile()


def run_chat_agent(user_message: str) -> dict[str, object]:
    state = get_compiled_chat_graph().invoke({"message": user_message, "errors": []})
    report = state.get("report")
    if not isinstance(report, dict):
        raise RuntimeError("chat graph finished without report")
    return report


class ChatWorkflow:
    def invoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        message = str(initial_state.get("original_text") or initial_state.get("message") or "")
        report = run_chat_agent(message)
        raw_outputs = dict(initial_state.get("raw_agent_outputs", {}))
        raw_outputs["chat_agent_adapter"] = {
            "engine": "chat_agent",
            "workflow": "evidence_contracted_case_graph",
        }
        return {
            **initial_state,
            "final_report": report,
            "raw_agent_outputs": raw_outputs,
        }

    async def ainvoke(self, initial_state: CryptoRiskState) -> CryptoRiskState:
        return self.invoke(initial_state)


def build_chat_workflow() -> ChatWorkflow:
    return ChatWorkflow()


chat_workflow = build_chat_workflow()
