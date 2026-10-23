from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from math import isfinite
from typing import Dict, Tuple, Any, Set

from app.attackpilot.utils.price import get_token_price, platform_to_chain
from app.attackpilot.utils.signature import parse_quantity
from app.attackpilot.utils.token_utils import ERC20_TRANSFER_TOPIC, parse_address, format_amount

NATIVE_TOKEN_ADDRESS = '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
ZERO_ADDRESS = '0x' + '0' * 40
NATIVE_TOKEN_ALIASES = {NATIVE_TOKEN_ADDRESS, ZERO_ADDRESS}
CHAIN_CONFIG = {
    'ethereum': {
        'wrapped': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',  # WETH
        'symbol': 'ETH',
        'name': 'Ether'
    },
    'bsc': {
        'wrapped': '0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c',  # WBNB
        'symbol': 'BNB',
        'name': 'BNB'
    }
}


def quote_price(quote: Any):
    """Return a usable valuation price without converting missing evidence to zero."""
    if isinstance(quote, dict):
        if quote.get('valuation_status') == 'unavailable':
            return None
        if quote.get('quote_status') in {'unavailable', 'stale'}:
            return None
        quote = quote.get('price')
    if quote is None or isinstance(quote, bool):
        return None
    try:
        value = float(quote)
        return value if isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _token_decimals(metadata: Dict, quote: Any):
    # Feed precision describes a USD quote; it never describes token units.
    value = metadata.get('decimals')
    if value is None and isinstance(quote, dict):
        value = quote.get('decimals')
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(value)
        return result if 0 <= result <= 255 and Decimal(str(value)) == result else None
    except (TypeError, ValueError, ArithmeticError):
        return None


def _usd_value(amount, price):
    if amount is None or price is None:
        return None
    value = amount * price
    return value if isfinite(value) else None


def enrich_valuation_asset_identity(quote: Dict, asset_info: Dict) -> Dict:
    """Attach known balance identity without changing provider or price evidence."""
    evidence = deepcopy(quote)
    original = evidence.get('valuation_asset')
    identity = dict(original) if isinstance(original, dict) else {}
    for field in ('symbol', 'name'):
        value = asset_info.get(field)
        if (isinstance(value, str) and value.strip()
                and value.strip().casefold() not in {'unknown', 'unknown token', '未知', '未知资产', '未知代币'}):
            identity[field] = value.strip()
    decimals = _token_decimals(asset_info, None)
    if decimals is not None:
        identity['decimals'] = decimals
    if identity:
        evidence['valuation_asset'] = identity
    return evidence


def _price_evidence_lines(quote: Dict) -> list[str]:
    lines = [
        f"      Price source: {quote.get('source', 'Unknown')}; "
        f"valuation_status: {quote.get('valuation_status', 'available' if quote_price(quote) is not None else 'unavailable')}; "
        f"requested_timestamp: {quote.get('requested_timestamp')}; "
        f"quote_timestamp: {quote.get('timestamp')}; "
        f"confidence: {quote.get('confidence')}"
    ]
    if quote.get('source_url'):
        lines.append(f"      Price source URL: {quote['source_url']}")
    feed = quote.get('chainlink')
    if isinstance(feed, dict):
        lines.append(
            f"      Chainlink reference: status={feed.get('status', 'unavailable')}; "
            f"reason={feed.get('reason_code', feed.get('reason'))}; pair={feed.get('pair')}; "
            f"feed_address={feed.get('feed_address')}; network_id={feed.get('network_id', feed.get('chain_id'))}; "
            f"round_id={feed.get('round_id')}; answer={feed.get('answer')}; "
            f"feed_decimals={feed.get('feed_decimals')}; updated_at={feed.get('updated_at')}; "
            f"requested_timestamp={feed.get('requested_timestamp')}"
        )
    return lines


