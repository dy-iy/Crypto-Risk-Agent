from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas_reports import AnalysisReportDispositionUpdate, AnalysisReportPayload
from app.services import analysis_report_service


class AnalysisReportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "analysis_reports.sqlite3"
        self.db_patch = patch.object(analysis_report_service, "REPORT_DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmpdir.cleanup()

    def test_analysis_report_round_trip(self) -> None:
        payload = AnalysisReportPayload(
            id="report-1",
            title="提现暂停风险分析报告",
            created_at="2026-05-30 16:00",
            input="某交易所暂停提现",
            report={"summary": "提现暂停需要核验", "risk_score": 90},
        )

        saved = analysis_report_service.save_analysis_report("user-1", payload)
        self.assertEqual(saved.id, "report-1")
        self.assertEqual(saved.disposition, "pending")

        updated = analysis_report_service.update_analysis_report_disposition(
            "user-1",
            "report-1",
            AnalysisReportDispositionUpdate(disposition="verified", disposition_note="已核验官方公告"),
        )
        self.assertEqual(updated.disposition, "verified")
        self.assertEqual(updated.disposition_note, "已核验官方公告")

        items = analysis_report_service.list_analysis_reports("user-1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].report["risk_score"], 90)

    def test_analysis_report_is_scoped_by_user(self) -> None:
        payload = AnalysisReportPayload(
            id="shared-id",
            title="报告",
            created_at="2026-05-30 16:00",
            input="风险事件",
            report={"summary": "test"},
        )

        analysis_report_service.save_analysis_report("user-a", payload)

        self.assertEqual(analysis_report_service.list_analysis_reports("user-b"), [])
        with self.assertRaises(analysis_report_service.AnalysisReportError):
            analysis_report_service.update_analysis_report_disposition(
                "user-b",
                "shared-id",
                AnalysisReportDispositionUpdate(disposition="ignored"),
            )

    def test_delete_missing_analysis_report_raises(self) -> None:
        with self.assertRaises(analysis_report_service.AnalysisReportError):
            analysis_report_service.delete_analysis_report("user-1", "missing-report")

    def test_analysis_report_size_limits(self) -> None:
        oversized_input = AnalysisReportPayload(
            id="too-large-input",
            title="报告",
            created_at="2026-05-30 16:00",
            input="x" * (analysis_report_service.MAX_REPORT_INPUT_CHARS + 1),
            report={"summary": "test"},
        )
        oversized_json = AnalysisReportPayload(
            id="too-large-json",
            title="报告",
            created_at="2026-05-30 16:00",
            input="风险事件",
            report={"blob": "x" * analysis_report_service.MAX_REPORT_JSON_BYTES},
        )

        with self.assertRaises(analysis_report_service.AnalysisReportTooLargeError):
            analysis_report_service.save_analysis_report("user-1", oversized_input)
        with self.assertRaises(analysis_report_service.AnalysisReportTooLargeError):
            analysis_report_service.save_analysis_report("user-1", oversized_json)


if __name__ == "__main__":
    unittest.main()
