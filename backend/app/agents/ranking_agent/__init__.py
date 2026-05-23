def run_ranking_agent(
    output_type: str = "all",
    date_filter: str | None = None,
    limit: int = 10,
) -> dict[str, object]:
    from app.agents.ranking_agent.graph import run_ranking_agent as _run_ranking_agent

    return _run_ranking_agent(output_type, date_filter, limit)

__all__ = ["run_ranking_agent"]
