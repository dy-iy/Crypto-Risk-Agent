import asyncio
import hashlib
import json
import os
import math
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal, InvalidOperation

import aiohttp
from typing import Dict, Union
from app.attackpilot.settings import CACHE_DIR

HTTP_PROXY = None
PRICE_CACHE_VERSION = 3
_quote_scope = ContextVar('attackpilot_price_quote_scope', default=None)
platform_to_chain = {
    "Ethereum": "ethereum",
    "BNBChain": "bsc"
}


@asynccontextmanager
async def price_quote_scope():
    """Reuse one complete quote per task, including unavailable vendor evidence."""
    requests = {}
    token = _quote_scope.set(requests)
    try:
        yield
    finally:
        try:
            for task in requests.values():
                if not task.done():
                    task.cancel()
            if requests:
                await asyncio.gather(*requests.values(), return_exceptions=True)
        finally:
            _quote_scope.reset(token)


def load_from_file(filepath: str) -> Union[Dict, None]:
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error occurred while reading the cache file (requesting again): {filepath}, Error: {e}")
            return None
    return None


def save_to_file(filepath: str, data: Dict):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            print(f"Data saved in: {filepath}")

    except Exception as e:
        print(f"Write cache error: {filepath}, error: {e}")


async def _get_defillama_price(
        chain: str,
        address: str,
        timestamp: int,
        search_width: str = '4h'
) -> Dict:

    filename = f"{chain}_{address}_{timestamp}.json"
    filepath = os.path.join(CACHE_DIR, 'price', filename)
    cached_data = load_from_file(filepath)
    coin_key = f"{chain}:{address}"
    url = f'https://coins.llama.fi/prices/historical/{timestamp}/{coin_key}?searchWidth={search_width}'

    # Older caches stored the requested time as if it were the quote time.
    # Refetch them rather than assigning a timestamp the provider never returned.
    if (
        isinstance(cached_data, dict)
        and cached_data.get('schema_version') == PRICE_CACHE_VERSION
        and cached_data.get('chain') == chain
        and cached_data.get('contract_address') == address
        and cached_data.get('requested_timestamp') == timestamp
        and cached_data.get('search_width') == search_width
        and cached_data.get('source') == 'defillama'
        and cached_data.get('source_url') == url
        and 'timestamp' in cached_data
    ):
        return cached_data

    proxy = None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as client:
        try:
            async with client.get(url, headers={'Accept': 'application/json'}, proxy=proxy) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'coins' in data and coin_key in data['coins']:
                        info = data['coins'][coin_key]

                        quote_timestamp = info.get('timestamp')
                        try:
                            parsed_timestamp = int(quote_timestamp)
                            if (
                                isinstance(quote_timestamp, bool)
                                or parsed_timestamp <= 0
                                or parsed_timestamp != float(quote_timestamp)
                            ):
                                parsed_timestamp = None
                        except (TypeError, ValueError, OverflowError):
                            parsed_timestamp = None

                        result = {
                            "schema_version": PRICE_CACHE_VERSION,
                            "contract_address": address,
                            "chain": chain,
                            "requested_timestamp": timestamp,
                            # A historical request can return a nearby quote;
                            # an absent provider time must remain unknown.
                            "timestamp": parsed_timestamp,
                            "price": float(info.get('price', 0)),
                            "symbol": info.get('symbol', 'Unknown'),
                            "decimals": _token_precision(info.get('decimals')),
                            "confidence": info.get('confidence', 0),
                            "source": "defillama",
                            "source_url": url,
                            "search_width": search_width
                        }

                        if parsed_timestamp is not None and parsed_timestamp <= timestamp and math.isfinite(result['price']) and result['price'] > 0:
                            save_to_file(filepath, result)
                        return result
                    else:
                        return {}
        except Exception as e:
            print(f"Network Error: {e}")
            return {}
    return {}


def pricing_policy_fingerprint() -> str:
    """Invalidate derived reports when feeds, limits, or valuation policy change."""
    from app.attackpilot.utils.chainlink_config import get_chainlink_config
    from app.attackpilot.utils.chainlink import STRATEGY
    try:
        config = get_chainlink_config()
    except ValueError:
        config = {"configuration": "invalid"}
    policy = {"version": 2, "chainlink": config, "chainlink_strategy": STRATEGY, "covered_feed_failure": "unpriced",
              "defillama": "past_quote_only", "comparison_max_skew_seconds": 300}
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def collect_price_evidence(processed: dict) -> dict:
    references = {}
    for tx, accounts in (processed.get('balance_change') or {}).items():
        if not isinstance(accounts, dict):
            continue
        assets = {}
        for balances in accounts.values():
            if not isinstance(balances, dict):
                continue
            for token, balance in balances.items():
                if isinstance(balance, dict) and isinstance(balance.get('price_evidence'), dict):
                    assets[token.lower()] = balance['price_evidence']
        if assets:
            references[tx] = assets
    return {'schema_version': 1, 'reference_prices': references,
            'protocol_oracle_reads': {
                tx: detail['oracle_evidence'] for tx, detail in (processed.get('transaction_to_detail') or {}).items()
                if isinstance(detail, dict) and isinstance(detail.get('oracle_evidence'), dict)
            }}


