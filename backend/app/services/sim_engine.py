from __future__ import annotations

import json
import math
from contextlib import contextmanager
from copy import deepcopy
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.services.data_loader import load_scored_news
from app.services.runtime_json_store import load_runtime_json_or_quarantine, write_runtime_json_atomic


INITIAL_CASH = 10_000.0
FEE_RATE = 0.001
INTERVAL_MINUTES = 15
LOOKBACK_DAYS = 7
KLINE_COUNT = LOOKBACK_DAYS * 24 * 60 // INTERVAL_MINUTES
DEFAULT_SIM_ACCOUNT_ID = "demo_user"
SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "TRXUSDT",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
KLINE_DIR = REPO_ROOT / "data" / "sim" / "klines"
KLINE_INTERVAL_MS = INTERVAL_MINUTES * 60 * 1000
SIM_ACCOUNTS_PATH = Path(__file__).resolve().parents[1] / "data" / "sim_accounts.json"
DEFAULT_GUEST_RETENTION_DAYS = 14


SYMBOL_META = {
    "BTCUSDT": {"name": "Bitcoin", "symbol": "BTC"},
    "ETHUSDT": {"name": "Ethereum", "symbol": "ETH"},
    "BNBUSDT": {"name": "BNB", "symbol": "BNB"},
    "SOLUSDT": {"name": "Solana", "symbol": "SOL"},
    "XRPUSDT": {"name": "XRP", "symbol": "XRP"},
    "DOGEUSDT": {"name": "Dogecoin", "symbol": "DOGE"},
    "ADAUSDT": {"name": "Cardano", "symbol": "ADA"},
    "AVAXUSDT": {"name": "Avalanche", "symbol": "AVAX"},
    "LINKUSDT": {"name": "Chainlink", "symbol": "LINK"},
    "TRXUSDT": {"name": "TRON", "symbol": "TRX"},
}

SYMBOL_KEYWORDS = {
    "BTCUSDT": ["BTC", "Bitcoin", "比特币"],
    "ETHUSDT": ["ETH", "Ethereum", "以太坊", "Vitalik"],
    "BNBUSDT": ["BNB", "Binance", "币安"],
    "SOLUSDT": ["SOL", "Solana"],
    "XRPUSDT": ["XRP", "Ripple"],
    "DOGEUSDT": ["DOGE", "Dogecoin", "狗狗币"],
    "ADAUSDT": ["ADA", "Cardano"],
    "AVAXUSDT": ["AVAX", "Avalanche"],
    "LINKUSDT": ["LINK", "Chainlink"],
    "TRXUSDT": ["TRX", "Tron", "波场"],
}

MOCK_BASE_PRICE = {
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
}


@dataclass
class Position:
    quantity: float = 0.0
    avg_cost: float = 0.0


