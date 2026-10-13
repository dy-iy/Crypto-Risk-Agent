from __future__ import annotations

import hashlib
from os import getenv
from typing import Mapping


def trust_proxy_headers_enabled() -> bool:
    return getenv("TRUST_PROXY_HEADERS", "1").strip() != "0"


def request_uses_https(scheme: str, headers: Mapping[str, str]) -> bool:
    if str(scheme or "").lower() == "https":
        return True
    if not trust_proxy_headers_enabled():
        return False
    forwarded_proto = str(headers.get("x-forwarded-proto") or "")
    return forwarded_proto.split(",", 1)[0].strip().lower() == "https"


def request_client_identity(client_host: str | None, headers: Mapping[str, str]) -> str:
    if trust_proxy_headers_enabled():
        forwarded_for = str(headers.get("x-forwarded-for") or "")
        # The edge Nginx appends the real client; the leftmost value is client-controlled.
        if forwarded_for:
            return forwarded_for.rsplit(",", 1)[-1].strip()[:128] or "unknown"
    return str(client_host or "")[:128] or "unknown"


def client_ip_hash(client_ip: str | None) -> str:
    normalized = str(client_ip or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12] if normalized else ""


def safe_user_agent(value: str | None) -> str:
    normalized = " ".join(str(value or "").strip().split())
    return normalized[:160]


def request_security_context(client_ip: str | None, user_agent: str | None) -> dict[str, str]:
    return {
        "client_ip_hash": client_ip_hash(client_ip),
        "user_agent": safe_user_agent(user_agent),
    }
