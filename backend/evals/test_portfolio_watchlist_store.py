from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas_portfolio import UserWatchlist, UserWatchlistCreate, UserWatchlistUpdate
from app.services import portfolio_service, portfolio_watchlist_store


def watch_item(symbol: str = "BTCUSDT", user_id: str = "demo_user") -> UserWatchlist:
    return UserWatchlist(
        id=f"{user_id}:{symbol}",
        user_id=user_id,
        symbol=symbol,
        base_asset=symbol[:-4],
        is_watched=True,
        is_holding=True,
        exposure_mode="exact",
        exposure_bucket="none",
        amount=1.5,
        avg_buy_price=100,
        alert_threshold=77,
        created_at="2026-01-01 00:00:00",
        updated_at="2026-01-01 00:00:00",
    )


class PortfolioWatchlistStoreTest(unittest.TestCase):
    def test_watchlist_store_crud_preserves_empty_after_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "portfolio.sqlite3"
            with patch.object(portfolio_watchlist_store, "PORTFOLIO_DB_PATH", db_path):
                self.assertFalse(portfolio_watchlist_store.is_watchlist_initialized())
                portfolio_watchlist_store.seed_watchlist_items([watch_item("ETHUSDT")])

                items = portfolio_watchlist_store.list_watchlist_records("demo_user")
                self.assertEqual([item.symbol for item in items], ["ETHUSDT"])

                portfolio_watchlist_store.delete_watchlist_record("demo_user", "ETHUSDT")
                self.assertEqual(portfolio_watchlist_store.list_watchlist_records("demo_user"), [])

                portfolio_watchlist_store.seed_watchlist_items([watch_item("SOLUSDT")])
                self.assertEqual(portfolio_watchlist_store.list_watchlist_records("demo_user"), [])

    def test_portfolio_service_migrates_legacy_json_watchlist_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            db_path = data_dir / "portfolio.sqlite3"
            state_path = data_dir / "portfolio_state.json"
            legacy_item = watch_item("SOLUSDT").model_dump()
            state_path.write_text(
                json.dumps(
                    {
                        "watchlist": [legacy_item],
                        "candles": {},
                        "news_links": [],
                        "risk_snapshots": {},
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(portfolio_watchlist_store, "PORTFOLIO_DB_PATH", db_path),
                patch.object(portfolio_service, "PORTFOLIO_STATE_PATH", state_path),
                patch.object(portfolio_service, "get_market_candles", return_value=[]),
            ):
                migrated = portfolio_service.list_watchlist("demo_user")
                self.assertEqual([item.symbol for item in migrated], ["SOLUSDT"])

                created = portfolio_service.add_watchlist_item(
                    UserWatchlistCreate(symbol="AAVE", is_holding=False),
                    "demo_user",
                )
                self.assertEqual(created.symbol, "AAVEUSDT")

                updated = portfolio_service.update_watchlist_item(
                    "AAVE",
                    UserWatchlistUpdate(is_holding=True, exposure_mode="bucket", exposure_bucket="none"),
                    "demo_user",
                )
                self.assertTrue(updated.is_holding)
                self.assertEqual(updated.exposure_bucket, "medium")

                portfolio_service.delete_watchlist_item("SOL", "demo_user")
                symbols = [item.symbol for item in portfolio_service.list_watchlist("demo_user")]
                self.assertEqual(symbols, ["AAVEUSDT"])


if __name__ == "__main__":
    unittest.main()
