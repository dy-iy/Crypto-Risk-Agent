from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = EXPERIMENT_DIR / "experiment_report.json"
METHODS = {
    "chat_agent": EXPERIMENT_DIR / "chat_agent" / "evaluation.json",
    "llm_ranking": EXPERIMENT_DIR / "llm_ranking" / "evaluation.json",
    "risk_scanner": EXPERIMENT_DIR / "risk_scanner" / "evaluation.json",
}
CHAT_AGENT_TARGETS = {
    "score_mae": {"operator": "<=", "target": 9.5},
    "score_within_tolerance_accuracy": {"operator": ">=", "target": 0.72},
    "level_accuracy": {"operator": ">=", "target": 0.78},
    "type_accuracy": {"operator": ">=", "target": 0.80},
    "all_three_accuracy": {"operator": ">=", "target": 0.60},
}
METRIC_SPECS = {
    "score_mae": {"label": "分数 MAE", "higher_is_better": False},
    "score_within_tolerance_accuracy": {"label": "10 分容差准确率", "higher_is_better": True},
    "level_accuracy": {"label": "等级准确率", "higher_is_better": True},
    "type_accuracy": {"label": "类别准确率", "higher_is_better": True},
    "all_three_accuracy": {"label": "三项全中准确率", "higher_is_better": True},
}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"评测结果不存在：{path}")
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def round_number(value: Any, digits: int = 4) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, digits)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits)


def percent(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{value * 100:.0f}%"


def percentage_points(value: float | int | None) -> str | None:
    if value is None:
        return None
    return f"{value * 100:.0f} 个百分点"


def extract_metrics(result: dict[str, Any]) -> dict[str, Any]:
    score_metrics = result.get("score_metrics", {})
    level_metrics = result.get("level_metrics", {})
    type_metrics = result.get("type_metrics", {})
    failed_cases = result.get("failed_cases", [])
    error_types: Counter[str] = Counter()
    failed_gold_types: Counter[str] = Counter()
    failed_predicted_types: Counter[str] = Counter()

    for case in failed_cases:
        error_types.update(case.get("error_types", []))
        failed_gold_type = str(case.get("gold_type") or "").strip()
        failed_predicted_type = str(case.get("predicted_type") or "").strip()
        if failed_gold_type:
            failed_gold_types[failed_gold_type] += 1
        if failed_predicted_type:
            failed_predicted_types[failed_predicted_type] += 1

    top_score_errors = sorted(
        (
            case
            for case in failed_cases
            if isinstance(case.get("score_abs_error"), int | float)
        ),
        key=lambda case: case.get("score_abs_error", 0),
        reverse=True,
    )[:5]

    return {
        "method": result.get("method"),
        "input_csv": result.get("input_csv"),
        "gold_csv": result.get("gold_csv"),
        "total_predictions": result.get("total_predictions"),
        "matched_gold_rows": result.get("matched_gold_rows"),
        "score_labeled_count": score_metrics.get("labeled_count"),
        "score_mae": round_number(score_metrics.get("mae")),
        "score_within_tolerance_accuracy": round_number(score_metrics.get("within_tolerance_accuracy")),
        "score_tolerance": score_metrics.get("score_tolerance"),
        "score_max_abs_error": score_metrics.get("max_abs_error"),
        "level_labeled_count": level_metrics.get("labeled_count"),
        "level_accuracy": round_number(level_metrics.get("accuracy")),
        "type_labeled_count": type_metrics.get("labeled_count"),
        "type_accuracy": round_number(type_metrics.get("accuracy")),
        "all_three_labeled_count": result.get("all_three_labeled_count"),
        "all_three_accuracy": round_number(result.get("all_three_accuracy")),
        "failed_case_count": len(failed_cases),
        "error_type_counts": dict(error_types.most_common()),
        "failed_gold_type_top": dict(failed_gold_types.most_common(8)),
        "failed_predicted_type_top": dict(failed_predicted_types.most_common(8)),
        "top_score_error_cases": [
            {
                "原始新闻id": case.get("原始新闻id"),
                "标题": case.get("标题"),
                "score_abs_error": case.get("score_abs_error"),
                "predicted_score": case.get("predicted_score"),
                "gold_score": case.get("gold_score"),
                "predicted_level": case.get("predicted_level"),
                "gold_level": case.get("gold_level"),
                "predicted_type": case.get("predicted_type"),
                "gold_type": case.get("gold_type"),
                "error_types": case.get("error_types"),
            }
            for case in top_score_errors
        ],
    }


def rank_methods(methods: dict[str, dict[str, Any]], metric: str, higher_is_better: bool) -> list[dict[str, Any]]:
    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, float]:
        value = item[1].get(metric)
        if value is None:
            return (1, 0)
        number = float(value)
        return (0, -number if higher_is_better else number)

    ranked = sorted(methods.items(), key=sort_key)
    rows: list[dict[str, Any]] = []
    previous_value: Any = object()
    current_rank = 0
    for index, (method, metrics) in enumerate(ranked, start=1):
        value = metrics.get(metric)
        if value != previous_value:
            current_rank = index
            previous_value = value
        rows.append({"rank": current_rank, "method": method, "value": value})
    return rows


