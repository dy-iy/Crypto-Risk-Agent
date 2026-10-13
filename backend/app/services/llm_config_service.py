from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from os import getenv


EXPECTED_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_TIMEOUT = 30.0
MIN_DEEPSEEK_TIMEOUT = 1.0
MAX_DEEPSEEK_TIMEOUT = 120.0


@dataclass(frozen=True)
class DeepSeekConfig:
    model: str
    base_url: str
    timeout: float
    raw_timeout: str
    timeout_valid: bool


def _parse_timeout(raw: str) -> tuple[float, bool]:
    if not raw.strip():
        return DEFAULT_DEEPSEEK_TIMEOUT, True
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DEEPSEEK_TIMEOUT, False
    if not isfinite(value) or value < MIN_DEEPSEEK_TIMEOUT or value > MAX_DEEPSEEK_TIMEOUT:
        return DEFAULT_DEEPSEEK_TIMEOUT, False
    return value, True


def get_deepseek_config() -> DeepSeekConfig:
    raw_timeout = getenv("DEEPSEEK_TIMEOUT", "").strip()
    timeout, timeout_valid = _parse_timeout(raw_timeout)
    return DeepSeekConfig(
        model=getenv("DEEPSEEK_MODEL", EXPECTED_DEEPSEEK_MODEL).strip() or EXPECTED_DEEPSEEK_MODEL,
        base_url=getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL,
        timeout=timeout,
        raw_timeout=raw_timeout,
        timeout_valid=timeout_valid,
    )
