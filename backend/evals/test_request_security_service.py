from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.request_security_service import (
    client_ip_hash,
    request_client_identity,
    request_security_context,
    request_uses_https,
    safe_user_agent,
    trust_proxy_headers_enabled,
)


class RequestSecurityServiceTest(unittest.TestCase):
    def test_request_uses_https_accepts_actual_https(self) -> None:
        with patch.dict("os.environ", {"TRUST_PROXY_HEADERS": "0"}, clear=False):
            self.assertTrue(request_uses_https("https", {}))

    def test_request_uses_https_trusts_forwarded_proto_only_when_enabled(self) -> None:
        headers = {"x-forwarded-proto": "https"}

        with patch.dict("os.environ", {"TRUST_PROXY_HEADERS": "1"}, clear=False):
            self.assertTrue(trust_proxy_headers_enabled())
            self.assertTrue(request_uses_https("http", headers))

        with patch.dict("os.environ", {"TRUST_PROXY_HEADERS": "0"}, clear=False):
            self.assertFalse(trust_proxy_headers_enabled())
            self.assertFalse(request_uses_https("http", headers))

    def test_request_client_identity_uses_forwarded_for_only_when_enabled(self) -> None:
        headers = {"x-forwarded-for": "203.0.113.10, 10.0.0.2"}

        with patch.dict("os.environ", {"TRUST_PROXY_HEADERS": "1"}, clear=False):
            self.assertEqual(request_client_identity("10.0.0.9", headers), "203.0.113.10")

        with patch.dict("os.environ", {"TRUST_PROXY_HEADERS": "0"}, clear=False):
            self.assertEqual(request_client_identity("10.0.0.9", headers), "10.0.0.9")

    def test_request_security_context_hashes_ip_and_sanitizes_user_agent(self) -> None:
        user_agent = "  Mozilla/5.0   Chrome/120  " + ("x" * 200)

        context = request_security_context("203.0.113.10", user_agent)

        self.assertEqual(context["client_ip_hash"], client_ip_hash("203.0.113.10"))
        self.assertEqual(len(context["client_ip_hash"]), 12)
        self.assertEqual(context["user_agent"], safe_user_agent(user_agent))
        self.assertLessEqual(len(context["user_agent"]), 160)


if __name__ == "__main__":
    unittest.main()
