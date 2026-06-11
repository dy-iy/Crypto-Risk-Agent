from __future__ import annotations

from os import getenv
from pathlib import Path
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock, Thread

from fastapi import APIRouter, Cookie, HTTPException, Query

from app.api.auth import SESSION_COOKIE_NAME
from app.schemas_portfolio import (
    CoinRiskSnapshot,
    MarketCandle,
    PortfolioRefreshJob,
    PortfolioImpactResponse,
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
from app.services.portfolio_impact_service import get_portfolio_impact_for_user
from app.services.auth_service import get_user_by_session
from app.services.runtime_json_store import load_runtime_json_or_quarantine, write_runtime_json_atomic
from app.services.task_audit_service import record_task_event


router = APIRouter(prefix="/api/portfolio", tags=["portfolio-risk-radar"])
PORTFOLIO_REFRESH_JOBS_PATH = Path(__file__).resolve().parents[1] / "data" / "portfolio_refresh_jobs.json"
_refresh_jobs: dict[str, PortfolioRefreshJob] = {}
_refresh_lock = Lock()
_refresh_jobs_lock = Lock()
_latest_job_by_user: dict[str, str] = {}


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_job_time(value: object) -> datetime:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.min


def _load_refresh_jobs() -> None:
    raw = load_runtime_json_or_quarantine(PORTFOLIO_REFRESH_JOBS_PATH)
    if not isinstance(raw, dict):
        return
    for job_id, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        try:
            job = PortfolioRefreshJob.model_validate(payload)
        except Exception:
            continue
        _refresh_jobs[str(job_id)] = job
        _latest_job_by_user[job.user_id] = job.job_id


def _persist_refresh_jobs() -> None:
    write_runtime_json_atomic(
        PORTFOLIO_REFRESH_JOBS_PATH,
        {job_id: job.model_dump(mode="json") for job_id, job in _refresh_jobs.items()},
    )


_load_refresh_jobs()


def _store_refresh_job(job: PortfolioRefreshJob) -> PortfolioRefreshJob:
    with _refresh_jobs_lock:
        job.updated_at = _now_text()
        _refresh_jobs[job.job_id] = job
        _latest_job_by_user[job.user_id] = job.job_id
        _persist_refresh_jobs()
    record_task_event(
        job_kind="portfolio_refresh",
        job_id=job.job_id,
        event_type="state_update",
        status=job.status,
        stage=job.stage,
        message=job.message,
        user_id=job.user_id,
        payload={"error": job.error, "has_result": job.result is not None},
    )
    return job


def _active_refresh_job(user_id: str) -> PortfolioRefreshJob | None:
    with _refresh_jobs_lock:
        job_id = _latest_job_by_user.get(user_id)
        if not job_id:
            return None
        job = _refresh_jobs.get(job_id)
    if job and job.status in {"queued", "running"}:
        return job
    return None


def _rebuild_latest_refresh_jobs_unlocked() -> None:
    _latest_job_by_user.clear()
    for job in sorted(_refresh_jobs.values(), key=lambda item: _parse_job_time(item.updated_at)):
        _latest_job_by_user[job.user_id] = job.job_id


def prune_portfolio_refresh_jobs(retention_days: int = 14, max_jobs: int = 100) -> dict[str, int]:
    safe_days = max(1, min(3650, int(retention_days or 14)))
    safe_max_jobs = max(1, min(100_000, int(max_jobs or 100)))
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=safe_days)
    active_statuses = {"queued", "running"}
    deleted_by_age = 0
    deleted_by_count = 0

    with _refresh_jobs_lock:
        inactive_ids = [
            job_id
            for job_id, job in _refresh_jobs.items()
            if job.status not in active_statuses
        ]
        for job_id in inactive_ids:
            job = _refresh_jobs.get(job_id)
            if not job:
                continue
            updated_at = _parse_job_time(job.finished_at or job.updated_at)
            if updated_at < cutoff:
                _refresh_jobs.pop(job_id, None)
                deleted_by_age += 1

        overflow = max(0, len(_refresh_jobs) - safe_max_jobs)
        if overflow:
            removable = [
                (job_id, _parse_job_time(job.finished_at or job.updated_at))
                for job_id, job in _refresh_jobs.items()
                if job.status not in active_statuses
            ]
            for job_id, _updated_at in sorted(removable, key=lambda item: item[1])[:overflow]:
                if _refresh_jobs.pop(job_id, None) is not None:
                    deleted_by_count += 1

        _rebuild_latest_refresh_jobs_unlocked()
        remaining = len(_refresh_jobs)
        _persist_refresh_jobs()

    return {
        "deleted_by_age": deleted_by_age,
        "deleted_by_count": deleted_by_count,
        "remaining_jobs": remaining,
        "retention_days": safe_days,
        "max_jobs": safe_max_jobs,
    }


