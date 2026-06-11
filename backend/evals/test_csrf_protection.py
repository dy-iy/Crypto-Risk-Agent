from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.csrf_service import CSRF_HEADER_NAME, csrf_request_allowed


SESSION_COOKIE_NAME = "cryptorisk_session"


def allowed(method: str, *, session: bool = False, csrf_header: bool = False) -> bool:
    cookies = {SESSION_COOKIE_NAME: "session-token"} if session else {}
    headers = {CSRF_HEADER_NAME: "1"} if csrf_header else {}
    return csrf_request_allowed(
        method=method,
        cookies=cookies,
        headers=headers,
        session_cookie_name=SESSION_COOKIE_NAME,
    )


class CsrfProtectionTest(unittest.TestCase):
    def test_safe_or_unauthenticated_requests_are_allowed(self) -> None:
        self.assertTrue(allowed("GET", session=True))
        self.assertTrue(allowed("POST"))

    def test_session_mutation_requires_csrf_header(self) -> None:
        self.assertFalse(allowed("POST", session=True))
        self.assertTrue(allowed("DELETE", session=True, csrf_header=True))

    def test_csrf_can_be_disabled_for_internal_testing(self) -> None:
        with patch.dict("os.environ", {"CSRF_PROTECTION_ENABLED": "0"}, clear=False):
            self.assertTrue(allowed("POST", session=True))


if __name__ == "__main__":
    unittest.main()
