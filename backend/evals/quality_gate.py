from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RISK_CASES_PATH = ROOT / "backend" / "evals" / "risk_cases_smoke.jsonl"
FRONTEND_DIR = ROOT / "frontend"
GITIGNORE_PATH = ROOT / ".gitignore"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

MIN_TOTAL_CASES = 80
MIN_CASES_PER_SCENARIO = 4
MIN_HIGH_RISK_RECALL = 0.9
MAX_HIGH_RISK_FALSE_POSITIVE_RATE = 0.15
MIN_SCENARIO_ACCURACY = 0.8
MIN_EVIDENCE_GRAPH_COVERAGE = 0.95
MIN_DECISION_TRACE_COVERAGE = 0.95
MAX_ERROR_RATE = 0.0
NO_HIGH_RISK_REQUIRED_SCENARIOS = {"S0_GENERAL_UNKNOWN"}

FORBIDDEN_FRONTEND_PATTERNS = [
    r"localhost",
    r"127\.0\.0\.1",
    r"\b8000\b",
    r"\b8001\b",
    r"\b8002\b",
]
FRONTEND_API_REQUEST_CALL_PATTERN = re.compile(
    r"\b(?:fetch|apiFetch|requestJson|cachedRequestJson|readCachedJson)\s*(?:<[^;\n({]+>)?\(\s*([\"'`])([^\"'`]+)\1"
)

REQUIRED_GITIGNORE_ENTRIES = [
    "backend/app/data/auth.sqlite3",
    "backend/app/data/analysis_reports.sqlite3",
    "backend/app/data/portfolio.sqlite3",
    "backend/app/data/task_audit.sqlite3",
    "backend/app/data/sim_accounts.json",
    "backend/app/data/portfolio_refresh_jobs.json",
    "backend/app/data/update_jobs.json",
    "backend/app/data/*.invalid.*.bak",
]

REQUIRED_ENV_EXAMPLE_KEYS = [
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_TIMEOUT",
    "CRYPTO_RISK_AGENT_OFFLINE",
    "AUTH_PASSWORD_PEPPER",
    "CORS_ALLOWED_ORIGINS",
    "ALLOW_LOCAL_CORS",
    "ALLOW_USER_ID_QUERY_OVERRIDE",
    "CSRF_PROTECTION_ENABLED",
    "TRUST_PROXY_HEADERS",
    "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY",
    "ALLOW_PUBLIC_REPORT_DEBUG",
    "ALLOW_SYSTEM_EVENT_GLOBAL_QUERY",
    "SYSTEM_ADMIN_USERNAMES",
    "SYSTEM_ADMIN_USER_IDS",
    "ALLOW_ADMIN_USERNAME_REGISTRATION",
    "API_RATE_LIMIT_ENABLED",
    "AUTH_RATE_LIMIT_PER_MINUTE",
    "AGENT_RATE_LIMIT_PER_5_MINUTES",
    "MUTATION_RATE_LIMIT_PER_MINUTE",
    "MAX_REQUEST_BODY_BYTES",
    "TASK_AUDIT_RETENTION_DAYS",
    "TASK_AUDIT_MAX_EVENTS",
]

FORBIDDEN_ENV_EXAMPLE_PATTERNS = [
    r"DEEPSEEK_API_KEY\s*=\s*sk-[A-Za-z0-9_-]+",
    r"AUTH_PASSWORD_PEPPER\s*=\s*(?!replace-with)[A-Za-z0-9+/=_-]{24,}",
]

FORBIDDEN_PUBLIC_ERROR_PATTERNS = [
    r"detail=f\"Agent workflow failed: \{exc\}\"",
    r"detail=f\"Risk assistant failed: \{exc\}\"",
    r"detail=f\"News update failed: \{exc\}\"",
    r"\{\"detail\": f\"Agent workflow failed: \{exc\}\"\}",
]

