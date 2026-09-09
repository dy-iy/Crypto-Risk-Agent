from __future__ import annotations

from app.schemas_auth import AuthUser
from app.services.analysis_report_service import delete_analysis_reports_for_user
from app.services.auth_service import delete_user_account
from app.services.daily_report_subscription_service import delete_daily_report_subscription
from app.services.daily_report_store import delete_daily_reports_for_user
from app.services.feishu_binding_service import delete_feishu_binding
from app.services.portfolio_watchlist_store import delete_watchlist_records_for_user
from app.services.sim_engine import sim_engine
from app.services.task_audit_service import delete_task_events_for_user


def delete_account_data(user: AuthUser) -> dict[str, int]:
    from app.attackpilot.lifecycle import delete_user_tasks
    attackpilot_deleted = delete_user_tasks(user.id)
    analysis_reports_deleted = delete_analysis_reports_for_user(user.id)
    portfolio_watchlist_deleted = delete_watchlist_records_for_user(user.id)
    daily_reports_deleted = delete_daily_reports_for_user(user.id)
    daily_report_subscriptions_deleted = delete_daily_report_subscription(user.id)
    feishu_bindings_deleted = delete_feishu_binding(user.id)
    sim_accounts_deleted = sim_engine.delete_account(user.id)
    audit_events_deleted = delete_task_events_for_user(user.id)
    auth_deleted = delete_user_account(user.id)
    return {
        "attackpilot_tasks_deleted": attackpilot_deleted,
        "analysis_reports_deleted": analysis_reports_deleted,
        "portfolio_watchlist_deleted": portfolio_watchlist_deleted,
        "daily_reports_deleted": daily_reports_deleted,
        "daily_report_subscriptions_deleted": daily_report_subscriptions_deleted,
        "feishu_bindings_deleted": feishu_bindings_deleted,
        "sim_accounts_deleted": sim_accounts_deleted,
        "audit_events_deleted": audit_events_deleted,
        "favorites_deleted": auth_deleted["favorites"],
        "sessions_deleted": auth_deleted["sessions"],
        "users_deleted": auth_deleted["users"],
    }
