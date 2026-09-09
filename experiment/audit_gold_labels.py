from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


EXPERIMENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"
DEFAULT_INPUT = EXPERIMENT_DIR / "data" / "crypto_market_news_100_labeled_v2.csv"
DEFAULT_OUTPUT = EXPERIMENT_DIR / "data" / "gold_label_quality_report.json"
DEFAULT_EXPECTED_ROWS = 100
SCORE_TOLERANCE = 10

CRITICAL_FIELDS = ("新闻id", "时间", "内容", "测试集类别", "gold_score", "gold_level", "gold_type")
EXPECTED_COLUMNS = (
    "新闻id",
    "时间",
    "标题",
    "内容",
    "链接",
    "测试集类别",
    "gold_score",
    "gold_level",
    "gold_type",
)
LEVELS = {"低风险", "中风险", "高风险"}
FALLBACK_RISK_TYPES = {
    "链上漏洞 / 攻击风险",
    "诈骗 / 跑路 / Rug Pull 风险",
    "监管与法律风险",
    "交易所与系统运维风险",
    "稳定币异常风险",
    "爆仓 / 清算风险",
    "大额转账 / 巨鲸行为风险",
    "异常行情波动风险",
    "项目治理 / 团队异常风险",
    "偿付能力 / 储备 / 流动性风险",
    "基础设施 / 协议层异常风险",
    "代币发行 / 异常增发风险",
    "跨链桥 / 跨链资金风险",
    "宏观 / 政策冲击风险",
}
METHOD_PATHS = {
    "chat_agent": EXPERIMENT_DIR / "chat_agent" / "chat_agent_results.csv",
    "llm_ranking": EXPERIMENT_DIR / "llm_ranking" / "llm_ranking_results.csv",
    "risk_scanner": EXPERIMENT_DIR / "risk_scanner" / "risk_scanner_results.csv",
}


def risk_types_from_backend() -> set[str]:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.agents.chat_agent.tools.risk_scanner import RISK_NAME_MAP
    except Exception:
        return set(FALLBACK_RISK_TYPES)
    return set(RISK_NAME_MAP.values())


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def read_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        return next(reader, [])


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def parse_score(value: object) -> int | None:
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def expected_level(score: int) -> str:
    if score >= 80:
        return "高风险"
    if score >= 50:
        return "中风险"
    return "低风险"


def row_ref(row: dict[str, str], row_number: int) -> dict[str, str]:
    return {
        "row_number": str(row_number),
        "新闻id": normalize_text(row.get("新闻id")),
        "标题": normalize_text(row.get("标题")) or normalize_text(row.get("内容"))[:60],
    }