def build_rankings(methods: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        metric: rank_methods(methods, metric, bool(spec["higher_is_better"]))
        for metric, spec in METRIC_SPECS.items()
    }


def build_overall_ranking(rankings: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rank_totals: dict[str, int] = {}
    rank_counts: dict[str, int] = {}
    for rows in rankings.values():
        for row in rows:
            method = str(row["method"])
            rank_totals[method] = rank_totals.get(method, 0) + int(row["rank"])
            rank_counts[method] = rank_counts.get(method, 0) + 1

    ranked = sorted(
        rank_totals,
        key=lambda method: (rank_totals[method] / rank_counts[method], rank_totals[method], method),
    )
    return [
        {
            "rank": index,
            "method": method,
            "average_metric_rank": round(rank_totals[method] / rank_counts[method], 4),
            "rank_sum": rank_totals[method],
        }
        for index, method in enumerate(ranked, start=1)
    ]


def target_passed(value: float | int | None, operator: str, target: float | int) -> bool:
    if value is None:
        return False
    if operator == "<=":
        return value <= target
    if operator == ">=":
        return value >= target
    raise ValueError(f"不支持的目标比较符：{operator}")


def build_target_check(chat_metrics: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for metric, rule in CHAT_AGENT_TARGETS.items():
        value = chat_metrics.get(metric)
        metrics[metric] = {
            "value": value,
            "operator": rule["operator"],
            "target": rule["target"],
            "passed": target_passed(value, str(rule["operator"]), rule["target"]),
        }
    return {
        "all_passed": all(item["passed"] for item in metrics.values()),
        "metrics": metrics,
    }


def build_method_delta(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    base_mae = base.get("score_mae")
    other_mae = other.get("score_mae")
    mae_reduction = None
    mae_reduction_rate = None
    if isinstance(base_mae, int | float) and isinstance(other_mae, int | float):
        mae_reduction = round(other_mae - base_mae, 4)
        mae_reduction_rate = round((other_mae - base_mae) / other_mae, 4) if other_mae else None

    return {
        "score_mae_reduction": mae_reduction,
        "score_mae_reduction_rate": mae_reduction_rate,
        "score_within_tolerance_accuracy_delta": diff(base, other, "score_within_tolerance_accuracy"),
        "level_accuracy_delta": diff(base, other, "level_accuracy"),
        "type_accuracy_delta": diff(base, other, "type_accuracy"),
        "all_three_accuracy_delta": diff(base, other, "all_three_accuracy"),
        "failed_case_count_reduction": diff(other, base, "failed_case_count"),
    }


def diff(left: dict[str, Any], right: dict[str, Any], metric: str) -> float | int | None:
    left_value = left.get(metric)
    right_value = right.get(metric)
    if not isinstance(left_value, int | float) or not isinstance(right_value, int | float):
        return None
    value = left_value - right_value
    return round(value, 4) if isinstance(value, float) else value


def build_presentation_points(methods: dict[str, dict[str, Any]], winner: str, target_check: dict[str, Any]) -> list[str]:
    chat = methods["chat_agent"]
    llm = methods["llm_ranking"]
    scanner = methods["risk_scanner"]
    points = [
        (
            f"chat_agent 为本轮最优方法：MAE {chat['score_mae']}，"
            f"10分容差 {percent(chat['score_within_tolerance_accuracy'])}，"
            f"等级准确率 {percent(chat['level_accuracy'])}，"
            f"类别准确率 {percent(chat['type_accuracy'])}，"
            f"三项全中 {percent(chat['all_three_accuracy'])}。"
        ),
        (
            f"相对 llm_ranking，chat_agent 的 MAE 降低 "
            f"{round(llm['score_mae'] - chat['score_mae'], 2)}，类别准确率提升 "
            f"{percentage_points(chat['type_accuracy'] - llm['type_accuracy'])}，三项全中提升 "
            f"{percentage_points(chat['all_three_accuracy'] - llm['all_three_accuracy'])}。"
        ),
        (
            f"相对 risk_scanner，chat_agent 的 MAE 降低 "
            f"{round(scanner['score_mae'] - chat['score_mae'], 2)}，10分容差准确率提升 "
            f"{percentage_points(chat['score_within_tolerance_accuracy'] - scanner['score_within_tolerance_accuracy'])}。"
        ),
    ]
    if target_check["all_passed"]:
        points.append("chat_agent 已通过第一阶段全部验收目标。")
    else:
        points.append("chat_agent 尚未通过全部第一阶段验收目标，需继续针对未达标指标优化。")
    if winner != "chat_agent":
        points.append(f"综合排名第一为 {winner}，需复核本轮实验结论。")
    return points


def build_report(method_paths: dict[str, Path]) -> dict[str, Any]:
    raw_results = {method: load_json(path) for method, path in method_paths.items()}
    method_metrics = {method: extract_metrics(result) for method, result in raw_results.items()}
    rankings = build_rankings(method_metrics)
    overall_ranking = build_overall_ranking(rankings)
    winner = str(overall_ranking[0]["method"])
    chat_target_check = build_target_check(method_metrics["chat_agent"])
    comparisons = {
        method: build_method_delta(method_metrics["chat_agent"], metrics)
        for method, metrics in method_metrics.items()
        if method != "chat_agent"
    }

    gold_csvs = sorted({str(metrics.get("gold_csv")) for metrics in method_metrics.values() if metrics.get("gold_csv")})
    score_tolerances = sorted(
        {
            metrics.get("score_tolerance")
            for metrics in method_metrics.values()
            if metrics.get("score_tolerance") is not None
        }
    )

    return {
        "report_title": "三种风险标注方法实验对比报告",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gold_csv": gold_csvs[0] if len(gold_csvs) == 1 else gold_csvs,
        "score_tolerance": score_tolerances[0] if len(score_tolerances) == 1 else score_tolerances,
        "sample_count": method_metrics["chat_agent"].get("matched_gold_rows"),
        "conclusion": {
            "best_overall_method": winner,
            "chat_agent_passed_stage_1_targets": chat_target_check["all_passed"],
            "headline": (
                "chat_agent 在 v2 金标上综合最优，并已达到第一阶段目标。"
                if winner == "chat_agent" and chat_target_check["all_passed"]
                else "本轮实验仍需复核综合排名或目标达成情况。"
            ),
            "presentation_points": build_presentation_points(method_metrics, winner, chat_target_check),
        },
        "stage_1_target_check": chat_target_check,
        "overall_ranking": overall_ranking,
        "metric_rankings": rankings,
        "method_metrics": method_metrics,
        "chat_agent_vs_baselines": comparisons,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize experiment evaluations into one report JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="汇总报告输出路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(METHODS)
    output = args.output.resolve()
    write_json(output, report)
    print(f"已写入：{output}")


if __name__ == "__main__":
    main()
