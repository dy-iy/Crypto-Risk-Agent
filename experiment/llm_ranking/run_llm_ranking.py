from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXPERIMENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.llm_news_risk_service import analyze_news_item_with_llm_strict_async  # noqa: E402


TIME_FIELD = "时间"
OUTPUT_FIELDS = [
    "新闻id",
    "原始新闻id",
    "时间",
    "标题",
    "内容",
    "链接",
    "事件",
    "风险分数",
    "风险等级",
    "风险类别",
    "gold_score",
    "gold_level",
    "gold_type",
]


def load_rows(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_news_time(row: dict[str, str]) -> datetime:
    value = (row.get(TIME_FIELD) or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return datetime.min


def sort_rows_by_time(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=parse_news_time, reverse=True)


def count_existing_results(output_path: Path) -> int:
    if not output_path.exists():
        return 0
    with output_path.open(newline="", encoding="utf-8") as file:
        return sum(1 for _ in csv.DictReader(file))


def output_header_matches(output_path: Path) -> bool:
    if not output_path.exists() or output_path.stat().st_size == 0:
        return True
    with output_path.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        try:
            return next(reader) == OUTPUT_FIELDS
        except StopIteration:
            return True


def write_header_if_needed(output_path: Path) -> None:
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=OUTPUT_FIELDS).writeheader()


def append_result(output_path: Path, result: dict[str, object]) -> None:
    with output_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writerow({field: result.get(field, "") for field in OUTPUT_FIELDS})


def row_title(row: dict[str, str]) -> str:
    return (row.get("标题", "") or row.get("内容", "")).strip().replace("\n", " ")


def build_item(row: dict[str, str], news_id: int) -> dict[str, object]:
    return {
        "news_id": row.get("新闻id", "").strip() or str(news_id),
        "id": row.get("新闻id", "").strip() or str(news_id),
        "title": row.get("标题", "").strip(),
        "content": row.get("内容", "").strip(),
    }


def build_output_row(row: dict[str, str], news_id: int, analysis: dict[str, object]) -> dict[str, object]:
    if analysis.get("source") != "llm":
        raise RuntimeError(f"LLM 标注未返回纯 LLM 结果：news_id={row.get('新闻id', '').strip()} source={analysis.get('source')}")
    return {
        "新闻id": news_id,
        "原始新闻id": row.get("新闻id", "").strip(),
        "时间": row.get("时间", "").strip(),
        "标题": row.get("标题", "").strip(),
        "内容": row.get("内容", "").strip(),
        "链接": row.get("链接", "").strip(),
        "事件": str(analysis.get("summary") or row.get("标题", "")).strip(),
        "风险分数": int(analysis.get("risk_score") or 0),
        "风险等级": str(analysis.get("risk_level") or "低风险"),
        "风险类别": str(analysis.get("risk_type") or "综合风险"),
        "gold_score": "",
        "gold_level": "",
        "gold_type": "",
    }


async def label_row(
    offset: int,
    row: dict[str, str],
    semaphore: asyncio.Semaphore,
) -> tuple[int, dict[str, object], str]:
    async with semaphore:
        analysis = await analyze_news_item_with_llm_strict_async(build_item(row, offset))
        return offset, build_output_row(row, offset, analysis), row_title(row)


async def run_labeling(
    input_path: Path,
    output_path: Path,
    limit: int | None,
    resume: bool,
    concurrency: int,
) -> None:
    rows = sort_rows_by_time(load_rows(input_path))
    if limit is not None:
        rows = rows[:limit]

    if not resume and output_path.exists():
        output_path.unlink()
    if resume and not output_header_matches(output_path):
        raise SystemExit(f"已有输出文件字段不匹配：{output_path}")

    completed_before = count_existing_results(output_path) if resume else 0
    if completed_before >= len(rows):
        print(f"已存在 {completed_before}/{len(rows)} 条结果，无需继续。")
        return
    write_header_if_needed(output_path)

    total = len(rows)
    pending_rows = rows[completed_before:]
    max_concurrency = min(max(1, concurrency), len(pending_rows))
    print(f"LLM 并发新闻数：{max_concurrency}")

    semaphore = asyncio.Semaphore(max_concurrency)
    tasks = [
        asyncio.create_task(label_row(offset, row, semaphore))
        for offset, row in enumerate(pending_rows, start=completed_before + 1)
    ]
    completed_rows: dict[int, dict[str, object]] = {}
    next_to_write = completed_before + 1

    with tqdm(total=total, initial=completed_before, desc="DeepSeek LLM 标注进度", unit="条") as progress:
        try:
            for task in asyncio.as_completed(tasks):
                offset, output_row, title = await task
                completed_rows[offset] = output_row
                progress.update(1)
                if title:
                    progress.set_postfix_str(title[:32])

                while next_to_write in completed_rows:
                    append_result(output_path, completed_rows.pop(next_to_write))
                    next_to_write += 1
        except Exception:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    while next_to_write in completed_rows:
        append_result(output_path, completed_rows.pop(next_to_write))
        next_to_write += 1

    print(f"完成：{output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ranking LLM experiment labeling.")
    parser.add_argument("--input", default=str(EXPERIMENT_DIR / "data" / "crypto_market_news_100.csv"))
    parser.add_argument("--output", default=str(SCRIPT_DIR / "llm_ranking_results.csv"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--concurrency", type=int, default=8, help="并发请求 DeepSeek 的新闻条数。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit 必须大于 0")
    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须大于 0")
    asyncio.run(
        run_labeling(
            Path(args.input).resolve(),
            Path(args.output).resolve(),
            args.limit,
            args.resume,
            args.concurrency,
        )
    )


if __name__ == "__main__":
    main()
