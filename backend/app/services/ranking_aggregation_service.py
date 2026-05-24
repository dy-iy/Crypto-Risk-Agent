from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from app.services.data_loader import shorten
from app.services.rule_risk_scorer import risk_level_from_score


SOURCE_URL_FIELDS = [
    "source_url",
    "url",
    "link",
    "original_url",
    "news_url",
    "网页",
    "链接",
    "原文链接",
]


def response_date(date_filter: str | None) -> str:
    if date_filter in {"24h", "7d"}:
        return date_filter
    return date_filter or date.today().isoformat()


def _parse_item_time(item: dict[str, object]) -> datetime | None:
    value = item.get("published_at") or item.get("date")
    if not value:
        return None

    text = str(value).strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _filter_news_by_recent_delta(items: list[dict[str, object]], delta: timedelta) -> list[dict[str, object]]:
    cutoff = datetime.now() - delta
    return [
        item
        for item in items
        if (published_at := _parse_item_time(item)) is not None and published_at >= cutoff
    ]


def filter_news_by_date(items: list[dict[str, object]], date_filter: str | None) -> list[dict[str, object]]:
    if date_filter == "24h":
        filtered = _filter_news_by_recent_delta(items, timedelta(hours=24))
        return filtered or items
    if date_filter == "7d":
        filtered = _filter_news_by_recent_delta(items, timedelta(days=7))
        return filtered or items
    if not date_filter:
        filtered = _filter_news_by_recent_delta(items, timedelta(hours=24))
        return filtered or items
    filtered = [item for item in items if item.get("date") == date_filter]
    return filtered or items


def first_text_value(item: dict[str, object], fields: list[str]) -> str:
    for field in fields:
        value = item.get(field)
        if value:
            return str(value)
    raw = item.get("raw")
    if isinstance(raw, dict):
        for field in fields:
            value = raw.get(field)
            if value:
                return str(value)
    return ""


def build_news_ranking(items: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    ranked = sorted(items, key=lambda item: int(item.get("risk_score", 0)), reverse=True)
    selected = ranked if limit <= 0 else ranked[:limit]
    output: list[dict[str, object]] = []
    for rank, item in enumerate(selected, start=1):
        output.append(
            {
                "rank": rank,
                "news_id": item.get("news_id", ""),
                "csv_order": item.get("csv_order", ""),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "date": item.get("date", ""),
                "risk_score": item.get("risk_score", 0),
                "risk_level": item.get("risk_level", ""),
                "risk_type": item.get("risk_type", ""),
                "published_at": item.get("published_at", ""),
                "coins": item.get("coins", []),
                "coin_details": item.get("coin_details", []),
                "summary": item.get("summary", ""),
                "evidence": item.get("evidence", ""),
                "source_url": first_text_value(item, SOURCE_URL_FIELDS),
            }
        )
    return output


def build_coin_ranking(items: list[dict[str, object]], limit: int) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    coin_names: dict[str, str] = {}

    for item in items:
        for coin in item.get("coin_details", []):
            symbol = coin["symbol"]
            grouped[symbol].append(item)
            coin_names[symbol] = coin["name"]

    coin_items = []
    for symbol, related_news in grouped.items():
        scores = [int(news.get("risk_score", 0)) for news in related_news]
        max_score = max(scores)
        avg_score = sum(scores) / len(scores)
        volume_score = min(len(related_news) / 5, 1) * 100
        final_score = round(max_score * 0.5 + avg_score * 0.3 + volume_score * 0.2, 1)
        top_news = max(related_news, key=lambda news: int(news.get("risk_score", 0)))
        risk_type_counter = Counter(str(news.get("risk_type", "")) for news in related_news)

        coin_items.append(
            {
                "symbol": symbol,
                "name": coin_names.get(symbol, symbol),
                "final_score": final_score,
                "risk_level": risk_level_from_score(final_score),
                "news_count": len(related_news),
                "main_risk_type": risk_type_counter.most_common(1)[0][0],
                "top_news_title": top_news.get("title", ""),
                "summary": shorten(str(top_news.get("summary", "")), 120),
                "related_news": [
                    {
                        "news_id": news.get("news_id", ""),
                        "title": news.get("title", ""),
                        "risk_score": news.get("risk_score", 0),
                        "risk_level": news.get("risk_level", ""),
                        "risk_type": news.get("risk_type", ""),
                        "published_at": news.get("published_at", ""),
                    }
                    for news in sorted(
                        related_news,
                        key=lambda news: int(news.get("risk_score", 0)),
                        reverse=True,
                    )
                ],
            }
        )

    ranked = sorted(coin_items, key=lambda item: item["final_score"], reverse=True)
    selected = ranked if limit <= 0 else ranked[:limit]
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
    return selected


def build_overview(
    items: list[dict[str, object]],
    news_ranking: list[dict[str, object]],
    coin_ranking: list[dict[str, object]],
    date_filter: str | None,
) -> dict[str, object]:
    return {
        "date": response_date(date_filter),
        "total_news": len(items),
        "high_risk_news": sum(1 for item in items if item.get("risk_level") == "高风险"),
        "top_news": news_ranking[0] if news_ranking else None,
        "top_coin": coin_ranking[0] if coin_ranking else None,
        "top_news_preview": news_ranking,
        "top_coin_preview": coin_ranking,
    }
