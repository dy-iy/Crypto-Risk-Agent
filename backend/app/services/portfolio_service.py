from __future__ import annotations

import json
import math
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from app.agents.ranking_agent.graph import run_ranking_agent
from app.agents.portfolio_risk_agent import generate_portfolio_risk_snapshot
from app.data.update_news import update_news_dataset
from app.schemas_portfolio import (
    CoinRiskSnapshot,
    MarketCandle,
    NewsCoinLink,
    PortfolioNewsItem,
    PortfolioRefreshResponse,
    PortfolioWatchlistItem,
    UserWatchlist,
    UserWatchlistCreate,
    UserWatchlistUpdate,
)
from app.services.coin_extraction_service import COIN_DICTIONARY, extract_coins_from_text
from app.services.data_loader import load_scored_news, read_raw_news_records, shorten
from app.services.ranking_aggregation_service import SOURCE_URL_FIELDS, first_text_value


DEFAULT_USER_ID = "demo_user"
DEFAULT_INTERVAL = "15m"
DEFAULT_LIMIT = 200
PORTFOLIO_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "portfolio_state.json"

BASE_PRICES = {
    "BTCUSDT": 68000.0,
    "ETHUSDT": 3600.0,
    "BNBUSDT": 610.0,
    "SOLUSDT": 155.0,
    "XRPUSDT": 0.62,
    "DOGEUSDT": 0.14,
    "ADAUSDT": 0.45,
    "AVAXUSDT": 34.0,
    "LINKUSDT": 15.0,
    "TRXUSDT": 0.11,
    "AAVEUSDT": 92.0,
    "UNIUSDT": 8.6,
    "CRVUSDT": 0.42,
    "USDTUSDT": 1.0,
    "USDCUSDT": 1.0,
}

_state_lock = Lock()


class PortfolioError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_symbol(symbol: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(symbol or "").strip().upper())
    if not normalized:
        raise PortfolioError("symbol is required")
    if normalized.endswith("USD") and not normalized.endswith("USDT"):
        normalized = f"{normalized}T"
    if not normalized.endswith("USDT"):
        normalized = f"{normalized}USDT"
    if len(normalized) <= 4:
        raise PortfolioError("invalid symbol")
    return normalized


