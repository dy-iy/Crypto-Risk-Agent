from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.agents.chat_agent.llm_agents.context_builder import build_final_context
from app.agents.chat_agent.llm_agents.impact_object_agent import analyze_impact_objects
from app.agents.chat_agent.llm_agents.risk_advice_agent import generate_risk_advice
from app.agents.chat_agent.schemas import DecisionResult, RiskCaseInput, SignalScanResult


def run_final_context_agents(
    case_input: RiskCaseInput,
    signal_scan: SignalScanResult,
    decision: DecisionResult,
) -> dict[str, object]:
    context = build_final_context(case_input, signal_scan, decision)
    with ThreadPoolExecutor(max_workers=2) as executor:
        impact_future = executor.submit(analyze_impact_objects, context)
        advice_future = executor.submit(generate_risk_advice, context)
        impact = impact_future.result()
        advice = advice_future.result()
    return {
        "impact_analysis": impact,
        "advice_generation": advice,
        "context_keys": list(context.keys()),
        "is_weak_risk": bool(context.get("is_weak_risk")),
        "has_established_risk": bool(context.get("has_established_risk")),
    }
