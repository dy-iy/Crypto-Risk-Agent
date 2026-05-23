import argparse
import asyncio
import sys
from pathlib import Path

from tqdm import tqdm

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.services.data_loader import (
    RAW_NEWS_QUEUE_PATH,
    SCORED_DATA_PATH,
    clear_raw_news_queue,
    load_normalized_news,
    load_scored_news,
    save_scored_news,
)
from app.services.llm_news_risk_service import analyze_news_item_with_llm_strict_async
from app.tools.ranking_tools import (
    attach_coin_entities,
    build_coin_ranking_output,
    build_news_ranking_output,
)


def _build_scored_item(item: dict[str, object], analysis: dict[str, object]) -> dict[str, object]:
    return {
        **item,
        "risk_score": analysis.get("risk_score", 0),
        "risk_level": analysis.get("risk_level", "低风险"),
        "risk_type": analysis.get("risk_type", "异常行情波动风险"),
        "evidence": analysis.get("evidence", ""),
        "summary": analysis.get("summary", ""),
        "coins": analysis.get("coins", []),
        "coin_details": [],
        "llm_analysis": analysis,
    }


async def _label_news_item(
    item_index: int,
    item: dict[str, object],
    semaphore: asyncio.Semaphore,
) -> tuple[int, dict[str, object]]:
    async with semaphore:
        analysis = await analyze_news_item_with_llm_strict_async(item)
        return item_index, _build_scored_item(item, analysis)


def _print_each_news(items: list[dict[str, object]]) -> None:
    print("\n========== LLM 标注结果 ==========")
    for item in items:
        coins = item.get("coins", [])
        if isinstance(coins, list):
            coin_text = ", ".join(str(coin) for coin in coins) or "无"
        else:
            coin_text = "无"
        print(
            f"[{item.get('news_id')}] "
            f"{item.get('risk_score')}分 | "
            f"{item.get('risk_level')} | "
            f"{item.get('risk_type')} | "
            f"币种：{coin_text} | "
            f"{item.get('title')}"
        )


def _print_sorted_news(items: list[dict[str, object]]) -> None:
    ranked = sorted(items, key=lambda item: int(item.get("risk_score", 0)), reverse=True)
    print("\n========== 新闻风险分数排序 ==========")
    for rank, item in enumerate(ranked, start=1):
        coins = item.get("coins", [])
        coin_text = ", ".join(str(coin) for coin in coins) if isinstance(coins, list) else ""
        print(
            f"#{rank:03d} | {item.get('risk_score')}分 | {item.get('risk_level')} | "
            f"{item.get('risk_type')} | {coin_text or '无币种'} | {item.get('title')}"
        )


def _print_coin_ranking(scored_items: list[dict[str, object]]) -> None:
    state = {
        "coin_enriched_news": scored_items,
        "limit": 20,
    }
    state = build_news_ranking_output(state)
    state = build_coin_ranking_output(state)
    coin_ranking = state.get("coin_ranking", [])
    print("\n========== 币种风险排序 Top 20 ==========")
    for item in coin_ranking:
        print(
            f"#{item.get('rank'):02d} | {item.get('symbol')} {item.get('name')} | "
            f"{item.get('final_score')}分 | {item.get('risk_level')} | "
            f"{item.get('news_count')}条 | {item.get('main_risk_type')}"
        )


def _csv_order(item: dict[str, object]) -> int:
    try:
        return int(str(item.get("csv_order") or item.get("news_id") or item.get("id") or "0"))
    except ValueError:
        return 0


async def _label_news_items(
    selected_news: list[dict[str, object]],
    concurrency: int,
) -> list[dict[str, object]]:
    progress = tqdm(total=len(selected_news), desc="DeepSeek LLM 标注进度", unit="条")
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        asyncio.create_task(_label_news_item(item_index, item, semaphore))
        for item_index, item in enumerate(selected_news)
    ]
    scored_results: list[tuple[int, dict[str, object]]] = []
    try:
        for task in asyncio.as_completed(tasks):
            item_index, scored_item = await task
            scored_results.append((item_index, scored_item))
            progress.update(1)
    except Exception:
        for task in tasks:
            task.cancel()
        raise
    finally:
        progress.close()

    return [item for _, item in sorted(scored_results, key=lambda result: result[0])]


def _max_csv_order(items: list[dict[str, object]]) -> int:
    return max((_csv_order(item) for item in items), default=0)


def _has_explicit_news_id(item: dict[str, object]) -> bool:
    raw_row = item.get("raw")
    if not isinstance(raw_row, dict):
        return False

    for field in ["news_id", "id", "新闻id", "新闻ID"]:
        value = raw_row.get(field)
        if value is not None and str(value).strip():
            return True
    return False


