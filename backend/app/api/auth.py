from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from app.schemas_auth import AuthCredentials, AuthResponse, AuthSessionItem, AuthUser, PasswordChangeRequest
from app.services.account_security_event_service import record_account_security_event, security_identifier_hash
from app.services.auth_service import (
    SESSION_TTL_SECONDS,
    AuthError,
    change_user_password,
    create_session,
    create_user,
    delete_session,
    get_user_by_session,
    list_user_sessions,
    revoke_other_sessions,
    verify_user,
)
from app.services.request_security_service import request_client_identity, request_security_context, request_uses_https


router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_COOKIE_NAME = "cryptorisk_session"


def _is_secure_request(request: Request) -> bool:
    return request_uses_https(request.url.scheme, request.headers)


def _set_session_cookie(request: Request, response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=datetime.now(timezone.utc) + timedelta(seconds=max_age),
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def _auth_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _request_client_ip(request: Request) -> str:
    client_host = request.client.host if request.client else ""
    return request_client_identity(client_host, request.headers)


def _request_user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _request_security_payload(request: Request) -> dict[str, str]:
    return request_security_context(_request_client_ip(request), _request_user_agent(request))


@router.post("/register", response_model=AuthResponse)
def register(payload: AuthCredentials, request: Request, response: Response) -> AuthResponse:
    try:
        user = create_user(payload.username, payload.password)
        token, _expires_at = create_session(
            user.id,
            client_ip=_request_client_ip(request),
            user_agent=_request_user_agent(request),
        )
        _set_session_cookie(request, response, token, SESSION_TTL_SECONDS)
        record_account_security_event(
            user_id=user.id,
            event_type="register",
            stage="registered",
            message="账号注册并创建登录会话",
            payload=_request_security_payload(request),
        )
        return AuthResponse(message="注册成功", user=user)
    except AuthError as exc:
        record_account_security_event(
            user_id="",
            event_type="register_failed",
            stage="registration_failed",
            message="账号注册失败",
            status="error",
            payload={
                **_request_security_payload(request),
                "username_hash": security_identifier_hash(payload.username),
                "reason": str(exc),
            },
        )
        raise _auth_error(exc) from exc


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthCredentials, request: Request, response: Response) -> AuthResponse:
    try:
        user = verify_user(payload.username, payload.password)
        token, _expires_at = create_session(
            user.id,
            client_ip=_request_client_ip(request),
            user_agent=_request_user_agent(request),
        )
        _set_session_cookie(request, response, token, SESSION_TTL_SECONDS)
        record_account_security_event(
            user_id=user.id,
            event_type="login",
            stage="logged_in",
            message="账号登录成功",
            payload=_request_security_payload(request),
        )
        return AuthResponse(message="登录成功", user=user)
    except AuthError as exc:
        record_account_security_event(
            user_id="",
            event_type="login_failed",
            stage="login_failed",
            message="账号登录失败",
            status="error",
            payload={
                **_request_security_payload(request),
                "username_hash": security_identifier_hash(payload.username),
                "reason": str(exc),
            },
        )
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/me", response_model=AuthUser | None)
def me(cryptorisk_session: str | None = Cookie(default=None)) -> AuthUser | None:
    return get_user_by_session(cryptorisk_session)


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = get_user_by_session(cryptorisk_session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再修改密码")
    try:
        result = change_user_password(
            user.id,
            payload.current_password,
            payload.new_password,
            keep_session_token=cryptorisk_session,
        )
    except AuthError as exc:
        record_account_security_event(
            user_id=user.id,
            event_type="password_change_failed",
            stage="password_change_failed",
            message="用户修改登录密码失败",
            status="error",
            payload={**_request_security_payload(request), "reason": str(exc)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_account_security_event(
        user_id=user.id,
        event_type="password_change",
        stage="password_changed",
        message="用户修改登录密码",
        payload={**_request_security_payload(request), "sessions_revoked": result.get("sessions_revoked", 0)},
    )
    return {
        "status": "success",
        "message": "密码已更新，其他登录会话已退出。",
        **result,
    }


@router.get("/sessions", response_model=list[AuthSessionItem])
def sessions(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> list[AuthSessionItem]:
    user = get_user_by_session(cryptorisk_session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再查看登录会话")
    return list_user_sessions(user.id, current_token=cryptorisk_session)


@router.post("/sessions/revoke-others")
def revoke_sessions(
    request: Request,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = get_user_by_session(cryptorisk_session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再管理登录会话")
    revoked = revoke_other_sessions(user.id, cryptorisk_session)
    record_account_security_event(
        user_id=user.id,
        event_type="sessions_revoke_others",
        stage="sessions_revoked",
        message="用户撤销其他登录会话",
        payload={**_request_security_payload(request), "sessions_revoked": revoked},
    )
    return {
        "status": "success",
        "message": "其他登录会话已退出。",
        "sessions_revoked": revoked,
    }


@router.post("/logout")
def logout(request: Request, response: Response, cryptorisk_session: str | None = Cookie(default=None)):
    user = get_user_by_session(cryptorisk_session)
    delete_session(cryptorisk_session)
    if user:
        record_account_security_event(
            user_id=user.id,
            event_type="logout",
            stage="logged_out",
            message="账号退出登录",
            payload=_request_security_payload(request),
        )
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "success", "message": "已退出登录"}
