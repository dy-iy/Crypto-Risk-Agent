from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query
from pydantic import BaseModel
from threading import Lock

from app.agents.daily_report_agent import run_daily_report_agent
from app.api.auth import SESSION_COOKIE_NAME
from app.services.auth_service import get_user_by_session
from app.services.daily_report_store import (
    get_latest_daily_report,
    list_daily_reports,
    save_daily_report,
)
from app.services.daily_report_subscription_service import (
    get_daily_report_subscription,
    set_daily_report_subscription,
)
from app.services.portfolio_service import DEFAULT_USER_ID
from app.services.follow_service import follow_snapshot, NoFollowsError


_generation_lock = Lock()
_generating_users: set[str] = set()

router = APIRouter(prefix="/api/daily-report", tags=["personal-daily-report"])


class DailyReportGenerateRequest(BaseModel):
    date: str | None = "24h"


class DailyReportSubscriptionRequest(BaseModel):
    enabled: bool


def _normalize_date(date: str | None) -> str:
    return date if date in {"24h", "7d"} else "24h"


def _resolve_user(
    cryptorisk_session: str | None,
    *, write: bool = False,
) -> tuple[str, str]:
    user = get_user_by_session(cryptorisk_session)
    if write and not user:
        raise HTTPException(status_code=401, detail="请先登录后再生成或订阅个人日报")
    user_id = user.id if user else DEFAULT_USER_ID
    display_name = user.display_name if user else "Demo 用户"
    return user_id, display_name


@router.get("")
def personal_daily_report(
    date: str | None = Query(default="24h"),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user_id, _ = _resolve_user(cryptorisk_session)
    return get_latest_daily_report(user_id, _normalize_date(date))


@router.get("/history")
def personal_daily_report_history(
    date: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user_id, _ = _resolve_user(cryptorisk_session)
    return list_daily_reports(user_id, _normalize_date(date) if date else None)


@router.get("/subscription")
def personal_daily_report_subscription(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user_id, _ = _resolve_user(cryptorisk_session)
    return get_daily_report_subscription(user_id)


@router.patch("/subscription")
def update_personal_daily_report_subscription(
    payload: DailyReportSubscriptionRequest,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user_id, _ = _resolve_user(cryptorisk_session, write=True)
    return set_daily_report_subscription(user_id, payload.enabled)


@router.post("/generate")
def generate_personal_daily_report(
    payload: DailyReportGenerateRequest | None = None,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    normalized_date = _normalize_date(payload.date if payload else "24h")
    user_id, display_name = _resolve_user(cryptorisk_session, write=True)
    if not follow_snapshot(user_id)["items"]:
        raise HTTPException(409, "请先添加关注币种，再生成关注日报")
    with _generation_lock:
        if user_id in _generating_users:
            raise HTTPException(status_code=409, detail="日报正在生成，请等待当前任务完成")
        _generating_users.add(user_id)
    try:
        report = run_daily_report_agent(
            normalized_date,
            user_id=user_id,
            user_display_name=display_name,
        )
        return save_daily_report(user_id, report)
    except NoFollowsError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        with _generation_lock:
            _generating_users.discard(user_id)
