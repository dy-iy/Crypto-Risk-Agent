import re
from typing import Any

from fastapi import APIRouter, Cookie, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import SESSION_COOKIE_NAME
from app.services.auth_service import get_user_by_session
from app.services.sim_engine import DEFAULT_SIM_ACCOUNT_ID, SimError, sim_engine


router = APIRouter(prefix="/api/sim", tags=["simulator"])
GUEST_SIM_ACCOUNT_PREFIX = "guest"


class BuyRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    amount_usdt: float = Field(..., gt=0)


class SellRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    quantity: float | str | None = None
    amount: str | None = None


class JumpRequest(BaseModel):
    index: int | None = Field(default=None, ge=0)
    target_time: str | None = None


def _handle_sim_error(exc: SimError) -> HTTPException:
    message = str(exc)
    status_code = 400
    if message.startswith("Unsupported symbol"):
        status_code = 404
    return HTTPException(status_code=status_code, detail=message)


def _safe_account_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())[:80]
    return normalized.strip("._-")


def _resolve_account_id(
    cryptorisk_session: str | None,
    sim_client_id: str | None,
) -> str:
    user = get_user_by_session(cryptorisk_session)
    if user:
        return user.id
    client_fragment = _safe_account_fragment(sim_client_id)
    if client_fragment:
        return f"{GUEST_SIM_ACCOUNT_PREFIX}:{client_fragment}"
    return DEFAULT_SIM_ACCOUNT_ID


@router.get("/symbols")
def sim_symbols() -> dict[str, Any]:
    return {"status": "success", "items": sim_engine.symbols()}


@router.post("/reset")
def sim_reset(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    return {"status": "success", "data": sim_engine.reset(account_id)}


@router.get("/state")
def sim_state(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    return {"status": "success", "data": sim_engine.state(account_id)}


@router.post("/next")
def sim_next(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    return {"status": "success", "data": sim_engine.next(account_id)}


@router.post("/jump")
def sim_jump(
    request: JumpRequest,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    try:
        return {
            "status": "success",
            "data": sim_engine.jump(
                request.index,
                request.target_time,
                account_id,
            ),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.post("/buy")
def sim_buy(
    request: BuyRequest,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    try:
        return {
            "status": "success",
            "data": sim_engine.buy(
                request.symbol,
                request.amount_usdt,
                account_id,
            ),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.post("/sell")
def sim_sell(
    request: SellRequest,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    try:
        return {
            "status": "success",
            "data": sim_engine.sell(
                request.symbol,
                request.quantity,
                request.amount,
                account_id,
            ),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.get("/candles")
def sim_candles(
    symbol: str,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    try:
        return {
            "status": "success",
            "symbol": symbol.upper(),
            "items": sim_engine.candles(symbol, account_id),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.get("/events")
def sim_events(
    symbol: str,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    sim_client_id: str | None = Header(default=None, alias="X-CryptoRisk-Sim-Client"),
) -> dict[str, Any]:
    account_id = _resolve_account_id(cryptorisk_session, sim_client_id)
    try:
        return {
            "status": "success",
            "symbol": symbol.upper(),
            "items": sim_engine.events(symbol, account_id),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc
