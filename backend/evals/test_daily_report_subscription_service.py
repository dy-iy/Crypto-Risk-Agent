from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import daily_report_subscription_service as subscriptions


class DailyReportSubscriptionServiceTest(unittest.TestCase):
    def test_subscription_toggle_persists_enabled_users(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subscriptions.json"
            with patch.object(subscriptions, "SUBSCRIPTIONS_PATH", path):
                enabled = subscriptions.set_daily_report_subscription("user-1", True)
                disabled = subscriptions.set_daily_report_subscription("user-2", False)

                self.assertTrue(enabled["enabled"])
                self.assertFalse(disabled["enabled"])
                self.assertTrue(subscriptions.get_daily_report_subscription("user-1")["enabled"])
                self.assertEqual(subscriptions.list_subscribed_daily_report_user_ids(), ["user-1"])


if __name__ == "__main__":
    unittest.main()
