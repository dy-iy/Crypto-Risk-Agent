from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from os import getenv
from pathlib import Path

from app.schemas_auth import AuthSessionItem, AuthUser
from app.schemas_favorites import FavoriteCreate, FavoriteItem, FavoriteType
from app.services.request_security_service import client_ip_hash, safe_user_agent


AUTH_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "auth.sqlite3"
SESSION_TTL_DAYS = 30
SESSION_TTL_SECONDS = SESSION_TTL_DAYS * 24 * 60 * 60
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390_000
LEGACY_PASSWORD_HASH_ITERATIONS = 120_000
PASSWORD_PEPPER = getenv("AUTH_PASSWORD_PEPPER", "")
COMMON_WEAK_PASSWORDS = {
    "123456",
    "1234567",
    "12345678",
    "123456789",
    "111111",
    "000000",
    "password",
    "password1",
    "qwerty",
    "qwerty123",
    "admin123",
    "risk123",
    "cryptorisk",
    "abc123456",
}


class AuthError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _password_material(password: str) -> bytes:
    return f"{password}{PASSWORD_PEPPER}".encode("utf-8")


def _hash_password(
    password: str,
    salt_hex: str | None = None,
    iterations: int = PASSWORD_HASH_ITERATIONS,
) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", _password_material(password), salt, iterations)
    return salt.hex(), digest.hex()


