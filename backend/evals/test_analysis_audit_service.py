from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import task_audit_service
from app.services.analysis_audit_service import (
    record_chat_analysis_error,
    record_chat_analysis_success,
    record_risk_assistant_success,
)


class AnalysisAuditServiceTest(unittest.TestCase):
    def test_chat_success_audit_records_summary_without_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            secret_text = "用户提交的敏感交易所提现危机文本"
            report = {
                "risk_score": 82,
                "risk_level": "high",
                "risk_type": "exchange_abnormality",
                "evidence_graph": [{"id": "e1"}],
                "decision_trace": [{"step": "rule"}],
                "scenario_assessments": [{"scenario": "S2"}],
                "chat_agent_result": {
                    "primary_scenario": "S2_EXCHANGE_ABNORMALITY",
                    "fallback_count": 1,
                    "llm_call_count": 2,
                    "report_mode": "deep_analysis",
                },
            }

            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                record_chat_analysis_success(
                    job_id="chat-1",
                    input_text=secret_text,
                    report=report,
                    duration_ms=123.4,
                    endpoint="/api/chat",
                    user_id="user-1",
                )
                events = task_audit_service.list_task_events(job_kind="chat_analysis")

        self.assertEqual(len(events), 1)
        event = events[0]
        payload = event["payload"]
        self.assertEqual(event["status"], "success")
        self.assertEqual(event["user_id"], "user-1")
        self.assertEqual(payload["risk_score"], 82)
        self.assertEqual(payload["primary_scenario"], "S2_EXCHANGE_ABNORMALITY")
        self.assertEqual(payload["input_chars"], len(secret_text))
        self.assertIn("input_sha256_16", payload)
        self.assertNotIn(secret_text, str(payload))

    def test_chat_error_and_risk_assistant_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                record_chat_analysis_error(
                    job_id="chat-2",
                    input_text="被攻击项目的长文本",
                    error=RuntimeError("llm unavailable"),
                    duration_ms=50,
                    endpoint="/api/chat/stream",
                    streaming=True,
                )
                record_risk_assistant_success(
                    job_id="assistant-1",
                    question="解释这条风险",
                    duration_ms=25,
                    endpoint="/api/risk-assistant",
                    answer_chars=128,
                )
                chat_events = task_audit_service.list_task_events(job_kind="chat_analysis")
                assistant_events = task_audit_service.list_task_events(job_kind="risk_assistant")

        self.assertEqual(chat_events[0]["status"], "error")
        self.assertEqual(chat_events[0]["payload"]["streaming"], True)
        self.assertEqual(chat_events[0]["payload"]["error_type"], "RuntimeError")
        self.assertEqual(assistant_events[0]["status"], "success")
        self.assertEqual(assistant_events[0]["payload"]["answer_chars"], 128)


if __name__ == "__main__":
    unittest.main()
