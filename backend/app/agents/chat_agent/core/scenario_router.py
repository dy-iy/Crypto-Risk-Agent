from __future__ import annotations

from app.agents.chat_agent.schemas import ScenarioId, SignalScanResult


def select_active_scenarios(signal_scan: SignalScanResult) -> list[ScenarioId]:
    ranked = sorted(signal_scan.scenario_scores.items(), key=lambda item: item[1], reverse=True)
    top_k = max(1, min(4, signal_scan.suggested_top_k))
    selected = [scenario for scenario, score in ranked if score >= 0.08][:top_k]
    if "S0_GENERAL_UNKNOWN" not in selected:
        selected.append("S0_GENERAL_UNKNOWN")
    return selected
