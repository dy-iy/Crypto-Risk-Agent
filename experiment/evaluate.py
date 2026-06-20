from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import mean


EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_GOLD_CSV = EXPERIMENT_DIR / "data" / "crypto_market_news_100_labeled.csv"
DEFAULT_SCORE_TOLERANCE = 10
METHODS = {
    "chat_agent": EXPERIMENT_DIR / "chat_agent" / "chat_agent_results.csv",
    "llm_ranking": EXPERIMENT_DIR / "llm_ranking" / "llm_ranking_results.csv",
    "risk_scanner": EXPERIMENT_DIR / "risk_scanner" / "risk_scanner_results.csv",
}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def accuracy(correct: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(correct / total, 4)


def confusion_increment(matrix: dict[str, dict[str, int]], gold: str, predicted: str) -> None:
    matrix.setdefault(gold, {})
    matrix[gold][predicted] = matrix[gold].get(predicted, 0) + 1


def sorted_confusion_matrix(matrix: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    return {
        gold: {predicted: counts[predicted] for predicted in sorted(counts)}
        for gold, counts in sorted(matrix.items())
    }


def build_gold_index(gold_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in gold_rows:
        news_id = normalize_text(row.get("新闻id"))
        if news_id:
            index[news_id] = row
    return index


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(EXPERIMENT_DIR))
    except ValueError:
        return str(path)


def score_metrics(
    matched_pairs: list[tuple[dict[str, str], dict[str, str]]],
    score_tolerance: int,
) -> dict[str, object]:
    errors: list[int] = []
    within_tolerance = 0
    for prediction, gold in matched_pairs:
        gold_score = parse_int(gold.get("gold_score"))
        predicted_score = parse_int(prediction.get("风险分数"))
        if gold_score is None or predicted_score is None:
            continue
        error = abs(predicted_score - gold_score)
        errors.append(error)
        if error <= score_tolerance:
            within_tolerance += 1

    return {
        "labeled_count": len(errors),
        "mae": round(mean(errors), 4) if errors else None,
        "within_tolerance_accuracy": accuracy(within_tolerance, len(errors)),
        "score_tolerance": score_tolerance,
        "max_abs_error": max(errors) if errors else None,
    }


def categorical_metrics(
    matched_pairs: list[tuple[dict[str, str], dict[str, str]]],
    prediction_field: str,
    gold_field: str,
) -> dict[str, object]:
    labeled_count = 0
    correct_count = 0
    matrix: dict[str, dict[str, int]] = {}
    for prediction, gold in matched_pairs:
        gold_value = normalize_text(gold.get(gold_field))
        if not gold_value:
            continue
        predicted_value = normalize_text(prediction.get(prediction_field)) or "__missing__"
        labeled_count += 1
        if predicted_value == gold_value:
            correct_count += 1
        confusion_increment(matrix, gold_value, predicted_value)

    return {
        "labeled_count": labeled_count,
        "accuracy": accuracy(correct_count, labeled_count),
        "confusion_matrix": sorted_confusion_matrix(matrix),
    }


def build_failed_case(
    prediction: dict[str, str],
    gold: dict[str, str],
    error_types: list[str],
) -> dict[str, object]:
    predicted_score = parse_int(prediction.get("风险分数"))
    gold_score = parse_int(gold.get("gold_score"))
    case: dict[str, object] = {
        "原始新闻id": normalize_text(prediction.get("原始新闻id")),
        "标题": normalize_text(prediction.get("标题") or gold.get("标题")),
        "predicted_score": predicted_score,
        "gold_score": gold_score,
        "predicted_level": normalize_text(prediction.get("风险等级")),
        "gold_level": normalize_text(gold.get("gold_level")),
        "predicted_type": normalize_text(prediction.get("风险类别")),
        "gold_type": normalize_text(gold.get("gold_type")),
        "error_types": error_types,
    }
    if predicted_score is not None and gold_score is not None:
        case["score_abs_error"] = abs(predicted_score - gold_score)
    return case


def failed_cases(
    matched_pairs: list[tuple[dict[str, str], dict[str, str]]],
    score_tolerance: int,
) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for prediction, gold in matched_pairs:
        errors: list[str] = []

        gold_score = parse_int(gold.get("gold_score"))
        if gold_score is not None:
            predicted_score = parse_int(prediction.get("风险分数"))
            if predicted_score is None:
                errors.append("score_invalid")
            elif abs(predicted_score - gold_score) > score_tolerance:
                errors.append("score_out_of_tolerance")

        gold_level = normalize_text(gold.get("gold_level"))
        if gold_level and normalize_text(prediction.get("风险等级")) != gold_level:
            errors.append("level_mismatch")

        gold_type = normalize_text(gold.get("gold_type"))
        if gold_type and normalize_text(prediction.get("风险类别")) != gold_type:
            errors.append("type_mismatch")

        if errors:
            cases.append(build_failed_case(prediction, gold, errors))
    return cases


def all_three_metrics(
    matched_pairs: list[tuple[dict[str, str], dict[str, str]]],
    score_tolerance: int,
) -> dict[str, object]:
    labeled_count = 0
    correct_count = 0
    for prediction, gold in matched_pairs:
        gold_score = parse_int(gold.get("gold_score"))
        gold_level = normalize_text(gold.get("gold_level"))
        gold_type = normalize_text(gold.get("gold_type"))
        if gold_score is None or not gold_level or not gold_type:
            continue

        labeled_count += 1
        predicted_score = parse_int(prediction.get("风险分数"))
        score_ok = predicted_score is not None and abs(predicted_score - gold_score) <= score_tolerance
        level_ok = normalize_text(prediction.get("风险等级")) == gold_level
        type_ok = normalize_text(prediction.get("风险类别")) == gold_type
        if score_ok and level_ok and type_ok:
            correct_count += 1

    return {
        "all_three_labeled_count": labeled_count,
        "all_three_accuracy": accuracy(correct_count, labeled_count),
    }


def evaluate_method(
    method: str,
    prediction_csv: Path,
    gold_csv: Path,
    gold_index: dict[str, dict[str, str]],
    score_tolerance: int,
) -> dict[str, object]:
    predictions = load_csv(prediction_csv)
    prediction_ids = {
        normalize_text(row.get("原始新闻id"))
        for row in predictions
        if normalize_text(row.get("原始新闻id"))
    }
    gold_ids = set(gold_index)
    unmatched_prediction_ids = sorted(prediction_ids - gold_ids)
    missing_prediction_ids = sorted(gold_ids - prediction_ids)

    matched_pairs = [
        (prediction, gold_index[original_id])
        for prediction in predictions
        if (original_id := normalize_text(prediction.get("原始新闻id"))) in gold_index
    ]
    all_three = all_three_metrics(matched_pairs, score_tolerance)
    return {
        "method": method,
        "input_csv": display_path(prediction_csv),
        "gold_csv": display_path(gold_csv),
        "total_predictions": len(predictions),
        "matched_gold_rows": len(matched_pairs),
        "unmatched_prediction_ids": unmatched_prediction_ids,
        "missing_prediction_ids": missing_prediction_ids,
        "score_metrics": score_metrics(matched_pairs, score_tolerance),
        "level_metrics": categorical_metrics(matched_pairs, "风险等级", "gold_level"),
        "type_metrics": categorical_metrics(matched_pairs, "风险类别", "gold_type"),
        **all_three,
        "failed_cases": failed_cases(matched_pairs, score_tolerance),
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_evaluation(gold_csv: Path, score_tolerance: int) -> list[Path]:
    gold_rows = load_csv(gold_csv)
    gold_index = build_gold_index(gold_rows)
    output_paths: list[Path] = []
    for method, prediction_csv in METHODS.items():
        if not prediction_csv.exists():
            raise FileNotFoundError(f"预测结果不存在：{prediction_csv}")
        result = evaluate_method(method, prediction_csv, gold_csv, gold_index, score_tolerance)
        output_path = prediction_csv.parent / "evaluation.json"
        write_json(output_path, result)
        output_paths.append(output_path)
    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate experiment results against manual gold labels.")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_CSV, help="统一人工金标 CSV。")
    parser.add_argument("--score-tolerance", type=int, default=DEFAULT_SCORE_TOLERANCE, help="风险分数容差。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.score_tolerance < 0:
        raise SystemExit("--score-tolerance 不能小于 0")
    output_paths = run_evaluation(args.gold.resolve(), args.score_tolerance)
    for path in output_paths:
        print(f"已写入：{path}")


if __name__ == "__main__":
    main()
