from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Deque


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    path_prefixes: tuple[str, ...]
    methods: tuple[str, ...]
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    rule_name: str = ""
    limit: int = 0
    remaining: int = 0
    reset_seconds: int = 0
    retry_after_seconds: int = 0


_events: dict[tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = Lock()
_last_cleanup_at = 0.0


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int = 100_000) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _enabled() -> bool:
    return os.getenv("API_RATE_LIMIT_ENABLED", "1").strip() != "0"


def rate_limit_rules() -> list[RateLimitRule]:
    return [
        RateLimitRule(
            name="auth",
            path_prefixes=("/api/auth/login", "/api/auth/register"),
            methods=("POST",),
            limit=_env_int("AUTH_RATE_LIMIT_PER_MINUTE", 8, minimum=1, maximum=300),
            window_seconds=60,
        ),
        RateLimitRule(
            name="agent",
            path_prefixes=("/api/chat", "/api/risk-assistant"),
            methods=("POST",),
            limit=_env_int("AGENT_RATE_LIMIT_PER_5_MINUTES", 30, minimum=1, maximum=1000),
            window_seconds=300,
        ),
        RateLimitRule(
            name="mutation",
            path_prefixes=(
                "/api/portfolio",
                "/api/user-assets",
                "/api/favorites",
                "/api/daily-report/generate",
                "/api/rankings/update-news",
            ),
            methods=("POST", "PATCH", "DELETE"),
            limit=_env_int("MUTATION_RATE_LIMIT_PER_MINUTE", 90, minimum=1, maximum=5000),
            window_seconds=60,
        ),
    ]


def match_rate_limit_rule(path: str, method: str) -> RateLimitRule | None:
    if not _enabled():
        return None
    normalized_method = str(method or "").upper()
    for rule in rate_limit_rules():
        if normalized_method not in rule.methods:
            continue
        if any(str(path or "").startswith(prefix) for prefix in rule.path_prefixes):
            return rule
    return None


def check_rate_limit(
    *,
    identity: str,
    path: str,
    method: str,
    now: float | None = None,
) -> RateLimitDecision:
    rule = match_rate_limit_rule(path, method)
    if rule is None:
        return RateLimitDecision(allowed=True)

    current_time = time.monotonic() if now is None else now
    key = (rule.name, identity or "unknown")
    cutoff = current_time - rule.window_seconds

    with _lock:
        _cleanup_expired_buckets_unlocked(current_time)
        bucket = _events[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= rule.limit:
            oldest = bucket[0]
            retry_after = max(1, int((oldest + rule.window_seconds) - current_time))
            return RateLimitDecision(
                allowed=False,
                rule_name=rule.name,
                limit=rule.limit,
                remaining=0,
                reset_seconds=retry_after,
                retry_after_seconds=retry_after,
            )

        bucket.append(current_time)
        remaining = max(0, rule.limit - len(bucket))
        reset_seconds = rule.window_seconds
        if bucket:
            reset_seconds = max(1, int((bucket[0] + rule.window_seconds) - current_time))
        return RateLimitDecision(
            allowed=True,
            rule_name=rule.name,
            limit=rule.limit,
            remaining=remaining,
            reset_seconds=reset_seconds,
        )


def reset_rate_limit_state() -> None:
    global _last_cleanup_at
    with _lock:
        _events.clear()
        _last_cleanup_at = 0.0


def _cleanup_expired_buckets_unlocked(current_time: float) -> None:
    global _last_cleanup_at
    if current_time - _last_cleanup_at < 60:
        return
    rules_by_name = {rule.name: rule for rule in rate_limit_rules()}
    for key, bucket in list(_events.items()):
        rule = rules_by_name.get(key[0])
        if rule is None:
            del _events[key]
            continue
        cutoff = current_time - rule.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            del _events[key]
    _last_cleanup_at = current_time


def rate_limit_status() -> dict[str, object]:
    rules = rate_limit_rules()
    with _lock:
        active_buckets = len(_events)
        active_events = sum(len(bucket) for bucket in _events.values())
    return {
        "enabled": _enabled(),
        "active_buckets": active_buckets,
        "active_events": active_events,
        "rules": [
            {
                "name": rule.name,
                "path_prefixes": list(rule.path_prefixes),
                "methods": list(rule.methods),
                "limit": rule.limit,
                "window_seconds": rule.window_seconds,
            }
            for rule in rules
        ],
    }
