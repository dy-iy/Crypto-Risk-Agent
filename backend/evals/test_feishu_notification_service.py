from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.services import feishu_notification_service as feishu


class FeishuNotificationServiceTest(unittest.TestCase):
    def test_send_skips_when_disabled(self) -> None:
        with patch.dict("os.environ", {"FEISHU_NOTIFY_ENABLED": "0"}, clear=False):
            result = feishu.send_daily_report_to_feishu("ou_1", {"headline": "日报"})

        self.assertFalse(result["sent"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")

    def test_missing_config_returns_clear_error(self) -> None:
        with patch.dict("os.environ", {"FEISHU_APP_ID": "", "FEISHU_APP_SECRET": ""}, clear=False):
            with self.assertRaises(feishu.FeishuConfigError):
                feishu.get_tenant_access_token()

    def test_placeholder_or_invalid_app_id_returns_clear_error(self) -> None:
        with patch.dict("os.environ", {"FEISHU_APP_ID": "你的飞书应用 App ID", "FEISHU_APP_SECRET": "你的飞书应用 App Secret"}, clear=False):
            with self.assertRaises(feishu.FeishuConfigError):
                feishu.build_feishu_oauth_url("state")

        with patch.dict("os.environ", {"FEISHU_APP_ID": "app", "FEISHU_APP_SECRET": "secret"}, clear=False):
            with self.assertRaises(feishu.FeishuConfigError):
                feishu.build_feishu_oauth_url("state")

    def test_send_message_uses_tenant_token_and_open_id(self) -> None:
        token_response = Mock()
        token_response.json.return_value = {"code": 0, "tenant_access_token": "tenant-token", "expire": 7200}
        token_response.raise_for_status.return_value = None
        message_response = Mock()
        message_response.json.return_value = {"code": 0, "data": {"message_id": "mid"}}
        message_response.raise_for_status.return_value = None
        http_client = Mock()
        http_client.post.side_effect = [token_response, message_response]

        with (
            patch.dict("os.environ", {"FEISHU_NOTIFY_ENABLED": "1", "FEISHU_APP_ID": "cli_app", "FEISHU_APP_SECRET": "secret"}, clear=False),
            patch.object(feishu, "_tenant_token_cache", {"token": "", "expires_at": 0.0}),
            patch.object(feishu, "_httpx", return_value=http_client),
        ):
            result = feishu.send_daily_report_to_feishu("ou_1", {"headline": "日报", "personal_risk_score": 88})

        self.assertTrue(result["sent"])
        self.assertEqual(result["message_id"], "mid")
        self.assertEqual(http_client.post.call_args_list[1].kwargs["json"]["receive_id"], "ou_1")


if __name__ == "__main__":
    unittest.main()