@dataclass
class SimAccountState:
    current_index: int = 0
    cash: float = INITIAL_CASH
    positions: dict[str, Position] = field(default_factory=dict)
    trade_history: list[dict[str, Any]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SimError(ValueError):
    pass


def _normalize_account_id(account_id: str | None) -> str:
    normalized = str(account_id or DEFAULT_SIM_ACCOUNT_ID).strip()
    return normalized or DEFAULT_SIM_ACCOUNT_ID


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise SimError("Symbol is required")
    if not normalized.endswith("USDT"):
        normalized = f"{normalized}USDT"
    if normalized not in SYMBOLS:
        raise SimError(f"Unsupported symbol: {symbol}")
    return normalized


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SimError(f"Invalid numeric value: {value}") from exc


def _parse_news_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _risk_score(item: dict[str, Any]) -> int:
    try:
        return int(float(item.get("risk_score") or item.get("final_risk_score") or 0))
    except (TypeError, ValueError):
        return 0


def _affected_symbols(item: dict[str, Any]) -> list[str]:
    symbols: set[str] = set()
    raw_coins = item.get("coins")
    if isinstance(raw_coins, list):
        for coin in raw_coins:
            symbol = str(coin or "").strip().upper()
            if symbol and not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"
            if symbol in SYMBOLS:
                symbols.add(symbol)

    raw_details = item.get("coin_details")
    if isinstance(raw_details, list):
        for detail in raw_details:
            if not isinstance(detail, dict):
                continue
            symbol = str(detail.get("symbol") or "").strip().upper()
            if symbol and not symbol.endswith("USDT"):
                symbol = f"{symbol}USDT"
            if symbol in SYMBOLS:
                symbols.add(symbol)

    haystack = f"{item.get('title') or ''} {item.get('content') or ''} {item.get('summary') or ''} {item.get('evidence') or ''}"
    haystack_upper = haystack.upper()
    for symbol, keywords in SYMBOL_KEYWORDS.items():
        if any(keyword.upper() in haystack_upper for keyword in keywords):
            symbols.add(symbol)

    return sorted(symbols)


def _related_symbol_details(item: dict[str, Any]) -> list[dict[str, str]]:
    haystack = f"{item.get('title') or ''} {item.get('content') or ''} {item.get('summary') or ''} {item.get('evidence') or ''}"
    haystack_upper = haystack.upper()
    details = []
    for symbol in _affected_symbols(item):
        matched = [
            keyword
            for keyword in SYMBOL_KEYWORDS.get(symbol, [])
            if keyword.upper() in haystack_upper
        ]
        details.append(
            {
                "symbol": symbol,
                "asset": SYMBOL_META[symbol]["symbol"],
                "name": SYMBOL_META[symbol]["name"],
                "matched_keywords": ", ".join(matched[:4]),
            }
        )
    return details


def _risk_level_label(score: int, fallback: Any) -> str:
    text = str(fallback or "").strip()
    if text:
        return text
    if score >= 80:
        return "高风险"
    if score >= 50:
        return "中风险"
    return "低风险"


def _public_risk_event(item: dict[str, Any], published_at: datetime) -> dict[str, Any] | None:
    score = _risk_score(item)
    affected_symbols = _affected_symbols(item)
    risk_type_text = str(item.get("risk_type") or "")
    if not affected_symbols and score >= 70 and any(
        keyword in f"{item.get('title') or ''} {item.get('content') or ''} {risk_type_text}".upper()
        for keyword in ["BINANCE", "币安", "EXCHANGE", "交易所"]
    ):
        affected_symbols = ["BNBUSDT", "BTCUSDT", "ETHUSDT"]
    if score < 50 and not affected_symbols:
        return None

    news_id = str(item.get("news_id") or item.get("id") or f"news-{int(published_at.timestamp())}")
    return {
        "id": news_id,
        "time": published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": str(item.get("title") or "Untitled risk event"),
        "summary": str(item.get("summary") or item.get("content") or ""),
        "risk_score": score,
        "risk_level": _risk_level_label(score, item.get("risk_level")),
        "risk_type": risk_type_text or "未分类风险",
        "affected_symbols": affected_symbols,
        "affected_assets": [SYMBOL_META[symbol]["symbol"] for symbol in affected_symbols],
        "related_symbols": affected_symbols,
        "related_symbol_details": _related_symbol_details({**item, "coins": affected_symbols}),
        "evidence": str(item.get("evidence") or ""),
        "source_url": str(item.get("source_url") or item.get("url") or ""),
        "analysis": item.get("llm_analysis") if isinstance(item.get("llm_analysis"), dict) else {},
    }


def _build_mock_klines(symbol: str) -> list[dict[str, float | int]]:
    rng = random.Random(symbol)
    base = MOCK_BASE_PRICE[symbol]
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    minute = (end.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES
    end = end.replace(minute=minute)
    start = end - timedelta(days=LOOKBACK_DAYS)

    price = base * (1 + rng.uniform(-0.035, 0.035))
    klines: list[dict[str, float | int]] = []
    for index in range(KLINE_COUNT):
        open_time = start + timedelta(minutes=INTERVAL_MINUTES * index)
        trend = math.sin(index / 42) * 0.0025 + math.cos(index / 93) * 0.0015
        shock = rng.uniform(-0.004, 0.004)
        open_price = price
        close_price = max(base * 0.05, open_price * (1 + trend + shock))
        high_price = max(open_price, close_price) * (1 + rng.uniform(0.0005, 0.006))
        low_price = min(open_price, close_price) * (1 - rng.uniform(0.0005, 0.006))
        volume = rng.uniform(1000, 9000) * (1 + abs(shock) * 80)
        close_time = open_time + timedelta(minutes=INTERVAL_MINUTES) - timedelta(milliseconds=1)
        klines.append(
            {
                "openTime": int(open_time.timestamp() * 1000),
                "open": round(open_price, 8),
                "high": round(high_price, 8),
                "low": round(low_price, 8),
                "close": round(close_price, 8),
                "volume": round(volume, 8),
                "closeTime": int(close_time.timestamp() * 1000),
            }
        )
        price = close_price
    return klines


def _coerce_kline(item: dict[str, Any]) -> dict[str, float | int]:
    return {
        "openTime": int(item["openTime"]),
        "open": float(item["open"]),
        "high": float(item["high"]),
        "low": float(item["low"]),
        "close": float(item["close"]),
        "volume": float(item["volume"]),
        "closeTime": int(item["closeTime"]),
    }


def _load_symbol_klines(symbol: str) -> list[dict[str, float | int]]:
    path = KLINE_DIR / f"{symbol}.json"
    try:
        with path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, list) or not raw:
            raise ValueError("Kline file is empty")
        return [_coerce_kline(item) for item in raw]
    except Exception:
        return _build_mock_klines(symbol)


def _position_to_dict(position: Position) -> dict[str, float]:
    return {
        "quantity": float(position.quantity),
        "avg_cost": float(position.avg_cost),
    }


def _position_from_dict(payload: Any) -> Position:
    if not isinstance(payload, dict):
        return Position()
    try:
        quantity = float(payload.get("quantity") or 0)
        avg_cost = float(payload.get("avg_cost") or 0)
    except (TypeError, ValueError):
        return Position()
    if quantity <= 0:
        return Position()
    return Position(quantity=quantity, avg_cost=max(0.0, avg_cost))


def _account_to_dict(account: SimAccountState) -> dict[str, Any]:
    return {
        "current_index": int(account.current_index),
        "cash": float(account.cash),
        "positions": {
            symbol: _position_to_dict(position)
            for symbol, position in account.positions.items()
            if symbol in SYMBOLS and position.quantity > 0
        },
        "trade_history": list(account.trade_history[:500]),
        "updated_at": account.updated_at,
    }


def _account_from_dict(payload: Any, max_index: int) -> SimAccountState:
    if not isinstance(payload, dict):
        return SimAccountState()
    try:
        current_index = max(0, min(max_index, int(payload.get("current_index") or 0)))
    except (TypeError, ValueError):
        current_index = 0
    try:
        cash = float(payload.get("cash") if payload.get("cash") is not None else INITIAL_CASH)
    except (TypeError, ValueError):
        cash = INITIAL_CASH

    positions: dict[str, Position] = {}
    raw_positions = payload.get("positions")
    if isinstance(raw_positions, dict):
        for symbol, raw_position in raw_positions.items():
            normalized = str(symbol or "").upper()
            if normalized not in SYMBOLS:
                continue
            position = _position_from_dict(raw_position)
            if position.quantity > 0:
                positions[normalized] = position

    raw_history = payload.get("trade_history")
    trade_history = raw_history if isinstance(raw_history, list) else []
    return SimAccountState(
        current_index=current_index,
        cash=max(0.0, cash),
        positions=positions,
        trade_history=[item for item in trade_history[:500] if isinstance(item, dict)],
        updated_at=str(payload.get("updated_at") or _now_iso()),
    )


class SimEngine:
    def __init__(self) -> None:
        self._lock = Lock()
        self.klines = {symbol: _load_symbol_klines(symbol) for symbol in SYMBOLS}
        self.max_index = min(len(items) for items in self.klines.values()) - 1
        self.risk_events_by_index = self._load_risk_events_by_index()
        self._accounts: dict[str, SimAccountState] = self._load_accounts()

    def reset(self, account_id: str | None = DEFAULT_SIM_ACCOUNT_ID) -> dict[str, Any]:
        with self._mutation(account_id):
            account = SimAccountState()
            self._accounts[_normalize_account_id(account_id)] = account
            self._persist_accounts_unlocked()
            return self._state_unlocked(account)

    def symbols(self) -> list[dict[str, str]]:
        return [
            {
                "symbol": symbol,
                "base_symbol": SYMBOL_META[symbol]["symbol"],
                "name": SYMBOL_META[symbol]["name"],
            }
            for symbol in SYMBOLS
        ]

    def next(self, account_id: str | None = DEFAULT_SIM_ACCOUNT_ID) -> dict[str, Any]:
        with self._mutation(account_id):
            account = self._account_unlocked(account_id)
            if account.current_index < self.max_index:
                account.current_index += 1
                self._touch_account_unlocked(account)
                self._persist_accounts_unlocked()
            return self._state_unlocked(account)

    def jump(
        self,
        index: int | None = None,
        target_time: str | None = None,
        account_id: str | None = DEFAULT_SIM_ACCOUNT_ID,
    ) -> dict[str, Any]:
        with self._mutation(account_id):
            account = self._account_unlocked(account_id)
            if index is None and target_time:
                parsed_time = _parse_news_time(target_time)
                if not parsed_time:
                    raise SimError("Invalid target_time")
                first_symbol = SYMBOLS[0]
                start_ms = int(self.klines[first_symbol][0]["openTime"])
                index = int((int(parsed_time.timestamp() * 1000) - start_ms) // KLINE_INTERVAL_MS)

            if index is None:
                raise SimError("Jump target is required")

            account.current_index = max(0, min(self.max_index, int(index)))
            self._touch_account_unlocked(account)
            self._persist_accounts_unlocked()
            return self._state_unlocked(account)

    def state(self, account_id: str | None = DEFAULT_SIM_ACCOUNT_ID) -> dict[str, Any]:
        with self._lock:
            return self._state_unlocked(self._account_unlocked(account_id))

    def account_state_snapshot(self, account_id: str | None) -> dict[str, Any] | None:
        normalized = _normalize_account_id(account_id)
        with self._lock:
            account = self._accounts.get(normalized)
            if not account:
                return None
            return self._state_unlocked(account)

    def account_count(self) -> int:
        with self._lock:
            return len(self._accounts)

    def delete_account(self, account_id: str | None) -> int:
        normalized = _normalize_account_id(account_id)
        with self._mutation(account_id):
            if normalized not in self._accounts:
                return 0
            del self._accounts[normalized]
            self._persist_accounts_unlocked()
            return 1

    def prune_guest_accounts(self, retention_days: int = DEFAULT_GUEST_RETENTION_DAYS) -> dict[str, Any]:
        safe_days = max(1, min(3650, int(retention_days or DEFAULT_GUEST_RETENTION_DAYS)))
        cutoff = datetime.now(timezone.utc) - timedelta(days=safe_days)
        with self._mutation():
            deleted_ids = [
                account_id
                for account_id, account in self._accounts.items()
                if account_id.startswith("guest:") and _parse_iso_datetime(account.updated_at) < cutoff
            ]
            for account_id in deleted_ids:
                del self._accounts[account_id]
            if deleted_ids:
                self._persist_accounts_unlocked()
            return {
                "deleted_accounts": len(deleted_ids),
                "remaining_accounts": len(self._accounts),
                "retention_days": safe_days,
            }

    def candles(self, symbol: str, account_id: str | None = DEFAULT_SIM_ACCOUNT_ID) -> list[dict[str, Any]]:
        normalized = _normalize_symbol(symbol)
        with self._lock:
            account = self._account_unlocked(account_id)
            return [
                self._public_candle(item)
                for item in self.klines[normalized][: account.current_index + 1]
            ]

    def events(self, symbol: str, account_id: str | None = DEFAULT_SIM_ACCOUNT_ID) -> list[dict[str, Any]]:
        normalized = _normalize_symbol(symbol)
        with self._lock:
            account = self._account_unlocked(account_id)
            events = []
            for index in range(account.current_index + 1):
                for event in self.risk_events_by_index.get(index, []):
                    if normalized in event.get("affected_symbols", []):
                        events.append(event)
            return sorted(
                events,
                key=lambda event: (int(event.get("candle_index") or 0), int(event.get("risk_score") or 0)),
                reverse=True,
            )

    def buy(
        self,
        symbol: str,
        amount_usdt: float,
        account_id: str | None = DEFAULT_SIM_ACCOUNT_ID,
    ) -> dict[str, Any]:
        normalized = _normalize_symbol(symbol)
        amount = _float(amount_usdt)
        if not math.isfinite(amount) or amount <= 0:
            raise SimError("Buy amount must be greater than 0")

        with self._mutation(account_id):
            account = self._account_unlocked(account_id)
            price = self._price_unlocked(normalized, account)
            fee = amount * FEE_RATE
            total_cost = amount + fee
            if total_cost > account.cash + 1e-9:
                raise SimError("Insufficient cash balance")

            quantity = amount / price
            position = account.positions.get(normalized, Position())
            existing_cost = position.quantity * position.avg_cost
            new_quantity = position.quantity + quantity
            new_avg_cost = (existing_cost + amount) / new_quantity
            account.positions[normalized] = Position(quantity=new_quantity, avg_cost=new_avg_cost)
            account.cash -= total_cost
            self._append_trade_unlocked(account, normalized, "BUY", price, quantity, amount, fee)
            self._touch_account_unlocked(account)
            self._persist_accounts_unlocked()
            return self._state_unlocked(account)

    def sell(
        self,
        symbol: str,
        quantity: float | str | None = None,
        amount: str | None = None,
        account_id: str | None = DEFAULT_SIM_ACCOUNT_ID,
    ) -> dict[str, Any]:
        normalized = _normalize_symbol(symbol)

        with self._mutation(account_id):
            account = self._account_unlocked(account_id)
            position = account.positions.get(normalized, Position())
            if position.quantity <= 0:
                raise SimError("No position to sell")

            if str(quantity).upper() == "ALL" or str(amount).upper() == "ALL":
                sell_quantity = position.quantity
            else:
                sell_quantity = _float(quantity)

            if not math.isfinite(sell_quantity) or sell_quantity <= 0:
                raise SimError("Sell quantity must be greater than 0")
            if sell_quantity > position.quantity + 1e-12:
                raise SimError("Insufficient position quantity")

            price = self._price_unlocked(normalized, account)
            gross = sell_quantity * price
            fee = gross * FEE_RATE
            account.cash += gross - fee
            remaining = position.quantity - sell_quantity
            if remaining <= 1e-12:
                account.positions.pop(normalized, None)
            else:
                account.positions[normalized] = Position(quantity=remaining, avg_cost=position.avg_cost)

            self._append_trade_unlocked(account, normalized, "SELL", price, sell_quantity, gross, fee)
            self._touch_account_unlocked(account)
            self._persist_accounts_unlocked()
            return self._state_unlocked(account)

    @contextmanager
    def _mutation(self, account_id=None):
        with self._lock:
            previous = dict(self._accounts)
            key = _normalize_account_id(account_id)
            if key in previous:
                previous[key] = deepcopy(previous[key])
            try:
                yield
            except Exception:
                self._accounts = previous
                raise

    def _account_unlocked(self, account_id: str | None) -> SimAccountState:
        normalized = _normalize_account_id(account_id)
        account = self._accounts.get(normalized)
        if not account:
            account = SimAccountState()
            self._accounts[normalized] = account
            try:
                self._persist_accounts_unlocked()
            except Exception:
                self._accounts.pop(normalized, None)
                raise
        return account

    def _touch_account_unlocked(self, account: SimAccountState) -> None:
        account.updated_at = _now_iso()

    def _load_accounts(self) -> dict[str, SimAccountState]:
        payload = load_runtime_json_or_quarantine(SIM_ACCOUNTS_PATH)
        raw_accounts = payload.get("accounts") if isinstance(payload, dict) else None
        if not isinstance(raw_accounts, dict):
            return {}
        accounts: dict[str, SimAccountState] = {}
        for raw_account_id, raw_account in raw_accounts.items():
            account_id = _normalize_account_id(str(raw_account_id))
            accounts[account_id] = _account_from_dict(raw_account, self.max_index)
        return accounts

    def _persist_accounts_unlocked(self) -> None:
        payload = {
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "accounts": {
                account_id: _account_to_dict(account)
                for account_id, account in sorted(self._accounts.items())
            },
        }
        if not write_runtime_json_atomic(SIM_ACCOUNTS_PATH, payload):
            raise SimError("模拟账户保存失败，本次操作未完成，请稍后重试")

    def _price_unlocked(self, symbol: str, account: SimAccountState) -> float:
        return float(self.klines[symbol][account.current_index]["close"])

    def _append_trade_unlocked(
        self,
        account: SimAccountState,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        amount_usdt: float,
        fee: float,
    ) -> None:
        candle = self.klines[symbol][account.current_index]
        account.trade_history.insert(
            0,
            {
                "time": _iso_from_ms(int(candle["openTime"])),
                "symbol": symbol,
                "side": side,
                "price": round(price, 8),
                "quantity": round(quantity, 12),
                "amount_usdt": round(amount_usdt, 8),
                "fee": round(fee, 8),
            },
        )

    def _state_unlocked(self, account: SimAccountState) -> dict[str, Any]:
        prices = {symbol: self._price_unlocked(symbol, account) for symbol in SYMBOLS}
        positions = []
        for symbol, position in account.positions.items():
            current_price = prices[symbol]
            market_value = position.quantity * current_price
            cost = position.quantity * position.avg_cost
            pnl = market_value - cost
            positions.append(
                {
                    "symbol": symbol,
                    "quantity": round(position.quantity, 12),
                    "avg_cost": round(position.avg_cost, 8),
                    "current_price": round(current_price, 8),
                    "market_value": round(market_value, 8),
                    "pnl": round(pnl, 8),
                    "pnl_rate": round(pnl / cost if cost else 0.0, 8),
                }
            )

        total_asset = account.cash + sum(item["market_value"] for item in positions)
        first_symbol = SYMBOLS[0]
        sim_time = _iso_from_ms(int(self.klines[first_symbol][account.current_index]["openTime"]))
        start_time = _iso_from_ms(int(self.klines[first_symbol][0]["openTime"]))
        end_time = _iso_from_ms(int(self.klines[first_symbol][self.max_index]["openTime"]))
        return {
            "current_index": account.current_index,
            "max_index": self.max_index,
            "start_time": start_time,
            "end_time": end_time,
            "sim_time": sim_time,
            "cash": round(account.cash, 8),
            "positions": sorted(positions, key=lambda item: item["symbol"]),
            "prices": {symbol: round(price, 8) for symbol, price in prices.items()},
            "total_asset": round(total_asset, 8),
            "return_rate": round((total_asset - INITIAL_CASH) / INITIAL_CASH, 8),
            "trade_history": list(account.trade_history),
            "risk_events": self.risk_events_by_index.get(account.current_index, []),
        }

    def _load_risk_events_by_index(self) -> dict[int, list[dict[str, Any]]]:
        first_symbol = SYMBOLS[0]
        start_ms = int(self.klines[first_symbol][0]["openTime"])
        events_by_index: dict[int, list[dict[str, Any]]] = {}

        for item in load_scored_news():
            published_at = _parse_news_time(item.get("published_at") or item.get("date"))
            if not published_at:
                continue
            index = int((int(published_at.timestamp() * 1000) - start_ms) // KLINE_INTERVAL_MS)
            if index < 0 or index > self.max_index:
                continue

            event = _public_risk_event(item, published_at)
            if not event:
                continue
            event["candle_index"] = index
            events_by_index.setdefault(index, []).append(event)

        for events in events_by_index.values():
            events.sort(key=lambda event: int(event.get("risk_score") or 0), reverse=True)
            del events[5:]
        return events_by_index

    @staticmethod
    def _public_candle(item: dict[str, float | int]) -> dict[str, float | int | str]:
        return {
            **item,
            "time": _iso_from_ms(int(item["openTime"])),
        }


sim_engine = SimEngine()
