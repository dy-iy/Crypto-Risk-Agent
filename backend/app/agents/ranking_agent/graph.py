from app.agents.ranking_agent.news_risk_agent import news_risk_agent
from app.agents.ranking_agent.state import RankingAgentState, RankingOutputType
from app.tools.ranking_tools import (
    attach_coin_entities,
    build_coin_ranking_output,
    build_news_ranking_output,
    build_ranking_response,
    load_ranking_input,
    persist_scored_dataset,
    review_ranking_outputs,
)


class RankingWorkflow:
    def invoke(self, initial_state: RankingAgentState) -> RankingAgentState:
        state = load_ranking_input(initial_state)
        state = news_risk_agent(state)
        state = attach_coin_entities(state)
        state = persist_scored_dataset(state)
        state = build_news_ranking_output(state)
        state = build_coin_ranking_output(state)
        state = review_ranking_outputs(state)
        return build_ranking_response(state)


ranking_workflow = RankingWorkflow()


def run_ranking_agent(
    output_type: RankingOutputType = "all",
    date_filter: str | None = None,
    limit: int = 10,
) -> dict:
    initial_state: RankingAgentState = {
        "date_filter": date_filter,
        "limit": max(1, min(limit, 50)),
        "output_type": output_type,
    }
    result = ranking_workflow.invoke(initial_state)
    return result.get("response", {})
