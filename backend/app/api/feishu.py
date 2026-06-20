from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.api.auth import SESSION_COOKIE_NAME
from app.services.auth_service import get_user_by_session
from app.services.feishu_binding_service import (
    consume_feishu_oauth_state,
    create_feishu_oauth_state,
    delete_feishu_binding,
    get_public_feishu_binding,
    upsert_feishu_binding,
)
from app.services.feishu_notification_service import (
    FeishuApiError,
    FeishuConfigError,
    build_feishu_oauth_url,
    exchange_code_for_feishu_profile,
    public_site_url,
)
from app.services.task_audit_service import record_task_event


router = APIRouter(prefix="/api/feishu", tags=["feishu"])


def _current_user(token: str | None):
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再绑定飞书")
    return user


def _daily_redirect(status: str) -> RedirectResponse:
    return RedirectResponse(f"{public_site_url()}/daily?feishu={status}", status_code=302)


@router.get("/oauth/start")
def start_feishu_oauth(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = _current_user(cryptorisk_session)
    try:
        state = create_feishu_oauth_state(user.id)
        return RedirectResponse(build_feishu_oauth_url(state), status_code=302)
    except FeishuConfigError as exc:
        raise HTTPException(status_code=503, detail="飞书应用配置未完成") from exc


@router.get("/oauth/callback")
def feishu_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = get_user_by_session(cryptorisk_session)
    if not user or not code or not state:
        return _daily_redirect("error")
    if not consume_feishu_oauth_state(state, user.id):
        record_task_event(
            job_kind="account_security",
            job_id="feishu-oauth-state-failed",
            event_type="feishu_bind_failed",
            status="error",
            stage="oauth_state_invalid",
            message="飞书 OAuth state 校验失败",
            user_id=user.id,
            payload={"path": request.url.path},
        )
        return _daily_redirect("error")

    try:
        profile = exchange_code_for_feishu_profile(code)
        binding = upsert_feishu_binding(user.id, profile)
    except (FeishuApiError, FeishuConfigError, ValueError) as exc:
        record_task_event(
            job_kind="account_security",
            job_id="feishu-oauth-bind-failed",
            event_type="feishu_bind_failed",
            status="error",
            stage="oauth_exchange_failed",
            message="飞书 OAuth 绑定失败",
            user_id=user.id,
            payload={"reason": str(exc)},
        )
        return _daily_redirect("error")

    record_task_event(
        job_kind="account_security",
        job_id="feishu-oauth-bound",
        event_type="feishu_bound",
        status="success",
        stage="bound",
        message="用户绑定飞书通知账号",
        user_id=user.id,
        payload={"bound": binding.get("bound"), "name": binding.get("name")},
    )
    return _daily_redirect("bound")


@router.get("/binding")
def feishu_binding(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _current_user(cryptorisk_session)
    return get_public_feishu_binding(user.id)


@router.delete("/binding")
def delete_binding(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _current_user(cryptorisk_session)
    deleted = delete_feishu_binding(user.id)
    record_task_event(
        job_kind="account_security",
        job_id="feishu-oauth-unbound",
        event_type="feishu_unbound",
        status="success",
        stage="unbound",
        message="用户解绑飞书通知账号",
        user_id=user.id,
        payload={"deleted": deleted},
    )
    return {"status": "success", "deleted": deleted, **get_public_feishu_binding(user.id)}