def price_evidence_retryable(data: dict) -> bool:
    """Incomplete vendor results may recover; do not pin a rerun to them."""
    evidence = data.get('price_evidence') or collect_price_evidence(data)
    if not isinstance(evidence, dict) or not isinstance(evidence.get('reference_prices', {}), dict):
        return True
    if any(not isinstance(assets, dict) or any(not isinstance(quote, dict) for quote in assets.values())
           for assets in evidence.get('reference_prices', {}).values()):
        return True
    return any(quote.get('valuation_status') == 'unavailable'
               for assets in evidence.get('reference_prices', {}).values() for quote in assets.values())


def _defillama_quote(raw: dict, chain: str, address: str, timestamp: int, search_width: str) -> dict:
    quote = dict(raw) if isinstance(raw, dict) else {}
    quote.update(chain=chain, contract_address=address, requested_timestamp=timestamp, source="defillama")
    reason = "missing_quote"
    try:
        value = Decimal(str(quote.get("price")))
        updated = quote.get("timestamp")
        width = re.fullmatch(r"([1-9][0-9]*)([mhd])", search_width)
        max_age = int(width[1]) * {"m": 60, "h": 3600, "d": 86400}[width[2]] if width else 14400
        if not value.is_finite() or value <= 0 or not math.isfinite(float(value)):
            reason = "invalid_answer"
        elif type(updated) is not int or updated <= 0:
            reason = "missing_timestamp"
        elif updated > timestamp:
            reason = "future_quote"
        elif timestamp - updated > max_age:
            reason = "stale_quote"
        else:
            quote.update(price=float(value), price_exact=str(value), quote_status="available", valuation_status="available")
            return quote
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        pass
    quote.update(price=None, quote_status="unavailable", valuation_status="unavailable", reason_code=reason)
    return quote


