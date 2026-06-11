from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from app.agents.ranking_agent.news_risk_agent import news_risk_agent
from app.agents.ranking_agent.state import RankingAgentState, RankingOutputType
from app.services.data_loader import DATA_PATH, SCORED_DATA_PATH
from app.tools.ranking_tools import (
    attach_coin_entities,
    build_coin_ranking_output,
    build_news_ranking_output,
    build_ranking_response,
    load_ranking_input,
    persist_scored_dataset,
    review_ranking_outputs,
    select_candidate_news_for_coin_output,
    select_limited_news_for_news_output,
)


class RankingWorkflow:
    def invoke(self, initial_state: RankingAgentState) -> RankingAgentState:
        state = load_ranking_input(initial_state)
        state = news_risk_agent(state)
        state = persist_scored_dataset(state)
        state = select_limited_news_for_news_output(state)
        state = select_candidate_news_for_coin_output(state)
        state = attach_coin_entities(state)
        output_type = state.get("output_type", "all")
        if output_type in {"overview", "news", "all"}:
            state = build_news_ranking_output(state)
        if output_type in {"overview", "coins", "all"}:
            state = build_coin_ranking_output(state)
        state = review_ranking_outputs(state)
        return build_ranking_response(state)


ranking_workflow = RankingWorkflow()


def _path_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _invoke_ranking_workflow(
    output_type: RankingOutputType,
    date_filter: str | None,
    normalized_limit: int,
    score_missing: bool,
    progress_callback=None,
) -> dict:
    initial_state: RankingAgentState = {
        "date_filter": date_filter,
        "limit": normalized_limit,
        "output_type": output_type,
        "score_missing": score_missing,
    }
    if progress_callback:
        initial_state["progress_callback"] = progress_callback
    result = ranking_workflow.invoke(initial_state)
    return result.get("response", {})


@lru_cache(maxsize=64)
def _run_cached_ranking_agent(
    output_type: RankingOutputType,
    date_filter: str | None,
    normalized_limit: int,
    raw_signature: tuple[str, int, int],
    scored_signature: tuple[str, int, int],
) -> dict:
    del raw_signature, scored_signature
    return _invoke_ranking_workflow(
        output_type=output_type,
        date_filter=date_filter,
        normalized_limit=normalized_limit,
        score_missing=False,
    )


def run_ranking_agent(
    output_type: RankingOutputType = "all",
    date_filter: str | None = None,
    limit: int = 10,
    progress_callback=None,
    score_missing: bool = True,
) -> dict:
    normalized_limit = 0 if limit <= 0 else min(limit, 5000)
    if not score_missing and progress_callback is None:
        return deepcopy(
            _run_cached_ranking_agent(
                output_type,
                date_filter,
                normalized_limit,
                _path_signature(DATA_PATH),
                _path_signature(SCORED_DATA_PATH),
            )
        )
    return _invoke_ranking_workflow(output_type, date_filter, normalized_limit, score_missing, progress_callback)
