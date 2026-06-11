from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evals.quality_gate import (
    check_env_example_contract,
    check_eval_metrics,
    check_frontend_api_boundaries,
    check_product_security_controls,
    check_public_error_boundaries,
    check_risk_case_coverage,
    check_runtime_data_gitignored,
)


class QualityGateTest(unittest.TestCase):
    def test_risk_case_coverage_detects_missing_counterexamples(self) -> None:
        cases = [
            {
                "id": f"case-{index}",
                "text": "bridge exploit",
                "expected_min_score": 76,
                "expected_max_score": 95,
                "expected_high_risk": True,
                "expected_scenario": "S10_BRIDGE_CROSS_CHAIN_RISK",
            }
            for index in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cases.jsonl"
            path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")

            check = check_risk_case_coverage(path)

        self.assertFalse(check.passed)
        self.assertIn("S10_BRIDGE_CROSS_CHAIN_RISK", check.details["scenarios_without_counterexamples"])

    def test_general_unknown_scenario_does_not_require_high_risk_example(self) -> None:
        cases = [
            {
                "id": f"general-{index}",
                "text": "市场观察，没有明确风险事件。",
                "expected_min_score": 0,
                "expected_max_score": 35,
                "expected_high_risk": False,
                "expected_scenario": "S0_GENERAL_UNKNOWN",
            }
            for index in range(80)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cases.jsonl"
            path.write_text("\n".join(json.dumps(case) for case in cases), encoding="utf-8")

            check = check_risk_case_coverage(path)

        self.assertTrue(check.passed)

    def test_frontend_boundary_check_finds_forbidden_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "lib").mkdir()
            (root / "lib" / "api.ts").write_text(
                "fetch('http://127.0.0.1:8001/api/chat')",
                encoding="utf-8",
            )

            check = check_frontend_api_boundaries(root)

        self.assertFalse(check.passed)
        self.assertEqual(check.details["violation_count"], 1)
        self.assertIn("forbidden_local_address_or_port", check.details["violations"][0]["reasons"])

    def test_frontend_boundary_check_requires_api_path_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "components").mkdir()
            (root / "components" / "bad-widget.tsx").write_text(
                'fetch("https://example.com/market-data")',
                encoding="utf-8",
            )

            check = check_frontend_api_boundaries(root)

        self.assertFalse(check.passed)
        self.assertEqual(check.details["violation_count"], 1)
        self.assertIn("frontend_request_must_use_api_path", check.details["violations"][0]["reasons"])

    def test_runtime_gitignore_check_requires_product_datastores(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".gitignore"
            path.write_text("backend/app/data/auth.sqlite3\n", encoding="utf-8")

            check = check_runtime_data_gitignored(path)

        self.assertFalse(check.passed)
        self.assertIn("backend/app/data/portfolio.sqlite3", check.details["missing_entries"])

    def test_env_example_contract_detects_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env.example"
            path.write_text("DEEPSEEK_API_KEY=replace-with-your-deepseek-api-key\n", encoding="utf-8")

            check = check_env_example_contract(path)

        self.assertFalse(check.passed)
        self.assertIn("AUTH_PASSWORD_PEPPER", check.details["missing_keys"])

    def test_env_example_contract_detects_realistic_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env.example"
            path.write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=sk-1234567890abcdef",
                        "DEEPSEEK_MODEL=deepseek-v4-pro",
                        "DEEPSEEK_BASE_URL=https://api.deepseek.com",
                        "DEEPSEEK_TIMEOUT=30",
                        "CRYPTO_RISK_AGENT_OFFLINE=0",
                        "AUTH_PASSWORD_PEPPER=replace-with-a-long-random-secret",
                        "CORS_ALLOWED_ORIGINS=https://kassa-wiki.top,https://www.kassa-wiki.top",
                        "ALLOW_LOCAL_CORS=0",
                        "ALLOW_USER_ID_QUERY_OVERRIDE=0",
                        "CSRF_PROTECTION_ENABLED=1",
                        "TRUST_PROXY_HEADERS=1",
                        "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY=0",
                        "ALLOW_SYSTEM_EVENT_GLOBAL_QUERY=0",
                        "SYSTEM_ADMIN_USERNAMES=",
                        "SYSTEM_ADMIN_USER_IDS=user-replace-with-admin-user-id",
                        "ALLOW_ADMIN_USERNAME_REGISTRATION=0",
                        "API_RATE_LIMIT_ENABLED=1",
                        "AUTH_RATE_LIMIT_PER_MINUTE=8",
                        "AGENT_RATE_LIMIT_PER_5_MINUTES=30",
                        "MUTATION_RATE_LIMIT_PER_MINUTE=90",
                        "MAX_REQUEST_BODY_BYTES=1000000",
                        "TASK_AUDIT_RETENTION_DAYS=30",
                        "TASK_AUDIT_MAX_EVENTS=20000",
                    ]
                ),
                encoding="utf-8",
            )

            check = check_env_example_contract(path)

        self.assertFalse(check.passed)
        self.assertTrue(check.details["forbidden_matches"])

    def test_current_env_example_contract_passes(self) -> None:
        check = check_env_example_contract()

        self.assertTrue(check.passed)

    def test_product_security_controls_detect_missing_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend" / "app" / "services").mkdir(parents=True)
            (root / "backend" / "app" / "services" / "csrf_service.py").write_text(
                "CSRF_PROTECTION_ENABLED = '1'\n",
                encoding="utf-8",
            )

            check = check_product_security_controls(root)

        self.assertFalse(check.passed)
        controls = {item["control"] for item in check.details["missing_controls"]}
        self.assertIn("csrf_service", controls)
        self.assertIn("account_export_delete_api", controls)

    def test_current_product_security_controls_pass(self) -> None:
        check = check_product_security_controls()

        self.assertTrue(check.passed)

    def test_public_error_boundaries_detect_exception_detail_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend" / "app" / "api").mkdir(parents=True)
            (root / "backend").mkdir(exist_ok=True)
            (root / "backend" / "main.py").write_text(
                'raise HTTPException(status_code=500, detail=f"Agent workflow failed: {exc}")\n',
                encoding="utf-8",
            )
            (root / "backend" / "app" / "api" / "risk_ranking.py").write_text(
                'raise HTTPException(status_code=500, detail="News update failed. Please retry later.")\n',
                encoding="utf-8",
            )

            check = check_public_error_boundaries(root)

        self.assertFalse(check.passed)
        self.assertEqual(check.details["violation_count"], 1)

    def test_current_public_error_boundaries_pass(self) -> None:
        check = check_public_error_boundaries()

        self.assertTrue(check.passed)

    def test_eval_metric_thresholds(self) -> None:
        passing = check_eval_metrics(
            {
                "error_rate": 0,
                "high_risk_recall": 0.95,
                "high_risk_false_positive_rate": 0.1,
                "scenario_accuracy": 0.85,
                "evidence_graph_coverage": 1,
                "decision_trace_coverage": 1,
            }
        )
        failing = check_eval_metrics(
            {
                "error_rate": 0,
                "high_risk_recall": 0.8,
                "high_risk_false_positive_rate": 0.2,
                "scenario_accuracy": 0.7,
                "evidence_graph_coverage": 0.5,
                "decision_trace_coverage": 0.5,
            }
        )

        self.assertTrue(passing.passed)
        self.assertFalse(failing.passed)
        self.assertIn("high_risk_recall", failing.details["failures"])


if __name__ == "__main__":
    unittest.main()