@contextmanager
def _connect():
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        _init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_scheme TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
            password_iterations INTEGER NOT NULL DEFAULT 120000,
            created_at TEXT NOT NULL
        )
        """
    )
    _ensure_column(conn, "users", "password_scheme", "TEXT NOT NULL DEFAULT 'pbkdf2_sha256'")
    _ensure_column(conn, "users", "password_iterations", "INTEGER NOT NULL DEFAULT 120000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            client_ip_hash TEXT NOT NULL DEFAULT '',
            user_agent TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    _ensure_column(conn, "sessions", "client_ip_hash", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "sessions", "user_agent", "TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_id TEXT NOT NULL,
            title TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, item_type, item_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_type ON favorites(user_id, item_type)")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if len(normalized) < 3:
        raise AuthError("用户名至少需要 3 个字符")
    if len(normalized) > 32:
        raise AuthError("用户名不能超过 32 个字符")
    if not all(char.isalnum() or char in {"_", "-", "."} for char in normalized):
        raise AuthError("用户名只能包含字母、数字、下划线、短横线或点")
    return normalized


def _validate_password_strength(username: str, password: str) -> None:
    if len(password) < 10:
        raise AuthError("密码至少需要 10 位，建议使用浏览器生成的强密码")
    if len(password) > 128:
        raise AuthError("密码不能超过 128 位")

    lowered = password.lower()
    if lowered in COMMON_WEAK_PASSWORDS:
        raise AuthError("这个密码过于常见，Chrome 可能会提示泄露，请换一个强密码")
    if username and username.lower() in lowered:
        raise AuthError("密码不能包含用户名")

    classes = [
        any(char.islower() for char in password),
        any(char.isupper() for char in password),
        any(char.isdigit() for char in password),
        any(not char.isalnum() for char in password),
    ]
    if sum(classes) < 3:
        raise AuthError("密码需要包含大小写字母、数字、符号中的至少 3 类")


def _env_csv_set(name: str) -> set[str]:
    return {
        item.strip().lower()
        for item in getenv(name, "").split(",")
        if item.strip()
    }


def _is_admin_user(user_id: str, username: str) -> bool:
    admin_usernames = _env_csv_set("SYSTEM_ADMIN_USERNAMES")
    admin_user_ids = _env_csv_set("SYSTEM_ADMIN_USER_IDS")
    return username.lower() in admin_usernames or user_id.lower() in admin_user_ids


def _admin_username_registration_allowed() -> bool:
    return getenv("ALLOW_ADMIN_USERNAME_REGISTRATION", "").strip() == "1"


def _ensure_username_can_register(normalized_username: str) -> None:
    if normalized_username in _env_csv_set("SYSTEM_ADMIN_USERNAMES") and not _admin_username_registration_allowed():
        raise AuthError("管理员用户名已保留，请先注册普通账号后通过 SYSTEM_ADMIN_USER_IDS 授权")


def _row_to_user(row: sqlite3.Row) -> AuthUser:
    return AuthUser(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        created_at=row["created_at"],
        is_admin=_is_admin_user(row["id"], row["username"]),
    )


def _row_to_favorite(row: sqlite3.Row) -> FavoriteItem:
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    return FavoriteItem(
        id=row["id"],
        user_id=row["user_id"],
        item_type=row["item_type"],
        item_id=row["item_id"],
        title=row["title"],
        payload=payload if isinstance(payload, dict) else {},
        created_at=row["created_at"],
    )


def _session_public_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _row_to_session(row: sqlite3.Row, current_token: str | None = None) -> AuthSessionItem:
    token = str(row["token"])
    return AuthSessionItem(
        session_id=_session_public_id(token),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        client_ip_hash=row["client_ip_hash"] or "",
        user_agent=row["user_agent"] or "",
        is_current=bool(current_token and hmac.compare_digest(token, current_token)),
    )


def create_user(username: str, password: str) -> AuthUser:
    normalized = _normalize_username(username)
    _ensure_username_can_register(normalized)
    _validate_password_strength(normalized, password)

    salt, password_hash = _hash_password(password)
    user_id = f"user-{uuid.uuid4().hex}"
    try:
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_salt, password_hash,
                    password_scheme, password_iterations, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    normalized,
                    normalized,
                    salt,
                    password_hash,
                    PASSWORD_HASH_SCHEME,
                    PASSWORD_HASH_ITERATIONS,
                    _now_text(),
                ),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return _row_to_user(row)
    except sqlite3.IntegrityError as exc:
        raise AuthError("用户名已存在") from exc


def verify_user(username: str, password: str) -> AuthUser:
    normalized = _normalize_username(username)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (normalized,)).fetchone()
        if not row:
            raise AuthError("用户名或密码错误")

        iterations = int(row["password_iterations"] or LEGACY_PASSWORD_HASH_ITERATIONS)
        _, password_hash = _hash_password(password, row["password_salt"], iterations)
        if not hmac.compare_digest(password_hash, row["password_hash"]):
            raise AuthError("用户名或密码错误")

        if iterations < PASSWORD_HASH_ITERATIONS:
            salt, next_hash = _hash_password(password)
            conn.execute(
                """
                UPDATE users
                SET password_salt = ?, password_hash = ?, password_scheme = ?, password_iterations = ?
                WHERE id = ?
                """,
                (salt, next_hash, PASSWORD_HASH_SCHEME, PASSWORD_HASH_ITERATIONS, row["id"]),
            )

        return _row_to_user(row)


def verify_user_password(user_id: str, password: str) -> None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("用户不存在")
        iterations = int(row["password_iterations"] or LEGACY_PASSWORD_HASH_ITERATIONS)
        _, password_hash = _hash_password(password, row["password_salt"], iterations)
        if not hmac.compare_digest(password_hash, row["password_hash"]):
            raise AuthError("当前密码错误")


def change_user_password(
    user_id: str,
    current_password: str,
    new_password: str,
    keep_session_token: str | None = None,
) -> dict[str, int]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise AuthError("用户不存在")

        iterations = int(row["password_iterations"] or LEGACY_PASSWORD_HASH_ITERATIONS)
        _, current_hash = _hash_password(current_password, row["password_salt"], iterations)
        if not hmac.compare_digest(current_hash, row["password_hash"]):
            raise AuthError("当前密码错误")

        _, next_hash_for_compare = _hash_password(new_password, row["password_salt"], iterations)
        if hmac.compare_digest(next_hash_for_compare, row["password_hash"]):
            raise AuthError("新密码不能与当前密码相同")

        _validate_password_strength(row["username"], new_password)
        salt, password_hash = _hash_password(new_password)
        conn.execute(
            """
            UPDATE users
            SET password_salt = ?, password_hash = ?, password_scheme = ?, password_iterations = ?
            WHERE id = ?
            """,
            (salt, password_hash, PASSWORD_HASH_SCHEME, PASSWORD_HASH_ITERATIONS, user_id),
        )
        if keep_session_token:
            sessions_revoked = conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token != ?",
                (user_id, keep_session_token),
            ).rowcount
        else:
            sessions_revoked = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount
    return {"sessions_revoked": max(0, int(sessions_revoked or 0))}


def create_session(
    user_id: str,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    with _connect() as conn:
        _prune_expired_sessions(conn, _now_text())
        conn.execute(
            """
            INSERT INTO sessions (
                token, user_id, created_at, expires_at, client_ip_hash, user_agent
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                token,
                user_id,
                _now_text(),
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                client_ip_hash(client_ip),
                safe_user_agent(user_agent),
            ),
        )
    return token, expires_at