def _run_refresh_job(job_id: str, user_id: str) -> None:
    with _refresh_lock:
        with _refresh_jobs_lock:
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


def _resolve_user_id(
    user_id: str | None,
    cryptorisk_session: str | None,
) -> str:
    if user_id and getenv("ALLOW_USER_ID_QUERY_OVERRIDE") == "1":
        return user_id
    user = get_user_by_session(cryptorisk_session)
    return user.id if user else DEFAULT_USER_ID


@router.get("/watchlist", response_model=list[PortfolioWatchlistItem])
def portfolio_watchlist(
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    return list_watchlist(_resolve_user_id(user_id, cryptorisk_session))


@router.post("/watchlist", response_model=UserWatchlist)
def create_portfolio_watchlist_item(
    payload: UserWatchlistCreate,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
        item = add_watchlist_item(payload, resolved_user_id)
        generate_risk_snapshot(item.symbol, resolved_user_id)
        return item
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.patch("/watchlist/{symbol}", response_model=UserWatchlist)
def patch_portfolio_watchlist_item(
    symbol: str,
    payload: UserWatchlistUpdate,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
        item = update_watchlist_item(symbol, payload, resolved_user_id)
        generate_risk_snapshot(item.symbol, resolved_user_id)
        return item
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.delete("/watchlist/{symbol}")
def remove_portfolio_watchlist_item(
    symbol: str,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        delete_watchlist_item(symbol, _resolve_user_id(user_id, cryptorisk_session))
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
def portfolio_symbol_risk(
    symbol: str,
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        return get_risk_snapshot(symbol, _resolve_user_id(user_id, cryptorisk_session))
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.get("/impact", response_model=PortfolioImpactResponse)
def portfolio_impact(
    user_id: str | None = Query(default=None),
    window_days: int = Query(default=30, ge=1, le=365),
    top_n: int = Query(default=10, ge=1, le=50),
    per_asset_limit: int = Query(default=200, ge=10, le=500),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    return get_portfolio_impact_for_user(
        user_id=_resolve_user_id(user_id, cryptorisk_session),
        window_days=window_days,
        top_n=top_n,
        per_asset_limit=per_asset_limit,
    )


@router.post("/refresh", response_model=PortfolioRefreshResponse)
def refresh_portfolio_risk(
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    try:
        return refresh_portfolio(_resolve_user_id(user_id, cryptorisk_session))
    except PortfolioError as exc:
        raise _handle_portfolio_error(exc) from exc


@router.post("/refresh/jobs", response_model=PortfolioRefreshJob)
def start_portfolio_refresh_job(
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
    existing = _active_refresh_job(resolved_user_id)
    if existing:
        return existing
    job = PortfolioRefreshJob(
        job_id=f"portfolio-{uuid.uuid4().hex}",
        user_id=resolved_user_id,
        status="queued",
        stage="queued",
        message="刷新任务已创建",
        started_at=_now_text(),
        updated_at=_now_text(),
    )
    _store_refresh_job(job)
    record_task_event(
        job_kind="portfolio_refresh",
        job_id=job.job_id,
        event_type="created",
        status=job.status,
        stage=job.stage,
        message=job.message,
        user_id=job.user_id,
    )
    Thread(target=_run_refresh_job, args=(job.job_id, resolved_user_id), daemon=True).start()
    return job


@router.get("/refresh/jobs/current", response_model=PortfolioRefreshJob)
def current_portfolio_refresh_job(
    user_id: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    resolved_user_id = _resolve_user_id(user_id, cryptorisk_session)
    with _refresh_jobs_lock:
        job_id = _latest_job_by_user.get(resolved_user_id)
        job = _refresh_jobs.get(job_id or "")
    if not job:
        raise HTTPException(status_code=404, detail="No portfolio refresh job")
    return job


@router.get("/refresh/jobs/{job_id}", response_model=PortfolioRefreshJob)
def get_portfolio_refresh_job(job_id: str):
    with _refresh_jobs_lock:
        job = _refresh_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Portfolio refresh job not found")
    return job
