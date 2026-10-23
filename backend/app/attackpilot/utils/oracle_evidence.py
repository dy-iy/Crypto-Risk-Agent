"""Read oracle outputs already present in a validated original execution trace."""
from datetime import datetime
import re

from eth_abi import decode
from eth_abi.exceptions import DecodingError
from web3 import Web3

from app.attackpilot.utils.chainlink_config import canonical_platform, get_chainlink_config


_LATEST = '0x' + Web3.keccak(text='latestRoundData()')[:4].hex()
_ROUND = '0x' + Web3.keccak(text='getRoundData(uint80)')[:4].hex()
_DECIMALS = '0x' + Web3.keccak(text='decimals()')[:4].hex()


def _bytes(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', value):
        return None
    return bytes.fromhex(value[2:])


def _timestamp(transaction):
    value = transaction.get('timestamp')
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return int(parsed.timestamp())
        except ValueError:
            pass
    return None


def extract_chainlink_observations(transaction: dict, platform: str) -> dict:
    """A selector alone never establishes that a contract is a Chainlink feed.

    This function performs no RPC calls. Reference prices and observed protocol
    reads remain separate evidence, even when they name the same feed.
    """
    result = {'schema_version': 1, 'status': 'not_observed', 'observations': [],
              'scope': 'configured_proxy_addresses_only', 'scan_complete': True,
              'absence_is_not_proof_of_no_oracle_usage': True}
    try:
        config = get_chainlink_config()
    except ValueError:
        return {**result, 'status': 'unavailable', 'reason_code': 'configuration_error', 'scan_complete': False}
    if not config['enabled']:
        return {**result, 'status': 'disabled', 'scan_complete': False}
    platform = canonical_platform(platform)
    feeds = {}
    for feed in config['feeds'].get(platform, {}).values():
        feeds.setdefault(feed['proxy_address'], feed)
    root = (transaction.get('transaction_info') or {}).get('call_trace')
    if not isinstance(root, dict):
        return {**result, 'status': 'unavailable', 'reason_code': 'missing_trace', 'scan_complete': False}
    stack, nodes, count = [root], [], 0
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        count += 1
        if count > 100000:
            result['scan_complete'] = False
            break
        target = node.get('to')
        target = target.lower() if isinstance(target, str) else ''
        if target in feeds:
            nodes.append((target, node))
        children = node.get('calls') or []
        if isinstance(children, list):
            stack.extend(reversed(children))
    # Only a successful decimals() read from this exact proxy counts as
    # transaction-local precision evidence. Catalog precision is kept separate.
    decimals = {}
    for target, node in nodes:
        data, output = _bytes(node.get('input')), _bytes(node.get('output'))
        if node.get('error') or node.get('error_message') or node.get('status') is False:
            continue
        if data == _bytes(_DECIMALS) and output is not None and len(output) == 32:
            value = int.from_bytes(output, 'big')
            if 0 <= value <= 36:
                decimals.setdefault(target, set()).add(value)
    tx_time = _timestamp(transaction)
    for target, node in nodes:
        data, output = _bytes(node.get('input')), _bytes(node.get('output'))
        if data is None or '0x' + data[:4].hex() not in {_LATEST, _ROUND}:
            continue
        if len(result['observations']) >= 100:
            result['scan_complete'] = False
            break
        feed = feeds[target]
        item = {
            'feed_address': target, 'pair': feed['pair'], 'network_id': feed['chain_id'],
            'identity_status': 'official_catalog_proxy' if feed['configuration_origin'] == 'official_catalog' else 'configured_proxy_unverified',
            'identity_scope': 'current_catalog_address_match',
            'method': 'latestRoundData' if '0x' + data[:4].hex() == _LATEST else 'getRoundData',
            'trace_position': node.get('absolute_position'), 'source': 'validated_original_tenderly_trace',
            'original_transaction_hash': transaction.get('original_transaction_hash'),
            'simulation_id': (transaction.get('baseline_validation') or {}).get('simulation_id'),
            'configured_feed_decimals': feed['feed_decimals'],
            'source_url': feed['source_url'], 'status': 'unavailable',
        }
        if node.get('error') or node.get('error_message') or node.get('status') is False:
            item['reason_code'] = 'oracle_call_reverted'
        elif len(data) != (4 if item['method'] == 'latestRoundData' else 36) or output is None or len(output) != 160:
            item['reason_code'] = 'invalid_oracle_output'
        else:
            try:
                round_id, answer, started, updated, answered = decode(
                    ['uint80', 'int256', 'uint256', 'uint256', 'uint80'], output,
                )
            except (DecodingError, ValueError, OverflowError):
                item['reason_code'] = 'invalid_oracle_output'
            else:
                item.update(status='observed', round_id=str(round_id), answer=str(answer),
                            started_at=started, updated_at=updated, answered_in_round=str(answered),
                            requested_timestamp=tx_time)
                if len(data) == 36:
                    item['requested_round_id'] = str(int.from_bytes(data[4:], 'big'))
                integrity = (
                    round_id > 0 and answered >= round_id and started > 0 and updated >= started
                    and (len(data) != 36 or int.from_bytes(data[4:], 'big') == round_id)
                )
                item['round_integrity_check'] = 'valid' if integrity else 'invalid'
                values = decimals.get(target, set())
                item['feed_decimals'] = next(iter(values)) if len(values) == 1 else None
                item['precision_evidence'] = 'same_transaction_read' if len(values) == 1 else 'not_established_in_trace'
                # These are application checks on the observed output, not proof
                # that a deviation caused an exploit or that a patch is correct.
                item['answer_check'] = 'valid' if answer > 0 else 'invalid'
                item['age_seconds'] = tx_time - updated if tx_time is not None and updated > 0 else None
                item['freshness_policy_seconds'] = feed['max_age_seconds']
                item['freshness_check'] = (
                    'unknown' if item['age_seconds'] is None else
                    'future' if item['age_seconds'] < 0 else
                    'stale' if item['age_seconds'] > feed['max_age_seconds'] else 'within_application_policy'
                )
        result['observations'].append(item)
    if result['observations']:
        result['status'] = 'observed'
    return result
