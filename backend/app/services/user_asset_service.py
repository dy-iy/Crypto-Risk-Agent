from __future__ import annotations

from app.schemas_portfolio import PortfolioWatchlistItem, UserWatchlist, UserWatchlistCreate, UserWatchlistUpdate
from app.services.portfolio_service import (
    DEFAULT_USER_ID,
    add_watchlist_item,
    delete_watchlist_item,
    list_watchlist,
    update_watchlist_item,
)


def list_user_assets(user_id: str = DEFAULT_USER_ID) -> list[PortfolioWatchlistItem]:
    return list_watchlist(user_id)


def add_user_asset(payload: UserWatchlistCreate, user_id: str = DEFAULT_USER_ID) -> UserWatchlist:
    return add_watchlist_item(payload, user_id)


def update_user_asset(symbol: str, payload: UserWatchlistUpdate, user_id: str = DEFAULT_USER_ID) -> UserWatchlist:
    return update_watchlist_item(symbol, payload, user_id)


def delete_user_asset(symbol: str, user_id: str = DEFAULT_USER_ID) -> None:
    delete_watchlist_item(symbol, user_id)