REQUIRED_SECURITY_CONTROL_MARKERS = [
    {
        "name": "llm_config_contract",
        "path": "backend/app/services/llm_config_service.py",
        "patterns": [
            'EXPECTED_DEEPSEEK_MODEL = "deepseek-v4-pro"',
            "get_deepseek_config",
            "MAX_DEEPSEEK_TIMEOUT",
        ],
    },
    {
        "name": "llm_runtime_uses_config_service",
        "path": "backend/app/llm.py",
        "patterns": [
            "get_deepseek_config",
            "base_url=config.base_url",
            "timeout=config.timeout",
            "model=config.model",
        ],
    },
    {
        "name": "csrf_service",
        "path": "backend/app/services/csrf_service.py",
        "patterns": [
            "CSRF_PROTECTION_ENABLED",
            "x-cryptorisk-csrf",
            "UNSAFE_METHODS",
            "session_cookie_name",
        ],
    },
    {
        "name": "csrf_middleware",
        "path": "backend/main.py",
        "patterns": [
            "csrf_request_allowed",
            "_csrf_request_allowed",
            "Missing CSRF protection header",
        ],
    },
    {
        "name": "proxy_header_trust_service",
        "path": "backend/app/services/request_security_service.py",
        "patterns": [
            "TRUST_PROXY_HEADERS",
            "request_uses_https",
            "request_client_identity",
            "request_security_context",
        ],
    },
    {
        "name": "session_cookie_proxy_guard",
        "path": "backend/app/api/auth.py",
        "patterns": [
            "request_uses_https",
            "secure=_is_secure_request(request)",
        ],
    },
    {
        "name": "rate_limit_proxy_guard",
        "path": "backend/main.py",
        "patterns": [
            "request_client_identity",
            "_request_identity",
        ],
    },
    {
        "name": "request_body_size_guard",
        "path": "backend/main.py",
        "patterns": [
            "max_request_body_bytes",
            "request_body_exceeds_limit",
            "Request body too large",
            "status_code=413",
        ],
    },
    {
        "name": "request_body_limit_service",
        "path": "backend/app/services/request_body_limit_service.py",
        "patterns": [
            "MAX_REQUEST_BODY_BYTES",
            "DEFAULT_MAX_REQUEST_BODY_BYTES",
            "MAX_REQUEST_BODY_BYTES_LIMIT",
            "request_body_exceeds_limit",
            "content_length_exceeds_limit",
        ],
    },
    {
        "name": "safe_public_error_responses",
        "path": "backend/app/services/error_response_service.py",
        "patterns": [
            "PUBLIC_AGENT_ERROR_DETAIL",
            "PUBLIC_RISK_ASSISTANT_ERROR_DETAIL",
            "PUBLIC_NEWS_UPDATE_ERROR_DETAIL",
            "PUBLIC_INTERNAL_ERROR_DETAIL",
            "public_error_payload",
        ],
    },
    {
        "name": "public_report_debug_sanitizer",
        "path": "backend/app/services/report_response_service.py",
        "patterns": [
            "ALLOW_PUBLIC_REPORT_DEBUG",
            "INTERNAL_REPORT_FIELDS",
            "sanitize_risk_report_for_public_api",
            '"debug"',
            '"raw_agent_outputs"',
        ],
    },
    {
        "name": "main_public_report_sanitizer",
        "path": "backend/main.py",
        "patterns": [
            "sanitize_risk_report_for_public_api",
            "_public_chat_response",
        ],
    },
    {
        "name": "main_safe_error_responses",
        "path": "backend/main.py",
        "patterns": [
            "PUBLIC_AGENT_ERROR_DETAIL",
            "PUBLIC_INTERNAL_ERROR_DETAIL",
            "PUBLIC_RISK_ASSISTANT_ERROR_DETAIL",
            "public_error_payload",
            "request_failed",
            "X-CryptoRisk-Job-ID",
        ],
    },
    {
        "name": "frontend_csrf_header",
        "path": "frontend/lib/api.ts",
        "patterns": [
            "X-CryptoRisk-CSRF",
            "csrfHeaders(restInit.method)",
            "csrfHeaders(\"POST\")",
        ],
    },
    {
        "name": "frontend_api_path_runtime_guard",
        "path": "frontend/lib/api.ts",
        "patterns": [
            "assertApiPath",
            "apiFetch",
            'path.startsWith("/api/")',
            "Frontend API requests must use /api/ paths.",
        ],
    },
    {
        "name": "admin_username_registration_guard",
        "path": "backend/app/services/auth_service.py",
        "patterns": [
            "ALLOW_ADMIN_USERNAME_REGISTRATION",
            "_ensure_username_can_register",
            "SYSTEM_ADMIN_USERNAMES",
        ],
    },
    {
        "name": "password_change_service",
        "path": "backend/app/services/auth_service.py",
        "patterns": [
            "change_user_password",
            "新密码不能与当前密码相同",
            "DELETE FROM sessions WHERE user_id = ? AND token != ?",
        ],
    },
    {
        "name": "password_change_api",
        "path": "backend/app/api/auth.py",
        "patterns": [
            '@router.post("/change-password")',
            "PasswordChangeRequest",
            "change_user_password",
        ],
    },
    {
        "name": "session_management_service",
        "path": "backend/app/services/auth_service.py",
        "patterns": [
            "list_user_sessions",
            "revoke_other_sessions",
            "_session_public_id",
            "client_ip_hash",
            "user_agent",
        ],
    },
    {
        "name": "auth_session_expiry_prune_service",
        "path": "backend/app/services/auth_service.py",
        "patterns": [
            "prune_expired_sessions",
            "_prune_expired_sessions",
            "DELETE FROM sessions WHERE expires_at <= ?",
            "remaining_sessions",
        ],
    },
    {
        "name": "session_management_api",
        "path": "backend/app/api/auth.py",
        "patterns": [
            '@router.get("/sessions"',
            '@router.post("/sessions/revoke-others")',
            "list_user_sessions",
            "revoke_other_sessions",
        ],
    },
    {
        "name": "system_auth_session_prune_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.post("/auth-sessions/prune")',
            "_require_system_admin_access(cryptorisk_session)",
            "prune_expired_sessions",
        ],
    },
    {
        "name": "system_admin_operations_audit",
        "path": "backend/app/api/system.py",
        "patterns": [
            "_record_system_admin_event",
            'job_kind="system_admin"',
            "task_events_prune",
            "guest_sim_accounts_prune",
            "auth_sessions_prune",
            "invalid_json_backups_prune",
            "admin_user_id",
        ],
    },
    {
        "name": "runtime_job_prune_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.post("/runtime-jobs/prune")',
            "prune_update_jobs",
            "prune_portfolio_refresh_jobs",
            "runtime_jobs_prune",
        ],
    },
    {
        "name": "news_update_job_prune",
        "path": "backend/app/api/risk_ranking.py",
        "patterns": [
            "load_runtime_json_or_quarantine",
            "write_runtime_json_atomic",
            "prune_update_jobs",
            "active_statuses = {\"queued\", \"running\"}",
            "_persist_update_jobs()",
            "remaining_jobs",
        ],
    },
    {
        "name": "portfolio_refresh_job_prune",
        "path": "backend/app/api/portfolio.py",
        "patterns": [
            "load_runtime_json_or_quarantine",
            "write_runtime_json_atomic",
            "prune_portfolio_refresh_jobs",
            "_rebuild_latest_refresh_jobs_unlocked",
            "_persist_refresh_jobs()",
            "remaining_jobs",
        ],
    },
    {
        "name": "account_security_events_api",
        "path": "backend/app/api/account.py",
        "patterns": [
            '@router.get("/security-events")',
            "list_account_security_events",
        ],
    },
    {
        "name": "system_task_events_admin_only",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.get("/task-events")',
            "_require_system_admin_access(cryptorisk_session)",
            "_redact_public_audit_summary",
        ],
    },
    {
        "name": "system_storage_inventory_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.get("/storage-inventory")',
            "_require_system_admin_access",
            "build_storage_inventory",
        ],
    },
    {
        "name": "system_invalid_json_backup_prune_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.post("/invalid-json-backups/prune")',
            "_require_system_admin_access",
            "prune_invalid_json_backups",
            "invalid_json_backups_prune",
        ],
    },
    {
        "name": "system_backup_manifest_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.get("/backup-manifest")',
            "_require_system_admin_access",
            "build_backup_manifest",
        ],
    },
    {
        "name": "system_guest_sim_prune_api",
        "path": "backend/app/api/system.py",
        "patterns": [
            '@router.post("/sim-accounts/prune")',
            "_require_system_admin_access",
            "prune_guest_accounts",
        ],
    },
    {
        "name": "storage_inventory_service",
        "path": "backend/app/services/storage_inventory_service.py",
        "patterns": [
            "build_storage_inventory",
            "build_backup_manifest",
            "sqlite_sidecar",
            "sim_accounts.json",
            "invalid_json_backups",
            "runtime_json_invalid_backup",
            "prune_invalid_json_backups",
            "deleted_files",
            "mode=ro",
            "account_count",
            "daily_reports",
        ],
    },
    {
        "name": "runtime_json_store_guard",
        "path": "backend/app/services/runtime_json_store.py",
        "patterns": [
            "quarantine_invalid_json",
            "load_runtime_json_or_quarantine",
            "write_runtime_json_atomic",
            ".invalid.",
            "temp_path.replace",
        ],
    },
    {
        "name": "sim_account_persistence",
        "path": "backend/app/services/sim_engine.py",
        "patterns": [
            "SIM_ACCOUNTS_PATH",
            "_load_accounts",
            "_persist_accounts_unlocked",
            "load_runtime_json_or_quarantine",
            "write_runtime_json_atomic",
            "prune_guest_accounts",
            "updated_at",
            "sim_accounts.json",
        ],
    },
    {
        "name": "account_security_event_audit",
        "path": "backend/app/services/account_security_event_service.py",
        "patterns": [
            "record_account_security_event",
            "security_identifier_hash",
            'job_kind="account_security"',
            "record_task_event",
        ],
    },
    {
        "name": "auth_failure_security_audit",
        "path": "backend/app/api/auth.py",
        "patterns": [
            'event_type="login_failed"',
            'event_type="register_failed"',
            'event_type="password_change_failed"',
            "_request_security_payload",
            "security_identifier_hash",
        ],
    },
    {
        "name": "frontend_password_change",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "handlePasswordChange",
            "changePassword(currentPassword, newPassword)",
            "修改登录密码",
        ],
    },
    {
        "name": "frontend_session_management",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "loadAuthSessions",
            "handleRevokeOtherSessions",
            "formatSessionUserAgent",
            "登录会话",
        ],
    },
    {
        "name": "frontend_account_security_events",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "fetchAccountSecurityEvents",
            "最近账号安全事件",
            "formatSecurityEventContext",
            "formatSecurityEventType",
        ],
    },
    {
        "name": "frontend_system_task_events",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "fetchSystemTaskEvents",
            "systemTaskEvents",
            "最近事件",
            "formatAuditPayloadSummary",
            "formatAuditUser",
        ],
    },
    {
        "name": "frontend_runtime_job_prune",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "pruneRuntimeJobs",
            "handlePruneRuntimeJobs",
            "清理任务状态",
            "runtimeJobPruneMessage",
        ],
    },
    {
        "name": "frontend_storage_inventory",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "fetchStorageInventory",
            "fetchBackupManifest",
            "backupManifest",
            "备份清单",
            "pruneGuestSimAccounts",
            "清理历史游客模拟数据",
            "storageInventory",
            "invalidJsonBackups",
            "损坏 JSON 备份",
            "runtime_json_invalid_backup",
            "pruneInvalidJsonBackups",
            "清理损坏备份",
            "运行时存储盘点",
            "formatDatastoreScale",
        ],
    },
    {
        "name": "frontend_storage_inventory_api",
        "path": "frontend/lib/api.ts",
        "patterns": [
            "StorageInventory",
            "invalid_json_backups",
            "file_count",
            "InvalidJsonBackupsPruneResult",
            '"/api/system/storage-inventory"',
            "fetchStorageInventory",
            "BackupManifest",
            '"/api/system/backup-manifest"',
            "fetchBackupManifest",
            "pruneGuestSimAccounts",
            "/api/system/sim-accounts/prune",
            "fetchSystemTaskEvents",
            "/api/system/task-events",
            "RuntimeJobsPruneResult",
            "pruneRuntimeJobs",
            "/api/system/runtime-jobs/prune",
            "pruneInvalidJsonBackups",
            "/api/system/invalid-json-backups/prune",
        ],
    },
    {
        "name": "frontend_auth_session_prune",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "pruneExpiredAuthSessions",
            "handlePruneExpiredAuthSessions",
            "清理过期会话",
            "system_admin",
            "系统运维",
        ],
    },
    {
        "name": "frontend_auth_session_prune_api",
        "path": "frontend/lib/api.ts",
        "patterns": [
            "AuthSessionPruneResult",
            "pruneExpiredAuthSessions",
            "/api/system/auth-sessions/prune",
        ],
    },
    {
        "name": "security_readiness_checks",
        "path": "backend/app/services/product_readiness_service.py",
        "patterns": [
            "DEEPSEEK_MODEL",
            "DEEPSEEK_CLIENT",
            "DEEPSEEK_TIMEOUT",
            "MAX_REQUEST_BODY_BYTES",
            "ALLOW_PUBLIC_REPORT_DEBUG",
            "CSRF_PROTECTION_ENABLED",
            "ALLOW_ADMIN_USERNAME_REGISTRATION",
            "ALLOW_PUBLIC_SYSTEM_OBSERVABILITY",
            "TRUST_PROXY_HEADERS",
            "SIM_ACCOUNTS_PATH",
            "PORTFOLIO_REFRESH_JOBS_PATH",
            "UPDATE_JOBS_PATH",
            "_json_runtime_status",
            "json.loads",
            "valid_json",
            "json_error",
            "sim_accounts_store",
            "portfolio_refresh_jobs_store",
            "news_update_jobs_store",
        ],
    },
    {
        "name": "account_export_delete_api",
        "path": "backend/app/api/account.py",
        "patterns": [
            '@router.get("/export")',
            '@router.delete("")',
            "AccountDeleteRequest",
            "verify_user_password",
            "delete-my-account",
            "account_delete_failed",
            "account_export",
            "account_delete",
            'job_id="account-export-redacted"',
            'job_id="account-delete-redacted"',
        ],
    },
    {
        "name": "account_export_full_payload",
        "path": "backend/app/services/account_export_service.py",
        "patterns": [
            "list_daily_report_payloads",
            "sim_engine.account_state_snapshot",
            "list_account_security_events",
            "list_user_sessions",
            '"sim_account"',
            '"auth_sessions"',
        ],
    },
    {
        "name": "account_lifecycle_service",
        "path": "backend/app/services/account_lifecycle_service.py",
        "patterns": [
            "delete_account_data",
            "delete_analysis_reports_for_user",
            "delete_watchlist_records_for_user",
            "delete_daily_reports_for_user",
            "sim_engine.delete_account",
            "delete_task_events_for_user",
            "audit_events_deleted",
            "delete_user_account",
        ],
    },
    {
        "name": "task_audit_user_lifecycle_cleanup",
        "path": "backend/app/services/task_audit_service.py",
        "patterns": [
            "delete_task_events_for_user",
            "DELETE FROM task_events WHERE user_id = ?",
            "idx_task_events_user",
        ],
    },
    {
        "name": "frontend_account_delete_audit_summary",
        "path": "frontend/components/risk-dashboard.tsx",
        "patterns": [
            "audit_events_deleted",
            "审计事件",
        ],
    },
]


