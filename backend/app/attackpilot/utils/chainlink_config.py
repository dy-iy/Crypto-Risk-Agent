"""Validated, network-specific configuration for public Chainlink USD feeds.

Only native ETH/BNB and their canonical wrapped forms are included by default.
In particular, a feed for an asset on BSC is not automatically a feed for a
Binance-Peg or bridged token with the same ticker.

The catalog heartbeat is an observation of today's configuration, not proof of
the heartbeat in a historical block. ``max_age_seconds`` is a separate, explicit
application policy for historical valuation. No account, key or wallet is used.
"""

from copy import deepcopy
from datetime import date
import json
import math
import os
import re
from urllib.parse import urlsplit


NATIVE_TOKEN_ADDRESS = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
CHAIN_IDS = {"Ethereum": 1, "BNBChain": 56}
_PLATFORMS = {"Ethereum": "Ethereum", "ethereum": "Ethereum", "BNBChain": "BNBChain", "bsc": "BNBChain", "BSC": "BNBChain"}
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_ASSET = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,23}\Z")


class ChainlinkConfigurationError(ValueError):
    """Configuration is invalid; the message never contains supplied values."""


def canonical_platform(platform: str) -> str | None:
    return _PLATFORMS.get(platform) if isinstance(platform, str) else None


def normalize_token_address(address: str) -> str | None:
    if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
        return None
    address = address.lower()
    return NATIVE_TOKEN_ADDRESS if address == ZERO_ADDRESS else address


def _feed(platform: str, symbol: str, proxy: str, heartbeat: int, path: str) -> dict:
    return {
        "chain_id": CHAIN_IDS[platform],
        "proxy_address": proxy.lower(),
        "pair": f"{symbol}/USD",
        "base_asset": symbol,
        "quote_asset": "USD",
        "token_symbol": symbol,
        "token_decimals": 18,
        "feed_decimals": 8,
        # A valuation policy, deliberately distinct from current feed metadata.
        "max_age_seconds": 3600,
        "heartbeat_seconds": heartbeat,
        "heartbeat_observed_at": "2026-10-21",
        "heartbeat_scope": "current_catalog_only",
        "configuration_origin": "official_catalog",
        "source_url": f"https://data.chain.link/feeds/{path}",
        "reference_directory_url": (
            "https://reference-data-directory.vercel.app/feeds-mainnet.json"
            if platform == "Ethereum"
            else "https://reference-data-directory.vercel.app/feeds-bsc-mainnet.json"
        ),
    }


# Standard proxy addresses (not the aggregator or an SVR proxy). Catalog source:
# https://github.com/smartcontractkit/documentation/blob/main/src/features/data/chains.ts
# and its network-specific reference directory JSON, checked 2026-10-21.
_ETH = _feed("Ethereum", "ETH", "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419", 3600, "ethereum/mainnet/eth-usd")
_BNB = _feed("BNBChain", "BNB", "0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE", 27, "bsc/mainnet/bnb-usd")
DEFAULT_FEEDS = {
    "Ethereum": {
        NATIVE_TOKEN_ADDRESS: {**_ETH, "mapping_type": "native_reference"},
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": {**_ETH, "token_symbol": "WETH", "mapping_type": "wrapped_native_reference"},
    },
    "BNBChain": {
        NATIVE_TOKEN_ADDRESS: {**_BNB, "mapping_type": "native_reference"},
        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": {**_BNB, "token_symbol": "WBNB", "mapping_type": "wrapped_native_reference"},
    },
}