def _base_asset(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    return normalized[:-4] if normalized.endswith("USDT") else normalized


def _state_template() -> dict[str, Any]:
    created_at = _now()
    seed_symbols = [
        ("BTCUSDT", True, 0.08, 64500.0, 72),
        ("ETHUSDT", True, 1.2, 3380.0, 68),
        ("SOLUSDT", False, 0, 0, 65),
    ]
    return {
        "watchlist": [
            UserWatchlist(
                id=f"{DEFAULT_USER_ID}:{symbol}",
                user_id=DEFAULT_USER_ID,
                symbol=symbol,
                base_asset=_base_asset(symbol),
                is_holding=is_holding,
                amount=amount,
                avg_buy_price=avg_buy_price,
                alert_threshold=threshold,
                created_at=created_at,
                updated_at=created_at,
            ).model_dump()
            for symbol, is_holding, amount, avg_buy_price, threshold in seed_symbols
        ],
        "candles": {},
        "news_links": [],
        "risk_snapshots": {},
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    try:
        temp_path.replace(path)
    except PermissionError:
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        try:
            temp_path.unlink()
        except OSError:
            pass


def _load_state_unlocked() -> dict[str, Any]:
    if not PORTFOLIO_STATE_PATH.exists() or PORTFOLIO_STATE_PATH.stat().st_size == 0:
        state = _state_template()
        _write_json(PORTFOLIO_STATE_PATH, state)
        return state
    try:
        with PORTFOLIO_STATE_PATH.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except json.JSONDecodeError:
        state = _state_template()
    if not isinstance(state, dict):
        state = _state_template()
    state.setdefault("watchlist", [])
    state.setdefault("candles", {})
    state.setdefault("news_links", [])
    state.setdefault("risk_snapshots", {})
    return state


def _save_state_unlocked(state: dict[str, Any]) -> None:
    _write_json(PORTFOLIO_STATE_PATH, state)


def _watch_items(user_id: str = DEFAULT_USER_ID) -> list[UserWatchlist]:
    with _state_lock:
        state = _load_state_unlocked()
        return [
            UserWatchlist.model_validate(item)
            for item in state.get("watchlist", [])
            if str(item.get("user_id") or DEFAULT_USER_ID) == user_id
        ]


def add_watchlist_item(payload: UserWatchlistCreate, user_id: str = DEFAULT_USER_ID) -> UserWatchlist:
    symbol = _normalize_symbol(payload.symbol)
    now = _now()
    with _state_lock:
        state = _load_state_unlocked()
        items = state.get("watchlist", [])
        for index, raw_item in enumerate(items):
            item = UserWatchlist.model_validate(raw_item)
            if item.user_id == user_id and item.symbol == symbol:
                updated = item.model_copy(
                    update={
                        "is_holding": payload.is_holding,
                        "amount": payload.amount,
                        "avg_buy_price": payload.avg_buy_price,
                        "alert_threshold": payload.alert_threshold,
                        "updated_at": now,
                    }
                )
                items[index] = updated.model_dump()
                _save_state_unlocked(state)
                return updated

        created = UserWatchlist(
            id=f"{user_id}:{symbol}",
            user_id=user_id,
            symbol=symbol,
            base_asset=_base_asset(symbol),
            is_holding=payload.is_holding,
            amount=payload.amount,
            avg_buy_price=payload.avg_buy_price,
            alert_threshold=payload.alert_threshold,
            created_at=now,
            updated_at=now,
        )
        items.append(created.model_dump())
        _save_state_unlocked(state)
        return created


def update_watchlist_item(symbol: str, payload: UserWatchlistUpdate, user_id: str = DEFAULT_USER_ID) -> UserWatchlist:
    normalized = _normalize_symbol(symbol)
    now = _now()
    updates = payload.model_dump(exclude_unset=True)
    with _state_lock:
        state = _load_state_unlocked()
        for index, raw_item in enumerate(state.get("watchlist", [])):
            item = UserWatchlist.model_validate(raw_item)
            if item.user_id == user_id and item.symbol == normalized:
                updated = item.model_copy(update={**updates, "updated_at": now})
                state["watchlist"][index] = updated.model_dump()
                _save_state_unlocked(state)
                return updated
    raise PortfolioError(f"watchlist symbol not found: {symbol}")


def delete_watchlist_item(symbol: str, user_id: str = DEFAULT_USER_ID) -> None:
    normalized = _normalize_symbol(symbol)
    with _state_lock:
        state = _load_state_unlocked()
        before = len(state.get("watchlist", []))
        state["watchlist"] = [
            item
            for item in state.get("watchlist", [])
            if not (str(item.get("user_id") or DEFAULT_USER_ID) == user_id and str(item.get("symbol")) == normalized)
        ]
        if len(state["watchlist"]) == before:
            raise PortfolioError(f"watchlist symbol not found: {symbol}")
        _save_state_unlocked(state)


def _candle_key(symbol: str, interval: str) -> str:
    return f"{_normalize_symbol(symbol)}:{interval or DEFAULT_INTERVAL}"


def _parse_interval_minutes(interval: str) -> int:
    if interval == "15m":
        return 15
    if interval.endswith("m") and interval[:-1].isdigit():
        return max(1, int(interval[:-1]))
    raise PortfolioError("only minute kline intervals are supported")


def _candle_from_binance(symbol: str, interval: str, raw: list[Any], created_at: str) -> MarketCandle:
    return MarketCandle(
        id=f"{symbol}:{interval}:{int(raw[0])}",
        symbol=symbol,
        interval=interval,
        open_time=int(raw[0]),
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]),
        source="binance_public",
        created_at=created_at,
    )


def _fetch_binance_candles(symbol: str, interval: str, limit: int) -> list[MarketCandle]:
    created_at = _now()
    response = httpx.get(
        "https://api.binance.com/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=6,
    )
    response.raise_for_status()
    raw_items = response.json()
    if not isinstance(raw_items, list) or not raw_items:
        raise PortfolioError("empty binance kline response")
    return [_candle_from_binance(symbol, interval, item, created_at) for item in raw_items if isinstance(item, list) and len(item) >= 6]


def _fallback_base_price(symbol: str) -> float:
    if symbol in BASE_PRICES:
        return BASE_PRICES[symbol]
    base = _base_asset(symbol)
    meta = COIN_DICTIONARY.get(base)
    if meta:
        return 12 + len(str(meta.get("name", base))) * 3
    return 5 + (sum(ord(char) for char in symbol) % 500)


