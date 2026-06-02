from __future__ import annotations

from app.api.portfolio import _resolve_user_id as resolve_portfolio_user_id
from app.api.user_assets import _resolve_user_id as resolve_asset_user_id
from app.services.portfolio_service import DEFAULT_USER_ID


def test_user_id_query_override_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_USER_ID_QUERY_OVERRIDE", raising=False)

    assert resolve_asset_user_id("attacker-user", None) == DEFAULT_USER_ID
    assert resolve_portfolio_user_id("attacker-user", None) == DEFAULT_USER_ID


def test_user_id_query_override_requires_explicit_env(monkeypatch):
    monkeypatch.setenv("ALLOW_USER_ID_QUERY_OVERRIDE", "1")

    assert resolve_asset_user_id("debug-user", None) == "debug-user"
    assert resolve_portfolio_user_id("debug-user", None) == "debug-user"
