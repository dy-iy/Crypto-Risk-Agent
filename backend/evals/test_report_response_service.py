from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.report_response_service import sanitize_risk_report_for_public_api


class ReportResponseServiceTest(unittest.TestCase):
    def test_public_report_sanitizer_removes_internal_debug_fields(self) -> None:
        report = {
            "summary": "风险分析完成",
            "risk_score": 80,
            "evidence_graph": [{"id": "ev-1"}],
            "decision_trace": {"final_score": 80},
            "scenario_assessments": [{"scenario": "S1_ATTACK_EXPLOIT"}],
            "debug": {"signal_scan": {"raw": "internal"}},
            "raw_agent_outputs": {"agent": "raw"},
            "merged_result": {"legacy": "merged"},
            "calibrated_result": {"legacy": "calibrated"},
            "structured_review_result": {"internal": True},
        }

        with patch.dict("os.environ", {"ALLOW_PUBLIC_REPORT_DEBUG": "0"}, clear=False):
            sanitized = sanitize_risk_report_for_public_api(report)

        self.assertEqual(sanitized["evidence_graph"], [{"id": "ev-1"}])
        self.assertEqual(sanitized["decision_trace"], {"final_score": 80})
        self.assertNotIn("debug", sanitized)
        self.assertNotIn("raw_agent_outputs", sanitized)
        self.assertNotIn("merged_result", sanitized)
        self.assertNotIn("calibrated_result", sanitized)
        self.assertNotIn("structured_review_result", sanitized)
        self.assertIn("debug", report)

    def test_public_report_debug_can_be_explicitly_enabled(self) -> None:
        report = {"summary": "风险分析完成", "debug": {"signal_scan": {"raw": "internal"}}}

        with patch.dict("os.environ", {"ALLOW_PUBLIC_REPORT_DEBUG": "1"}, clear=False):
            sanitized = sanitize_risk_report_for_public_api(report)

        self.assertEqual(sanitized["debug"], {"signal_scan": {"raw": "internal"}})
        self.assertIsNot(sanitized, report)


if __name__ == "__main__":
    unittest.main()