def duplicate_values(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    counts = Counter(normalize_text(row.get(field)) for row in rows if normalize_text(row.get(field)))
    return {value: count for value, count in counts.items() if count > 1}


def content_signature(row: dict[str, str]) -> str:
    text = normalize_text(row.get("标题") or row.get("内容"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def distribution(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    counts = Counter(normalize_text(row.get(field)) or "__missing__" for row in rows)
    return {key: counts[key] for key in sorted(counts)}


def score_stats_by_type(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    scores_by_type: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        score = parse_score(row.get("gold_score"))
        risk_type = normalize_text(row.get("gold_type")) or "__missing__"
        if score is not None:
            scores_by_type[risk_type].append(score)

    stats: dict[str, dict[str, Any]] = {}
    for risk_type, scores in sorted(scores_by_type.items()):
        stats[risk_type] = {
            "count": len(scores),
            "min": min(scores),
            "max": max(scores),
            "avg": round(mean(scores), 2),
        }
    return stats


def load_method_predictions() -> dict[str, dict[str, dict[str, str]]]:
    predictions: dict[str, dict[str, dict[str, str]]] = {}
    for method, path in METHOD_PATHS.items():
        if not path.exists():
            continue
        rows = load_csv(path)
        predictions[method] = {
            normalize_text(row.get("原始新闻id")): row
            for row in rows
            if normalize_text(row.get("原始新闻id"))
        }
    return predictions


def score_close(predicted: object, gold: object) -> bool:
    predicted_score = parse_score(predicted)
    gold_score = parse_score(gold)
    return predicted_score is not None and gold_score is not None and abs(predicted_score - gold_score) <= SCORE_TOLERANCE


def suspicious_by_predictions(
    rows: list[dict[str, str]],
    predictions: dict[str, dict[str, dict[str, str]]],
) -> list[dict[str, Any]]:
    if not predictions:
        return []

    suspicious: list[dict[str, Any]] = []
    method_count = len(predictions)
    for index, row in enumerate(rows, start=2):
        news_id = normalize_text(row.get("新闻id"))
        if not news_id:
            continue
        misses = {"score": 0, "level": 0, "type": 0}
        method_rows: dict[str, dict[str, str]] = {}
        for method, by_id in predictions.items():
            prediction = by_id.get(news_id)
            if not prediction:
                continue
            method_rows[method] = {
                "风险分数": normalize_text(prediction.get("风险分数")),
                "风险等级": normalize_text(prediction.get("风险等级")),
                "风险类别": normalize_text(prediction.get("风险类别")),
            }
            if not score_close(prediction.get("风险分数"), row.get("gold_score")):
                misses["score"] += 1
            if normalize_text(prediction.get("风险等级")) != normalize_text(row.get("gold_level")):
                misses["level"] += 1
            if normalize_text(prediction.get("风险类别")) != normalize_text(row.get("gold_type")):
                misses["type"] += 1

        if not method_rows:
            continue
        flags = [
            name
            for name, count in misses.items()
            if count == method_count
        ]
        if flags:
            suspicious.append(
                {
                    **row_ref(row, index),
                    "gold": {
                        "score": normalize_text(row.get("gold_score")),
                        "level": normalize_text(row.get("gold_level")),
                        "type": normalize_text(row.get("gold_type")),
                    },
                    "flags": flags,
                    "predictions": method_rows,
                }
            )
    return suspicious


def audit(path: Path, expected_rows: int) -> dict[str, Any]:
    allowed_types = risk_types_from_backend() | {"综合风险"}
    header = read_header(path)
    rows = load_csv(path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    missing_columns = [column for column in EXPECTED_COLUMNS if column not in header]
    extra_columns = [column for column in header if column not in EXPECTED_COLUMNS]
    if missing_columns:
        errors.append({"type": "missing_columns", "columns": missing_columns})
    if extra_columns:
        warnings.append({"type": "extra_columns", "columns": extra_columns})
    if len(rows) != expected_rows:
        errors.append({"type": "row_count_mismatch", "expected": expected_rows, "actual": len(rows)})

    duplicate_ids = duplicate_values(rows, "新闻id")
    duplicate_links = duplicate_values(rows, "链接")
    if duplicate_ids:
        errors.append({"type": "duplicate_news_ids", "values": duplicate_ids})
    if duplicate_links:
        warnings.append({"type": "duplicate_links", "values": duplicate_links})

    signature_counts = Counter(content_signature(row) for row in rows)
    duplicate_signatures = {
        signature: count
        for signature, count in signature_counts.items()
        if count > 1
    }
    if duplicate_signatures:
        warnings.append({"type": "duplicate_title_or_content_signatures", "values": duplicate_signatures})

    missing_titles = 0
    score_values: list[int] = []
    for row_number, row in enumerate(rows, start=2):
        for field in CRITICAL_FIELDS:
            if not normalize_text(row.get(field)):
                errors.append({"type": "missing_field", "field": field, **row_ref(row, row_number)})

        if not normalize_text(row.get("标题")):
            missing_titles += 1

        score = parse_score(row.get("gold_score"))
        if score is None:
            errors.append({"type": "invalid_score", "value": row.get("gold_score"), **row_ref(row, row_number)})
            continue
        score_values.append(score)
        if score < 0 or score > 100:
            errors.append({"type": "score_out_of_range", "score": score, **row_ref(row, row_number)})

        level = normalize_text(row.get("gold_level"))
        if level not in LEVELS:
            errors.append({"type": "invalid_level", "level": level, **row_ref(row, row_number)})
        elif level != expected_level(score):
            errors.append(
                {
                    "type": "score_level_mismatch",
                    "score": score,
                    "level": level,
                    "expected_level": expected_level(score),
                    **row_ref(row, row_number),
                }
            )

        risk_type = normalize_text(row.get("gold_type"))
        if risk_type not in allowed_types:
            errors.append({"type": "invalid_type", "gold_type": risk_type, **row_ref(row, row_number)})
        if risk_type == "综合风险" and score > 20:
            warnings.append({"type": "general_risk_score_above_20", "score": score, **row_ref(row, row_number)})
        if risk_type != "综合风险" and score <= 10:
            warnings.append({"type": "explicit_type_score_at_or_below_10", "score": score, **row_ref(row, row_number)})

    if missing_titles:
        warnings.append({"type": "missing_titles", "count": missing_titles})

    method_predictions = load_method_predictions()
    suspicious = suspicious_by_predictions(rows, method_predictions)
    if suspicious:
        warnings.append({"type": "method_disagreement_review_candidates", "count": len(suspicious)})

    return {
        "input_csv": str(path),
        "expected_rows": expected_rows,
        "row_count": len(rows),
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "score_summary": {
            "count": len(score_values),
            "min": min(score_values) if score_values else None,
            "max": max(score_values) if score_values else None,
            "avg": round(mean(score_values), 2) if score_values else None,
        },
        "level_distribution": distribution(rows, "gold_level"),
        "type_distribution": distribution(rows, "gold_type"),
        "score_stats_by_type": score_stats_by_type(rows),
        "errors": errors,
        "warnings": warnings,
        "method_disagreement_review_candidates": suspicious,
    }


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit manual gold labels for the experiment dataset.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="待检查的统一金标 CSV。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="质量报告 JSON 输出路径。")
    parser.add_argument("--expected-rows", type=int, default=DEFAULT_EXPECTED_ROWS, help="期望样本行数。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = audit(args.input.resolve(), args.expected_rows)
    write_report(args.output.resolve(), report)
    print(
        f"金标质检完成：passed={report['passed']} "
        f"errors={report['error_count']} warnings={report['warning_count']} "
        f"report={args.output}"
    )
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
