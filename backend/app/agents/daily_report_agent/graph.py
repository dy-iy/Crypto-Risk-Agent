from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agents.daily_report_agent.nodes import (
    aggregate_daily_signals_node,
    finalize_daily_report_node,
    llm_daily_writer_node,
    load_daily_source_node,
    load_user_profile_node,
)
from app.agents.daily_report_agent.state import DailyReportState


@lru_cache(maxsize=1)
def get_compiled_daily_report_graph():
    graph = StateGraph(DailyReportState)
    graph.add_node("load_user_profile", load_user_profile_node)
    graph.add_node("load_daily_source", load_daily_source_node)
    graph.add_node("aggregate_daily_signals", aggregate_daily_signals_node)
    graph.add_node("llm_daily_writer", llm_daily_writer_node)
    graph.add_node("finalize_daily_report", finalize_daily_report_node)

    graph.add_edge(START, "load_user_profile")
    graph.add_edge("load_user_profile", "load_daily_source")
    graph.add_edge("load_daily_source", "aggregate_daily_signals")
    graph.add_edge("aggregate_daily_signals", "llm_daily_writer")
    graph.add_edge("llm_daily_writer", "finalize_daily_report")
    graph.add_edge("finalize_daily_report", END)
    return graph.compile()


def run_daily_report_agent(
    date_filter: str | None = "24h",
    user_id: str | None = None,
    user_display_name: str | None = None,
) -> dict[str, object]:
    normalized_date = date_filter if date_filter in {"24h", "7d"} else "24h"
    state = get_compiled_daily_report_graph().invoke(
        {
            "date_filter": normalized_date,
            "range": "7d" if normalized_date == "7d" else "24h",
            "user_id": user_id or "demo_user",
            "user_display_name": user_display_name or "",
            "errors": [],
        }
    )
    report = state.get("report")
    if not isinstance(report, dict):
        raise RuntimeError("daily report graph finished without report")
    return report
