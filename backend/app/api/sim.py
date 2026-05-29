from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.sim_engine import SimError, sim_engine


router = APIRouter(prefix="/api/sim", tags=["simulator"])


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


@router.get("/symbols")
def sim_symbols() -> dict[str, Any]:
    return {"status": "success", "items": sim_engine.symbols()}


@router.post("/reset")
def sim_reset() -> dict[str, Any]:
    return {"status": "success", "data": sim_engine.reset()}


@router.get("/state")
def sim_state() -> dict[str, Any]:
    return {"status": "success", "data": sim_engine.state()}


@router.post("/next")
def sim_next() -> dict[str, Any]:
    return {"status": "success", "data": sim_engine.next()}


@router.post("/jump")
def sim_jump(request: JumpRequest) -> dict[str, Any]:
    try:
        return {"status": "success", "data": sim_engine.jump(request.index, request.target_time)}
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.post("/buy")
def sim_buy(request: BuyRequest) -> dict[str, Any]:
    try:
        return {"status": "success", "data": sim_engine.buy(request.symbol, request.amount_usdt)}
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.post("/sell")
def sim_sell(request: SellRequest) -> dict[str, Any]:
    try:
        return {
            "status": "success",
            "data": sim_engine.sell(request.symbol, request.quantity, request.amount),
        }
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.get("/candles")
def sim_candles(symbol: str) -> dict[str, Any]:
    try:
        return {"status": "success", "symbol": symbol.upper(), "items": sim_engine.candles(symbol)}
    except SimError as exc:
        raise _handle_sim_error(exc) from exc


@router.get("/events")
def sim_events(symbol: str) -> dict[str, Any]:
    try:
        return {"status": "success", "symbol": symbol.upper(), "items": sim_engine.events(symbol)}
    except SimError as exc:
        raise _handle_sim_error(exc) from exc
