from __future__ import annotations

import pytest

from app.schemas_reports import AnalysisReportDispositionUpdate, AnalysisReportPayload
from app.services import analysis_report_service


@pytest.fixture()
def report_db(tmp_path, monkeypatch):
    db_path = tmp_path / "analysis_reports.sqlite3"
    monkeypatch.setattr(analysis_report_service, "REPORT_DB_PATH", db_path)
    return db_path


def test_analysis_report_round_trip(report_db):
    payload = AnalysisReportPayload(
        id="report-1",
        title="提现暂停风险分析报告",
        created_at="2026-05-30 16:00",
        input="某交易所暂停提现",
        report={"summary": "提现暂停需要核验", "risk_score": 90},
    )

    saved = analysis_report_service.save_analysis_report("user-1", payload)
    assert saved.id == "report-1"
    assert saved.disposition == "pending"

    updated = analysis_report_service.update_analysis_report_disposition(
        "user-1",
        "report-1",
        AnalysisReportDispositionUpdate(disposition="verified", disposition_note="已核验官方公告"),
    )
    assert updated.disposition == "verified"
    assert updated.disposition_note == "已核验官方公告"

    items = analysis_report_service.list_analysis_reports("user-1")
    assert len(items) == 1
    assert items[0].report["risk_score"] == 90


def test_analysis_report_is_scoped_by_user(report_db):
    payload = AnalysisReportPayload(
        id="shared-id",
        title="报告",
        created_at="2026-05-30 16:00",
        input="风险事件",
        report={"summary": "test"},
    )

    analysis_report_service.save_analysis_report("user-a", payload)

    assert analysis_report_service.list_analysis_reports("user-b") == []
    with pytest.raises(analysis_report_service.AnalysisReportError):
        analysis_report_service.update_analysis_report_disposition(
            "user-b",
            "shared-id",
            AnalysisReportDispositionUpdate(disposition="ignored"),
        )
