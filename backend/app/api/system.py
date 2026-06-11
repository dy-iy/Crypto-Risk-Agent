from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Cookie, HTTPException, Query, Response, status

from app.api.auth import SESSION_COOKIE_NAME
from app.schemas_auth import AuthUser
from app.services.auth_service import get_user_by_session, prune_expired_sessions
from app.services.product_readiness_service import get_product_readiness
from app.services.rate_limit_service import rate_limit_status
from app.services.sim_engine import DEFAULT_GUEST_RETENTION_DAYS, sim_engine
from app.services.storage_inventory_service import (
    build_backup_manifest,
    build_storage_inventory,
    prune_invalid_json_backups,
)
from app.services.task_audit_service import (
    list_task_events,
    prune_task_audit_events,
    record_task_event,
    task_audit_metrics,
)


router = APIRouter(prefix="/api/system", tags=["system"])


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip() == "1"


def _require_observability_access(token: str | None) -> AuthUser | None:
    if _env_enabled("ALLOW_PUBLIC_SYSTEM_OBSERVABILITY"):
        return None
    return _require_system_admin_access(token)


def _require_system_admin_access(token: str | None) -> AuthUser:
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再查看系统运行状态")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限查看系统运行状态")
    return user


def _redact_public_audit_summary(summary: dict[str, Any]) -> dict[str, Any]:
    redacted = {**summary}
    by_kind = []
    for item in summary.get("by_kind", []):
        if not isinstance(item, dict):
            continue
        by_kind.append({**item, "latest_event": None})
    redacted["by_kind"] = by_kind
    return redacted


def _record_system_admin_event(
    *,
    admin: AuthUser,
    event_type: str,
    stage: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    record_task_event(
        job_kind="system_admin",
        job_id=f"system-admin-{uuid4().hex}",
        event_type=event_type,
        status="success",
        stage=stage,
        message=message,
        user_id=admin.id,
        payload={
            "admin_user_id": admin.id,
            "admin_username": admin.username,
            **(payload or {}),
        },
    )


def _prune_update_jobs(retention_days: int, max_jobs: int) -> dict[str, int]:
    from app.api.risk_ranking import prune_update_jobs

    return prune_update_jobs(retention_days=retention_days, max_jobs=max_jobs)


def _prune_portfolio_refresh_jobs(retention_days: int, max_jobs: int) -> dict[str, int]:
    from app.api.portfolio import prune_portfolio_refresh_jobs

    return prune_portfolio_refresh_jobs(retention_days=retention_days, max_jobs=max_jobs)


@router.get("/readiness")
def system_readiness(response: Response) -> dict[str, object]:
    readiness = get_product_readiness()
    if readiness.get("status") == "not_ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness


@router.get("/version")
def system_version() -> dict[str, object]:
    readiness = get_product_readiness()
    return {
        "service": readiness["service"],
        "version": readiness["version"],
        "started_at": readiness["started_at"],
        "uptime_seconds": readiness["uptime_seconds"],
    }


@router.get("/task-events")
def system_task_events(
    job_kind: str | None = Query(default=None, max_length=64),
    job_id: str | None = Query(default=None, max_length=128),
    user_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_system_admin_access(cryptorisk_session)
    return {
        "items": list_task_events(
            job_kind=job_kind,
            job_id=job_id,
            user_id=user_id,
            limit=limit,
        )
    }


@router.get("/audit-summary")
def system_audit_summary(
    window_hours: int = Query(default=24, ge=1, le=24 * 30),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    access = _require_observability_access(cryptorisk_session)
    metrics = task_audit_metrics(window_hours=window_hours)
    if access is None:
        return _redact_public_audit_summary(metrics)
    return metrics


@router.post("/task-events/prune")
def system_prune_task_events(
    retention_days: int | None = Query(default=None, ge=1, le=3650),
    max_events: int | None = Query(default=None, ge=1, le=2_000_000),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    admin = _require_system_admin_access(cryptorisk_session)
    result = prune_task_audit_events(retention_days=retention_days, max_events=max_events)
    _record_system_admin_event(
        admin=admin,
        event_type="task_events_prune",
        stage="task_events_pruned",
        message="管理员清理任务审计账本",
        payload={
            **result,
            "retention_days": retention_days,
            "max_events": max_events,
        },
    )
    return {"status": "success", **result}


@router.post("/sim-accounts/prune")
def system_prune_guest_sim_accounts(
    retention_days: int = Query(default=DEFAULT_GUEST_RETENTION_DAYS, ge=1, le=3650),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    admin = _require_system_admin_access(cryptorisk_session)
    result = sim_engine.prune_guest_accounts(retention_days=retention_days)
    _record_system_admin_event(
        admin=admin,
        event_type="guest_sim_accounts_prune",
        stage="guest_sim_accounts_pruned",
        message="管理员清理过期游客模拟账户",
        payload=result,
    )
    return {"status": "success", **result}


@router.post("/auth-sessions/prune")
def system_prune_expired_auth_sessions(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    admin = _require_system_admin_access(cryptorisk_session)
    result = prune_expired_sessions()
    _record_system_admin_event(
        admin=admin,
        event_type="auth_sessions_prune",
        stage="auth_sessions_pruned",
        message="管理员清理过期登录会话",
        payload=result,
    )
    return {"status": "success", **result}


@router.post("/runtime-jobs/prune")
def system_prune_runtime_jobs(
    retention_days: int = Query(default=14, ge=1, le=3650),
    max_jobs: int = Query(default=100, ge=1, le=100_000),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    admin = _require_system_admin_access(cryptorisk_session)
    news_update = _prune_update_jobs(retention_days=retention_days, max_jobs=max_jobs)
    portfolio_refresh = _prune_portfolio_refresh_jobs(retention_days=retention_days, max_jobs=max_jobs)
    result = {
        "news_update": news_update,
        "portfolio_refresh": portfolio_refresh,
        "retention_days": retention_days,
        "max_jobs": max_jobs,
    }
    _record_system_admin_event(
        admin=admin,
        event_type="runtime_jobs_prune",
        stage="runtime_jobs_pruned",
        message="管理员清理运行态任务状态",
        payload=result,
    )
    return {"status": "success", **result}


@router.post("/invalid-json-backups/prune")
def system_prune_invalid_json_backups(
    retention_days: int = Query(default=30, ge=1, le=3650),
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    admin = _require_system_admin_access(cryptorisk_session)
    result = prune_invalid_json_backups(retention_days=retention_days)
    _record_system_admin_event(
        admin=admin,
        event_type="invalid_json_backups_prune",
        stage="invalid_json_backups_pruned",
        message="管理员清理损坏 JSON 隔离备份",
        payload=result,
    )
    return {"status": "success", **result}


@router.get("/rate-limits")
def system_rate_limits(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_observability_access(cryptorisk_session)
    return rate_limit_status()


@router.get("/storage-inventory")
def system_storage_inventory(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_system_admin_access(cryptorisk_session)
    return build_storage_inventory()


@router.get("/backup-manifest")
def system_backup_manifest(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict[str, object]:
    _require_system_admin_access(cryptorisk_session)
    return build_backup_manifest()
