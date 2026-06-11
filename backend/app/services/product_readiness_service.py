from __future__ import annotations

import json
import os
from importlib.util import find_spec
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.llm_config_service import EXPECTED_DEEPSEEK_MODEL, get_deepseek_config
from app.services.request_body_limit_service import (
    DEFAULT_MAX_REQUEST_BODY_BYTES,
    MAX_REQUEST_BODY_BYTES_LIMIT,
    MIN_REQUEST_BODY_BYTES,
)

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
REPO_ROOT = APP_DIR.parents[1]
STARTED_AT = datetime.now(timezone.utc)
MASTERED_NEWS_PATH = DATA_DIR / "mastered_news.csv"
RAW_NEWS_QUEUE_PATH = DATA_DIR / "raw_news.csv"
SCORED_DATA_PATH = DATA_DIR / "scored_news.json"
PORTFOLIO_STATE_PATH = DATA_DIR / "portfolio_state.json"
PORTFOLIO_REFRESH_JOBS_PATH = DATA_DIR / "portfolio_refresh_jobs.json"
UPDATE_JOBS_PATH = DATA_DIR / "update_jobs.json"
SIM_ACCOUNTS_PATH = DATA_DIR / "sim_accounts.json"
PORTFOLIO_DB_PATH = DATA_DIR / "portfolio.sqlite3"
AUTH_DB_PATH = DATA_DIR / "auth.sqlite3"
REPORT_DB_PATH = DATA_DIR / "analysis_reports.sqlite3"
DAILY_REPORTS_DIR = DATA_DIR / "daily_reports"
TASK_AUDIT_DB_PATH = DATA_DIR / "task_audit.sqlite3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip() == "1"


def _request_body_limit_check() -> dict[str, Any]:
    raw = os.getenv("MAX_REQUEST_BODY_BYTES", "").strip()
    configured = raw or str(DEFAULT_MAX_REQUEST_BODY_BYTES)
    valid = True
    try:
        parsed = int(raw) if raw else DEFAULT_MAX_REQUEST_BODY_BYTES
    except ValueError:
        parsed = DEFAULT_MAX_REQUEST_BODY_BYTES
        valid = False
    effective = max(MIN_REQUEST_BODY_BYTES, min(MAX_REQUEST_BODY_BYTES_LIMIT, parsed))
    in_range = MIN_REQUEST_BODY_BYTES <= parsed <= MAX_REQUEST_BODY_BYTES_LIMIT
    return {
        "name": "MAX_REQUEST_BODY_BYTES",
        "ok": valid and in_range,
        "severity": "warning",
        "configured": configured,
        "effective_bytes": effective,
        "message": "公网入口建议限制请求体大小；应设置为 16384-10000000 字节的整数，默认 1000000。",
    }


def _display_path(path: Path) -> str:
    if not path.is_absolute():
        return str(path)
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _file_status(path: Path, required: bool, kind: str) -> dict[str, Any]:
    exists = path.exists()
    size = path.stat().st_size if exists and path.is_file() else 0
    ok = exists and (size > 0 or kind in {"runtime_file", "runtime_dir", "optional_queue"})
    if kind == "runtime_dir":
        ok = path.exists() and path.is_dir()
    return {
        "name": path.name,
        "path": _display_path(path),
        "kind": kind,
        "required": required,
        "exists": exists,
        "size_bytes": size,
        "ok": ok if required else True,
    }


def _runtime_dir_status(path: Path) -> dict[str, Any]:
    exists = path.exists()
    writable = path.exists() and os.access(path, os.W_OK)
    return {
        "name": path.name,
        "path": _display_path(path),
        "kind": "runtime_dir",
        "required": True,
        "exists": exists,
        "writable": writable,
        "ok": exists and writable,
    }


