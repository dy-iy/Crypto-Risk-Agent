from app.agents.ranking_agent.state import RankingAgentState
from app.services.llm_news_risk_service import analyze_news_with_llm


def _is_complete_scored_item(item: dict[str, object]) -> bool:
    if item.get("llm_source") == "rule_fallback":
        return False
    return bool(
        item.get("risk_score") is not None
        and item.get("risk_level")
        and item.get("risk_type")
        and item.get("evidence")
    )


def news_risk_agent(state: RankingAgentState) -> RankingAgentState:
    if state.get("raw_dataset_empty"):
        return {
            **state,
            "scored_news": [],
        }

    scored_by_id = {
        str(item.get("news_id") or item.get("id")): item
        for item in state.get("scored_dataset", [])
        if _is_complete_scored_item(item)
    }
    missing_news = (
        [
            item
            for item in state.get("filtered_news", [])
            if str(item.get("news_id") or item.get("id")) not in scored_by_id
        ]
        if state.get("score_missing", True)
        else []
    )
    llm_analysis = (
        analyze_news_with_llm(missing_news, state.get("progress_callback"))
        if missing_news
        else {}
    )
    scored_news: list[dict[str, object]] = []

    for item in state.get("filtered_news", []):
        news_id = str(item.get("news_id") or item.get("id"))
        cached = scored_by_id.get(news_id)
        analysis = llm_analysis.get(news_id, {})
        source = cached or analysis
        risk_score = source.get("risk_score", 0)
        risk_level = source.get("risk_level", "低风险")
        risk_type = source.get("risk_type", "异常行情波动风险")
        evidence = source.get("evidence", "")
        summary = source.get("summary", "")
        coins = source.get("coins", [])

        scored_news.append(
            {
                **item,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_type": risk_type,
                "evidence": evidence,
                "summary": summary,
                "coins": coins,
                "coin_details": source.get("coin_details", []),
                "llm_analysis": analysis or {"source": "scored_dataset", "coins": coins},
            }
        )

    return {
        **state,
        "scored_news": scored_news,
    }