def _prune_expired_sessions(conn: sqlite3.Connection, now_text: str) -> int:
    deleted = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_text,)).rowcount
    return max(0, int(deleted or 0))


def prune_expired_sessions() -> dict[str, int | str]:
    now = _now_text()
    with _connect() as conn:
        deleted = _prune_expired_sessions(conn, now)
        remaining = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
    return {
        "deleted_sessions": deleted,
        "remaining_sessions": max(0, int(remaining or 0)),
        "pruned_at": now,
    }


def get_user_by_session(token: str | None) -> AuthUser | None:
    if not token:
        return None
    with _connect() as conn:
        now = _now_text()
        _prune_expired_sessions(conn, now)
        row = conn.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        return _row_to_user(row) if row else None


def get_user_by_id(user_id: str) -> AuthUser | None:
    if not user_id:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None


def list_users() -> list[AuthUser]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [_row_to_user(row) for row in rows]


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def list_user_sessions(user_id: str, current_token: str | None = None) -> list[AuthSessionItem]:
    with _connect() as conn:
        now = _now_text()
        _prune_expired_sessions(conn, now)
        rows = conn.execute(
            """
            SELECT token, created_at, expires_at, client_ip_hash, user_agent
            FROM sessions
            WHERE user_id = ? AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (user_id, now),
        ).fetchall()
        return [_row_to_session(row, current_token) for row in rows]


def revoke_other_sessions(user_id: str, keep_session_token: str | None) -> int:
    if not keep_session_token:
        return 0
    with _connect() as conn:
        deleted = conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
            (user_id, keep_session_token),
        ).rowcount
    return max(0, int(deleted or 0))


def delete_user_account(user_id: str) -> dict[str, int]:
    with _connect() as conn:
        sessions_deleted = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,)).rowcount
        favorites_deleted = conn.execute("DELETE FROM favorites WHERE user_id = ?", (user_id,)).rowcount
        users_deleted = conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount
    return {
        "sessions": max(0, int(sessions_deleted or 0)),
        "favorites": max(0, int(favorites_deleted or 0)),
        "users": max(0, int(users_deleted or 0)),
    }


def list_favorites(user_id: str, item_type: FavoriteType | None = None) -> list[FavoriteItem]:
    with _connect() as conn:
        if item_type:
            rows = conn.execute(
                """
                SELECT * FROM favorites
                WHERE user_id = ? AND item_type = ?
                ORDER BY created_at DESC
                """,
                (user_id, item_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [_row_to_favorite(row) for row in rows]


def add_favorite(user_id: str, payload: FavoriteCreate) -> FavoriteItem:
    favorite_id = f"fav-{uuid.uuid4().hex}"
    now = _now_text()
    payload_json = json.dumps(payload.payload, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO favorites (id, user_id, item_type, item_id, title, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, item_type, item_id)
            DO UPDATE SET title = excluded.title, payload_json = excluded.payload_json
            """,
            (
                favorite_id,
                user_id,
                payload.item_type,
                payload.item_id,
                payload.title[:300],
                payload_json,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM favorites WHERE user_id = ? AND item_type = ? AND item_id = ?",
            (user_id, payload.item_type, payload.item_id),
        ).fetchone()
        return _row_to_favorite(row)


def delete_favorite(user_id: str, item_type: FavoriteType, item_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND item_type = ? AND item_id = ?",
            (user_id, item_type, item_id),
        )
