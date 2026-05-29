from __future__ import annotations

from collections import Counter
from statistics import mean

from app.schemas_portfolio import CoinRiskSnapshot, MarketCandle, PortfolioNewsItem, RiskLevel, UserWatchlist


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _risk_level(score: int) -> RiskLevel:
    if score >= 85:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def _price_change_24h(candles: list[MarketCandle]) -> float:
    if len(candles) < 2:
        return 0
    latest = candles[-1].close
    base_index = max(0, len(candles) - 97)
    base = candles[base_index].close or candles[0].close
    if not base:
        return 0
    return (latest - base) / base


def _volatility_score(candles: list[MarketCandle]) -> float:
    if len(candles) < 4:
        return 0
    recent = candles[-96:] if len(candles) >= 96 else candles
    highest = max(item.high for item in recent)
    lowest = min(item.low for item in recent)
    latest = recent[-1].close
    if not latest:
        return 0
    range_volatility = abs(highest - lowest) / latest

    recent_volume = mean([item.volume for item in recent[-12:]]) if len(recent) >= 12 else mean([item.volume for item in recent])
    previous_slice = recent[-48:-12] if len(recent) >= 48 else recent[:-12]
    previous_volume = mean([item.volume for item in previous_slice]) if previous_slice else recent_volume
    volume_change = abs(recent_volume - previous_volume) / previous_volume if previous_volume else 0

    return min(100, range_volatility * 520 + volume_change * 28)


def _news_score(news_items: list[PortfolioNewsItem]) -> float:
    if not news_items:
        return 0
    scores = [item.risk_score for item in news_items]
    high_count = sum(1 for score in scores if score >= 70)
    return min(100, max(scores) * 0.52 + mean(scores) * 0.28 + min(high_count, 5) * 4)


def _holding_score(watch: UserWatchlist, latest_price: float) -> float:
    if not watch.is_holding or watch.amount <= 0 or latest_price <= 0:
        return 0
    market_value = watch.amount * latest_price
    exposure_score = min(18, market_value / 1000)
    if watch.avg_buy_price <= 0:
        return exposure_score
    pnl_rate = (latest_price - watch.avg_buy_price) / watch.avg_buy_price
    drawdown_score = min(22, abs(min(0, pnl_rate)) * 140)
    return exposure_score + drawdown_score


def _main_risk_types(news_items: list[PortfolioNewsItem]) -> list[str]:
    types = [item.risk_type for item in news_items if item.risk_type]
    if not types:
        return ["行情波动"]
    return [item for item, _ in Counter(types).most_common(3)]


def _holding_impact(watch: UserWatchlist, latest_price: float) -> str:
    if not watch.is_holding or watch.amount <= 0:
        return "当前未标记持仓，主要关注该币种的市场与新闻风险变化。"
    market_value = watch.amount * latest_price
    if watch.avg_buy_price > 0:
        pnl = (latest_price - watch.avg_buy_price) * watch.amount
        pnl_rate = (latest_price - watch.avg_buy_price) / watch.avg_buy_price
        direction = "浮盈" if pnl >= 0 else "浮亏"
        return f"当前模拟持仓约 {market_value:.2f} USDT，{direction} {pnl:.2f} USDT（{pnl_rate:.2%}），风险变化会直接影响该敞口。"
    return f"当前模拟持仓约 {market_value:.2f} USDT，未设置买入均价，暂无法计算浮动盈亏。"


def generate_portfolio_risk_snapshot(
    *,
    generated_at: str,
    news_items: list[PortfolioNewsItem],
    snapshot_id: str,
    symbol: str,
    user_id: str,
    watch: UserWatchlist,
    candles: list[MarketCandle],
) -> CoinRiskSnapshot:
    latest_price = candles[-1].close if candles else 0
    price_change = _price_change_24h(candles)
    market_score = min(100, abs(price_change) * 460 + _volatility_score(candles) * 0.55)
    news_component = _news_score(news_items)
    holding_component = _holding_score(watch, latest_price)

    if news_items:
        score = _clamp_score(news_component * 0.62 + market_score * 0.25 + holding_component * 0.13)
    else:
        score = _clamp_score(market_score * 0.78 + holding_component * 0.22)

    high_risk_count = sum(1 for item in news_items if item.risk_score >= 70)
    risk_types = _main_risk_types(news_items)
    evidence_refs = [
        f"{item.news_id}: {item.evidence or item.summary or item.title}"
        for item in sorted(news_items, key=lambda item: item.risk_score, reverse=True)[:5]
    ]

    if news_items:
        top_news = sorted(news_items, key=lambda item: item.risk_score, reverse=True)[0]
        summary = (
            f"{symbol} 近期待监测新闻 {len(news_items)} 条，最高风险新闻为“{top_news.title}”，"
            f"风险分 {top_news.risk_score}/100。24h 行情变化 {price_change:.2%}。"
        )
    else:
        summary = (
            "相关新闻不足，主要基于行情波动分析："
            f"{symbol} 24h 价格变化 {price_change:.2%}，当前未发现可引用的相关新闻证据。"
        )

    if score >= 85:
        advice = "建议立即核验官方公告、链上资金流和交易所状态，降低单一币种风险暴露，并提高预警阈值关注频率。"
    elif score >= 70:
        advice = "建议重点跟踪高风险新闻证据、价格波动和成交量异常，必要时减少集中敞口并保留流动性。"
    elif score >= 40:
        advice = "建议维持监控，关注新闻是否升级、价格是否跌破关键区间，并检查持仓成本与预警阈值。"
    else:
        advice = "当前风险较低，建议保持观察，等待更多相关新闻或行情异常信号再调整监控策略。"

    return CoinRiskSnapshot(
        id=snapshot_id,
        user_id=user_id,
        symbol=symbol,
        risk_score=score,
        risk_level=_risk_level(score),
        main_risk_types=risk_types,
        price_change_24h=price_change,
        related_news_count=len(news_items),
        high_risk_news_count=high_risk_count,
        holding_impact=_holding_impact(watch, latest_price),
        ai_summary=summary,
        ai_advice=advice,
        evidence_refs=evidence_refs,
        generated_at=generated_at,
    )
