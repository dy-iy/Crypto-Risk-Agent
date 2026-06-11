from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException

from app.api.auth import SESSION_COOKIE_NAME
from app.schemas_auth import AuthUser
from app.schemas_reports import (
    AnalysisReportDispositionUpdate,
    AnalysisReportItem,
    AnalysisReportPayload,
)
from app.services.analysis_report_service import (
    AnalysisReportError,
    AnalysisReportTooLargeError,
    delete_analysis_report,
    list_analysis_reports,
    save_analysis_report,
    update_analysis_report_disposition,
)
from app.services.auth_service import get_user_by_session


router = APIRouter(prefix="/api/analysis-reports", tags=["analysis-reports"])


def _current_user(token: str | None) -> AuthUser:
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录后再同步分析报告")
    return user


@router.get("", response_model=list[AnalysisReportItem])
def analysis_reports(
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> list[AnalysisReportItem]:
    user = _current_user(cryptorisk_session)
    return list_analysis_reports(user.id)


@router.put("/{report_id}", response_model=AnalysisReportItem)
def upsert_analysis_report(
    report_id: str,
    payload: AnalysisReportPayload,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AnalysisReportItem:
    user = _current_user(cryptorisk_session)
    if payload.id != report_id:
        raise HTTPException(status_code=400, detail="report id mismatch")
    try:
        return save_analysis_report(user.id, payload)
    except AnalysisReportTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.patch("/{report_id}/disposition", response_model=AnalysisReportItem)
def patch_analysis_report_disposition(
    report_id: str,
    payload: AnalysisReportDispositionUpdate,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AnalysisReportItem:
    user = _current_user(cryptorisk_session)
    try:
        return update_analysis_report_disposition(user.id, report_id, payload)
    except AnalysisReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{report_id}")
def remove_analysis_report(
    report_id: str,
    cryptorisk_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
):
    user = _current_user(cryptorisk_session)
    try:
        delete_analysis_report(user.id, report_id)
    except AnalysisReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success", "message": "分析报告已删除"}