def _mock_candles(symbol: str, interval: str, limit: int) -> list[MarketCandle]:
    interval_minutes = _parse_interval_minutes(interval)
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = end.replace(minute=(end.minute // interval_minutes) * interval_minutes)
    start = end - timedelta(minutes=interval_minutes * max(1, limit - 1))
    seed_bucket = int(end.timestamp() // (interval_minutes * 60))
    rng = random.Random(f"portfolio:{symbol}:{interval}:{seed_bucket // 12}")
    base = _fallback_base_price(symbol)
    price = base * (1 + rng.uniform(-0.025, 0.025))
    created_at = _now()
    candles: list[MarketCandle] = []

    for index in range(limit):
        open_time = start + timedelta(minutes=interval_minutes * index)
        drift = math.sin(index / 26) * 0.0018 + math.cos(index / 67) * 0.001
        shock = rng.uniform(-0.005, 0.005)
        open_price = price
        close_price = max(base * 0.05, open_price * (1 + drift + shock))
        high_price = max(open_price, close_price) * (1 + rng.uniform(0.0005, 0.006))
        low_price = min(open_price, close_price) * (1 - rng.uniform(0.0005, 0.006))
        volume = rng.uniform(1200, 9800) * (1 + abs(shock) * 90)
        open_ms = int(open_time.timestamp() * 1000)
        candles.append(
            MarketCandle(
                id=f"{symbol}:{interval}:{open_ms}",
                symbol=symbol,
                interval=interval,
                open_time=open_ms,
                open=round(open_price, 8),
                high=round(high_price, 8),
                low=round(low_price, 8),
                close=round(close_price, 8),
                volume=round(volume, 8),
                source="mock_fallback",
                created_at=created_at,
            )
        )
        price = close_price

    return candles


def sync_market_candles(symbol: str, interval: str = DEFAULT_INTERVAL, limit: int = DEFAULT_LIMIT) -> list[MarketCandle]:
    normalized = _normalize_symbol(symbol)
    safe_limit = max(20, min(1000, int(limit or DEFAULT_LIMIT)))
    try:
        candles = _fetch_binance_candles(normalized, interval, safe_limit)
    except Exception:
        candles = _mock_candles(normalized, interval, safe_limit)

    with _state_lock:
        state = _load_state_unlocked()
        state["candles"][_candle_key(normalized, interval)] = [item.model_dump() for item in candles]
        _save_state_unlocked(state)
    return candles


def get_market_candles(symbol: str, interval: str = DEFAULT_INTERVAL, limit: int = DEFAULT_LIMIT) -> list[MarketCandle]:
    normalized = _normalize_symbol(symbol)
    safe_limit = max(1, min(1000, int(limit or DEFAULT_LIMIT)))
    with _state_lock:
        state = _load_state_unlocked()
        raw_items = state.get("candles", {}).get(_candle_key(normalized, interval), [])
    candles = [MarketCandle.model_validate(item) for item in raw_items]
    if len(candles) >= min(20, safe_limit):
        return candles[-safe_limit:]
    return sync_market_candles(normalized, interval, max(DEFAULT_LIMIT, safe_limit))[-safe_limit:]


def _news_match(symbol: str, item: dict[str, Any]) -> tuple[float, str] | None:
    base = _base_asset(symbol)
    raw_coin_details = item.get("coin_details")
    if isinstance(raw_coin_details, list):
        for detail in raw_coin_details:
            if not isinstance(detail, dict):
                continue
            detail_symbol = str(detail.get("symbol") or "").upper()
            if detail_symbol in {base, symbol}:
                terms = detail.get("matched_terms") if isinstance(detail.get("matched_terms"), list) else []
                return 0.92, f"币种实体匹配：{', '.join([str(term) for term in terms[:3]]) or base}"

    raw_coins = item.get("coins")
    if isinstance(raw_coins, list):
        for coin in raw_coins:
            coin_text = str(coin or "").upper()
            if coin_text in {base, symbol}:
                return 0.86, f"新闻币种字段包含 {base}"

    title = str(item.get("title") or "")
    content = str(item.get("content") or item.get("summary") or "")
    terms = [str(term) for term in COIN_DICTIONARY.get(base, {}).get("terms", [base])]
    text = f"{title}\n{content}"
    text_upper = text.upper()
    if not any(term in text if re.search(r"[\u4e00-\u9fff]", term) else term.upper() in text_upper for term in terms):
        return None

    matches = extract_coins_from_text(title, content)
    for match in matches:
        if match["symbol"].upper() == base:
            return 0.76, f"文本关键词匹配：{', '.join(match['matched_terms'][:3])}"
    return None


def _clamp_news_score(value: object) -> int:
    try:
        score = int(float(value or 0))
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _portfolio_news_item(symbol: str, item: dict[str, Any], confidence: float, reason: str) -> PortfolioNewsItem:
    news_id = str(item.get("news_id") or item.get("id") or uuid.uuid4().hex)
    return PortfolioNewsItem(
        news_id=news_id,
        title=str(item.get("title") or ""),
        content=str(item.get("content") or ""),
        published_at=str(item.get("published_at") or item.get("date") or ""),
        risk_score=_clamp_news_score(item.get("risk_score")),
        risk_level=str(item.get("risk_level") or ""),
        risk_type=str(item.get("risk_type") or ""),
        evidence=str(item.get("evidence") or ""),
        summary=str(item.get("summary") or shorten(str(item.get("content") or ""), 160)),
        source_url=first_text_value(item, SOURCE_URL_FIELDS),
        matched_reason=reason,
        confidence=confidence,
    )


def get_related_news(symbol: str, limit: int = 20) -> list[PortfolioNewsItem]:
    normalized = _normalize_symbol(symbol)
    enriched_items = load_scored_news()
    matched: list[PortfolioNewsItem] = []
    links: list[NewsCoinLink] = []
    created_at = _now()

    for item in enriched_items:
        if not isinstance(item, dict):
            continue
        match = _news_match(normalized, item)
        if not match:
            continue
        confidence, reason = match
        news_item = _portfolio_news_item(normalized, item, confidence, reason)
        matched.append(news_item)
        links.append(
            NewsCoinLink(
                id=f"{news_item.news_id}:{normalized}",
                news_id=news_item.news_id,
                symbol=normalized,
                confidence=confidence,
                matched_reason=reason,
                created_at=created_at,
            )
        )

    matched = sorted(matched, key=lambda item: (item.risk_score, item.published_at), reverse=True)[: max(1, min(100, limit))]
    link_ids = {link.id for link in links}
    with _state_lock:
        state = _load_state_unlocked()
        existing_links = [
            item
            for item in state.get("news_links", [])
            if str(item.get("id")) not in link_ids and str(item.get("symbol")) != normalized
        ]
        state["news_links"] = existing_links + [link.model_dump() for link in links]
        _save_state_unlocked(state)
    return matched


def _latest_snapshot(symbol: str, user_id: str = DEFAULT_USER_ID) -> CoinRiskSnapshot | None:
    normalized = _normalize_symbol(symbol)
    with _state_lock:
        state = _load_state_unlocked()
        raw = state.get("risk_snapshots", {}).get(f"{user_id}:{normalized}")
    return CoinRiskSnapshot.model_validate(raw) if raw else None


def _store_snapshot(snapshot: CoinRiskSnapshot) -> None:
    with _state_lock:
        state = _load_state_unlocked()
        state["risk_snapshots"][f"{snapshot.user_id}:{snapshot.symbol}"] = snapshot.model_dump()
        _save_state_unlocked(state)


def generate_risk_snapshot(symbol: str, user_id: str = DEFAULT_USER_ID) -> CoinRiskSnapshot:
    normalized = _normalize_symbol(symbol)
    watches = _watch_items(user_id)
    watch = next((item for item in watches if item.symbol == normalized), None)
    if watch is None:
        watch = UserWatchlist(
            id=f"{user_id}:{normalized}",
            user_id=user_id,
            symbol=normalized,
            base_asset=_base_asset(normalized),
            created_at=_now(),
            updated_at=_now(),
        )
    candles = get_market_candles(normalized, DEFAULT_INTERVAL, DEFAULT_LIMIT)
    news_items = get_related_news(normalized, 20)
    generated_at = _now()
    snapshot = generate_portfolio_risk_snapshot(
        generated_at=generated_at,
        news_items=news_items,
        snapshot_id=f"{user_id}:{normalized}:{generated_at}",
        symbol=normalized,
        user_id=user_id,
        watch=watch,
        candles=candles,
    )
    _store_snapshot(snapshot)
    return snapshot


def get_risk_snapshot(symbol: str, user_id: str = DEFAULT_USER_ID) -> CoinRiskSnapshot:
    snapshot = _latest_snapshot(symbol, user_id)
    if snapshot:
        return snapshot
    return generate_risk_snapshot(symbol, user_id)


def _refresh_news_dataset_for_portfolio() -> tuple[bool, str]:
    try:
        update_result = update_news_dataset()
        read_raw_news_records.cache_clear()
        run_ranking_agent("all", date_filter="7d", limit=10)
        read_raw_news_records.cache_clear()
        if update_result.get("crawler_error"):
            return False, "新闻源暂时不可达，已使用本地新闻集刷新关联。"
        added_count = int(update_result.get("added_count") or 0)
        return True, f"新闻已同步，新增 {added_count} 条。"
    except Exception as exc:
        return False, f"新闻刷新失败，已使用现有新闻集：{exc}"


def _watchlist_response_item(watch: UserWatchlist) -> PortfolioWatchlistItem:
    candles = get_market_candles(watch.symbol, DEFAULT_INTERVAL, DEFAULT_LIMIT)
    latest_price = candles[-1].close if candles else 0
    price_change_24h = 0.0
    if len(candles) >= 2:
        base = candles[max(0, len(candles) - 97)].close or candles[0].close
        price_change_24h = (latest_price - base) / base if base else 0
    market_value = latest_price * watch.amount if watch.is_holding else 0
    floating_pnl = (latest_price - watch.avg_buy_price) * watch.amount if watch.is_holding and watch.avg_buy_price else 0
    floating_pnl_rate = (latest_price - watch.avg_buy_price) / watch.avg_buy_price if watch.is_holding and watch.avg_buy_price else 0
    snapshot = _latest_snapshot(watch.symbol, watch.user_id)

    return PortfolioWatchlistItem(
        **watch.model_dump(),
        current_price=latest_price,
        price_change_24h=price_change_24h,
        market_value=market_value,
        floating_pnl=floating_pnl,
        floating_pnl_rate=floating_pnl_rate,
        risk_score=snapshot.risk_score if snapshot else 0,
        risk_level=snapshot.risk_level if snapshot else "low",
        ai_summary=snapshot.ai_summary if snapshot else "",
    )


def list_watchlist(user_id: str = DEFAULT_USER_ID) -> list[PortfolioWatchlistItem]:
    return [_watchlist_response_item(watch) for watch in _watch_items(user_id)]


def refresh_portfolio(user_id: str = DEFAULT_USER_ID) -> PortfolioRefreshResponse:
    watches = _watch_items(user_id)
    if not watches:
        return PortfolioRefreshResponse(
            updated_at=_now(),
            message="No watchlist symbols to refresh",
        )

    _news_refreshed, news_message = _refresh_news_dataset_for_portfolio()
    related_news_ids: set[str] = set()
    market_sources: set[str] = set()
    snapshots = 0
    success_symbols: list[str] = []

    for watch in watches:
        candles = sync_market_candles(watch.symbol, DEFAULT_INTERVAL, DEFAULT_LIMIT)
        market_sources.update({item.source for item in candles})
        news_items = get_related_news(watch.symbol, 30)
        related_news_ids.update({item.news_id for item in news_items})
        snapshot = generate_portfolio_risk_snapshot(
            generated_at=_now(),
            news_items=news_items,
            snapshot_id=f"{user_id}:{watch.symbol}:{uuid.uuid4().hex}",
            symbol=watch.symbol,
            user_id=user_id,
            watch=watch,
            candles=candles,
        )
        _store_snapshot(snapshot)
        snapshots += 1
        success_symbols.append(watch.symbol)

    source = "mixed"
    if len(market_sources) == 1:
        source = next(iter(market_sources))

    return PortfolioRefreshResponse(
        updated_at=_now(),
        success_symbols=len(success_symbols),
        related_news_count=len(related_news_ids),
        risk_snapshots=snapshots,
        symbols=success_symbols,
        market_source=source,
        message=f"已刷新自选币种行情、相关新闻关联与风险快照。{news_message}",
    )