class BalanceAnalyzer:
    @staticmethod
    def safe_int(value: Any) -> int:
        return parse_quantity(value)

    @classmethod
    def parse_tenderly_data(cls, macro_data: Dict) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict]]:
        raw_balance_changes = defaultdict(lambda: defaultdict(int))
        extracted_metadata = {}
        balance_diff_entries = macro_data.get('balance_diff', []) or []
        for bd in balance_diff_entries:
            addr = (bd.get('address') or '').lower()
            if not addr: continue
            delta = cls.safe_int(bd.get('dirty')) - cls.safe_int(bd.get('original'))
            if delta != 0:
                raw_balance_changes[addr][NATIVE_TOKEN_ADDRESS] += delta

        # A receipt's raw Transfer records are authoritative. A provider can
        # omit individual asset_changes, so do not suppress all logs merely
        # because one transfer for the same token was supplied there.
        logged_tokens = set()
        nonfungible_tokens = set()
        for log in macro_data.get('logs', []) or []:
            raw = log.get('raw') or log
            topics = raw.get('topics', [])
            if (len(topics) == 4 and isinstance(topics[0], str)
                    and topics[0].lower() == ERC20_TRANSFER_TOPIC):
                nonfungible_tokens.add(raw['address'].lower())
            if (not topics or not isinstance(topics[0], str)
                    or topics[0].lower() != ERC20_TRANSFER_TOPIC or len(topics) != 3):
                # ERC-721 uses the same signature but has four topics; tokenId
                # must never become a fungible quantity or a USD valuation.
                continue
            token_addr = raw['address'].lower()
            f_addr = parse_address(topics[1]).lower()
            t_addr = parse_address(topics[2]).lower()
            amt = cls.safe_int(raw.get('data'))
            logged_tokens.add(token_addr)
            if amt > 0:
                if f_addr != ZERO_ADDRESS:
                    raw_balance_changes[f_addr][token_addr] -= amt
                if t_addr != ZERO_ADDRESS:
                    raw_balance_changes[t_addr][token_addr] += amt

        for asset in macro_data.get('asset_changes', []) or []:
            token_info = asset.get('token_info', {}) or {}
            token_addr = (token_info.get('contract_address') or '').lower()

            is_native = token_addr in NATIVE_TOKEN_ALIASES or not token_addr

            standard = str(token_info.get('standard') or '').upper().replace('-', '')
            if is_native or standard in {'ERC721', 'ERC1155'} or token_addr in nonfungible_tokens:
                continue

            from_addr = (asset.get('from') or '').lower()
            to_addr = (asset.get('to') or '').lower()
            if token_addr not in extracted_metadata:
                extracted_metadata[token_addr] = {
                    "symbol": token_info.get("symbol", "UNKNOWN"),
                    "name": token_info.get("name", "Unknown Token"),
                    "decimals": token_info.get("decimals"),
                    "contract": token_addr
                }

            if token_addr in logged_tokens:
                continue
            amount = cls.safe_int(asset.get('raw_amount'))
            if amount <= 0:
                continue

            if from_addr and from_addr != '0x' + '0' * 40:
                raw_balance_changes[from_addr][token_addr] -= amount
            if to_addr and to_addr != '0x' + '0' * 40:
                raw_balance_changes[to_addr][token_addr] += amount

        return raw_balance_changes, extracted_metadata

    @staticmethod
    def calculate_usd_values(
            raw_changes: Dict[str, Dict[str, int]],
            metadata: Dict[str, Dict],
            prices: Dict[str, Any],
            _platform: str
    ) -> Dict[str, Dict[str, Any]]:
        final_output = {}

        chain_slug = platform_to_chain.get(_platform)
        chain_config = CHAIN_CONFIG.get(chain_slug, {})
        native_symbol = chain_config.get('symbol', 'native')
        native_name = chain_config.get('name', 'Native Asset')

        for user_address, assets in raw_changes.items():
            if not user_address or user_address == '0x' + '0' * 40: continue

            user_assets = {}
            for asset_key, raw_amount in assets.items():
                if raw_amount == 0: continue

                asset_key_lower = asset_key.lower()
                quote = prices.get(asset_key_lower)
                price = quote_price(quote)

                if asset_key_lower in NATIVE_TOKEN_ALIASES:
                    decimals = 18
                    fmt_val = float(Decimal(raw_amount) / Decimal(10 ** decimals))
                    asset_info = {
                        "symbol": native_symbol,
                        "name": native_name,
                        "decimals": decimals,
                        "raw_amount": raw_amount,
                        "fmt_amount": format_amount(raw_amount, 18),
                        "usd_value": _usd_value(fmt_val, price),
                        "is_token": False,
                        "contract": "N/A"
                    }
                else:
                    meta = metadata.get(asset_key_lower, {})
                    decimals = _token_decimals(meta, quote)
                    fmt_val = float(Decimal(raw_amount) / Decimal(10 ** decimals)) if decimals is not None else None
                    asset_info = {
                        "symbol": meta.get('symbol', 'UNKNOWN'),
                        "name": meta.get('name', 'Unknown Token'),
                        "decimals": decimals,
                        "raw_amount": raw_amount,
                        "fmt_amount": format_amount(raw_amount, decimals) if decimals is not None else None,
                        "usd_value": _usd_value(fmt_val, price),
                        "is_token": True,
                        "contract": asset_key
                    }
                if isinstance(quote, dict):
                    asset_info['price_evidence'] = enrich_valuation_asset_identity(quote, asset_info)
                asset_info['valuation_status'] = 'available' if asset_info['usd_value'] is not None else 'unavailable'
                user_assets[asset_key] = asset_info

            if user_assets:
                final_output[user_address] = user_assets

        return final_output

    @staticmethod
    def calculate_usd_values_markdown(raw_changes: Dict[str, Dict[str, int]],
                                      metadata: Dict[str, Dict],
                                      prices: Dict[str, Any], *, platform: str | None = None) -> str:
        lines = ["\n### Balance Changes (Simulation Result)"]

        has_changes = False
        for user_addr, assets in raw_changes.items():
            user_lines = []
            for token_addr, raw_amount in assets.items():
                if raw_amount == 0: continue

                quote = prices.get(token_addr.lower())
                meta = metadata.get(token_addr.lower(), {})
                if token_addr.lower() in NATIVE_TOKEN_ALIASES:
                    chain_slug = platform_to_chain.get(platform)
                    if not chain_slug and isinstance(quote, dict):
                        chain_slug = quote.get('chain')
                    chain_config = CHAIN_CONFIG.get(chain_slug, {})
                    meta = {'decimals': 18, 'symbol': chain_config.get('symbol', 'native')}
                decimals = _token_decimals(meta, quote)
                symbol = meta.get('symbol') or (quote.get('symbol') if isinstance(quote, dict) else None) or 'UNKNOWN'
                price = quote_price(quote)
                fmt_amount = float(Decimal(raw_amount) / Decimal(10 ** decimals)) if decimals is not None else None
                usd_value = _usd_value(fmt_amount, price)

                if fmt_amount is None:
                    user_lines.append(f"    - {symbol}: raw_amount={raw_amount}; token decimals unavailable (USD unavailable)")
                else:
                    sign = "+" if fmt_amount > 0 else ""
                    user_lines.append(f"    - {symbol}: {sign}{fmt_amount:.4f} (${usd_value if usd_value is not None else 'Unknown'})")
                if isinstance(quote, dict):
                    user_lines.extend(_price_evidence_lines(quote))

            if user_lines:
                has_changes = True
                lines.append(f"- Address: {user_addr}")
                lines.extend(user_lines)

        if not has_changes:
            return "No significant balance changes detected."

        return "\n".join(lines)


