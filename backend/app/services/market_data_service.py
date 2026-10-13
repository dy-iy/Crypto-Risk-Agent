"""Read-only public spot market data. Never generate synthetic prices."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic, time
from typing import Any, Callable
import json
import math

import httpx

BASE_URL = 'https://data-api.binance.vision/api/v3'
SYMBOLS = {
    'BTCUSDT': 'Bitcoin', 'ETHUSDT': 'Ethereum', 'BNBUSDT': 'BNB',
    'SOLUSDT': 'Solana', 'XRPUSDT': 'XRP', 'DOGEUSDT': 'Dogecoin',
    'ADAUSDT': 'Cardano', 'AVAXUSDT': 'Avalanche', 'LINKUSDT': 'Chainlink',
    'TRXUSDT': 'TRON', 'SUIUSDT': 'Sui', 'AAVEUSDT': 'Aave',
    'DOTUSDT': 'Polkadot', 'LTCUSDT': 'Litecoin', 'UNIUSDT': 'Uniswap',
}
INTERVALS = ('1m', '5m', '15m', '1h', '4h', '1d')
MAX_CACHE_ENTRIES = 128
MAX_STALE_SECONDS = 300
_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_retry_after: OrderedDict[str, float] = OrderedDict()
_cache_lock = Lock()
_request_locks = [Lock() for _ in range(16)]
_client = httpx.Client(timeout=httpx.Timeout(6, connect=3), limits=httpx.Limits(max_connections=16, max_keepalive_connections=8), follow_redirects=False)


class MarketDataUnavailable(Exception):
    pass


def close_market_client() -> None:
    _client.close()


def number(value: Any, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError('Invalid market number')
    return result


def symbol_metadata() -> list[dict[str, str]]:
    return [{'symbol': symbol, 'base': symbol[:-4], 'quote': 'USDT', 'name': name} for symbol, name in SYMBOLS.items()]


def _cached(key: str, ttl: float, fetch: Callable[[], Any]) -> dict[str, Any]:
    # Striped locks bound memory and coalesce concurrent reads of the same feed.
    with _request_locks[hash(key) % len(_request_locks)]:
        now = monotonic()
        with _cache_lock:
            previous = _cache.get(key)
            retry_at = _retry_after.get(key, 0)
            if previous:
                _cache.move_to_end(key)
        if previous and now - previous[0] < ttl:
            return deepcopy(previous[1])
        if now < retry_at:
            if previous and now - previous[0] <= MAX_STALE_SECONDS:
                return {**deepcopy(previous[1]), 'stale': True}
            raise MarketDataUnavailable('行情源暂时不可用，请稍后重试')
        try:
            data = fetch()
            result = {'data': data, 'source': 'Binance Spot', 'as_of': int(time() * 1000), 'stale': False}
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
            with _cache_lock:
                _retry_after[key] = monotonic() + 10
                _retry_after.move_to_end(key)
                while len(_retry_after) > MAX_CACHE_ENTRIES:
                    _retry_after.popitem(last=False)
            if previous and now - previous[0] <= MAX_STALE_SECONDS:
                return {**deepcopy(previous[1]), 'stale': True}
            raise MarketDataUnavailable('行情源暂时不可用，请稍后重试') from exc
        with _cache_lock:
            _cache[key] = (monotonic(), result)
            _cache.move_to_end(key)
            _retry_after.pop(key, None)
            while len(_cache) > MAX_CACHE_ENTRIES:
                _cache.popitem(last=False)
        return deepcopy(result)


def _get(path: str, params: dict[str, Any]) -> Any:
    response = _client.get(f'{BASE_URL}/{path}', params=params)
    response.raise_for_status()
    return response.json()


def tickers() -> dict[str, Any]:
    def fetch():
        rows = _get('ticker/24hr', {'symbols': json.dumps(list(SYMBOLS), separators=(",", ":")), 'type': 'MINI'})
        if not isinstance(rows, list) or not rows:
            raise ValueError('Empty tickers')
        result = []
        for row in rows:
            symbol = row['symbol']
            if symbol not in SYMBOLS:
                continue
            price, opening = number(row['lastPrice'], positive=True), number(row['openPrice'], positive=True)
            change = (price / opening - 1) * 100
            if not math.isfinite(change):
                raise ValueError('Invalid change')
            result.append({'symbol': symbol, 'price': price, 'change_pct': change,
                           'high': number(row['highPrice'], positive=True), 'low': number(row['lowPrice'], positive=True),
                           'volume': number(row['volume']), 'quote_volume': number(row['quoteVolume']), 'time': int(row['closeTime'])})
        if not result:
            raise ValueError('No supported tickers')
        return result
    return _cached('tickers', 5, fetch)


def candles(symbol: str, interval: str, limit: int, end_time: int | None = None) -> dict[str, Any]:
    def fetch():
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        if end_time is not None:
            params['endTime'] = end_time
        rows = _get('klines', params)
        if not isinstance(rows, list):
            raise ValueError('Invalid candles')
        result = {}
        for row in rows:
            timestamp = int(row[0]) // 1000
            if timestamp <= 0:
                raise ValueError('Invalid candle time')
            o, h, l, c = (number(row[index], positive=True) for index in (1, 2, 3, 4))
            if h < max(o, c, l) or l > min(o, c):
                raise ValueError('Invalid OHLC')
            result[timestamp] = {'time': timestamp, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': number(row[5])}
        return [result[key] for key in sorted(result)]
    return _cached(f'candles:{symbol}:{interval}:{limit}:{end_time}', 60 if end_time else 5, fetch)


def depth(symbol: str) -> dict[str, Any]:
    def fetch():
        row = _get('depth', {'symbol': symbol, 'limit': 20})
        def levels(side):
            return [{'price': number(item[0], positive=True), 'quantity': number(item[1])} for item in row[side]][:20]
        return {'bids': sorted(levels('bids'), key=lambda item: item['price'], reverse=True),
                'asks': sorted(levels('asks'), key=lambda item: item['price'])}
    return _cached(f'depth:{symbol}', 3, fetch)


def trades(symbol: str) -> dict[str, Any]:
    def fetch():
        rows = _get('trades', {'symbol': symbol, 'limit': 30})
        if not isinstance(rows, list):
            raise ValueError('Invalid trades')
        return [{'id': str(row['id']), 'price': number(row['price'], positive=True),
                 'quantity': number(row['qty']), 'time': int(row['time']),
                 'side': 'sell' if row['isBuyerMaker'] else 'buy'} for row in reversed(rows)]
    return _cached(f'trades:{symbol}', 3, fetch)
