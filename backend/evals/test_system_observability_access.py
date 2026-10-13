from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch

from app.schemas_auth import AuthUser


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def load_system_api_with_fastapi_stub():
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

    _APIRouter.patch = _APIRouter.post
    fastapi_stub.APIRouter = _APIRouter
    fastapi_stub.Cookie = lambda *args, **kwargs: None
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Query = lambda default=None, *args, **kwargs: default
    fastapi_stub.Request = object
    fastapi_stub.Response = object
    fastapi_stub.status = types.SimpleNamespace(HTTP_503_SERVICE_UNAVAILABLE=503)
    with patch.dict(sys.modules, {"fastapi": fastapi_stub}):
        sys.modules.pop("app.api.system", None)
        return importlib.import_module("app.api.system")


class SystemObservabilityAccessTest(unittest.TestCase):
    def test_observability_requires_session_by_default(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api._require_observability_access(None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_escape_hatch(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session") as get_user:
                result = system_api._require_observability_access(None)

        self.assertIsNone(result)
        get_user.assert_not_called()

    def test_non_admin_session_is_forbidden(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(id="user-1", username="demo", display_name="demo", created_at="2026-01-01")
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user):
                with self.assertRaises(_HTTPException) as context:
                    system_api._require_observability_access("session-token")

        self.assertEqual(context.exception.status_code, 403)

    def test_admin_session_is_allowed(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user):
                result = system_api._require_observability_access("session-token")

        self.assertEqual(result.id, "user-1")

    def test_admin_can_prune_task_events(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
                system_api,
                "record_task_event",
            ) as audit:
                with patch.object(
                    system_api,
                    "prune_task_audit_events",
                    return_value={"deleted_by_age": 2, "deleted_by_count": 3, "remaining_events": 10},
                ) as prune:
                    result = system_api.system_prune_task_events(
                        retention_days=7,
                        max_events=100,
                        cryptorisk_session="session-token",
                    )

        prune.assert_called_once_with(retention_days=7, max_events=100)
        audit.assert_called_once()
        audit_kwargs = audit.call_args.kwargs
        self.assertEqual(audit_kwargs["job_kind"], "system_admin")
        self.assertEqual(audit_kwargs["event_type"], "task_events_prune")
        self.assertEqual(audit_kwargs["user_id"], "user-1")
        self.assertEqual(audit_kwargs["payload"]["deleted_by_age"], 2)
        self.assertEqual(audit_kwargs["payload"]["max_events"], 100)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["remaining_events"], 10)

    def test_admin_can_prune_guest_sim_accounts(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
                system_api,
                "record_task_event",
            ) as audit, patch.object(
                system_api.sim_engine,
                "prune_guest_accounts",
                return_value={"deleted_accounts": 2, "remaining_accounts": 3, "retention_days": 14},
            ) as prune:
                result = system_api.system_prune_guest_sim_accounts(
                    retention_days=14,
                    cryptorisk_session="session-token",
                )

        prune.assert_called_once_with(retention_days=14)
        audit.assert_called_once()
        audit_kwargs = audit.call_args.kwargs
        self.assertEqual(audit_kwargs["job_kind"], "system_admin")
        self.assertEqual(audit_kwargs["event_type"], "guest_sim_accounts_prune")
        self.assertEqual(audit_kwargs["user_id"], "user-1")
        self.assertEqual(audit_kwargs["payload"]["deleted_accounts"], 2)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_accounts"], 2)

    def test_admin_can_prune_expired_auth_sessions(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
                system_api,
                "record_task_event",
            ) as audit, patch.object(
                system_api,
                "prune_expired_sessions",
                return_value={
                    "deleted_sessions": 2,
                    "remaining_sessions": 5,
                    "pruned_at": "2026-01-01 00:00:00",
                },
            ) as prune:
                result = system_api.system_prune_expired_auth_sessions(
                    cryptorisk_session="session-token",
                )

        prune.assert_called_once_with()
        audit.assert_called_once()
        audit_kwargs = audit.call_args.kwargs
        self.assertEqual(audit_kwargs["job_kind"], "system_admin")
        self.assertEqual(audit_kwargs["event_type"], "auth_sessions_prune")
        self.assertEqual(audit_kwargs["user_id"], "user-1")
        self.assertEqual(audit_kwargs["payload"]["remaining_sessions"], 5)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_sessions"], 2)

    def test_admin_can_prune_runtime_jobs(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        news_result = {"deleted_by_age": 1, "deleted_by_count": 0, "remaining_jobs": 2, "retention_days": 14, "max_jobs": 100}
        portfolio_result = {"deleted_by_age": 2, "deleted_by_count": 1, "remaining_jobs": 3, "retention_days": 14, "max_jobs": 100}
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
                system_api,
                "record_task_event",
            ) as audit, patch.object(
                system_api,
                "_prune_update_jobs",
                return_value=news_result,
            ) as prune_news, patch.object(
                system_api,
                "_prune_portfolio_refresh_jobs",
                return_value=portfolio_result,
            ) as prune_portfolio:
                result = system_api.system_prune_runtime_jobs(
                    retention_days=14,
                    max_jobs=100,
                    cryptorisk_session="session-token",
                )

        prune_news.assert_called_once_with(retention_days=14, max_jobs=100)
        prune_portfolio.assert_called_once_with(retention_days=14, max_jobs=100)
        audit.assert_called_once()
        audit_kwargs = audit.call_args.kwargs
        self.assertEqual(audit_kwargs["job_kind"], "system_admin")
        self.assertEqual(audit_kwargs["event_type"], "runtime_jobs_prune")
        self.assertEqual(audit_kwargs["payload"]["news_update"]["deleted_by_age"], 1)
        self.assertEqual(audit_kwargs["payload"]["portfolio_refresh"]["deleted_by_count"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["news_update"]["remaining_jobs"], 2)

    def test_admin_can_prune_invalid_json_backups(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        prune_result = {
            "deleted_files": 2,
            "deleted_bytes": 100,
            "remaining_files": 1,
            "remaining_bytes": 50,
            "retention_days": 30,
            "deleted": [],
        }
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "0"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
                system_api,
                "record_task_event",
            ) as audit, patch.object(
                system_api,
                "prune_invalid_json_backups",
                return_value=prune_result,
            ) as prune:
                result = system_api.system_prune_invalid_json_backups(
                    retention_days=30,
                    cryptorisk_session="session-token",
                )

        prune.assert_called_once_with(retention_days=30)
        audit.assert_called_once()
        audit_kwargs = audit.call_args.kwargs
        self.assertEqual(audit_kwargs["job_kind"], "system_admin")
        self.assertEqual(audit_kwargs["event_type"], "invalid_json_backups_prune")
        self.assertEqual(audit_kwargs["payload"]["deleted_files"], 2)
        self.assertEqual(audit_kwargs["payload"]["remaining_files"], 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["deleted_files"], 2)

    def test_public_observability_does_not_allow_prune(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_prune_task_events(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_guest_sim_prune(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_prune_guest_sim_accounts(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_auth_session_prune(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_prune_expired_auth_sessions(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_runtime_jobs_prune(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_prune_runtime_jobs(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_invalid_json_backup_prune(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_prune_invalid_json_backups(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_task_event_details(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_task_events(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_audit_summary_redacts_latest_event_details(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session") as get_user, patch.object(
                system_api,
                "task_audit_metrics",
                return_value={
                    "window_hours": 24,
                    "total_events": 1,
                    "window_events": 1,
                    "by_kind": [
                        {
                            "job_kind": "account_export",
                            "total": 1,
                            "success": 1,
                            "error": 0,
                            "queued": 0,
                            "running": 0,
                            "other": 0,
                            "error_rate": 0,
                            "latest_event": {
                                "job_id": "account-export-user-1",
                                "status": "success",
                                "stage": "exported",
                                "message": "用户导出账号数据",
                                "created_at": "2026-01-01 00:00:00",
                            },
                        }
                    ],
                    "retention": {"retention_days": 30, "max_events": 20000},
                },
            ):
                result = system_api.system_audit_summary(cryptorisk_session=None)

        get_user.assert_not_called()
        self.assertIsNone(result["by_kind"][0]["latest_event"])

    def test_admin_can_read_storage_inventory(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
            system_api,
            "build_storage_inventory",
            return_value={"datastores": [], "runtime": {"sim_accounts": 0}},
        ) as inventory:
            result = system_api.system_storage_inventory(cryptorisk_session="session-token")

        inventory.assert_called_once_with()
        self.assertEqual(result["runtime"]["sim_accounts"], 0)

    def test_admin_can_read_backup_manifest(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        user = AuthUser(
            id="user-1",
            username="admin",
            display_name="admin",
            created_at="2026-01-01",
            is_admin=True,
        )
        with patch.object(system_api, "get_user_by_session", return_value=user), patch.object(
            system_api,
            "build_backup_manifest",
            return_value={"target_count": 1, "items": []},
        ) as manifest:
            result = system_api.system_backup_manifest(cryptorisk_session="session-token")

        manifest.assert_called_once_with()
        self.assertEqual(result["target_count"], 1)

    def test_public_observability_does_not_allow_storage_inventory(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_storage_inventory(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)

    def test_public_observability_does_not_allow_backup_manifest(self) -> None:
        system_api = load_system_api_with_fastapi_stub()
        with patch.dict("os.environ", {"ALLOW_PUBLIC_SYSTEM_OBSERVABILITY": "1"}, clear=False):
            with patch.object(system_api, "get_user_by_session", return_value=None):
                with self.assertRaises(_HTTPException) as context:
                    system_api.system_backup_manifest(cryptorisk_session=None)

        self.assertEqual(context.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
