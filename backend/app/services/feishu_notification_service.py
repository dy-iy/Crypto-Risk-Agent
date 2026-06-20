from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[1]
for env_path in [
    APP_DIR.parents[1] / ".env",
    APP_DIR.parent / ".env",
    APP_DIR / ".env",
]:
    load_dotenv(env_path)

FEISHU_AUTH_BASE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
FEISHU_TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_USER_ACCESS_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v1/access_token"
FEISHU_USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"
FEISHU_SEND_MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
FEISHU_TIMEOUT_SECONDS = 8.0

_tenant_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


class FeishuConfigError(RuntimeError):
    pass


class FeishuApiError(RuntimeError):
    pass


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ["replace", "your-", "app id", "app_id", "app secret", "app_secret"]) or "你的" in value


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def feishu_notify_enabled() -> bool:
    return _env("FEISHU_NOTIFY_ENABLED") == "1"


def public_site_url() -> str:
    return (_env("PUBLIC_SITE_URL") or "https://kassa-wiki.top").rstrip("/")


def _required_config() -> tuple[str, str]:
    app_id = _env("FEISHU_APP_ID")
    app_secret = _env("FEISHU_APP_SECRET")
    if not app_id or not app_secret or _looks_like_placeholder(app_id) or _looks_like_placeholder(app_secret):
        raise FeishuConfigError("missing_feishu_app_config")
    if not app_id.startswith("cli_"):
        raise FeishuConfigError("invalid_feishu_app_id")
    return app_id, app_secret


def _httpx():
    try:
        import httpx  # type: ignore
    except ModuleNotFoundError as exc:
        raise FeishuConfigError("missing_httpx_dependency") from exc
    return httpx


def feishu_oauth_redirect_uri() -> str:
    configured = _env("FEISHU_OAUTH_REDIRECT_URI")
    if configured:
        return configured
    return f"{public_site_url()}/api/feishu/oauth/callback"


def build_feishu_oauth_url(state: str) -> str:
    app_id, _app_secret = _required_config()
    query = urlencode({
        "app_id": app_id,
        "redirect_uri": feishu_oauth_redirect_uri(),
        "state": state,
    })
    return f"{FEISHU_AUTH_BASE_URL}?{query}"


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        response = _httpx().post(url, json=payload, headers=headers, timeout=FEISHU_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        raise FeishuApiError(str(exc)) from exc
    if not isinstance(data, dict):
        raise FeishuApiError("invalid_feishu_response")
    code = data.get("code")
    if code not in (0, None):
        raise FeishuApiError(str(data.get("msg") or data.get("message") or code))
    return data


def get_tenant_access_token() -> str:
    now = time.time()
    cached = str(_tenant_token_cache.get("token") or "")
    if cached and float(_tenant_token_cache.get("expires_at") or 0) > now + 60:
        return cached

    app_id, app_secret = _required_config()
    data = _post_json(
        FEISHU_TENANT_TOKEN_URL,
        {"app_id": app_id, "app_secret": app_secret},
    )
    token = str(data.get("tenant_access_token") or "")
    if not token:
        raise FeishuApiError("missing_tenant_access_token")
    expire = int(data.get("expire") or 7200)
    _tenant_token_cache.update({"token": token, "expires_at": now + max(60, expire)})
    return token


def exchange_code_for_feishu_profile(code: str) -> dict[str, Any]:
    tenant_token = get_tenant_access_token()
    token_data = _post_json(
        FEISHU_USER_ACCESS_TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
        },
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    data = token_data.get("data") if isinstance(token_data.get("data"), dict) else token_data
    user_access_token = str(data.get("access_token") or data.get("user_access_token") or "")
    if not user_access_token:
        raise FeishuApiError("missing_user_access_token")

    try:
        response = _httpx().get(
            FEISHU_USER_INFO_URL,
            headers={"Authorization": f"Bearer {user_access_token}"},
            timeout=FEISHU_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        info_payload = response.json()
    except Exception as exc:
        raise FeishuApiError(str(exc)) from exc
    if not isinstance(info_payload, dict):
        raise FeishuApiError("invalid_feishu_user_info")
    if info_payload.get("code") not in (0, None):
        raise FeishuApiError(str(info_payload.get("msg") or info_payload.get("message") or info_payload.get("code")))
    profile = info_payload.get("data") if isinstance(info_payload.get("data"), dict) else info_payload
    if not profile.get("open_id"):
        raise FeishuApiError("missing_open_id")
    return profile


def _report_url() -> str:
    return f"{public_site_url()}/daily"


def _top_asset_lines(report: dict[str, Any]) -> list[str]:
    assets = report.get("asset_reports") if isinstance(report.get("asset_reports"), list) else []
    lines = []
    for item in assets[:3]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("asset_symbol") or item.get("asset_name") or "资产")
        score = int(item.get("personal_risk_score") or 0)
        level = str(item.get("risk_level") or "")
        summary = str(item.get("summary") or "")[:80]
        lines.append(f"{symbol}: {score} / {level} - {summary}")
    return lines or ["暂无资产分项风险。"]


def build_daily_report_card(report: dict[str, Any]) -> dict[str, Any]:
    score = int(report.get("personal_risk_score") or 0)
    alert_level = str(report.get("alert_level") or "未生成")
    headline = str(report.get("headline") or "资产日报")
    affected_assets = report.get("affected_assets") if isinstance(report.get("affected_assets"), list) else []
    summary = str(report.get("summary") or "今日资产日报已生成，请进入网站查看详情。")[:300]
    top_assets = "\n".join(f"- {line}" for line in _top_asset_lines(report))
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red" if score >= 90 else "orange" if score >= 80 else "blue",
            "title": {
                "tag": "plain_text",
                "content": f"资产日报｜{alert_level}｜个人风险分 {score}",
            },
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{headline}**\n{summary}"}},
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**命中资产**\n{', '.join(map(str, affected_assets[:8])) or '--'}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**红色/高风险事件**\n{int(report.get('personal_red_count') or 0)} / {int(report.get('personal_high_count') or 0)}"}},
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**Top 资产风险**\n{top_assets}"}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看完整日报"},
                        "url": _report_url(),
                        "type": "primary",
                    }
                ],
            },
        ],
    }


def send_daily_report_to_feishu(open_id: str, report: dict[str, Any]) -> dict[str, Any]:
    if not feishu_notify_enabled():
        return {"sent": False, "skipped": True, "reason": "disabled"}
    if not open_id:
        return {"sent": False, "skipped": True, "reason": "missing_open_id"}

    tenant_token = get_tenant_access_token()
    card = build_daily_report_card(report)
    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    data = _post_json(
        f"{FEISHU_SEND_MESSAGE_URL}?receive_id_type=open_id",
        payload,
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    return {
        "sent": True,
        "skipped": False,
        "message_id": str((data.get("data") or {}).get("message_id") if isinstance(data.get("data"), dict) else ""),
    }