@dataclass
class GateCheck:
    name: str
    passed: bool
    severity: str = "critical"
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_risk_case_coverage(path: Path = RISK_CASES_PATH) -> GateCheck:
    cases = _load_jsonl(path)
    scenario_counts: dict[str, int] = {}
    high_risk_counts: dict[str, int] = {}
    non_high_risk_counts: dict[str, int] = {}
    missing_fields: list[str] = []
    ids: set[str] = set()
    duplicate_ids: list[str] = []

    required_fields = {
        "id",
        "text",
        "expected_min_score",
        "expected_max_score",
        "expected_high_risk",
        "expected_scenario",
    }
    for index, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or f"line-{index}")
        if case_id in ids:
            duplicate_ids.append(case_id)
        ids.add(case_id)
        missing = sorted(required_fields - set(case))
        if missing:
            missing_fields.append(f"{case_id}:{','.join(missing)}")
        scenario = str(case.get("expected_scenario") or "unknown")
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1
        if bool(case.get("expected_high_risk")):
            high_risk_counts[scenario] = high_risk_counts.get(scenario, 0) + 1
        else:
            non_high_risk_counts[scenario] = non_high_risk_counts.get(scenario, 0) + 1

    undercovered = {
        scenario: count
        for scenario, count in scenario_counts.items()
        if count < MIN_CASES_PER_SCENARIO
    }
    scenarios_without_high = [
        scenario
        for scenario in scenario_counts
        if scenario not in NO_HIGH_RISK_REQUIRED_SCENARIOS and high_risk_counts.get(scenario, 0) == 0
    ]
    scenarios_without_counterexamples = [
        scenario for scenario in scenario_counts if non_high_risk_counts.get(scenario, 0) == 0
    ]
    passed = (
        len(cases) >= MIN_TOTAL_CASES
        and not undercovered
        and not scenarios_without_high
        and not scenarios_without_counterexamples
        and not missing_fields
        and not duplicate_ids
    )
    return GateCheck(
        name="risk_case_coverage",
        passed=passed,
        message="评测集覆盖满足上线门槛" if passed else "评测集覆盖不足或样本格式异常",
        details={
            "total_cases": len(cases),
            "min_total_cases": MIN_TOTAL_CASES,
            "scenario_counts": scenario_counts,
            "min_cases_per_scenario": MIN_CASES_PER_SCENARIO,
            "undercovered_scenarios": undercovered,
            "scenarios_without_high_risk_examples": scenarios_without_high,
            "high_risk_requirement_exemptions": sorted(NO_HIGH_RISK_REQUIRED_SCENARIOS),
            "scenarios_without_counterexamples": scenarios_without_counterexamples,
            "missing_fields": missing_fields[:20],
            "duplicate_ids": duplicate_ids[:20],
        },
    )


