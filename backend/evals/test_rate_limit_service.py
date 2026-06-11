from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import rate_limit_service


class RateLimitServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        rate_limit_service.reset_rate_limit_state()

    def tearDown(self) -> None:
        rate_limit_service.reset_rate_limit_state()

    def test_agent_limit_blocks_after_configured_threshold(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "API_RATE_LIMIT_ENABLED": "1",
                "AGENT_RATE_LIMIT_PER_5_MINUTES": "2",
            },
            clear=False,
        ):
            first = rate_limit_service.check_rate_limit(
                identity="client-a",
                path="/api/chat",
                method="POST",
                now=100,
            )
            second = rate_limit_service.check_rate_limit(
                identity="client-a",
                path="/api/chat/stream",
                method="POST",
                now=101,
            )
            blocked = rate_limit_service.check_rate_limit(
                identity="client-a",
                path="/api/risk-assistant/stream",
                method="POST",
                now=102,
            )

        self.assertTrue(first.allowed)
        self.assertEqual(second.remaining, 0)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.rule_name, "agent")
        self.assertEqual(blocked.retry_after_seconds, 298)

    def test_rate_limit_window_recovers(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "API_RATE_LIMIT_ENABLED": "1",
                "AUTH_RATE_LIMIT_PER_MINUTE": "1",
            },
            clear=False,
        ):
            allowed = rate_limit_service.check_rate_limit(
                identity="client-b",
                path="/api/auth/login",
                method="POST",
                now=200,
            )
            blocked = rate_limit_service.check_rate_limit(
                identity="client-b",
                path="/api/auth/login",
                method="POST",
                now=201,
            )
            recovered = rate_limit_service.check_rate_limit(
                identity="client-b",
                path="/api/auth/login",
                method="POST",
                now=261,
            )

        self.assertTrue(allowed.allowed)
        self.assertFalse(blocked.allowed)
        self.assertTrue(recovered.allowed)

    def test_unmatched_or_disabled_paths_are_allowed(self) -> None:
        with patch.dict("os.environ", {"API_RATE_LIMIT_ENABLED": "1"}, clear=False):
            health = rate_limit_service.check_rate_limit(
                identity="client-c",
                path="/api/system/readiness",
                method="GET",
                now=300,
            )
        with patch.dict("os.environ", {"API_RATE_LIMIT_ENABLED": "0"}, clear=False):
            disabled = rate_limit_service.check_rate_limit(
                identity="client-c",
                path="/api/auth/login",
                method="POST",
                now=300,
            )

        self.assertTrue(health.allowed)
        self.assertEqual(health.rule_name, "")
        self.assertTrue(disabled.allowed)
        self.assertEqual(disabled.rule_name, "")

    def test_mutation_limit_is_separate_from_agent_limit(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "API_RATE_LIMIT_ENABLED": "1",
                "AGENT_RATE_LIMIT_PER_5_MINUTES": "1",
                "MUTATION_RATE_LIMIT_PER_MINUTE": "1",
            },
            clear=False,
        ):
            agent = rate_limit_service.check_rate_limit(
                identity="client-d",
                path="/api/chat",
                method="POST",
                now=400,
            )
            mutation = rate_limit_service.check_rate_limit(
                identity="client-d",
                path="/api/portfolio/watchlist",
                method="POST",
                now=401,
            )
            blocked_mutation = rate_limit_service.check_rate_limit(
                identity="client-d",
                path="/api/portfolio/watchlist",
                method="POST",
                now=402,
            )

        self.assertTrue(agent.allowed)
        self.assertTrue(mutation.allowed)
        self.assertFalse(blocked_mutation.allowed)
        self.assertEqual(blocked_mutation.rule_name, "mutation")

    def test_expired_buckets_are_cleaned_up(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "API_RATE_LIMIT_ENABLED": "1",
                "AUTH_RATE_LIMIT_PER_MINUTE": "1",
            },
            clear=False,
        ):
            rate_limit_service.check_rate_limit(
                identity="stale-client",
                path="/api/auth/login",
                method="POST",
                now=10,
            )
            status_before = rate_limit_service.rate_limit_status()
            rate_limit_service.check_rate_limit(
                identity="fresh-client",
                path="/api/auth/login",
                method="POST",
                now=200,
            )
            status_after = rate_limit_service.rate_limit_status()

        self.assertGreaterEqual(status_before["active_buckets"], 1)
        self.assertEqual(status_after["active_buckets"], 1)


if __name__ == "__main__":
    unittest.main()
