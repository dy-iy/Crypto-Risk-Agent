from __future__ import annotations

from fastapi import APIRouter, Body, Cookie, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.api.auth import SESSION_COOKIE_NAME
from app.schemas_auth import AuthUser
from app.services.account_export_service import build_account_export
from app.services.account_lifecycle_service import delete_account_data
from app.services.auth_service import AuthError, get_user_by_session, verify_user_password
from app.services.task_audit_service import list_account_security_events, record_task_event


router = APIRouter(prefix="/api/account", tags=["account"])


class AccountDeleteRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)


def _current_user(token: str | None) -> AuthUser:
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再导出账号数据")
    return user


@router.get("/export")
def export_account_data(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _current_user(cryptorisk_session)
    payload = build_account_export(user, current_session_token=cryptorisk_session)
    record_task_event(
        job_kind="account_export",
        job_id="account-export-redacted",
        event_type="account_export",
        status="success",
        stage="exported",
        message="用户导出账号数据",
        user_id=user.id,
        payload={"summary": payload.get("summary", {})},
    )
    return payload


@router.get("/security-events")
def account_security_events(
    limit: int = Query(default=30, ge=1, le=100),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    user = _current_user(cryptorisk_session)
    return {"items": list_account_security_events(user.id, limit=limit)}


@router.delete("")
def delete_account(
    response: Response,
    payload: AccountDeleteRequest = Body(...),
    confirm: str = Query(default=""),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    if confirm != "delete-my-account":
        raise HTTPException(status_code=400, detail="missing account deletion confirmation")
    user = _current_user(cryptorisk_session)
    try:
        verify_user_password(user.id, payload.current_password)
    except AuthError as exc:
        record_task_event(
            job_kind="account_security",
            job_id="account-delete-confirmation-failed",
            event_type="account_delete_failed",
            status="error",
            stage="password_confirmation_failed",
            message="账号删除密码确认失败",
            user_id=user.id,
            payload={"reason": str(exc)},
        )
        raise HTTPException(status_code=403, detail="当前密码错误，账号数据未删除") from exc
    result = delete_account_data(user)
    record_task_event(
        job_kind="account_delete",
        job_id="account-delete-redacted",
        event_type="account_delete",
        status="success",
        stage="deleted",
        message="用户删除账号数据",
        user_id="",
        payload={"summary": result},
    )
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "success", "message": "账号数据已删除", "summary": result}
