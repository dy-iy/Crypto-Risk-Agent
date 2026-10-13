from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from app.services import market_data_service as market

router = APIRouter(prefix='/api/market', tags=['market-readonly'])


def _symbol(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in market.SYMBOLS:
        raise HTTPException(status_code=422, detail='不支持的交易对')
    return normalized


def _read(function, *args):
    try:
        return function(*args)
    except market.MarketDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc), headers={'Retry-After': '10'}) from exc


@router.get('/symbols')
def symbols():
    return market.symbol_metadata()


@router.get('/tickers')
def tickers():
    return _read(market.tickers)


@router.get('/candles')
def candles(symbol: str = Query(max_length=24), interval: Literal['1m', '5m', '15m', '1h', '4h', '1d'] = '15m',
            limit: int = Query(default=500, ge=2, le=1000), end_time: int | None = Query(default=None, gt=0)):
    return _read(market.candles, _symbol(symbol), interval, limit, end_time)


@router.get('/depth')
def depth(symbol: str = Query(max_length=24)):
    return _read(market.depth, _symbol(symbol))


@router.get('/trades')
def trades(symbol: str = Query(max_length=24)):
    return _read(market.trades, _symbol(symbol))
