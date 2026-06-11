from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import auth_service
from app.services import task_audit_service
from app.services.account_security_event_service import record_account_security_event, security_identifier_hash
from app.services.auth_service import (
    AuthError,
    change_user_password,
    create_session,
    create_user,
    get_user_by_session,
    list_user_sessions,
    prune_expired_sessions,
    revoke_other_sessions,
    verify_user,
    verify_user_password,
)


STRONG_PASSWORD = "Secur3!Passphrase"


class AuthServiceAdminRegistrationTest(unittest.TestCase):
    def test_reserved_admin_username_cannot_be_registered_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                with patch.dict(
                    "os.environ",
                    {
                        "SYSTEM_ADMIN_USERNAMES": "admin,ops",
                        "ALLOW_ADMIN_USERNAME_REGISTRATION": "0",
                    },
                    clear=False,
                ):
                    with self.assertRaises(AuthError) as context:
                        create_user("admin", STRONG_PASSWORD)

        self.assertIn("管理员用户名已保留", str(context.exception))

    def test_admin_username_registration_requires_explicit_bootstrap_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                with patch.dict(
                    "os.environ",
                    {
                        "SYSTEM_ADMIN_USERNAMES": "admin",
                        "ALLOW_ADMIN_USERNAME_REGISTRATION": "1",
                    },
                    clear=False,
                ):
                    user = create_user("admin", STRONG_PASSWORD)

        self.assertTrue(user.is_admin)

    def test_admin_user_id_grants_existing_account_admin_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("operator", STRONG_PASSWORD)
                self.assertFalse(user.is_admin)

                with patch.dict("os.environ", {"SYSTEM_ADMIN_USER_IDS": user.id}, clear=False):
                    verified = verify_user("operator", STRONG_PASSWORD)

        self.assertTrue(verified.is_admin)

    def test_change_password_revokes_other_sessions_and_keeps_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("holder", STRONG_PASSWORD)
                current_token, _ = create_session(user.id)
                other_token, _ = create_session(user.id)

                result = change_user_password(
                    user.id,
                    STRONG_PASSWORD,
                    "N3w!Secur3!Passphrase",
                    keep_session_token=current_token,
                )

                self.assertEqual(result["sessions_revoked"], 1)
                self.assertIsNotNone(get_user_by_session(current_token))
                self.assertIsNone(get_user_by_session(other_token))
                self.assertEqual(verify_user("holder", "N3w!Secur3!Passphrase").id, user.id)
                with self.assertRaises(AuthError):
                    verify_user("holder", STRONG_PASSWORD)

    def test_change_password_rejects_wrong_current_password_and_same_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("riskuser", STRONG_PASSWORD)

                with self.assertRaises(AuthError) as wrong_context:
                    change_user_password(user.id, "Wrong!Passphrase1", "N3w!Secur3!Passphrase")
                with self.assertRaises(AuthError) as same_context:
                    change_user_password(user.id, STRONG_PASSWORD, STRONG_PASSWORD)

        self.assertIn("当前密码错误", str(wrong_context.exception))
        self.assertIn("新密码不能与当前密码相同", str(same_context.exception))

    def test_verify_user_password_requires_current_password(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("deleteholder", STRONG_PASSWORD)

                verify_user_password(user.id, STRONG_PASSWORD)
                with self.assertRaises(AuthError) as context:
                    verify_user_password(user.id, "Wrong!Passphrase1")

        self.assertIn("当前密码错误", str(context.exception))

    def test_list_and_revoke_other_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("sessionuser", STRONG_PASSWORD)
                current_token, _ = create_session(
                    user.id,
                    client_ip="203.0.113.7",
                    user_agent="Mozilla/5.0 Chrome/120",
                )
                other_token, _ = create_session(user.id)

                sessions = list_user_sessions(user.id, current_token=current_token)
                revoked = revoke_other_sessions(user.id, current_token)
                sessions_after_revoke = list_user_sessions(user.id, current_token=current_token)

                self.assertEqual(len(sessions), 2)
                self.assertTrue(any(item.is_current for item in sessions))
                self.assertFalse(any(item.session_id == current_token for item in sessions))
                self.assertFalse(any(item.session_id == other_token for item in sessions))
                current_session = next(item for item in sessions if item.is_current)
                self.assertEqual(len(current_session.client_ip_hash), 12)
                self.assertEqual(current_session.user_agent, "Mozilla/5.0 Chrome/120")
                self.assertEqual(revoked, 1)
                self.assertEqual(len(sessions_after_revoke), 1)
                self.assertTrue(sessions_after_revoke[0].is_current)
                self.assertIsNotNone(get_user_by_session(current_token))
                self.assertIsNone(get_user_by_session(other_token))

    def test_prune_expired_sessions_keeps_active_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite3"
            with patch.object(auth_service, "AUTH_DB_PATH", db_path):
                user = create_user("pruneuser", STRONG_PASSWORD)
                active_token, _ = create_session(user.id)
                with auth_service._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO sessions (
                            token, user_id, created_at, expires_at, client_ip_hash, user_agent
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "expired-session-token",
                            user.id,
                            "2020-01-01 00:00:00",
                            "2020-01-02 00:00:00",
                            "",
                            "",
                        ),
                    )

                result = prune_expired_sessions()
                sessions = list_user_sessions(user.id, current_token=active_token)

        self.assertEqual(result["deleted_sessions"], 1)
        self.assertEqual(result["remaining_sessions"], 1)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].is_current)

    def test_account_security_event_helper_records_user_safe_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                record_account_security_event(
                    user_id="user-1",
                    event_type="sessions_revoke_others",
                    stage="sessions_revoked",
                    message="用户撤销其他登录会话",
                    payload={"sessions_revoked": 2},
                )
                events = task_audit_service.list_account_security_events("user-1")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["job_kind"], "account_security")
        self.assertEqual(events[0]["event_type"], "sessions_revoke_others")
        self.assertEqual(events[0]["payload"]["sessions_revoked"], 2)

    def test_account_security_event_helper_supports_failed_event_without_plain_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "task_audit.sqlite3"
            with patch.object(task_audit_service, "TASK_AUDIT_DB_PATH", audit_path):
                record_account_security_event(
                    user_id="",
                    event_type="login_failed",
                    stage="login_failed",
                    message="账号登录失败",
                    status="error",
                    payload={"username_hash": security_identifier_hash("DemoUser"), "reason": "用户名或密码错误"},
                )
                events = task_audit_service.list_task_events(job_kind="account_security", limit=5)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "error")
        self.assertEqual(events[0]["event_type"], "login_failed")
        self.assertEqual(events[0]["payload"]["username_hash"], security_identifier_hash("demouser"))
        self.assertNotIn("DemoUser", str(events[0]["payload"]))


if __name__ == "__main__":
    unittest.main()
