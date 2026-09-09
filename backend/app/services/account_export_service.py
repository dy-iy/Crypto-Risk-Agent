from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas_auth import AuthUser
from app.services.analysis_report_service import list_analysis_reports
from app.services.auth_service import list_favorites, list_user_sessions
from app.services.daily_report_store import list_daily_report_payloads
from app.services.feishu_binding_service import get_public_feishu_binding
from app.services.portfolio_watchlist_store import list_watchlist_records
from app.services.sim_engine import sim_engine
from app.services.task_audit_service import list_account_security_events


def build_account_export(user: AuthUser, current_session_token: str | None = None) -> dict[str, Any]:
    from app.attackpilot.store import export_user
    attackpilot = export_user(user.id)
    analysis_reports = [item.model_dump() for item in list_analysis_reports(user.id)]
    favorites = [item.model_dump() for item in list_favorites(user.id)]
    watchlist = [item.model_dump() for item in list_watchlist_records(user.id)]
    daily_reports = list_daily_report_payloads(user.id)
    feishu_binding = get_public_feishu_binding(user.id)
    sim_account = sim_engine.account_state_snapshot(user.id)
    account_security_events = list_account_security_events(user.id, limit=100)
    auth_sessions = [
        item.model_dump()
        for item in list_user_sessions(user.id, current_token=current_session_token)
    ]
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "created_at": user.created_at,
        },
        "summary": {
            "attackpilot_tasks": len(attackpilot["tasks"]),
            "analysis_reports": len(analysis_reports),
            "favorites": len(favorites),
            "portfolio_watchlist": len(watchlist),
            "daily_reports": len(daily_reports),
            "feishu_binding": 1 if feishu_binding.get("bound") else 0,
            "sim_account": 1 if sim_account else 0,
            "sim_positions": len(sim_account.get("positions", [])) if sim_account else 0,
            "sim_trades": len(sim_account.get("trade_history", [])) if sim_account else 0,
            "account_security_events": len(account_security_events),
            "auth_sessions": len(auth_sessions),
        },
        "analysis_reports": analysis_reports,
        "attackpilot": attackpilot,
        "favorites": favorites,
        "portfolio_watchlist": watchlist,
        "daily_reports": daily_reports,
        "feishu_binding": feishu_binding,
        "sim_account": sim_account,
        "account_security_events": account_security_events,
        "auth_sessions": auth_sessions,
    }
