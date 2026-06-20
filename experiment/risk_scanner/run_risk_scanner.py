from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXPERIMENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.chat_agent.tools.risk_scanner import score_all_risks  # noqa: E402


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


def risk_level_from_score(score: int) -> str:
    if score >= 80:
        return "高风险"
    if score >= 50:
        return "中风险"
    return "低风险"


def normalized_category(value: object) -> str:
    category = str(value or "").strip()
    if not category or category == "无明显风险":
        return "综合风险"
    return category


def build_output_row(row: dict[str, str], news_id: int, analysis: dict[str, object]) -> dict[str, object]:
    score = int(analysis.get("risk") or 0)
    category = normalized_category(analysis.get("rule_primary_type"))
    event = "规则扫描未发现明确风险信号。" if category == "综合风险" else f"规则扫描命中{category}。"
    return {
        "新闻id": news_id,
        "原始新闻id": row.get("新闻id", "").strip(),
        "时间": row.get("时间", "").strip(),
        "标题": row.get("标题", "").strip(),
        "内容": row.get("内容", "").strip(),
        "链接": row.get("链接", "").strip(),
        "事件": event,
        "风险分数": score,
        "风险等级": risk_level_from_score(score),
        "风险类别": category,
        "gold_score": "",
        "gold_level": "",
        "gold_type": "",
    }


def run_labeling(input_path: Path, output_path: Path, limit: int | None, resume: bool) -> None:
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
    for offset, row in enumerate(rows[completed_before:], start=completed_before + 1):
        title = (row.get("标题", "") or row.get("内容", "")).strip().replace("\n", " ")
        print(f"[{offset}/{total}] risk_scanner 标注：{title[:64]}", flush=True)
        analysis = score_all_risks(f"{row.get('标题', '')}\n{row.get('内容', '')}")
        append_result(output_path, build_output_row(row, offset, analysis))

    print(f"完成：{output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run risk_scanner rule experiment labeling.")
    parser.add_argument("--input", default=str(EXPERIMENT_DIR / "data" / "crypto_market_news_100.csv"))
    parser.add_argument("--output", default=str(SCRIPT_DIR / "risk_scanner_results.csv"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit 必须大于 0")
    run_labeling(Path(args.input).resolve(), Path(args.output).resolve(), args.limit, args.resume)


if __name__ == "__main__":
    main()