def _iter_frontend_text_files(frontend_dir: Path) -> list[Path]:
    ignored_suffixes = {".ico", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".woff", ".woff2"}
    if not frontend_dir.exists():
        return []
    return [
        path
        for path in frontend_dir.rglob("*")
        if path.is_file()
        and "node_modules" not in path.parts
        and ".next" not in path.parts
        and path.suffix.lower() not in ignored_suffixes
    ]


def check_frontend_api_boundaries(frontend_dir: Path = FRONTEND_DIR) -> GateCheck:
    violations: list[dict[str, Any]] = []
    compiled = [re.compile(pattern) for pattern in FORBIDDEN_FRONTEND_PATTERNS]
    for path in _iter_frontend_text_files(frontend_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            reasons: list[str] = []
            if any(pattern.search(line) for pattern in compiled):
                reasons.append("forbidden_local_address_or_port")
            request_match = FRONTEND_API_REQUEST_CALL_PATTERN.search(line)
            if request_match and not request_match.group(2).startswith("/api/"):
                reasons.append("frontend_request_must_use_api_path")
            if reasons:
                violations.append(
                    {
                        "path": _display_path(path),
                        "line": line_number,
                        "reasons": reasons,
                        "preview": line.strip()[:160],
                    }
                )
    passed = not violations
    return GateCheck(
        name="frontend_api_boundaries",
        passed=passed,
        message="前端未发现本地地址或端口硬编码" if passed else "前端存在部署禁止的本地地址或端口硬编码",
        details={
            "forbidden_patterns": FORBIDDEN_FRONTEND_PATTERNS,
            "violations": violations[:30],
            "violation_count": len(violations),
        },
    )


def check_runtime_data_gitignored(path: Path = GITIGNORE_PATH) -> GateCheck:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [entry for entry in REQUIRED_GITIGNORE_ENTRIES if entry not in text]
    passed = not missing
    return GateCheck(
        name="runtime_data_gitignored",
        passed=passed,
        message="运行时数据已纳入 gitignore" if passed else "运行时数据 gitignore 覆盖不完整",
        details={
            "required_entries": REQUIRED_GITIGNORE_ENTRIES,
            "missing_entries": missing,
        },
    )


def _parse_env_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def check_env_example_contract(path: Path = ENV_EXAMPLE_PATH) -> GateCheck:
    if not path.exists():
        return GateCheck(
            name="env_example_contract",
            passed=False,
            message=".env.example 缺失，部署环境变量缺少可复制模板",
            details={
                "path": _display_path(path),
                "missing_keys": REQUIRED_ENV_EXAMPLE_KEYS,
                "forbidden_matches": [],
            },
        )

    text = path.read_text(encoding="utf-8")
    keys = _parse_env_keys(text)
    missing = [key for key in REQUIRED_ENV_EXAMPLE_KEYS if key not in keys]
    forbidden_matches: list[dict[str, Any]] = []
    for pattern in FORBIDDEN_ENV_EXAMPLE_PATTERNS:
        compiled = re.compile(pattern)
        for line_number, line in enumerate(text.splitlines(), start=1):
            if compiled.search(line.strip()):
                forbidden_matches.append(
                    {
                        "pattern": pattern,
                        "line": line_number,
                        "preview": line.strip()[:120],
                    }
                )
    passed = not missing and not forbidden_matches
    return GateCheck(
        name="env_example_contract",
        passed=passed,
        message="环境变量模板完整且未发现疑似真实密钥" if passed else "环境变量模板缺失关键项或包含疑似真实密钥",
        details={
            "path": _display_path(path),
            "required_keys": REQUIRED_ENV_EXAMPLE_KEYS,
            "missing_keys": missing,
            "forbidden_matches": forbidden_matches[:20],
        },
    )


def check_product_security_controls(root: Path = ROOT) -> GateCheck:
    missing: list[dict[str, Any]] = []
    for control in REQUIRED_SECURITY_CONTROL_MARKERS:
        path = root / str(control["path"])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            missing.append(
                {
                    "control": control["name"],
                    "path": str(control["path"]),
                    "missing_patterns": list(control["patterns"]),
                    "reason": "file_missing",
                }
            )
            continue
        missing_patterns = [pattern for pattern in control["patterns"] if pattern not in text]
        if missing_patterns:
            missing.append(
                {
                    "control": control["name"],
                    "path": str(control["path"]),
                    "missing_patterns": missing_patterns,
                    "reason": "pattern_missing",
                }
            )
    passed = not missing
    return GateCheck(
        name="product_security_controls",
        passed=passed,
        message="关键产品安全与账号生命周期控制已存在" if passed else "关键产品安全或账号生命周期控制缺失",
        details={
            "required_controls": [
                {"name": item["name"], "path": item["path"], "patterns": item["patterns"]}
                for item in REQUIRED_SECURITY_CONTROL_MARKERS
            ],
            "missing_controls": missing,
        },
    )


def check_public_error_boundaries(root: Path = ROOT) -> GateCheck:
    violations: list[dict[str, Any]] = []
    compiled = [re.compile(pattern) for pattern in FORBIDDEN_PUBLIC_ERROR_PATTERNS]
    for relative_path in ["backend/main.py", "backend/app/api/risk_ranking.py"]:
        path = root / relative_path
        if not path.exists():
            violations.append({"path": relative_path, "line": 0, "preview": "file_missing"})
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in compiled):
                violations.append(
                    {
                        "path": relative_path,
                        "line": line_number,
                        "preview": line.strip()[:160],
                    }
                )
    passed = not violations
    return GateCheck(
        name="public_error_boundaries",
        passed=passed,
        message="公开错误响应未拼接内部异常" if passed else "公开错误响应存在内部异常泄露风险",
        details={
            "forbidden_patterns": FORBIDDEN_PUBLIC_ERROR_PATTERNS,
            "violations": violations[:30],
            "violation_count": len(violations),
        },
    )