def _sqlite_runtime_status(path: Path, name: str) -> dict[str, Any]:
    exists = path.exists()
    writable = path.exists() and os.access(path, os.W_OK)
    size = path.stat().st_size if exists and path.is_file() else 0
    ok = True
    message = "运行时数据库尚未创建，将在首次使用时自动初始化。"
    if exists:
        ok = path.is_file() and writable
        message = "运行时数据库文件可写。" if ok else "运行时数据库文件不可写或路径异常。"
    return {
        "name": name,
        "path": _display_path(path),
        "kind": "runtime_database",
        "required": False,
        "exists": exists,
        "writable": writable,
        "size_bytes": size,
        "severity": "warning",
        "message": message,
        "ok": ok,
    }


def _json_runtime_status(path: Path, name: str, message_prefix: str) -> dict[str, Any]:
    exists = path.exists()
    writable = path.exists() and os.access(path, os.W_OK)
    size = path.stat().st_size if exists and path.is_file() else 0
    ok = True
    message = f"{message_prefix}尚未创建，将在首次使用时自动初始化。"
    valid_json: bool | None = None
    json_error = ""
    if exists:
        ok = path.is_file() and writable
        message = f"{message_prefix}可写。" if ok else f"{message_prefix}不可写或路径异常。"
        if path.is_file():
            try:
                json.loads(path.read_text(encoding="utf-8"))
                valid_json = True
            except (OSError, json.JSONDecodeError) as exc:
                valid_json = False
                json_error = str(exc)
                ok = False
                message = f"{message_prefix}不是合法 JSON，可能已损坏或写入中断。"
    return {
        "name": name,
        "path": _display_path(path),
        "kind": "runtime_json",
        "required": False,
        "exists": exists,
        "writable": writable,
        "valid_json": valid_json,
        "json_error": json_error,
        "size_bytes": size,
        "severity": "warning",
        "message": message,
        "ok": ok,
    }


def _environment_checks() -> list[dict[str, Any]]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    pepper = os.getenv("AUTH_PASSWORD_PEPPER", "").strip()
    cors = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    offline_mode = _env_bool("CRYPTO_RISK_AGENT_OFFLINE")
    deepseek_config = get_deepseek_config()
    deepseek_client_available = find_spec("openai") is not None
    return [
        {
            "name": "DEEPSEEK_API_KEY",
            "required": False,
            "configured": bool(api_key),
            "severity": "warning",
            "message": "缺少 DeepSeek API Key 时系统会进入规则兜底/离线能力，Agent 深度会下降。",
            "ok": bool(api_key) or offline_mode,
        },
        {
            "name": "DEEPSEEK_CLIENT",
            "required": True,
            "configured": deepseek_client_available,
            "package": "openai",
            "severity": "critical",
            "message": "Python openai 客户端必须可导入，DeepSeek 兼容接口调用依赖该包；离线模式下可忽略。",
            "ok": deepseek_client_available or offline_mode,
        },
        {
            "name": "DEEPSEEK_MODEL",
            "required": True,
            "configured": deepseek_config.model,
            "expected": EXPECTED_DEEPSEEK_MODEL,
            "severity": "critical",
            "message": f"本项目固定使用 {EXPECTED_DEEPSEEK_MODEL}，避免模型漂移导致风控输出不可复现。",
            "ok": deepseek_config.model == EXPECTED_DEEPSEEK_MODEL,
        },
        {
            "name": "DEEPSEEK_BASE_URL",
            "required": False,
            "configured": deepseek_config.base_url,
            "severity": "warning",
            "message": "生产环境建议使用 HTTPS DeepSeek 兼容接口地址。",
            "ok": deepseek_config.base_url.startswith("https://"),
        },
        {
            "name": "DEEPSEEK_TIMEOUT",
            "required": False,
            "configured": deepseek_config.raw_timeout or str(deepseek_config.timeout),
            "effective_seconds": deepseek_config.timeout,
            "severity": "warning",
            "message": "DeepSeek 超时时间应为 1-120 秒的数字；非法值会回退到默认 30 秒。",
            "ok": deepseek_config.timeout_valid,
        },
        {
            "name": "AUTH_PASSWORD_PEPPER",
            "required": True,
            "configured": bool(pepper),
            "severity": "critical",
            "message": "生产环境必须设置密码 pepper，避免数据库泄露后密码哈希更容易被离线攻击。",
            "ok": bool(pepper),
        },
        {
            "name": "CORS_ALLOWED_ORIGINS",
            "required": False,
            "configured": bool(cors),
            "severity": "info",
            "message": "未显式配置时使用 kassa-wiki.top 默认域名。",
            "ok": True,
        },
    ]


