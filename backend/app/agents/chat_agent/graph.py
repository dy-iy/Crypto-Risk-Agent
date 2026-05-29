from __future__ import annotations

from functools import lru_cache
from typing import Callable, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.chat_agent.nodes import (
    RiskCaseState,
    adaptive_router_node,
    apply_validation_decision_node,
    conflict_validator_node,
    deterministic_decision_engine_node,
    fast_exit_decision_node,
    fast_signal_scan_node,
    final_context_agents_node,
    low_risk_gate_node,
    normalize_input_node,
    report_generator_node,
    risk_type_branch_analysis_node,
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
    graph.add_node("fast_exit_decision", fast_exit_decision_node)
    graph.add_node("risk_type_branch_analysis", risk_type_branch_analysis_node)
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
            "deep_analysis": "risk_type_branch_analysis",
        },
    )
    graph.add_conditional_edges(
        "low_risk_gate",
        _route_after_low_risk_gate,
        {
            "fast_exit": "fast_exit_decision",
            "deep_analysis": "risk_type_branch_analysis",
        },
    )
    graph.add_edge("fast_exit_decision", "final_context_agents")
    graph.add_edge("risk_type_branch_analysis", "deterministic_decision_engine")
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


CHAT_PROGRESS_STAGES = {
    "input_standardization": {"index": 0, "label": "输入标准化"},
    "risk_signal_scan": {"index": 1, "label": "风险信号扫描"},
    "evidence_extraction": {"index": 2, "label": "提取证据"},
    "report_generation": {"index": 3, "label": "生成报告"},
}


def run_chat_agent_with_progress(
    user_message: str,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    def emit(stage: str) -> None:
        if not progress_callback:
            return
        meta = CHAT_PROGRESS_STAGES[stage]
        progress_callback({"stage": stage, **meta})

    state: RiskCaseState = {"message": user_message, "errors": []}

    emit("input_standardization")
    state = normalize_input_node(state)

    emit("risk_signal_scan")
    state = fast_signal_scan_node(state)
    state = adaptive_router_node(state)

    if _route_after_adaptive_router(state) == "fast_exit":
        state = low_risk_gate_node(state)
        if _route_after_low_risk_gate(state) == "fast_exit":
            emit("report_generation")
            state = fast_exit_decision_node(state)
            state = final_context_agents_node(state)
            state = report_generator_node(state)
            report = state.get("report")
            if not isinstance(report, dict):
                raise RuntimeError("chat graph finished without report")
            return report

    emit("evidence_extraction")
    state = risk_type_branch_analysis_node(state)
    state = deterministic_decision_engine_node(state)
    state = validation_gate_node(state)
    if _route_after_validation_gate(state) == "need_validation":
        state = conflict_validator_node(state)
        state = apply_validation_decision_node(state)

    emit("report_generation")
    state = final_context_agents_node(state)
    state = report_generator_node(state)
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
            "workflow": "risk_type_branch_graph",
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