def _normalize_incremental_order(
    raw_items: list[dict[str, object]],
    existing_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    existing_order = {
        str(item.get("news_id") or item.get("id")): _csv_order(item)
        for item in existing_items
    }
    next_order = _max_csv_order(existing_items)
    normalized_items: list[dict[str, object]] = []

    for item in raw_items:
        news_id = str(item.get("news_id") or item.get("id"))
        explicit_news_id = _has_explicit_news_id(item)

        if news_id in existing_order and not explicit_news_id:
            next_order += 1
            csv_order = next_order
            news_id = str(next_order)
            item = {**item, "id": news_id, "news_id": news_id}
        else:
            csv_order = existing_order.get(news_id)
            if csv_order is None:
                next_order += 1
                csv_order = next_order
        normalized_items.append({**item, "csv_order": csv_order})

    return normalized_items


def _merge_scored_news(
    existing_items: list[dict[str, object]],
    new_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged_by_id = {
        str(item.get("news_id") or item.get("id")): item
        for item in existing_items
    }
    for item in new_items:
        news_id = str(item.get("news_id") or item.get("id"))
        merged_by_id[news_id] = item
    return sorted(merged_by_id.values(), key=_csv_order)


async def run_rank_agent_async(
    limit: int | None,
    output_path: Path,
    concurrency: int,
) -> None:
    raw_news = load_normalized_news()
    if not raw_news:
        raise SystemExit("未评分数据集 raw_300_news.csv 没有内容，无法运行 rank agent。")

    selected_news = raw_news[:limit] if limit else raw_news

    print(f"未评分新闻数量：{len(raw_news)}")
    print(f"本次 LLM 标注数量：{len(selected_news)}")
    print(f"LLM 并发新闻数：{concurrency}")
    print(f"输出已评分数据集：{output_path}")

    scored_items = await _label_news_items(selected_news, concurrency)

    state = {
        "scored_news": scored_items,
    }
    state = attach_coin_entities(state)
    scored_items = state.get("coin_enriched_news", [])
    scored_items = sorted(scored_items, key=_csv_order)

    save_scored_news(scored_items, str(output_path))
    _print_each_news(scored_items)
    _print_sorted_news(scored_items)
    _print_coin_ranking(scored_items)
    print("\n已写入：", output_path)


async def update_from_raw_news_async(
    output_path: Path,
    concurrency: int,
) -> None:
    raw_items = load_normalized_news(str(RAW_NEWS_QUEUE_PATH))
    if not raw_items:
        print(f"{RAW_NEWS_QUEUE_PATH} 没有待标注新闻。")
        return

    existing_items = load_scored_news(str(output_path))
    selected_news = _normalize_incremental_order(raw_items, existing_items)

    print(f"待标注增量新闻数量：{len(selected_news)}")
    print(f"LLM 并发新闻数：{concurrency}")
    print(f"增量输入文件：{RAW_NEWS_QUEUE_PATH}")
    print(f"输出已评分数据集：{output_path}")

    scored_items = await _label_news_items(selected_news, concurrency)
    state = {
        "scored_news": scored_items,
    }
    state = attach_coin_entities(state)
    enriched_items = sorted(state.get("coin_enriched_news", []), key=_csv_order)
    merged_items = _merge_scored_news(existing_items, enriched_items)

    save_scored_news(merged_items, str(output_path))
    clear_raw_news_queue(str(RAW_NEWS_QUEUE_PATH))

    print("\n========== 本次新增标注结果 ==========")
    _print_each_news(enriched_items)
    _print_sorted_news(merged_items)
    _print_coin_ranking(merged_items)
    print("\n已追加写入：", output_path)
    print("已清空：", RAW_NEWS_QUEUE_PATH)
    print("后端排行榜将在下一次 /api/rankings 请求时读取最新 scored_news.json。")


def run_rank_agent(limit: int | None, output_path: Path, concurrency: int) -> None:
    asyncio.run(run_rank_agent_async(limit, output_path, concurrency))


def update_from_raw_news(output_path: Path, concurrency: int) -> None:
    asyncio.run(update_from_raw_news_async(output_path, concurrency))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CryptoRisk ranking agent from terminal.")
    parser.add_argument("--limit", type=int, default=None, help="只标注前 N 条。默认标注全部。")
    parser.add_argument("--concurrency", type=int, default=8, help="并发请求 DeepSeek 的新闻条数。")
    parser.add_argument(
        "--update-from-raw-news",
        action="store_true",
        help="标注 raw_news.csv 中的增量新闻，追加到 scored_news.json，然后清空 raw_news.csv。",
    )
    parser.add_argument(
        "--output",
        default=str(SCORED_DATA_PATH),
        help="已评分数据集输出路径。",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须大于 0。")

    output_path = Path(args.output)
    if args.update_from_raw_news:
        update_from_raw_news(output_path, args.concurrency)
    else:
        run_rank_agent(args.limit, output_path, args.concurrency)


if __name__ == "__main__":
    main()
