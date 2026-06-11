from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from evals.quality_gate import (  # noqa: E402
    build_gate_result,
    check_env_example_contract,
    check_eval_metrics,
    check_frontend_api_boundaries,
    check_product_security_controls,
    check_public_error_boundaries,
    check_risk_case_coverage,
    check_runtime_data_gitignored,
)


def _read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run CryptoRisk product quality gate.")
    parser.add_argument(
        "--risk-eval-json",
        type=Path,
        default=None,
        help="Optional JSON output from backend/evals/run_risk_eval.py to enforce metric thresholds.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    args = parser.parse_args()

    checks = [
        check_risk_case_coverage(),
        check_frontend_api_boundaries(),
        check_runtime_data_gitignored(),
        check_env_example_contract(),
        check_product_security_controls(),
        check_public_error_boundaries(),
    ]
    if args.risk_eval_json:
        checks.append(check_eval_metrics(_read_json(args.risk_eval_json)))

    result = build_gate_result(checks)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