def check_eval_metrics(metrics: dict[str, Any]) -> GateCheck:
    thresholds = {
        "error_rate": {"max": MAX_ERROR_RATE},
        "high_risk_recall": {"min": MIN_HIGH_RISK_RECALL},
        "high_risk_false_positive_rate": {"max": MAX_HIGH_RISK_FALSE_POSITIVE_RATE},
        "scenario_accuracy": {"min": MIN_SCENARIO_ACCURACY},
        "evidence_graph_coverage": {"min": MIN_EVIDENCE_GRAPH_COVERAGE},
        "decision_trace_coverage": {"min": MIN_DECISION_TRACE_COVERAGE},
    }
    failures: dict[str, dict[str, float]] = {}
    for metric_name, threshold in thresholds.items():
        value = float(metrics.get(metric_name, 0))
        if "min" in threshold and value < threshold["min"]:
            failures[metric_name] = {"value": value, "min": threshold["min"]}
        if "max" in threshold and value > threshold["max"]:
            failures[metric_name] = {"value": value, "max": threshold["max"]}

    passed = not failures
    return GateCheck(
        name="risk_eval_metrics",
        passed=passed,
        message="风控评测指标达到上线门槛" if passed else "风控评测指标未达到上线门槛",
        details={
            "thresholds": thresholds,
            "failures": failures,
            "metrics": metrics,
        },
    )


def run_static_quality_gate() -> dict[str, Any]:
    checks = [
        check_risk_case_coverage(),
        check_frontend_api_boundaries(),
        check_runtime_data_gitignored(),
        check_env_example_contract(),
        check_product_security_controls(),
        check_public_error_boundaries(),
    ]
    return build_gate_result(checks)


def build_gate_result(checks: list[GateCheck]) -> dict[str, Any]:
    failed = [check for check in checks if not check.passed and check.severity == "critical"]
    warnings = [check for check in checks if not check.passed and check.severity != "critical"]
    return {
        "status": "pass" if not failed else "fail",
        "total_checks": len(checks),
        "failed_checks": len(failed),
        "warning_checks": len(warnings),
        "checks": [check.model_dump() for check in checks],
    }