async def fetch_token_prices(
        chain_slug: str,
        timestamp: int,
        token_addresses: Set[str],
        *,
        include_metadata: bool = False,
        block_context=None,
) -> Dict[str, Any]:
    """Resolve the chain's wrapped native token and optionally retain full quotes."""
    if not token_addresses or not timestamp:
        return {}

    chain_config = CHAIN_CONFIG.get(chain_slug)
    if not chain_config:
        return {}
    wrapped_address = chain_config['wrapped'].lower()

    final_query_list = []

    for addr in token_addresses:
        addr_lower = addr.lower()
        target = wrapped_address if addr_lower in NATIVE_TOKEN_ALIASES else addr_lower
        final_query_list.append(f"{chain_slug}:{target}")

    if not final_query_list:
        return {}

    final_query_str = ",".join(sorted(set(final_query_list)))
    price_results = {}

    try:
        prices = await get_token_price(final_query_str, timestamp, **(
            {'block_context': block_context} if block_context is not None else {}))

        for key, info in prices.items():
            if not isinstance(info, dict):
                continue
            response_chain, separator, token_addr = key.lower().partition(':')
            if not separator or response_chain != chain_slug:
                continue
            if (info.get('chain') is not None and info['chain'] != chain_slug
                    or info.get('contract_address') is not None and str(info['contract_address']).lower() != token_addr):
                continue
            quote = deepcopy(info) if include_metadata else quote_price(info)
            if quote is None:
                continue
            if include_metadata:
                # The queried asset can be a wrapped token while the balance
                # belongs to its native asset. Keep provider evidence intact.
                source_asset = {
                    'chain': info.get('chain', chain_slug),
                    'contract_address': info.get('contract_address', token_addr),
                    'symbol': info.get('symbol'),
                    'decimals': info.get('token_decimals', info.get('decimals')),
                }
                quote['source_asset'] = source_asset
                quote['valuation_asset'] = {
                    **deepcopy(source_asset), 'contract_address': token_addr, 'is_native': False,
                }
            price_results[token_addr] = quote

            if token_addr == wrapped_address.lower():
                for alias in NATIVE_TOKEN_ALIASES:
                    native_quote = deepcopy(quote)
                    if include_metadata:
                        native_quote['valuation_asset'] = {
                            'chain': chain_slug, 'contract_address': alias,
                            'symbol': chain_config['symbol'], 'decimals': 18, 'is_native': True,
                        }
                    price_results[alias] = native_quote

    except Exception as e:
        print(f"Batch price fetch error: {e}")

    return price_results