def _security_checks() -> list[dict[str, Any]]:
    admin_configured = bool(os.getenv("SYSTEM_ADMIN_USERNAMES", "").strip()) or bool(
        os.getenv("SYSTEM_ADMIN_USER_IDS", "").strip()
    )
    return [
        {
            "name": "API_RATE_LIMIT_ENABLED",
            "ok": os.getenv("API_RATE_LIMIT_ENABLED", "1").strip() != "0",
            "severity": "warning",
            "message": "公网部署建议开启 API 限流，保护登录和高成本 Agent 分析入口。",
        },
        _request_body_limit_check(),
        {
            "name": "ALLOW_USER_ID_QUERY_OVERRIDE",
            "ok": not _env_bool("ALLOW_USER_ID_QUERY_OVERRIDE"),
            "severity": "critical",
            "message": "生产环境必须关闭 query user_id 覆盖，避免越权访问其他用户资产。",
        },
        {
            "name": "CSRF_PROTECTION_ENABLED",
            "ok": os.getenv("CSRF_PROTECTION_ENABLED", "1").strip() != "0",
            "severity": "critical",
            "message": "Cookie 登录态的写请求必须启用 CSRF 防护，避免跨站请求伪造。",
        },
        {
            "name": "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY",
            "ok": not _env_bool("ALLOW_PUBLIC_SYSTEM_OBSERVABILITY"),
            "severity": "critical",
            "message": "生产环境必须关闭公开系统观测接口，避免泄露审计、限流和运行状态细节。",
        },
        {
            "name": "ALLOW_PUBLIC_REPORT_DEBUG",
            "ok": not _env_bool("ALLOW_PUBLIC_REPORT_DEBUG"),
            "severity": "critical",
            "message": "生产环境必须关闭公开报告 debug，避免向前端暴露内部 Agent 状态和诊断字段。",
        },
        {
            "name": "SYSTEM_ADMIN_USERS",
            "ok": admin_configured or _env_bool("ALLOW_PUBLIC_SYSTEM_OBSERVABILITY"),
            "severity": "warning",
            "message": "建议通过 SYSTEM_ADMIN_USERNAMES 或 SYSTEM_ADMIN_USER_IDS 配置系统观测管理员。",
        },
        {
            "name": "ALLOW_ADMIN_USERNAME_REGISTRATION",
            "ok": not _env_bool("ALLOW_ADMIN_USERNAME_REGISTRATION"),
            "severity": "critical",
            "message": "公网环境必须关闭管理员用户名公开注册，避免抢注管理员账号。",
        },
        {
            "name": "ALLOW_SYSTEM_EVENT_GLOBAL_QUERY",
            "ok": not _env_bool("ALLOW_SYSTEM_EVENT_GLOBAL_QUERY"),
            "severity": "warning",
            "message": "系统观测已改为管理员可见；该兼容开关不建议在生产环境开启。",
        },
        {
            "name": "ALLOW_LOCAL_CORS",
            "ok": not _env_bool("ALLOW_LOCAL_CORS"),
            "severity": "warning",
            "message": "公网部署建议关闭本地 CORS 白名单。",
        },
        {
            "name": "CRYPTO_RISK_AGENT_OFFLINE",
            "ok": not _env_bool("CRYPTO_RISK_AGENT_OFFLINE"),
            "severity": "warning",
            "message": "离线模式适合演示兜底，不适合作为完整 Agent 深度运行状态。",
        },
        {
            "name": "TRUST_PROXY_HEADERS",
            "ok": True,
            "severity": "info",
            "message": "通过 Nginx 反代部署时可保持开启；若后端会被公网直连，应设置为 0，避免信任客户端伪造的代理头。",
            "configured": os.getenv("TRUST_PROXY_HEADERS", "1").strip(),
        },
    ]


