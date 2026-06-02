from __future__ import annotations

from os import getenv

from fastapi import APIRouter, Cookie, HTTPException, Query

from app.api.auth import SESSION_COOKIE_NAME
from app.schemas_portfolio import PortfolioWatchlistItem, UserWatchlist, UserWatchlistCreate, UserWatchlistUpdate
from app.services.auth_service import get_user_by_session
from app.services.portfolio_service import DEFAULT_USER_ID, PortfolioError, generate_risk_snapshot
from app.services.user_asset_service import (
    add_user_asset,
    delete_user_asset,
    list_user_assets,
    update_user_asset,
)


router = APIRouter(prefix="/api/user-assets", tags=["user-assets"])


def _resolve_user_id(
    user_id: str | None,
    cryptorisk_session: str | None,
) -> str:
    if user_id and getenv("ALLOW_USER_ID_QUERY_OVERRIDE") == "1":
        return user_id
    user = get_user_by_session(cryptorisk_session)
    return user.id if user else DEFAULT_USER_ID


def _handle_asset_error(exc: PortfolioError) -> HTTPException:
    message = str(exc)
    status_code = 404 if "not found" in message else 400
    return HTTPException(status_code=status_code, detail=message)


@router.get("", response_model=list[PortfolioWatchlistItem])
def user_assets(
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    return list_user_assets(_resolve_user_id(user_id, cryptorisk_session))


@router.post("", response_model=UserWatchlist)
def create_user_asset(
    payload: UserWatchlistCreate,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
        item = add_user_asset(payload, resolved_user_id)
        generate_risk_snapshot(item.symbol, resolved_user_id)
        return item
    except PortfolioError as exc:
        raise _handle_asset_error(exc) from exc


@router.patch("/{symbol}", response_model=UserWatchlist)
def patch_user_asset(
    symbol: str,
    payload: UserWatchlistUpdate,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
        item = update_user_asset(symbol, payload, resolved_user_id)
        generate_risk_snapshot(item.symbol, resolved_user_id)
        return item
    except PortfolioError as exc:
        raise _handle_asset_error(exc) from exc


@router.delete("/{symbol}")
def remove_user_asset(
    symbol: str,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        delete_user_asset(symbol, _resolve_user_id(user_id, cryptorisk_session))
        return {"status": "success", "message": "user asset deleted"}
    except PortfolioError as exc:
        raise _handle_asset_error(exc) from exc
