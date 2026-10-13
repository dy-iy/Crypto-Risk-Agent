from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas_portfolio import EventAssetRelation, PortfolioWatchlistItem
from app.services.portfolio_impact_service import (
    calculate_portfolio_impact_score,
    get_portfolio_impact_for_user,
    resolve_user_exposure_pct,
)


def watch_item(
    symbol: str = "SOLUSDT",
    *,
    amount: float = 0,
    custom_exposure_pct: float | None = None,
    exposure_bucket: str = "medium",
    is_holding: bool = True,
    market_value: float = 0,
    price: float = 100,
) -> PortfolioWatchlistItem:
    return PortfolioWatchlistItem(
        id=f"demo:{symbol}",
        user_id="demo_user",
        symbol=symbol,
        base_asset=symbol.replace("USDT", ""),
        is_watched=True,
        is_holding=is_holding,
        exposure_mode="bucket",
        exposure_bucket=exposure_bucket,
        custom_exposure_pct=custom_exposure_pct,
        amount=amount,
        avg_buy_price=0,
        alert_threshold=70,
        created_at="2026-05-30 00:00:00",
        updated_at="2026-05-30 00:00:00",
        current_price=price,
        price_change_24h=0,
        market_value=market_value,
        floating_pnl=0,
        floating_pnl_rate=0,
        risk_score=70,
        risk_level="medium",
        ai_summary="",
    )


def relation(symbol: str = "SOLUSDT") -> EventAssetRelation:
    return EventAssetRelation(
        id=f"event-1:{symbol}",
        event_id="event-1",
        asset_symbol=symbol,
        relation_score=0.9,
        relation_type="ecosystem_protocol",
        direction="negative",
        base_asset_impact_score=72,
        reasons=["事件涉及 Solana 生态协议"],
        created_at="2026-05-30 00:00:00",
        updated_at="2026-05-30 00:00:00",
    )


class PortfolioImpactServiceTest(unittest.TestCase):
    def test_watched_asset_without_holding_is_not_in_impact_list(self) -> None:
        with patch("app.services.portfolio_impact_service.list_watchlist", return_value=[watch_item(is_holding=False)]):
            result = get_portfolio_impact_for_user()
        self.assertEqual(result.assets, [])

    def test_holding_without_quantity_uses_medium_bucket(self) -> None:
        item = watch_item(exposure_bucket="medium")
        with (
            patch("app.services.portfolio_impact_service.list_watchlist", return_value=[item]),
            patch("app.services.portfolio_impact_service._load_recent_relations_by_symbol", return_value={"SOLUSDT": [relation()]}),
            patch("app.services.portfolio_impact_service.load_scored_news", return_value=[{
                "news_id": "event-1",
                "title": "Solana 生态协议出现异常",
                "risk_score": 80,
                "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }]),
            patch("app.services.portfolio_impact_service._write_impact_cache"),
        ):
            result = get_portfolio_impact_for_user()
        self.assertEqual(result.assets[0].exposureSource, "bucket")
        self.assertGreater(result.assets[0].topEvents[0].portfolioImpactScore, 0)

    def test_high_bucket_scores_above_low_bucket(self) -> None:
        low = calculate_portfolio_impact_score({
            "eventRiskScore": 80,
            "assetRelationScore": 0.9,
            "userExposurePct": 0.05,
            "timeDecayFactor": 1,
        })
        high = calculate_portfolio_impact_score({
            "eventRiskScore": 80,
            "assetRelationScore": 0.9,
            "userExposurePct": 0.30,
            "timeDecayFactor": 1,
        })
        self.assertGreater(high, low)

    def test_custom_exposure_takes_priority(self) -> None:
        pct, source = resolve_user_exposure_pct(watch_item(custom_exposure_pct=0.42, amount=2, market_value=200), 1000)
        self.assertEqual(source, "custom")
        self.assertEqual(pct, 0.42)

    def test_exact_exposure_uses_quantity_market_value(self) -> None:
        pct, source = resolve_user_exposure_pct(watch_item(amount=2, market_value=200), 1000)
        self.assertEqual(source, "exact")
        self.assertEqual(pct, 0.2)

    def test_mark_holding_does_not_require_quantity(self) -> None:
        pct, source = resolve_user_exposure_pct(watch_item(amount=0, market_value=0, exposure_bucket="medium"), 0)
        self.assertEqual(source, "bucket")
        self.assertEqual(pct, 0.15)

    def test_new_asset_sync_is_scoped_to_that_asset_relation(self) -> None:
        item = watch_item(symbol="SOLUSDT", exposure_bucket="medium")
        with (
            patch("app.services.portfolio_impact_service.list_watchlist", return_value=[item]),
            patch("app.services.portfolio_impact_service._load_recent_relations_by_symbol", side_effect=[{"SOLUSDT": []}, {"SOLUSDT": [relation("SOLUSDT")]}]),
            patch("app.services.portfolio_impact_service._sync_event_asset_relations") as sync,
            patch("app.services.portfolio_impact_service.load_scored_news", return_value=[{
                "news_id": "event-1",
                "title": "Solana 生态协议出现异常",
                "risk_score": 80,
                "published_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }]),
            patch("app.services.portfolio_impact_service._write_impact_cache"),
        ):
            get_portfolio_impact_for_user()
        sync.assert_called_once()
        self.assertEqual(sync.call_args.args[0], {"SOLUSDT"})


if __name__ == "__main__":
    unittest.main()
