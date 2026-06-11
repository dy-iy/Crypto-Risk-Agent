from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import task_audit_service


class TaskAuditServiceTest(unittest.TestCase):
    def test_task_events_are_recorded_and_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                task_audit_service.record_task_event(
                    job_kind="news_update",
                    job_id="job-1",
                    event_type="created",
                    status="queued",
                    stage="queued",
                    message="created",
                    payload={"source": "test"},
                )
                task_audit_service.record_task_event(
                    job_kind="news_update",
                    job_id="job-1",
                    event_type="state_update",
                    status="success",
                    stage="done",
                    message="done",
                    payload={"processed": 3},
                )

                events = task_audit_service.list_task_events(job_kind="news_update", job_id="job-1")
                summary = task_audit_service.task_audit_summary()

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["status"], "success")
        self.assertEqual(events[0]["payload"]["processed"], 3)
        self.assertEqual(events[1]["event_type"], "created")
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["recent_error_events"], 0)

    def test_task_audit_metrics_group_by_kind_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                task_audit_service.record_task_event(
                    job_kind="chat_analysis",
                    job_id="chat-1",
                    event_type="analysis_run",
                    status="success",
                    stage="completed",
                    message="done",
                )
                task_audit_service.record_task_event(
                    job_kind="chat_analysis",
                    job_id="chat-2",
                    event_type="analysis_run",
                    status="error",
                    stage="failed",
                    message="failed",
                )
                task_audit_service.record_task_event(
                    job_kind="portfolio_refresh",
                    job_id="portfolio-1",
                    event_type="state_update",
                    status="running",
                    stage="refreshing",
                    message="running",
                )

                metrics = task_audit_service.task_audit_metrics(window_hours=24)

        by_kind = {item["job_kind"]: item for item in metrics["by_kind"]}
        self.assertEqual(metrics["window_events"], 3)
        self.assertEqual(by_kind["chat_analysis"]["total"], 2)
        self.assertEqual(by_kind["chat_analysis"]["success"], 1)
        self.assertEqual(by_kind["chat_analysis"]["error"], 1)
        self.assertEqual(by_kind["chat_analysis"]["error_rate"], 0.5)
        self.assertEqual(by_kind["portfolio_refresh"]["running"], 1)
        self.assertEqual(by_kind["portfolio_refresh"]["latest_event"]["job_id"], "portfolio-1")

    def test_task_audit_prune_by_max_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                for index in range(5):
                    task_audit_service.record_task_event(
                        job_kind="chat_analysis",
                        job_id=f"chat-{index}",
                        event_type="analysis_run",
                        status="success",
                        stage="completed",
                        message="done",
                    )

                result = task_audit_service.prune_task_audit_events(retention_days=3650, max_events=3)
                events = task_audit_service.list_task_events(job_kind="chat_analysis", limit=10)

        self.assertEqual(result["deleted_by_count"], 2)
        self.assertEqual(result["remaining_events"], 3)
        self.assertEqual([event["job_id"] for event in events], ["chat-4", "chat-3", "chat-2"])

    def test_account_security_events_only_include_account_kinds_for_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                task_audit_service.record_task_event(
                    job_kind="account_security",
                    job_id="sec-1",
                    event_type="password_change",
                    status="success",
                    stage="password_changed",
                    message="changed",
                    user_id="user-1",
                )
                task_audit_service.record_task_event(
                    job_kind="account_export",
                    job_id="export-1",
                    event_type="account_export",
                    status="success",
                    stage="exported",
                    message="exported",
                    user_id="user-1",
                )
                task_audit_service.record_task_event(
                    job_kind="chat_analysis",
                    job_id="chat-1",
                    event_type="analysis_run",
                    status="success",
                    stage="completed",
                    message="chat",
                    user_id="user-1",
                )
                task_audit_service.record_task_event(
                    job_kind="account_security",
                    job_id="sec-2",
                    event_type="login",
                    status="success",
                    stage="logged_in",
                    message="login",
                    user_id="user-2",
                )

                events = task_audit_service.list_account_security_events("user-1")

        self.assertEqual([event["event_type"] for event in events], ["account_export", "password_change"])
        self.assertTrue(all(event["user_id"] == "user-1" for event in events))

    def test_delete_task_events_for_user_removes_only_matching_user_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                for index in range(2):
                    task_audit_service.record_task_event(
                        job_kind="chat_analysis",
                        job_id=f"chat-{index}",
                        event_type="analysis_run",
                        status="success",
                        stage="completed",
                        message="done",
                        user_id="user-1",
                    )
                task_audit_service.record_task_event(
                    job_kind="account_security",
                    job_id="sec-2",
                    event_type="login",
                    status="success",
                    stage="logged_in",
                    message="login",
                    user_id="user-2",
                )

                deleted = task_audit_service.delete_task_events_for_user("user-1")
                remaining_user_1 = task_audit_service.list_task_events(user_id="user-1")
                remaining_user_2 = task_audit_service.list_task_events(user_id="user-2")

        self.assertEqual(deleted, 2)
        self.assertEqual(remaining_user_1, [])
        self.assertEqual(len(remaining_user_2), 1)
        self.assertEqual(remaining_user_2[0]["job_id"], "sec-2")


if __name__ == "__main__":
    unittest.main()
