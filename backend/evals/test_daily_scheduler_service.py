from __future__ import annotations

import importlib
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def load_scheduler_service_with_stubs():
    ranking_graph_stub = types.ModuleType("app.agents.ranking_agent.graph")
    ranking_graph_stub.run_ranking_agent = lambda *args, **kwargs: {"date": "7d"}
    daily_report_agent_stub = types.ModuleType("app.agents.daily_report_agent")
    daily_report_agent_stub.run_daily_report_agent = lambda *args, **kwargs: {"range": "24h"}
    update_news_stub = types.ModuleType("app.data.update_news")
    update_news_stub.update_news_dataset = lambda *args, **kwargs: {
        "fetched_count": 1,
        "added_count": 1,
        "crawler_error": "",
    }
    auth_service_stub = types.ModuleType("app.services.auth_service")
    auth_service_stub.get_user_by_id = lambda *args, **kwargs: None
    portfolio_service_stub = types.ModuleType("app.services.portfolio_service")
    portfolio_service_stub.DEFAULT_USER_ID = "demo_user"
    with patch.dict(
        sys.modules,
        {
            "app.agents.ranking_agent.graph": ranking_graph_stub,
            "app.agents.daily_report_agent": daily_report_agent_stub,
            "app.data.update_news": update_news_stub,
            "app.services.auth_service": auth_service_stub,
            "app.services.portfolio_service": portfolio_service_stub,
        },
    ):
        sys.modules.pop("app.services.daily_scheduler_service", None)
        return importlib.import_module("app.services.daily_scheduler_service")


class DailySchedulerServiceTest(unittest.TestCase):
    def test_run_if_due_waits_until_configured_time(self) -> None:
        scheduler = load_scheduler_service_with_stubs()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "daily_scheduler_state.json"
            with patch.object(scheduler, "SCHEDULER_STATE_PATH", state_path):
                scheduler.set_daily_scheduler_enabled(True)
                result = scheduler.run_daily_scheduler_if_due(datetime(2026, 6, 11, 7, 59))

        self.assertFalse(result["due"])
        self.assertEqual(result["last_run_date"], "")

    def test_run_if_due_generates_reports_for_subscribed_users(self) -> None:
        scheduler = load_scheduler_service_with_stubs()
        saved_reports: list[tuple[str, dict[str, object]]] = []

        class _User:
            display_name = "Alice"

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "daily_scheduler_state.json"
            with (
                patch.object(scheduler, "SCHEDULER_STATE_PATH", state_path),
                patch.object(scheduler, "list_subscribed_daily_report_user_ids", return_value=["user-1"]),
                patch.object(scheduler, "get_user_by_id", return_value=_User()),
                patch.object(scheduler, "save_daily_report", side_effect=lambda user_id, report: saved_reports.append((user_id, report)) or {"report_id": "r1"}),
            ):
                scheduler.set_daily_scheduler_enabled(True)
                result = scheduler.run_daily_scheduler_if_due(datetime(2026, 6, 11, 8, 0))

        self.assertTrue(result["due"])
        self.assertEqual(result["last_run_date"], "2026-06-11")
        self.assertEqual(result["last_result"]["subscribed_user_count"], 1)
        self.assertEqual(result["last_result"]["generated_report_count"], 1)
        self.assertEqual(saved_reports[0][0], "user-1")

    def test_disabled_scheduler_does_not_run(self) -> None:
        scheduler = load_scheduler_service_with_stubs()
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "daily_scheduler_state.json"
            with patch.object(scheduler, "SCHEDULER_STATE_PATH", state_path):
                scheduler.set_daily_scheduler_enabled(False)
                result = scheduler.run_daily_scheduler_if_due(datetime(2026, 6, 11, 9, 0))

        self.assertFalse(result["due"])
        self.assertFalse(result["enabled"])


if __name__ == "__main__":
    unittest.main()
