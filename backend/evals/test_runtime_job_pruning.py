from __future__ import annotations

import json
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas_portfolio import PortfolioRefreshJob


def load_runtime_job_modules_with_fastapi_stub():
    fastapi_stub = types.ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def patch(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

        def delete(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.Cookie = lambda *args, **kwargs: None
    fastapi_stub.HTTPException = Exception
    fastapi_stub.Query = lambda default=None, *args, **kwargs: default
    fastapi_stub.Request = object
    fastapi_stub.Response = object
    update_news_stub = types.ModuleType("app.data.update_news")
    update_news_stub.update_news_dataset = lambda *args, **kwargs: {"crawler_error": "stubbed"}
    with patch.dict(sys.modules, {"fastapi": fastapi_stub, "app.data.update_news": update_news_stub}):
        sys.modules.pop("app.api.portfolio", None)
        sys.modules.pop("app.api.risk_ranking", None)
        portfolio = importlib.import_module("app.api.portfolio")
        risk_ranking = importlib.import_module("app.api.risk_ranking")
        return portfolio, risk_ranking


class RuntimeJobPruningTest(unittest.TestCase):
    def test_news_update_jobs_loader_quarantines_corrupt_store(self) -> None:
        _portfolio, risk_ranking = load_runtime_job_modules_with_fastapi_stub()
        original_jobs = dict(risk_ranking._update_jobs)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                jobs_path = Path(tmpdir) / "update_jobs.json"
                jobs_path.write_text("{broken", encoding="utf-8")
                with patch.object(risk_ranking, "UPDATE_JOBS_PATH", jobs_path):
                    risk_ranking._update_jobs.clear()
                    risk_ranking._load_update_jobs()
                    backups = list(jobs_path.parent.glob("update_jobs.json.invalid.*.bak"))

                self.assertEqual(risk_ranking._update_jobs, {})
                self.assertFalse(jobs_path.exists())
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
        finally:
            risk_ranking._update_jobs.clear()
            risk_ranking._update_jobs.update(original_jobs)

    def test_prune_news_update_jobs_removes_only_inactive_old_jobs(self) -> None:
        _portfolio, risk_ranking = load_runtime_job_modules_with_fastapi_stub()
        original_jobs = dict(risk_ranking._update_jobs)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                jobs_path = Path(tmpdir) / "update_jobs.json"
                with patch.object(risk_ranking, "UPDATE_JOBS_PATH", jobs_path):
                    risk_ranking._update_jobs.clear()
                    risk_ranking._update_jobs.update(
                        {
                            "old-success": {
                                "job_id": "old-success",
                                "status": "success",
                                "updated_at": "2020-01-01 00:00:00",
                                "finished_at": "2020-01-01 00:00:00",
                            },
                            "recent-error": {
                                "job_id": "recent-error",
                                "status": "error",
                                "updated_at": "2999-01-01 00:00:00",
                                "finished_at": "2999-01-01 00:00:00",
                            },
                            "active-running": {
                                "job_id": "active-running",
                                "status": "running",
                                "updated_at": "2020-01-01 00:00:00",
                            },
                        }
                    )

                    result = risk_ranking.prune_update_jobs(retention_days=14, max_jobs=10)
                    persisted = json.loads(jobs_path.read_text(encoding="utf-8"))

            self.assertEqual(result["deleted_by_age"], 1)
            self.assertEqual(result["remaining_jobs"], 2)
            self.assertNotIn("old-success", persisted)
            self.assertIn("recent-error", persisted)
            self.assertIn("active-running", persisted)
        finally:
            risk_ranking._update_jobs.clear()
            risk_ranking._update_jobs.update(original_jobs)

    def test_portfolio_refresh_jobs_loader_quarantines_corrupt_store(self) -> None:
        portfolio, _risk_ranking = load_runtime_job_modules_with_fastapi_stub()
        original_jobs = dict(portfolio._refresh_jobs)
        original_latest = dict(portfolio._latest_job_by_user)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                jobs_path = Path(tmpdir) / "portfolio_refresh_jobs.json"
                jobs_path.write_text("{broken", encoding="utf-8")
                with patch.object(portfolio, "PORTFOLIO_REFRESH_JOBS_PATH", jobs_path):
                    portfolio._refresh_jobs.clear()
                    portfolio._latest_job_by_user.clear()
                    portfolio._load_refresh_jobs()
                    backups = list(jobs_path.parent.glob("portfolio_refresh_jobs.json.invalid.*.bak"))

                self.assertEqual(portfolio._refresh_jobs, {})
                self.assertEqual(portfolio._latest_job_by_user, {})
                self.assertFalse(jobs_path.exists())
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
        finally:
            portfolio._refresh_jobs.clear()
            portfolio._refresh_jobs.update(original_jobs)
            portfolio._latest_job_by_user.clear()
            portfolio._latest_job_by_user.update(original_latest)

    def test_prune_portfolio_refresh_jobs_rebuilds_latest_user_index(self) -> None:
        portfolio, _risk_ranking = load_runtime_job_modules_with_fastapi_stub()
        original_jobs = dict(portfolio._refresh_jobs)
        original_latest = dict(portfolio._latest_job_by_user)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                jobs_path = Path(tmpdir) / "portfolio_refresh_jobs.json"
                with patch.object(portfolio, "PORTFOLIO_REFRESH_JOBS_PATH", jobs_path):
                    portfolio._refresh_jobs.clear()
                    portfolio._latest_job_by_user.clear()
                    portfolio._refresh_jobs.update(
                        {
                            "old-success": PortfolioRefreshJob(
                                job_id="old-success",
                                user_id="user-1",
                                status="success",
                                updated_at="2020-01-01 00:00:00",
                                finished_at="2020-01-01 00:00:00",
                            ),
                            "recent-success": PortfolioRefreshJob(
                                job_id="recent-success",
                                user_id="user-1",
                                status="success",
                                updated_at="2999-01-01 00:00:00",
                                finished_at="2999-01-01 00:00:00",
                            ),
                            "active-running": PortfolioRefreshJob(
                                job_id="active-running",
                                user_id="user-2",
                                status="running",
                                updated_at="2020-01-01 00:00:00",
                            ),
                        }
                    )
                    portfolio._latest_job_by_user.update({"user-1": "old-success", "user-2": "active-running"})

                    result = portfolio.prune_portfolio_refresh_jobs(retention_days=14, max_jobs=10)
                    persisted = json.loads(jobs_path.read_text(encoding="utf-8"))

            self.assertEqual(result["deleted_by_age"], 1)
            self.assertEqual(result["remaining_jobs"], 2)
            self.assertNotIn("old-success", persisted)
            self.assertIn("recent-success", persisted)
            self.assertIn("active-running", persisted)
            self.assertEqual(portfolio._latest_job_by_user["user-1"], "recent-success")
            self.assertEqual(portfolio._latest_job_by_user["user-2"], "active-running")
        finally:
            portfolio._refresh_jobs.clear()
            portfolio._refresh_jobs.update(original_jobs)
            portfolio._latest_job_by_user.clear()
            portfolio._latest_job_by_user.update(original_latest)


if __name__ == "__main__":
    unittest.main()