def _positive_number(value, field: str, *, maximum: float, integral: bool = True):
    if isinstance(value, bool):
        raise ChainlinkConfigurationError(f"Invalid Chainlink configuration: {field}.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ChainlinkConfigurationError(f"Invalid Chainlink configuration: {field}.") from None
    if not math.isfinite(number) or number <= 0 or (integral and not number.is_integer()):
        raise ChainlinkConfigurationError(f"Invalid Chainlink configuration: {field}.")
    number = min(number, maximum)
    return int(number) if integral else number


def _boolean_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ChainlinkConfigurationError(f"Invalid Chainlink configuration: {name}.")


def _source_url(value, field: str) -> str:
    if not isinstance(value, str):
        raise ChainlinkConfigurationError(f"Invalid Chainlink feed: {field}.")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in {"data.chain.link", "docs.chain.link", "reference-data-directory.vercel.app"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 443}
            and not parsed.query
            and not parsed.fragment
            and bool(parsed.path)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ChainlinkConfigurationError(f"Invalid Chainlink feed: {field}.")
    return value


def _validate_feed(platform: str, address: str, value: dict, previous: dict | None) -> dict:
    if not isinstance(value, dict):
        raise ChainlinkConfigurationError("Invalid Chainlink feed configuration.")
    allowed = {
        "chain_id", "proxy_address", "pair", "base_asset", "quote_asset", "token_symbol",
        "token_decimals", "feed_decimals", "max_age_seconds", "heartbeat_seconds",
        "heartbeat_observed_at", "heartbeat_scope", "source_url", "reference_directory_url", "mapping_type",
    }
    if set(value) - allowed:
        raise ChainlinkConfigurationError("Unknown Chainlink feed configuration field.")
    result = {**(previous or {}), **value}
    # A different proxy or base asset must not inherit the bundled feed's
    # observed heartbeat or reference-directory attribution.
    if previous and any(value.get(field, previous.get(field)) != previous.get(field) for field in ("proxy_address", "base_asset", "feed_decimals")):
        for field in ("heartbeat_seconds", "heartbeat_observed_at", "reference_directory_url"):
            if field not in value:
                result.pop(field, None)
        if "source_url" not in value:
            raise ChainlinkConfigurationError("An overridden Chainlink proxy or asset requires an explicit source URL.")
    required = {"proxy_address", "base_asset", "quote_asset", "token_decimals", "feed_decimals", "max_age_seconds", "source_url"}
    if not required.issubset(result):
        raise ChainlinkConfigurationError("Missing required Chainlink feed configuration.")
    if result.get("chain_id", CHAIN_IDS[platform]) != CHAIN_IDS[platform] or isinstance(result.get("chain_id"), bool):
        raise ChainlinkConfigurationError("Chainlink feed chain ID does not match its network.")
    result["chain_id"] = CHAIN_IDS[platform]
    proxy = result["proxy_address"]
    if not isinstance(proxy, str) or not _ADDRESS.fullmatch(proxy) or proxy.lower() in {ZERO_ADDRESS, NATIVE_TOKEN_ADDRESS}:
        raise ChainlinkConfigurationError("Invalid Chainlink feed proxy address.")
    result["proxy_address"] = proxy.lower()
    base = result["base_asset"]
    if not isinstance(base, str) or not _ASSET.fullmatch(base) or result["quote_asset"] != "USD":
        raise ChainlinkConfigurationError("Chainlink feed must identify an explicit USD asset pair.")
    if result.get("pair", f"{base}/USD") != f"{base}/USD":
        raise ChainlinkConfigurationError("Chainlink feed pair does not match its assets.")
    result["pair"] = f"{base}/USD"
    symbol = result.get("token_symbol", base)
    if not isinstance(symbol, str) or not _ASSET.fullmatch(symbol):
        raise ChainlinkConfigurationError("Invalid Chainlink feed token symbol.")
    result["token_symbol"] = symbol
    for field in ("token_decimals", "feed_decimals"):
        number = result[field]
        if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= 36:
            raise ChainlinkConfigurationError(f"Invalid Chainlink feed: {field}.")
    result["max_age_seconds"] = _positive_number(result["max_age_seconds"], "max_age_seconds", maximum=604800)
    if "heartbeat_seconds" in result:
        result["heartbeat_seconds"] = _positive_number(result["heartbeat_seconds"], "heartbeat_seconds", maximum=604800)
    if "heartbeat_observed_at" in result:
        try:
            date.fromisoformat(result["heartbeat_observed_at"])
        except (TypeError, ValueError):
            raise ChainlinkConfigurationError("Invalid Chainlink feed heartbeat observation date.") from None
    if result.get("heartbeat_scope", "current_catalog_only") != "current_catalog_only":
        raise ChainlinkConfigurationError("Chainlink catalog heartbeat is not historical evidence.")
    result["heartbeat_scope"] = "current_catalog_only"
    result["source_url"] = _source_url(result["source_url"], "source_url")
    if "reference_directory_url" in result:
        result["reference_directory_url"] = _source_url(result["reference_directory_url"], "reference_directory_url")
    mapping = result.get("mapping_type", "explicit_token_reference")
    if mapping not in {"native_reference", "wrapped_native_reference", "explicit_token_reference"}:
        raise ChainlinkConfigurationError("Invalid Chainlink feed mapping type.")
    result["mapping_type"] = mapping
    result["token_address"] = address
    # An administrator's explicit mapping is not independently verified by the
    # bundled catalog, even when it cites an official documentation URL.
    result["configuration_origin"] = "configured_override"
    return result


def get_chainlink_config() -> dict:
    """Load bounded settings and validated per-network token/feed overrides.

    ``ATTACKPILOT_CHAINLINK_FEEDS`` merges a JSON mapping of canonical platform
    names to token-address mappings. A feed value of ``null`` removes only that
    mapping. A new mapping requires explicit asset/decimal/source information;
    symbols alone never select feeds. Invalid settings raise a safe error and
    must not silently select a feed from another chain or another provider.
    """
    config = {
        "enabled": _boolean_env("ATTACKPILOT_CHAINLINK_ENABLED", True),
        "timeout_seconds": _positive_number(os.getenv("ATTACKPILOT_CHAINLINK_TOTAL_TIMEOUT_SECONDS", "30"), "total_timeout_seconds", maximum=120, integral=False),
        "request_timeout_seconds": _positive_number(os.getenv("ATTACKPILOT_CHAINLINK_REQUEST_TIMEOUT_SECONDS", "8"), "request_timeout_seconds", maximum=30, integral=False),
        "max_rpc_calls": _positive_number(os.getenv("ATTACKPILOT_CHAINLINK_MAX_RPC_CALLS", "64"), "max_rpc_calls", maximum=200),
        "max_history_rounds": _positive_number(os.getenv("ATTACKPILOT_CHAINLINK_MAX_HISTORY_ROUNDS", "32"), "max_history_rounds", maximum=64),
        "max_phases": _positive_number(os.getenv("ATTACKPILOT_CHAINLINK_MAX_PHASES", "8"), "max_phases", maximum=32),
        "feeds": deepcopy(DEFAULT_FEEDS),
    }
    config["request_timeout_seconds"] = min(config["request_timeout_seconds"], config["timeout_seconds"])
    raw = os.getenv("ATTACKPILOT_CHAINLINK_FEEDS", "{}")
    if len(raw) > 131072:
        raise ChainlinkConfigurationError("Chainlink feed configuration exceeds its size limit.")
    try:
        overrides = json.loads(raw)
    except (TypeError, ValueError):
        raise ChainlinkConfigurationError("Invalid Chainlink feed configuration JSON.") from None
    if not isinstance(overrides, dict) or set(overrides) - set(CHAIN_IDS):
        raise ChainlinkConfigurationError("Unsupported network in Chainlink feed configuration.")
    for platform, feeds in overrides.items():
        if not isinstance(feeds, dict) or len(feeds) > 128:
            raise ChainlinkConfigurationError("Invalid Chainlink network feed mapping.")
        normalized = set()
        for key, value in feeds.items():
            address = normalize_token_address(key)
            if address is None or address in normalized:
                raise ChainlinkConfigurationError("Invalid or duplicate Chainlink token address.")
            normalized.add(address)
            if value is None:
                config["feeds"][platform].pop(address, None)
            else:
                config["feeds"][platform][address] = _validate_feed(platform, address, value, config["feeds"][platform].get(address))
    for feeds in config["feeds"].values():
        for address, value in feeds.items():
            value["token_address"] = address
    return config


def get_chainlink_feed(platform: str, token_address: str, config: dict | None = None) -> dict | None:
    """Return a copy of the exact network/address mapping, or ``None``."""
    network = canonical_platform(platform)
    address = normalize_token_address(token_address)
    if network is None or address is None:
        return None
    config = get_chainlink_config() if config is None else config
    feed = config.get("feeds", {}).get(network, {}).get(address)
    return deepcopy(feed) if feed else None