def _data_checks() -> list[dict[str, Any]]:
    return [
        _runtime_dir_status(DATA_DIR),
        _file_status(MASTERED_NEWS_PATH, required=True, kind="seed_dataset"),
        _file_status(SCORED_DATA_PATH, required=True, kind="scored_cache"),
        _file_status(RAW_NEWS_QUEUE_PATH, required=False, kind="optional_queue"),
        _file_status(PORTFOLIO_STATE_PATH, required=False, kind="runtime_file"),
        _file_status(SIM_ACCOUNTS_PATH, required=False, kind="runtime_file"),
        _file_status(PORTFOLIO_REFRESH_JOBS_PATH, required=False, kind="runtime_file"),
        _file_status(UPDATE_JOBS_PATH, required=False, kind="runtime_file"),
        _file_status(PORTFOLIO_DB_PATH, required=False, kind="runtime_file"),
        _file_status(AUTH_DB_PATH, required=False, kind="runtime_file"),
        _file_status(REPORT_DB_PATH, required=False, kind="runtime_file"),
        _file_status(TASK_AUDIT_DB_PATH, required=False, kind="runtime_file"),
        _runtime_dir_status(DAILY_REPORTS_DIR.parent),
    ]


def _storage_checks() -> list[dict[str, Any]]:
    return [
        _sqlite_runtime_status(AUTH_DB_PATH, "auth_db"),
        _sqlite_runtime_status(REPORT_DB_PATH, "analysis_report_db"),
        _sqlite_runtime_status(PORTFOLIO_DB_PATH, "portfolio_db"),
        _sqlite_runtime_status(TASK_AUDIT_DB_PATH, "task_audit_db"),
        _json_runtime_status(SIM_ACCOUNTS_PATH, "sim_accounts_store", "模拟交易账户状态文件"),
        _json_runtime_status(PORTFOLIO_REFRESH_JOBS_PATH, "portfolio_refresh_jobs_store", "组合刷新任务状态文件"),
        _json_runtime_status(UPDATE_JOBS_PATH, "news_update_jobs_store", "新闻更新任务状态文件"),
    ]


def _summarize_status(checks: list[dict[str, Any]]) -> str:
    critical_failed = [
        item
        for item in checks
        if not item.get("ok", False) and item.get("severity") == "critical"
    ]
    required_failed = [
        item
        for item in checks
        if item.get("required") and not item.get("ok", False)
    ]
    warning_failed = [
        item
        for item in checks
        if not item.get("ok", False) and item.get("severity") == "warning"
    ]
    if critical_failed or required_failed:
        return "not_ready"
    if warning_failed:
        return "degraded"
    return "ready"


def get_product_readiness() -> dict[str, Any]:
    environment = _environment_checks()
    security = _security_checks()
    data = _data_checks()
    storage = _storage_checks()
    flat_checks = [*environment, *security, *data, *storage]
    status = _summarize_status(flat_checks)
    return {
        "status": status,
        "service": "cryptorisk-agent",
        "checked_at": _now_iso(),
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "version": os.getenv("APP_VERSION", "local"),
        "environment": environment,
        "security": security,
        "data": data,
        "storage": storage,
        "summary": {
            "total_checks": len(flat_checks),
            "failed_checks": sum(1 for item in flat_checks if not item.get("ok", False)),
            "critical_failures": sum(
                1 for item in flat_checks if not item.get("ok", False) and item.get("severity") == "critical"
            ),
        },
    }
