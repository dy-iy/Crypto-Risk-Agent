from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas import ChatRequest, RiskAssistantRequest
from app.services.product_readiness_service import get_product_readiness


class ProductReadinessServiceTest(unittest.TestCase):
    def test_readiness_payload_has_operational_sections(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_LOCAL_CORS": "0",
                "CRYPTO_RISK_AGENT_OFFLINE": "0",
                "CSRF_PROTECTION_ENABLED": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertIn(readiness["status"], {"ready", "degraded", "not_ready"})
        self.assertEqual(readiness["service"], "cryptorisk-agent")
        self.assertTrue(readiness["environment"])
        self.assertTrue(readiness["security"])
        self.assertTrue(readiness["data"])
        self.assertTrue(readiness["storage"])
        self.assertIn("failed_checks", readiness["summary"])
        storage_names = {item["name"] for item in readiness["storage"]}
        security_names = {item["name"] for item in readiness["security"]}
        environment_names = {item["name"] for item in readiness["environment"]}
        self.assertIn("task_audit_db", storage_names)
        self.assertIn("sim_accounts_store", storage_names)
        self.assertIn("portfolio_refresh_jobs_store", storage_names)
        self.assertIn("news_update_jobs_store", storage_names)
        self.assertIn("TRUST_PROXY_HEADERS", security_names)
        self.assertIn("DEEPSEEK_MODEL", environment_names)
        self.assertIn("DEEPSEEK_TIMEOUT", environment_names)
        self.assertIn("DEEPSEEK_CLIENT", environment_names)

    def test_wrong_deepseek_model_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-chat",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_environment = [
            item["name"]
            for item in readiness["environment"]
            if not item.get("ok")
        ]
        self.assertIn("DEEPSEEK_MODEL", failed_environment)

    def test_invalid_deepseek_timeout_degrades_readiness(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "DEEPSEEK_TIMEOUT": "not-a-number",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        failed_environment = [
            item["name"]
            for item in readiness["environment"]
            if not item.get("ok")
        ]
        self.assertIn("DEEPSEEK_TIMEOUT", failed_environment)

    def test_missing_deepseek_client_is_not_ready_when_online(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
                "CRYPTO_RISK_AGENT_OFFLINE": "0",
            },
            clear=False,
        ), patch("app.services.product_readiness_service.find_spec", return_value=None):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_environment = [
            item["name"]
            for item in readiness["environment"]
            if not item.get("ok")
        ]
        self.assertIn("DEEPSEEK_CLIENT", failed_environment)

    def test_missing_deepseek_client_is_allowed_in_offline_mode(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
                "CRYPTO_RISK_AGENT_OFFLINE": "1",
            },
            clear=False,
        ), patch("app.services.product_readiness_service.find_spec", return_value=None):
            readiness = get_product_readiness()

        environment = {item["name"]: item for item in readiness["environment"]}
        self.assertTrue(environment["DEEPSEEK_CLIENT"]["ok"])
        self.assertTrue(environment["DEEPSEEK_API_KEY"]["ok"])

    def test_insecure_user_id_override_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_security = [
            item["name"]
            for item in readiness["security"]
            if not item.get("ok")
        ]
        self.assertIn("ALLOW_USER_ID_QUERY_OVERRIDE", failed_security)

    def test_public_system_observability_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_security = [
            item["name"]
            for item in readiness["security"]
            if not item.get("ok")
        ]
        self.assertIn("ALLOW_PUBLIC_SYSTEM_OBSERVABILITY", failed_security)

    def test_public_report_debug_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "ALLOW_PUBLIC_REPORT_DEBUG": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_security = [
            item["name"]
            for item in readiness["security"]
            if not item.get("ok")
        ]
        self.assertIn("ALLOW_PUBLIC_REPORT_DEBUG", failed_security)

    def test_disabled_csrf_protection_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "0",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_security = [
            item["name"]
            for item in readiness["security"]
            if not item.get("ok")
        ]
        self.assertIn("CSRF_PROTECTION_ENABLED", failed_security)

    def test_admin_username_registration_is_not_ready(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
                "ALLOW_ADMIN_USERNAME_REGISTRATION": "1",
            },
            clear=False,
        ):
            readiness = get_product_readiness()

        self.assertEqual(readiness["status"], "not_ready")
        failed_security = [
            item["name"]
            for item in readiness["security"]
            if not item.get("ok")
        ]
        self.assertIn("ALLOW_ADMIN_USERNAME_REGISTRATION", failed_security)

    def test_invalid_runtime_json_degrades_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_json = Path(tmpdir) / "sim_accounts.json"
            invalid_json.write_text("{broken", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AUTH_PASSWORD_PEPPER": "test-pepper",
                    "DEEPSEEK_API_KEY": "test-key",
                    "DEEPSEEK_MODEL": "deepseek-v4-pro",
                    "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                    "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                    "CSRF_PROTECTION_ENABLED": "1",
                    "SYSTEM_ADMIN_USER_IDS": "user-admin",
                    "ALLOW_ADMIN_USERNAME_REGISTRATION": "0",
                    "CRYPTO_RISK_AGENT_OFFLINE": "0",
                },
                clear=False,
            ), patch("app.services.product_readiness_service.find_spec", return_value=object()), patch(
                "app.services.product_readiness_service.SIM_ACCOUNTS_PATH",
                invalid_json,
            ):
                readiness = get_product_readiness()

        storage = {item["name"]: item for item in readiness["storage"]}
        self.assertEqual(readiness["status"], "degraded")
        self.assertFalse(storage["sim_accounts_store"]["ok"])
        self.assertFalse(storage["sim_accounts_store"]["valid_json"])
        self.assertIn("不是合法 JSON", storage["sim_accounts_store"]["message"])

    def test_invalid_request_body_limit_degrades_readiness(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AUTH_PASSWORD_PEPPER": "test-pepper",
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "ALLOW_USER_ID_QUERY_OVERRIDE": "0",
                "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0",
                "CSRF_PROTECTION_ENABLED": "1",
                "SYSTEM_ADMIN_USER_IDS": "user-admin",
                "ALLOW_ADMIN_USERNAME_REGISTRATION": "0",
                "CRYPTO_RISK_AGENT_OFFLINE": "0",
                "MAX_REQUEST_BODY_BYTES": "not-a-number",
            },
            clear=False,
        ), patch("app.services.product_readiness_service.find_spec", return_value=object()):
            readiness = get_product_readiness()

        security = {item["name"]: item for item in readiness["security"]}
        self.assertEqual(readiness["status"], "degraded")
        self.assertFalse(security["MAX_REQUEST_BODY_BYTES"]["ok"])
        self.assertEqual(security["MAX_REQUEST_BODY_BYTES"]["effective_bytes"], 1_000_000)

    def test_request_input_limits_are_enforced(self) -> None:
        ChatRequest(message="a" * 12000)
        RiskAssistantRequest(question="q" * 2000, selected_text="s" * 12000)

        with self.assertRaises(ValidationError):
            ChatRequest(message="a" * 12001)
        with self.assertRaises(ValidationError):
            RiskAssistantRequest(question="q" * 2001)


if __name__ == "__main__":
    unittest.main()
