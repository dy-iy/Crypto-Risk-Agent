from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.attackpilot import settings as attackpilot_settings

from app.schemas_auth import AuthUser
from app.schemas_favorites import FavoriteCreate
from app.schemas_portfolio import UserWatchlistCreate
from app.schemas_reports import AnalysisReportPayload
from app.services import analysis_report_service, auth_service, daily_report_store, portfolio_watchlist_store, task_audit_service
from app.services.account_export_service import build_account_export
from app.services.account_lifecycle_service import delete_account_data
from app.services.analysis_report_service import save_analysis_report
from app.services.auth_service import add_favorite, create_session, create_user, get_user_by_session, list_favorites
from app.services.daily_report_store import save_daily_report
from app.services.portfolio_service import add_watchlist_item
from app.services.portfolio_watchlist_store import list_watchlist_records
from app.services.sim_engine import sim_engine


class AccountExportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.sim_account_ids: set[str] = set()
        root = Path(self.tmpdir.name)
        self.patches = [
            patch.object(attackpilot_settings, "DATABASE_PATH", root / "attackpilot.sqlite3"),
            patch.object(attackpilot_settings, "RUNTIME_ROOT", root / "attackpilot"),
            patch.object(analysis_report_service, "REPORT_DB_PATH", root / "analysis_reports.sqlite3"),
            patch.object(auth_service, "AUTH_DB_PATH", root / "auth.sqlite3"),
            patch.object(portfolio_watchlist_store, "PORTFOLIO_DB_PATH", root / "portfolio.sqlite3"),
            patch.object(daily_report_store, "DAILY_REPORTS_DIR", root / "daily_reports"),
            patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", root / "task_audit.sqlite3"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        for account_id in {*self.sim_account_ids, "user-1", "user-2", "user-3"}:
            sim_engine.delete_account(account_id)
        self.tmpdir.cleanup()

    def test_account_export_contains_only_current_user_data(self) -> None:
        user = AuthUser(
            id="user-1",
            username="demo",
            display_name="Demo",
            created_at="2026-01-01 00:00:00",
        )
        other_user = AuthUser(
            id="user-2",
            username="other",
            display_name="Other",
            created_at="2026-01-01 00:00:00",
        )
        save_analysis_report(
            user.id,
            AnalysisReportPayload(
                id="report-1",
                title="报告",
                created_at="2026-06-01 10:00:00",
                input="风险事件",
                report={"risk_score": 80},
            ),
        )
        save_analysis_report(
            other_user.id,
            AnalysisReportPayload(
                id="report-2",
                title="其他报告",
                created_at="2026-06-01 10:00:00",
                input="其他事件",
                report={"risk_score": 10},
            ),
        )
        add_favorite(
            user.id,
            FavoriteCreate(item_type="report", item_id="report-1", title="收藏报告", payload={"score": 80}),
        )
        add_watchlist_item(UserWatchlistCreate(symbol="BTC", is_holding=True, amount=0.1), user_id=user.id)
        save_daily_report(user.id, {"range": "24h", "headline": "今日风险", "personal_risk_score": 70})
        self.sim_account_ids.add(user.id)
        sim_engine.reset(user.id)
        sim_engine.buy("ETH", 500, user.id)
        task_audit_service.record_task_event(
            job_kind="account_security",
            job_id="security-1",
            event_type="password_change",
            status="success",
            stage="password_changed",
            message="用户修改登录密码",
            user_id=user.id,
            payload={"sessions_revoked": 1},
        )
        task_audit_service.record_task_event(
            job_kind="account_security",
            job_id="security-2",
            event_type="login",
            status="success",
            stage="logged_in",
            message="其他用户登录",
            user_id=other_user.id,
        )
        current_token, _ = create_session(
            user.id,
            client_ip="203.0.113.7",
            user_agent="Mozilla/5.0 Chrome/120",
        )
        other_token, _ = create_session(
            other_user.id,
            client_ip="198.51.100.9",
            user_agent="Other Browser",
        )

        exported = build_account_export(user, current_session_token=current_token)

        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(exported["user"]["id"], user.id)
        self.assertEqual(exported["summary"]["analysis_reports"], 1)
        self.assertEqual(exported["summary"]["favorites"], 1)
        self.assertEqual(exported["summary"]["portfolio_watchlist"], 1)
        self.assertEqual(exported["summary"]["daily_reports"], 1)
        self.assertEqual(exported["summary"]["sim_account"], 1)
        self.assertEqual(exported["summary"]["sim_positions"], 1)
        self.assertEqual(exported["summary"]["sim_trades"], 1)
        self.assertEqual(exported["summary"]["account_security_events"], 1)
        self.assertEqual(exported["summary"]["auth_sessions"], 1)
        self.assertEqual(exported["analysis_reports"][0]["id"], "report-1")
        self.assertEqual(exported["portfolio_watchlist"][0]["symbol"], "BTCUSDT")
        self.assertEqual(exported["daily_reports"][0]["headline"], "今日风险")
        self.assertEqual(exported["daily_reports"][0]["personal_risk_score"], 70)
        self.assertIn("report_id", exported["daily_reports"][0])
        self.assertEqual(exported["sim_account"]["positions"][0]["symbol"], "ETHUSDT")
        self.assertEqual(exported["sim_account"]["trade_history"][0]["side"], "BUY")
        self.assertEqual(exported["account_security_events"][0]["event_type"], "password_change")
        self.assertEqual(exported["account_security_events"][0]["payload"]["sessions_revoked"], 1)
        self.assertEqual(exported["auth_sessions"][0]["is_current"], True)
        self.assertEqual(len(exported["auth_sessions"][0]["client_ip_hash"]), 12)
        self.assertEqual(exported["auth_sessions"][0]["user_agent"], "Mozilla/5.0 Chrome/120")
        serialized_sessions = str(exported["auth_sessions"])
        self.assertNotIn(current_token, serialized_sessions)
        self.assertNotIn(other_token, serialized_sessions)

    def test_delete_account_data_removes_current_user_records(self) -> None:
        user = create_user("demo", "Secur3!Passphrase")
        other_user = create_user("other", "Secur3!Passphrase")
        token, _ = create_session(user.id)
        save_analysis_report(
            user.id,
            AnalysisReportPayload(
                id="report-1",
                title="报告",
                created_at="2026-06-01 10:00:00",
                input="风险事件",
                report={"risk_score": 80},
            ),
        )
        save_analysis_report(
            other_user.id,
            AnalysisReportPayload(
                id="report-2",
                title="其他报告",
                created_at="2026-06-01 10:00:00",
                input="其他事件",
                report={"risk_score": 10},
            ),
        )
        add_favorite(user.id, FavoriteCreate(item_type="report", item_id="report-1", title="收藏报告"))
        add_watchlist_item(UserWatchlistCreate(symbol="BTC", is_holding=True, amount=0.1), user_id=user.id)
        save_daily_report(user.id, {"range": "24h", "headline": "今日风险", "personal_risk_score": 70})
        self.sim_account_ids.update({user.id, other_user.id})
        sim_engine.reset(user.id)
        sim_engine.buy("BTC", 1000, user.id)
        sim_engine.reset(other_user.id)
        sim_engine.buy("ETH", 1000, other_user.id)
        task_audit_service.record_task_event(
            job_kind="account_security",
            job_id="sec-1",
            event_type="login",
            status="success",
            stage="logged_in",
            message="用户登录",
            user_id=user.id,
        )
        task_audit_service.record_task_event(
            job_kind="chat_analysis",
            job_id="chat-1",
            event_type="analysis_run",
            status="success",
            stage="completed",
            message="分析完成",
            user_id=user.id,
        )
        task_audit_service.record_task_event(
            job_kind="account_security",
            job_id="sec-2",
            event_type="login",
            status="success",
            stage="logged_in",
            message="其他用户登录",
            user_id=other_user.id,
        )

        result = delete_account_data(user)

        self.assertEqual(result["users_deleted"], 1)
        self.assertEqual(result["sessions_deleted"], 1)
        self.assertEqual(result["favorites_deleted"], 1)
        self.assertEqual(result["analysis_reports_deleted"], 1)
        self.assertEqual(result["portfolio_watchlist_deleted"], 1)
        self.assertEqual(result["daily_reports_deleted"], 1)
        self.assertEqual(result["sim_accounts_deleted"], 1)
        self.assertEqual(result["audit_events_deleted"], 2)
        self.assertIsNone(get_user_by_session(token))
        self.assertEqual(analysis_report_service.list_analysis_reports(user.id), [])
        self.assertEqual(list_watchlist_records(user.id), [])
        self.assertEqual(daily_report_store.list_daily_reports(user.id), [])
        self.assertEqual(list_favorites(user.id), [])
        self.assertEqual(task_audit_service.list_task_events(user_id=user.id), [])
        self.assertEqual(len(task_audit_service.list_task_events(user_id=other_user.id)), 1)
        self.assertIsNone(sim_engine.account_state_snapshot(user.id))
        self.assertEqual(len(analysis_report_service.list_analysis_reports(other_user.id)), 1)
        self.assertIsNotNone(sim_engine.account_state_snapshot(other_user.id))


if __name__ == "__main__":
    unittest.main()
