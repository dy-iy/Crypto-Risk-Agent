from __future__ import annotations

import os
from typing import Any


DEFAULT_MAX_REQUEST_BODY_BYTES = 1_000_000
MIN_REQUEST_BODY_BYTES = 16_384
MAX_REQUEST_BODY_BYTES_LIMIT = 10_000_000
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def max_request_body_bytes() -> int:
    raw = os.getenv("MAX_REQUEST_BODY_BYTES", "").strip()
    if not raw:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_REQUEST_BODY_BYTES
    return max(MIN_REQUEST_BODY_BYTES, min(MAX_REQUEST_BODY_BYTES_LIMIT, value))


def content_length_exceeds_limit(headers: Any, limit_bytes: int) -> bool:
    raw = str(headers.get("content-length", "") or "").strip()
    if not raw:
        return False
    try:
        return int(raw) > limit_bytes
    except ValueError:
        return False


async def request_body_exceeds_limit(request: Any, limit_bytes: int) -> bool:
    if str(getattr(request, "method", "")).upper() not in BODY_METHODS:
        return False
    if content_length_exceeds_limit(request.headers, limit_bytes):
        return True
    if not hasattr(request, "stream"):
        return len(await request.body()) > limit_bytes
    # Measure actual bytes, including chunked requests and misleading headers.
    parts = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit_bytes:
            return True
        parts.append(chunk)
    # Starlette's middleware forwards this cached body to the downstream route.
    request._body = b"".join(parts)
    return False