def _token_precision(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        return parsed if 0 <= parsed <= 255 and Decimal(str(value)) == parsed else None
    except (TypeError, ValueError, ArithmeticError):
        return None


def price_block_context(transaction):
    """Extract an exact block hint; the price reader verifies it against RPC."""
    if not isinstance(transaction, dict):
        return None
    number = transaction.get('block_number', transaction.get('number'))
    # A transaction's `hash` identifies the transaction, not its block.
    block_hash = transaction.get('block_hash') if 'block_number' in transaction else transaction.get('hash')
    timestamp = transaction.get('timestamp')
    if (type(number) is not int or number <= 0 or type(timestamp) is not int or timestamp <= 0
            or not isinstance(block_hash, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', block_hash)):
        return None
    return {'number': number, 'hash': block_hash.lower(), 'timestamp': timestamp}


def _vendor_comparison(primary: dict, alternative: dict) -> dict:
    """Comparison of vendor references; provider independence is not assumed."""
    result = {"status": "unavailable", "independence_verified": False,
              "max_timestamp_skew_seconds": 300}
    if primary.get("status") != "available" or alternative.get("valuation_status") != "available":
        return result
    skew = abs(primary["timestamp"] - alternative["timestamp"])
    result["timestamp_skew_seconds"] = skew
    if skew > 300:
        return {**result, "status": "not_comparable", "reason_code": "timestamp_misalignment"}
    base = Decimal(str(primary["price"]))
    deviation = abs(Decimal(str(alternative["price"])) - base) / base * 100
    if not math.isfinite(float(deviation)):
        return {**result, "status": "not_comparable", "reason_code": "comparison_out_of_range"}
    return {**result, "status": "compared", "deviation_percent": float(deviation),
            "primary_source": "chainlink", "comparison_source": "defillama"}


async def _get_single_token_price(chain: str, address: str, timestamp: int,
                                  search_width: str = '4h', *, block_context=None) -> Dict:
    from app.attackpilot.utils.chainlink import get_chainlink_price
    chain = str(chain).lower()
    address = str(address).lower()
    base = {"schema_version": 3, "chain": chain, "contract_address": address,
            "requested_timestamp": timestamp, "price": None, "timestamp": None,
            "quote_status": "unavailable", "valuation_status": "unavailable"}
    if chain not in platform_to_chain.values() or not re.fullmatch(r"0x[0-9a-f]{40}", address):
        return {**base, "source": "unavailable", "reason_code": "unsupported_asset"}
    if type(timestamp) is not int or timestamp <= 0:
        return {**base, "source": "unavailable", "reason_code": "invalid_timestamp"}
    try:
        oracle = await get_chainlink_price(chain, address, timestamp, **(
            {'block_context': block_context} if block_context is not None else {}))
    except ValueError:
        return {**base, "source": "unavailable", "reason_code": "configuration_error",
                "chainlink": {"status": "unavailable", "reason_code": "configuration_error"}}
    oracle = {**oracle, "reason_code": oracle.get("reason_code", oracle.get("reason")),
              "network_id": oracle.get("network_id", oracle.get("chain_id"))}
    # A failed quote does not erase an explicitly configured asset identity.
    # Keep canonical wrapped-token metadata separate from price availability.
    base.update({key: oracle[key] for key in ('symbol', 'token_decimals', 'decimals')
                 if oracle.get(key) is not None})
    if oracle.get('reason_code') == 'invalid_feed_configuration':
        return {**base, "source": "unavailable", "reason_code": "configuration_error", "chainlink": oracle}
    try:
        alternative_raw = await _get_defillama_price(chain, address, timestamp, search_width)
    except (aiohttp.ClientError, TimeoutError, ValueError, ArithmeticError):
        alternative_raw = {}
    alternative = _defillama_quote(
        alternative_raw,
        chain, address, timestamp, search_width,
    )
    if oracle.get("status") == "available":
        return {**base, **oracle, "schema_version": 3, "source": "chainlink",
                "quote_status": "available", "valuation_status": "available",
                "chainlink": dict(oracle), "alternative_quote": alternative,
                "vendor_comparison": _vendor_comparison(oracle, alternative)}
    if oracle.get("status") in {"unsupported", "disabled"}:
        return {**base, **alternative, "schema_version": 3, "chainlink": dict(oracle),
                "fallback_reason": "feed_not_configured" if oracle["status"] == "unsupported" else "chainlink_disabled"}
    # A configured feed with insufficient evidence is not silently replaced by a
    # different source. Preserve that source separately for manual review.
    return {**base, "source": "chainlink", "chainlink": dict(oracle),
            "quote_status": oracle.get("status", "unavailable"),
            "reason_code": oracle.get("reason_code", oracle.get("reason", "missing_quote")),
            "alternative_quote": alternative}


async def get_single_token_price(chain: str, address: str, timestamp: int,
                                 search_width: str = '4h', *, block_context=None) -> Dict:
    block_context = price_block_context(block_context)
    requests = _quote_scope.get()
    if requests is None or type(timestamp) is not int or not isinstance(search_width, str):
        return await _get_single_token_price(chain, address, timestamp, search_width, block_context=block_context)
    chain, address = str(chain).lower(), str(address).lower()
    context_key = tuple(block_context[key] for key in ('number', 'hash', 'timestamp')) if block_context else None
    key = (pricing_policy_fingerprint(), chain, address, timestamp, search_width, context_key)
    task = requests.get(key)
    if task is None:
        task = asyncio.create_task(_get_single_token_price(chain, address, timestamp, search_width,
                                                        block_context=block_context))
        requests[key] = task
    try:
        # An individual consumer's cancellation must not invalidate another
        # consumer's quote. The owning scope cancels remaining work on exit.
        return deepcopy(await asyncio.shield(task))
    except Exception:
        if requests.get(key) is task:
            requests.pop(key)
        raise


async def get_token_price(coins: str, timestamp: int, *, block_context=None) -> Dict:
    """
    coins : "chain:address,chain:address"
    """
    result = {}
    # Keep the free RPC from receiving an unbounded fan-out for large reports.
    semaphore = asyncio.Semaphore(2)
    coin_list = sorted({coin.strip().lower() for coin in coins.split(',') if ':' in coin})
    async def resolve(coin):
        async with semaphore:
            chain, address = coin.split(':', 1)
            try:
                return await get_single_token_price(chain, address, timestamp, block_context=block_context)
            except (aiohttp.ClientError, TimeoutError, ValueError, ArithmeticError):
                return {"chain": chain, "contract_address": address, "requested_timestamp": timestamp,
                        "price": None, "source": "unavailable", "quote_status": "unavailable",
                        "valuation_status": "unavailable", "reason_code": "price_service_unavailable"}
    items = await asyncio.gather(*(resolve(coin) for coin in coin_list))
    for coin, item in zip(coin_list, items):
        if item:
            result[coin] = item
    return result


