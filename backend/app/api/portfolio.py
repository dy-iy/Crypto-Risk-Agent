from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock, Thread

from fastapi import APIRouter, HTTPException, Query

from app.schemas_portfolio import (
    CoinRiskSnapshot,
    MarketCandle,
    PortfolioRefreshJob,
    PortfolioNewsItem,
    PortfolioRefreshResponse,
    PortfolioWatchlistItem,
    UserWatchlist,
    UserWatchlistCreate,
    UserWatchlistUpdate,
)
from app.services.portfolio_service import (
    DEFAULT_USER_ID,
    PortfolioError,
    add_watchlist_item,
    delete_watchlist_item,
    generate_risk_snapshot,
    get_market_candles,
    get_related_news,
    get_risk_snapshot,
    list_watchlist,
    refresh_portfolio,
    update_watchlist_item,
)


router = APIRouter(prefix="/api/portfolio", tags=["portfolio-risk-radar"])
_refresh_jobs: dict[str, PortfolioRefreshJob] = {}
_refresh_lock = Lock()
_latest_job_by_user: dict[str, str] = {}


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _store_refresh_job(job: PortfolioRefreshJob) -> PortfolioRefreshJob:
    job.updated_at = _now_text()
    _refresh_jobs[job.job_id] = job
    _latest_job_by_user[job.user_id] = job.job_id
    return job


def _active_refresh_job(user_id: str) -> PortfolioRefreshJob | None:
    job_id = _latest_job_by_user.get(user_id)
    if not job_id:
        return None
    job = _refresh_jobs.get(job_id)
    if job and job.status in {"queued", "running"}:
        return job
    return None


def _run_refresh_job(job_id: str, user_id: str) -> None:
    with _refresh_lock:
        job = _refresh_jobs.get(job_id)
        if not job:
            return
        _store_refresh_job(job.model_copy(update={
            "status": "running",
            "stage": "news",
            "message": "正在同步新闻、行情与币种风险快照",
            "started_at": job.started_at or _now_text(),
        }))
        try:
            result = refresh_portfolio(user_id)
            _store_refresh_job(job.model_copy(update={
                "status": "success",
                "stage": "done",
                "message": result.message,
                "result": result,
                "finished_at": _now_text(),
            }))
        except Exception as exc:
            _store_refresh_job(job.model_copy(update={
                "status": "error",
                "stage": "error",
                "message": f"刷新失败：{exc}",
                "error": str(exc),
                "finished_at": _now_text(),
            }))


def _handle_portfolio_error(exc: PortfolioError) -> HTTPException:
    message = str(exc)
    status_code = 404 if "not found" in message else 400
    return HTTPException(status_code=status_code, detail=message)


@router.get("/watchlist", response_model=list[PortfolioWatchlistItem])
def portfolio_watchlist(user_id: str = Query(default=DEFAULT_USER_ID)):
    return list_watchlist(user_id)


@router.post("/watchlist", response_model=UserWatchlist)
def create_portfolio_watchlist_item(payload: UserWatchlistCreate, user_id: str = Query(default=DEFAULT_USER_ID)):
    try:
        item = add_watchlist_item(payload, user_id)
        generate_risk_snapshot(item.symbol, user_id)
        return item
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.patch("/watchlist/{symbol}", response_model=UserWatchlist)
def patch_portfolio_watchlist_item(symbol: str, payload: UserWatchlistUpdate, user_id: str = Query(default=DEFAULT_USER_ID)):
    try:
        item = update_watchlist_item(symbol, payload, user_id)
        generate_risk_snapshot(item.symbol, user_id)
        return item
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.delete("/watchlist/{symbol}")
def remove_portfolio_watchlist_item(symbol: str, user_id: str = Query(default=DEFAULT_USER_ID)):
    try:
        delete_watchlist_item(symbol, user_id)
        return {"status": "success", "message": "watchlist item deleted"}
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/market/{symbol}", response_model=list[MarketCandle])
def portfolio_market_candles(
    symbol: str,
    interval: str = Query(default="15m"),
    limit: int = Query(default=200, ge=20, le=1000),
):
    try:
        return get_market_candles(symbol, interval, limit)
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/news/{symbol}", response_model=list[PortfolioNewsItem])
def portfolio_symbol_news(symbol: str, limit: int = Query(default=20, ge=1, le=100)):
    try:
        return get_related_news(symbol, limit)
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/risk/{symbol}", response_model=CoinRiskSnapshot)
def portfolio_symbol_risk(symbol: str, user_id: str = Query(default=DEFAULT_USER_ID)):
    try:
        return get_risk_snapshot(symbol, user_id)
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.post("/refresh", response_model=PortfolioRefreshResponse)
def refresh_portfolio_risk(user_id: str = Query(default=DEFAULT_USER_ID)):
    try:
        return refresh_portfolio(user_id)
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.post("/refresh/jobs", response_model=PortfolioRefreshJob)
def start_portfolio_refresh_job(user_id: str = Query(default=DEFAULT_USER_ID)):
    existing = _active_refresh_job(user_id)
    if existing:
        return existing
    job = PortfolioRefreshJob(
        job_id=f"portfolio-{uuid.uuid4().hex}",
        user_id=user_id,
        status="queued",
        stage="queued",
        message="刷新任务已创建",
        started_at=_now_text(),
        updated_at=_now_text(),
    )
    _store_refresh_job(job)
    Thread(target=_run_refresh_job, args=(job.job_id, user_id), daemon=True).start()
    return job


@router.get("/refresh/jobs/current", response_model=PortfolioRefreshJob)
def current_portfolio_refresh_job(user_id: str = Query(default=DEFAULT_USER_ID)):
    job_id = _latest_job_by_user.get(user_id)
    if not job_id or job_id not in _refresh_jobs:
        raise HTTPException(status_code=404, detail="No portfolio refresh job")
    return _refresh_jobs[job_id]


@router.get("/refresh/jobs/{job_id}", response_model=PortfolioRefreshJob)
def get_portfolio_refresh_job(job_id: str):
    job = _refresh_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Portfolio refresh job not found")
    return job
