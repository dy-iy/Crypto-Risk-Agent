from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.chat_agent import run_chat_agent  # noqa: E402


DATASET = Path(__file__).with_name("risk_cases_smoke.jsonl")


def _load_cases() -> list[dict[str, object]]:
    with DATASET.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _is_high(score: int) -> bool:
    return score >= 76


def main() -> int:
    cases = _load_cases()
    case_by_id = {case["id"]: case for case in cases}
    rows: list[dict[str, object]] = []
    latencies: list[float] = []
    errors = 0
    fallback_count = 0
    llm_call_count = 0
    json_parse_error_count = 0

    for case in cases:
        start = time.perf_counter()
        try:
            report = run_chat_agent(str(case["text"]))
        except Exception as exc:
            errors += 1
            rows.append({"id": case["id"], "error": str(exc)})
            continue
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)
        chat_agent_result = report.get("chat_agent_result") or report.get("v6_result", {}) if isinstance(report, dict) else {}
        debug = report.get("debug", {}) if isinstance(report, dict) else {}
        evidence_debug = debug.get("evidence_extraction", {}) if isinstance(debug, dict) else {}
        score = int(report.get("risk_score", 0))
        primary = str(chat_agent_result.get("primary_scenario") or "")
        expected_min = int(case["expected_min_score"])
        expected_max = int(case["expected_max_score"])
        expected_mid = (expected_min + expected_max) / 2
        expected_high = bool(case["expected_high_risk"])
        extraction_mode = str(chat_agent_result.get("extraction_mode") or evidence_debug.get("mode") or "unknown")
        case_fallback_count = int(chat_agent_result.get("fallback_count") or evidence_debug.get("fallback_count") or 0)
        case_llm_call_count = int(chat_agent_result.get("llm_call_count") or evidence_debug.get("llm_call_count") or 0)
        case_json_parse_errors = int(
            chat_agent_result.get("json_parse_error_count") or evidence_debug.get("json_parse_error_count") or 0
        )
        fallback_count += case_fallback_count
        llm_call_count += case_llm_call_count
        json_parse_error_count += case_json_parse_errors
        rows.append(
            {
                "id": case["id"],
                "score": score,
                "primary_scenario": primary,
                "expected_scenario": case["expected_scenario"],
                "scenario_ok": primary == case["expected_scenario"],
                "score_ok": expected_min <= score <= expected_max,
                "high_ok": _is_high(score) == expected_high,
                "score_abs_error": round(abs(score - expected_mid), 1),
                "extraction_mode": extraction_mode,
                "latency_ms": round(latency_ms, 1),
            }
        )

    valid = [row for row in rows if "error" not in row]
    true_positive = sum(
        1
        for row in valid
        if _is_high(int(row["score"])) and bool(case_by_id[row["id"]]["expected_high_risk"])
    )
    false_positive = sum(
        1
        for row in valid
        if _is_high(int(row["score"])) and not bool(case_by_id[row["id"]]["expected_high_risk"])
    )
    false_negative = sum(
        1
        for row in valid
        if not _is_high(int(row["score"])) and bool(case_by_id[row["id"]]["expected_high_risk"])
    )
    scenario_accuracy = sum(1 for row in valid if row["scenario_ok"]) / max(1, len(valid))
    score_range_accuracy = sum(1 for row in valid if row["score_ok"]) / max(1, len(valid))
    high_risk_accuracy = sum(1 for row in valid if row["high_ok"]) / max(1, len(valid))
    high_risk_precision = true_positive / max(1, true_positive + false_positive)
    high_risk_recall = true_positive / max(1, true_positive + false_negative)
    score_mae = statistics.mean(float(row["score_abs_error"]) for row in valid) if valid else 0
    latency_avg = statistics.mean(latencies) if latencies else 0
    latency_p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0

    print(json.dumps(
        {
            "total": len(cases),
            "valid": len(valid),
            "error_rate": errors / max(1, len(cases)),
            "scenario_accuracy": round(scenario_accuracy, 3),
            "score_range_accuracy": round(score_range_accuracy, 3),
            "high_risk_accuracy": round(high_risk_accuracy, 3),
            "high_risk_precision": round(high_risk_precision, 3),
            "high_risk_recall": round(high_risk_recall, 3),
            "score_mae": round(score_mae, 2),
            "latency_avg": round(latency_avg, 1),
            "latency_p95": round(latency_p95, 1),
            "latency_avg_ms": round(latency_avg, 1),
            "latency_p95_ms": round(latency_p95, 1),
            "fallback_count": fallback_count,
            "llm_call_count": llm_call_count,
            "json_parse_error_count": json_parse_error_count,
            "failed_cases": [row for row in rows if row.get("error") or not row.get("scenario_ok") or not row.get("score_ok") or not row.get("high_ok")],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
