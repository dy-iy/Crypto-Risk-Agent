from __future__ import annotations

import os
from typing import Mapping


CSRF_HEADER_NAME = "x-cryptorisk-csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_request_allowed(
    *,
    method: str,
    cookies: Mapping[str, str],
    headers: Mapping[str, str],
    session_cookie_name: str,
) -> bool:
    if os.getenv("CSRF_PROTECTION_ENABLED", "1").strip() == "0":
        return True
    if method.upper() not in UNSAFE_METHODS:
        return True
    if not cookies.get(session_cookie_name):
        return True
    return headers.get(CSRF_HEADER_NAME, "") == "1"
