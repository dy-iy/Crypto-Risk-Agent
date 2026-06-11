from __future__ import annotations

import re

from app.services.auth_service import get_user_by_session
from app.services.sim_engine import DEFAULT_SIM_ACCOUNT_ID


GUEST_SIM_ACCOUNT_PREFIX = "guest"


def safe_sim_account_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "").strip())[:80]
    return normalized.strip("._-")


def resolve_sim_account_id(
    cryptorisk_session: str | None,
    sim_client_id: str | None,
) -> str:
    user = get_user_by_session(cryptorisk_session)
    if user:
        return user.id
    client_fragment = safe_sim_account_fragment(sim_client_id)
    if client_fragment:
        return f"{GUEST_SIM_ACCOUNT_PREFIX}:{client_fragment}"
    return DEFAULT_SIM_ACCOUNT_ID
