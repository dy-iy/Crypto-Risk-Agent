from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import request_body_limit_service as body_limit


class _FakeRequest:
    def __init__(self, *, method: str = "POST", headers: dict[str, str] | None = None, body: bytes = b"") -> None:
        self.method = method
        self.headers = headers or {}
        self._body = body
        self.body_read_count = 0

    async def body(self) -> bytes:
        self.body_read_count += 1
        return self._body


class RequestBodyLimitTest(unittest.IsolatedAsyncioTestCase):
    def test_max_request_body_bytes_uses_default_for_invalid_env(self) -> None:
        with patch.dict("os.environ", {"MAX_REQUEST_BODY_BYTES": "not-a-number"}, clear=False):
            self.assertEqual(body_limit.max_request_body_bytes(), body_limit.DEFAULT_MAX_REQUEST_BODY_BYTES)

    async def test_content_length_rejects_without_reading_body(self) -> None:
        request = _FakeRequest(
            headers={"content-length": "1001"},
            body=b"x" * 1001,
        )

        exceeds = await body_limit.request_body_exceeds_limit(request, 1000)

        self.assertTrue(exceeds)
        self.assertEqual(request.body_read_count, 0)

    async def test_missing_content_length_checks_body_bytes(self) -> None:
        request = _FakeRequest(body=b"x" * 1001)

        exceeds = await body_limit.request_body_exceeds_limit(request, 1000)

        self.assertTrue(exceeds)
        self.assertEqual(request.body_read_count, 1)

    async def test_get_requests_ignore_body_limit_check(self) -> None:
        request = _FakeRequest(method="GET", body=b"x" * 1001)

        exceeds = await body_limit.request_body_exceeds_limit(request, 1000)

        self.assertFalse(exceeds)
        self.assertEqual(request.body_read_count, 0)

    def test_content_length_helper_handles_invalid_header(self) -> None:
        request = SimpleNamespace(headers={"content-length": "invalid"})

        self.assertFalse(body_limit.content_length_exceeds_limit(request.headers, 1000))


if __name__ == "__main__":
    unittest.main()
