from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from tqdm import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
EXPERIMENT_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXPERIMENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.chat_agent import run_chat_agent  # noqa: E402


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


def build_message(row: dict[str, str], news_id: int) -> str:
    return (
        "请对下面这条加密货币市场新闻做完整事件风险分析，输出时需要给出事件摘要、风险分数、风险等级、风险类别。\n\n"
        f"新闻ID：{news_id}\n"
        f"原始新闻ID：{row.get('新闻id', '').strip()}\n"
        f"发布时间：{row.get('时间', '').strip()}\n"
        f"标题：{row.get('标题', '').strip()}\n"
        f"内容：{row.get('内容', '').strip()}\n"
        f"链接：{row.get('链接', '').strip()}"
    )


def has_established_branch(report: dict[str, object]) -> bool:
    result = report.get("chat_agent_result")
    branches = result.get("risk_type_branches") if isinstance(result, dict) else report.get("risk_type_branches")
    if not isinstance(branches, list):
        return False
    for branch in branches:
        if not isinstance(branch, dict) or branch.get("established") is not True:
            continue
        try:
            if int(float(branch.get("branch_score") or 0)) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def rule_primary_category(report: dict[str, object]) -> str:
    debug = report.get("debug")
    if not isinstance(debug, dict):
        return ""
    signal_scan = debug.get("signal_scan")
    if not isinstance(signal_scan, dict):
        return ""
    scan_debug = signal_scan.get("debug")
    if not isinstance(scan_debug, dict):
        return ""
    category = str(scan_debug.get("rule_primary_type") or "").strip()
    if category and category != "无明显风险":
        return category
    return ""


def report_score(report: dict[str, object]) -> int:
    try:
        return int(float(report.get("risk_score") or report.get("final_risk_score") or 0))
    except (TypeError, ValueError):
        return 0


def first_category(report: dict[str, object]) -> str:
    if str(report.get("risk_status") or "") == "low_risk" and not has_established_branch(report):
        if report_score(report) <= 10:
            return "综合风险"
        return rule_primary_category(report) or "综合风险"
    primary = str(report.get("primary_category") or "").strip()
    if primary and primary != "综合风险":
        return primary
    rule_primary = rule_primary_category(report)
    if rule_primary:
        return rule_primary
    if primary:
        return primary
    categories = report.get("risk_categories")
    if isinstance(categories, list) and categories:
        return str(categories[0]).strip() or "综合风险"
    return "综合风险"


def event_summary(report: dict[str, object], row: dict[str, str]) -> str:
    return str(report.get("summary") or "").strip() or row.get("标题", "").strip()


def three_level_from_score(score: int) -> str:
    if score >= 80:
        return "高风险"
    if score >= 50:
        return "中风险"
    return "低风险"


def build_output_row(row: dict[str, str], news_id: int, report: dict[str, object]) -> dict[str, object]:
    score = report_score(report)
    return {
        "新闻id": news_id,
        "原始新闻id": row.get("新闻id", "").strip(),
        "时间": row.get("时间", "").strip(),
        "标题": row.get("标题", "").strip(),
        "内容": row.get("内容", "").strip(),
        "链接": row.get("链接", "").strip(),
        "事件": event_summary(report, row),
        "风险分数": score,
        "风险等级": three_level_from_score(score),
        "风险类别": first_category(report),
        "gold_score": "",
        "gold_level": "",
        "gold_type": "",
    }


def label_row(offset: int, row: dict[str, str]) -> tuple[int, dict[str, object], str]:
    report = run_chat_agent(build_message(row, offset))
    return offset, build_output_row(row, offset, report), row_title(row)


def run_labeling(
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
    max_workers = min(max(1, concurrency), len(pending_rows))
    print(f"chat_agent 并发新闻数：{max_workers}")

    completed_rows: dict[int, dict[str, object]] = {}
    next_to_write = completed_before + 1

    with ThreadPoolExecutor(max_workers=max_workers) as executor, tqdm(
        total=total,
        initial=completed_before,
        desc="chat_agent 标注进度",
        unit="条",
    ) as progress:
        futures = [
            executor.submit(label_row, offset, row)
            for offset, row in enumerate(pending_rows, start=completed_before + 1)
        ]
        try:
            for future in as_completed(futures):
                offset, output_row, title = future.result()
                completed_rows[offset] = output_row
                progress.update(1)
                if title:
                    progress.set_postfix_str(title[:32])

                while next_to_write in completed_rows:
                    append_result(output_path, completed_rows.pop(next_to_write))
                    next_to_write += 1
        except Exception:
            for future in futures:
                future.cancel()
            raise

    while next_to_write in completed_rows:
        append_result(output_path, completed_rows.pop(next_to_write))
        next_to_write += 1

    print(f"完成：{output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chat_agent experiment labeling.")
    parser.add_argument("--input", default=str(EXPERIMENT_DIR / "data" / "crypto_market_news_100.csv"))
    parser.add_argument("--output", default=str(SCRIPT_DIR / "chat_agent_results.csv"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--concurrency", type=int, default=3, help="并发运行 chat_agent 的新闻条数。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit 必须大于 0")
    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须大于 0")
    run_labeling(Path(args.input).resolve(), Path(args.output).resolve(), args.limit, args.resume, args.concurrency)


if __name__ == "__main__":
    main()
