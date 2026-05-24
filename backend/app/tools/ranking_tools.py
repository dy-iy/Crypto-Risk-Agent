from app.agents.ranking_agent.state import RankingAgentState
from app.services.coin_extraction_service import COIN_DICTIONARY, extract_coins_from_text
from app.services.data_loader import load_normalized_news, load_scored_news, save_scored_news
from app.services.ranking_aggregation_service import (
    build_coin_ranking,
    build_news_ranking,
    build_overview,
    filter_news_by_date,
    response_date,
)


def load_ranking_input(state: RankingAgentState) -> RankingAgentState:
    raw_news = load_normalized_news()
    scored_dataset = load_scored_news()
    ranking_source = _merge_raw_and_scored_news(raw_news, scored_dataset)
    filtered_news = filter_news_by_date(ranking_source, state.get("date_filter"))
    return {
        **state,
        "raw_news": raw_news,
        "ranking_source": ranking_source,
        "raw_dataset_empty": len(raw_news) == 0,
        "scored_dataset": scored_dataset,
        "filtered_news": filtered_news,
    }


def _merge_raw_and_scored_news(
    raw_news: list[dict[str, object]],
    scored_dataset: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not scored_dataset:
        return raw_news

    raw_by_id = {
        str(item.get("news_id") or item.get("id")): item
        for item in raw_news
    }
    merged: list[dict[str, object]] = []
    seen_ids: set[str] = set()

    for scored_item in scored_dataset:
        news_id = str(scored_item.get("news_id") or scored_item.get("id"))
        raw_item = raw_by_id.get(news_id, {})
        merged.append({**raw_item, **scored_item})
        seen_ids.add(news_id)

    for raw_item in raw_news:
        news_id = str(raw_item.get("news_id") or raw_item.get("id"))
        if news_id not in seen_ids:
            merged.append(raw_item)

    return merged


def persist_scored_dataset(state: RankingAgentState) -> RankingAgentState:
    if state.get("raw_dataset_empty"):
        return state
    if not state.get("score_missing", True):
        return state

    existing_by_id = {
        str(item.get("news_id") or item.get("id")): item
        for item in state.get("scored_dataset", [])
    }
    for item in state.get("coin_enriched_news", state.get("scored_news", [])):
        news_id = str(item.get("news_id") or item.get("id"))
        existing_by_id[news_id] = {
            "news_id": item.get("news_id"),
            "csv_order": item.get("csv_order"),
            "title": item.get("title"),
            "content": item.get("content"),
            "date": item.get("date"),
            "published_at": item.get("published_at"),
            "risk_score": item.get("risk_score"),
            "risk_level": item.get("risk_level"),
            "risk_type": item.get("risk_type"),
            "evidence": item.get("evidence"),
            "summary": item.get("summary"),
            "coins": item.get("coins", []),
            "coin_details": item.get("coin_details", []),
            "llm_source": item.get("llm_analysis", {}).get("source", ""),
        }

    order_source = state.get("ranking_source", state.get("raw_news", []))
    raw_order = {
        str(item.get("news_id") or item.get("id")): index
        for index, item in enumerate(order_source, start=1)
    }
    merged = sorted(
        existing_by_id.values(),
        key=lambda item: raw_order.get(
            str(item.get("news_id") or item.get("id")),
            int(str(item.get("csv_order") or "999999")) if str(item.get("csv_order") or "").isdigit() else 999999,
        ),
    )
    save_scored_news(merged)
    return {
        **state,
        "scored_dataset": merged,
    }


def _coin_details_from_llm(symbols: list[str]) -> list[dict[str, object]]:
    details = []
    for symbol in symbols:
        normalized = str(symbol).strip().upper()
        meta = COIN_DICTIONARY.get(normalized)
        if not meta:
            continue
        details.append(
            {
                "symbol": normalized,
                "name": str(meta["name"]),
                "matched_terms": ["LLM"],
            }
        )
    return details


def attach_coin_entities(state: RankingAgentState) -> RankingAgentState:
    enriched_news = []
    for item in state.get("scored_news", []):
        coins = item.get("coin_details", [])
        if not coins:
            llm_symbols = item.get("llm_analysis", {}).get("coins", [])
            coins = _coin_details_from_llm(llm_symbols)
        if not coins and item.get("coins"):
            coins = _coin_details_from_llm(item.get("coins", []))
        if not coins:
            coins = extract_coins_from_text(item.get("title", ""), item.get("content", ""))
        enriched_news.append(
            {
                **item,
                "coins": [coin["symbol"] for coin in coins],
                "coin_details": coins,
            }
        )

    return {
        **state,
        "coin_enriched_news": enriched_news,
    }


def build_news_ranking_output(state: RankingAgentState) -> RankingAgentState:
    news_ranking = build_news_ranking(
        state.get("coin_enriched_news", []),
        state.get("limit", 10),
    )
    return {
        **state,
        "news_ranking": news_ranking,
    }


def build_coin_ranking_output(state: RankingAgentState) -> RankingAgentState:
    coin_ranking = build_coin_ranking(
        state.get("coin_enriched_news", []),
        state.get("limit", 10),
    )
    return {
        **state,
        "coin_ranking": coin_ranking,
    }


def _clamp_score(value: object) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def review_ranking_outputs(state: RankingAgentState) -> RankingAgentState:
    notes: list[str] = []
    valid_symbols = set(COIN_DICTIONARY.keys())

    reviewed_news = []
    for item in state.get("news_ranking", []):
        score = _clamp_score(item.get("risk_score"))
        if score != item.get("risk_score"):
            notes.append(f"news:{item.get('news_id')} risk_score clamped")
        reviewed_news.append({**item, "risk_score": score})

    reviewed_coins = []
    for item in state.get("coin_ranking", []):
        if item.get("symbol") not in valid_symbols:
            notes.append(f"coin:{item.get('symbol')} removed by dictionary review")
            continue
        final_score = max(0, min(100, float(item.get("final_score", 0))))
        reviewed_coins.append({**item, "final_score": round(final_score, 1)})

    return {
        **state,
        "news_ranking": reviewed_news,
        "coin_ranking": reviewed_coins,
        "review_notes": notes,
    }


def build_ranking_response(state: RankingAgentState) -> RankingAgentState:
    output_type = state.get("output_type", "all")
    date_filter = state.get("date_filter")
    news_ranking = state.get("news_ranking", [])
    coin_ranking = state.get("coin_ranking", [])
    overview = build_overview(
        state.get("coin_enriched_news", []),
        news_ranking,
        coin_ranking,
        date_filter,
    )

    if output_type == "overview":
        response = overview
    elif output_type == "news":
        response = {
            "date": response_date(date_filter),
            "ranking_type": "news",
            "items": news_ranking,
        }
    elif output_type == "coins":
        response = {
            "date": response_date(date_filter),
            "ranking_type": "coin",
            "items": coin_ranking,
        }
    else:
        response = {
            "date": response_date(date_filter),
            "overview": overview,
            "news": {
                "ranking_type": "news",
                "items": news_ranking,
            },
            "coins": {
                "ranking_type": "coin",
                "items": coin_ranking,
            },
            "review_notes": state.get("review_notes", []),
        }

    if state.get("raw_dataset_empty"):
        response = {
            **response,
            "warning": "主新闻集 mastered_news.csv 为空，无法生成新的排行榜。",
        }

    return {
        **state,
        "overview": overview,
        "response": response,
    }
