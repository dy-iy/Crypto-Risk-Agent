"""Lightweight account follows, backed by the existing watchlist records."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas_portfolio import UserWatchlist
from app.services.coin_library_service import list_coin_library
from app.services import portfolio_watchlist_store as store


class NoFollowsError(ValueError):
    pass


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{1,24}', symbol):
        raise ValueError('无效币种')
    return symbol if symbol.endswith('USDT') else symbol + 'USDT'


def _catalog():
    return {str(item['symbol']): item for item in list_coin_library()}


def follow_snapshot(user_id: str) -> dict:
    catalog = _catalog()
    records = store.list_watchlist_records(user_id)
    items = [{'symbol': row.symbol, 'base_asset': row.base_asset,
              'name': str(catalog.get(row.symbol, {}).get('name') or row.base_asset),
              'alert_threshold': row.alert_threshold, 'created_at': row.created_at,
              'updated_at': row.updated_at}
             for row in sorted(records, key=lambda row: row.symbol) if row.is_watched]
    revision = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return {'items': items, 'revision': revision}


def mutate_follow(user_id: str, raw_symbol: str, action: str, threshold: int | None = None) -> dict:
    symbol = normalize_symbol(raw_symbol)
    catalog = _catalog()
    now = datetime.now(timezone.utc).isoformat()
    # One transaction changes only follow fields; historic holdings are never rewritten.
    with store._db_lock:
        with store._connect() as connection:
            store._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute('SELECT * FROM portfolio_watchlist WHERE user_id = ? AND symbol = ?', (user_id, symbol)).fetchone()
            if action == 'add':
                if not row:
                    if symbol not in catalog:
                        raise ValueError('币种不在支持的币种库中')
                    item = UserWatchlist(id=str(uuid4()), user_id=user_id, symbol=symbol,
                                         base_asset=str(catalog[symbol]['base_asset']), created_at=now, updated_at=now)
                    store._write_watchlist_item(connection, item)
                elif not row['is_watched']:
                    connection.execute('UPDATE portfolio_watchlist SET is_watched = 1, updated_at = ? WHERE user_id = ? AND symbol = ?', (now, user_id, symbol))
            elif action == 'remove':
                connection.execute('UPDATE portfolio_watchlist SET is_watched = 0, updated_at = ? WHERE user_id = ? AND symbol = ? AND is_watched = 1', (now, user_id, symbol))
            elif action == 'threshold':
                if not row or not row['is_watched']:
                    raise LookupError('请先关注该币种')
                if row['alert_threshold'] != threshold:
                    connection.execute('UPDATE portfolio_watchlist SET alert_threshold = ?, updated_at = ? WHERE user_id = ? AND symbol = ?', (threshold, now, user_id, symbol))
            else:
                raise ValueError('不支持的关注操作')
            connection.commit()
    return follow_snapshot(user_id)
