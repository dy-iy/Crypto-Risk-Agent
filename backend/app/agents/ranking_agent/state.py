from typing import Literal, TypedDict


RankingOutputType = Literal["overview", "news", "coins", "all"]


class RankingAgentState(TypedDict, total=False):
    date_filter: str | None
    limit: int
    output_type: RankingOutputType
    raw_news: list[dict[str, object]]
    ranking_source: list[dict[str, object]]
    raw_dataset_empty: bool
    scored_dataset: list[dict[str, object]]
    filtered_news: list[dict[str, object]]
    scored_news: list[dict[str, object]]
    coin_enriched_news: list[dict[str, object]]
    news_ranking: list[dict[str, object]]
    coin_ranking: list[dict[str, object]]
    overview: dict[str, object]
    response: dict[str, object]
    review_notes: list[str]
