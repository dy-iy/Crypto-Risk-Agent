from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterable, Iterator

from app.schemas_portfolio import UserWatchlist


PORTFOLIO_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "portfolio.sqlite3"
WATCHLIST_INITIALIZED_KEY = "watchlist_initialized"

_db_lock = Lock()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    PORTFOLIO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(PORTFOLIO_DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_watchlist (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            base_asset TEXT NOT NULL,
            is_watched INTEGER NOT NULL,
            is_holding INTEGER NOT NULL,
            exposure_mode TEXT NOT NULL,
            exposure_bucket TEXT NOT NULL,
            custom_exposure_pct REAL,
            amount REAL NOT NULL,
            avg_buy_price REAL NOT NULL,
            alert_threshold INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, symbol)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portfolio_watchlist_user_symbol
        ON portfolio_watchlist(user_id, symbol)
        """
    )
    connection.commit()


def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO portfolio_metadata(key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value),
    )


def is_watchlist_initialized() -> bool:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            row = connection.execute(
                "SELECT value FROM portfolio_metadata WHERE key = ?",
                (WATCHLIST_INITIALIZED_KEY,),
            ).fetchone()
            return bool(row and row["value"] == "1")


def _write_watchlist_item(connection: sqlite3.Connection, item: UserWatchlist) -> None:
    connection.execute(
        """
        INSERT INTO portfolio_watchlist(
            id,
            user_id,
            symbol,
            base_asset,
            is_watched,
            is_holding,
            exposure_mode,
            exposure_bucket,
            custom_exposure_pct,
            amount,
            avg_buy_price,
            alert_threshold,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, symbol) DO UPDATE SET
            id = excluded.id,
            base_asset = excluded.base_asset,
            is_watched = excluded.is_watched,
            is_holding = excluded.is_holding,
            exposure_mode = excluded.exposure_mode,
            exposure_bucket = excluded.exposure_bucket,
            custom_exposure_pct = excluded.custom_exposure_pct,
            amount = excluded.amount,
            avg_buy_price = excluded.avg_buy_price,
            alert_threshold = excluded.alert_threshold,
            created_at = portfolio_watchlist.created_at,
            updated_at = excluded.updated_at
        """,
        (
            item.id,
            item.user_id,
            item.symbol,
            item.base_asset,
            int(item.is_watched),
            int(item.is_holding),
            item.exposure_mode,
            item.exposure_bucket,
            item.custom_exposure_pct,
            item.amount,
            item.avg_buy_price,
            item.alert_threshold,
            item.created_at,
            item.updated_at,
        ),
    )


def seed_watchlist_items(items: Iterable[UserWatchlist]) -> None:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            row = connection.execute(
                "SELECT value FROM portfolio_metadata WHERE key = ?",
                (WATCHLIST_INITIALIZED_KEY,),
            ).fetchone()
            if row and row["value"] == "1":
                return
            for item in items:
                _write_watchlist_item(connection, item)
            _set_metadata(connection, WATCHLIST_INITIALIZED_KEY, "1")
            connection.commit()


def _row_to_watchlist(row: sqlite3.Row) -> UserWatchlist:
    return UserWatchlist(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        symbol=str(row["symbol"]),
        base_asset=str(row["base_asset"]),
        is_watched=bool(row["is_watched"]),
        is_holding=bool(row["is_holding"]),
        exposure_mode=str(row["exposure_mode"]),
        exposure_bucket=str(row["exposure_bucket"]),
        custom_exposure_pct=row["custom_exposure_pct"],
        amount=float(row["amount"] or 0),
        avg_buy_price=float(row["avg_buy_price"] or 0),
        alert_threshold=int(row["alert_threshold"] if row["alert_threshold"] is not None else 70),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def list_watchlist_records(user_id: str) -> list[UserWatchlist]:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT *
                FROM portfolio_watchlist
                WHERE user_id = ?
                ORDER BY is_holding DESC, is_watched DESC, symbol ASC
                """,
                (user_id,),
            ).fetchall()
            return [_row_to_watchlist(row) for row in rows]


def upsert_watchlist_record(item: UserWatchlist) -> UserWatchlist:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            _write_watchlist_item(connection, item)
            connection.commit()
    return item


def delete_watchlist_record(user_id: str, symbol: str) -> bool:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            cursor = connection.execute(
                "DELETE FROM portfolio_watchlist WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
            )
            connection.commit()
            return cursor.rowcount > 0


def delete_watchlist_records_for_user(user_id: str) -> int:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            cursor = connection.execute("DELETE FROM portfolio_watchlist WHERE user_id = ?", (user_id,))
            connection.commit()
            return max(0, int(cursor.rowcount or 0))


def portfolio_store_summary() -> dict[str, int | str]:
    with _db_lock:
        with _connect() as connection:
            _ensure_schema(connection)
            watchlist_count = connection.execute("SELECT COUNT(*) FROM portfolio_watchlist").fetchone()[0]
            user_count = connection.execute("SELECT COUNT(DISTINCT user_id) FROM portfolio_watchlist").fetchone()[0]
            initialized = connection.execute(
                "SELECT value FROM portfolio_metadata WHERE key = ?",
                (WATCHLIST_INITIALIZED_KEY,),
            ).fetchone()
            return {
                "path": str(PORTFOLIO_DB_PATH),
                "watchlist_count": int(watchlist_count or 0),
                "user_count": int(user_count or 0),
                "watchlist_initialized": "1" if initialized and initialized["value"] == "1" else "0",
            }
