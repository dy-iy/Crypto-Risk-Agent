"""Deterministic evidence gate for unmodified historical transaction replays.

Simulation transaction hashes and indexes describe a synthetic transaction.  The
historical insertion position comes from ``simulation.transaction_index``.
"""
import hashlib
import json
import re
from typing import Any

from app.attackpilot.errors import HistoricalReplayValidationError


def _fail(status: str, code: str, field: str) -> None:
    raise HistoricalReplayValidationError(status, code, details={'field': field})


def _quantity(value: Any, field: str, *, empty_hex: bool = False) -> int:
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)', value):
        number = int(value, 16 if value.lower().startswith('0x') else 10)
    elif empty_hex and value == '0x':
        number = 0
    else:
        _fail('unavailable', 'missing_evidence', field)
    if number < 0:
        _fail('unavailable', 'missing_evidence', field)
    return number


def _hex(value: Any, field: str, *, size: int | None = None, creation: bool = False) -> str | None:
    if creation and value in (None, ''):
        return None
    if not isinstance(value, str) or not re.fullmatch(r'0[xX](?:[0-9a-fA-F]{2})*', value):
        _fail('unavailable', 'missing_evidence', field)
    if size is not None and len(value) != 2 + size * 2:
        _fail('unavailable', 'missing_evidence', field)
    return value.lower()


def _status(value: Any, field: str) -> int:
    number = int(value) if type(value) is bool else _quantity(value, field)
    if number not in (0, 1):
        _fail('unavailable', 'missing_evidence', field)
    return number


def _equal(actual: Any, expected: Any, field: str, code: str = 'context_mismatch') -> None:
    if actual != expected:
        _fail('inconsistent', code, field)


def _logs(logs: Any, field: str, *, simulation: bool = False) -> list[tuple]:
    # Tenderly explicitly uses null for an empty log collection. Missing the
    # collection itself is handled by callers and must never imply zero events.
    if simulation and logs is None:
        logs = []
    if not isinstance(logs, list):
        _fail('unavailable', 'missing_evidence', field)
    result = []
    for item in logs:
        if not isinstance(item, dict):
            _fail('unavailable', 'missing_evidence', field)
        raw = item.get('raw', item) if simulation else item
        if not isinstance(raw, dict) or not isinstance(raw.get('topics'), list):
            _fail('unavailable', 'missing_evidence', field)
        if raw.get('removed') is True:
            _fail('inconsistent', 'receipt_mismatch', field)
        result.append((
            _hex(raw.get('address'), f'{field}.address', size=20),
            tuple(_hex(topic, f'{field}.topics', size=32) for topic in raw['topics']),
            _hex(raw.get('data'), f'{field}.data'),
        ))
    return result


def validate_original_transaction(transaction_hash: str, chain_id: int,
                                  transaction: Any, receipt: Any) -> dict:
    """Validate RPC identity/receipt before paying for or trusting a replay."""
    tx_hash = _hex(transaction_hash, 'transaction_hash', size=32)
    if not isinstance(transaction, dict) or not isinstance(receipt, dict):
        _fail('unavailable', 'missing_evidence', 'rpc_transaction_receipt')
    if 'to' not in transaction:
        _fail('unavailable', 'missing_evidence', 'rpc.to')
    context = {
        'transaction_hash': tx_hash,
        'chain_id': _quantity(chain_id, 'chain_id'),
        'block_number': _quantity(transaction.get('blockNumber'), 'rpc.blockNumber'),
        'transaction_index': _quantity(transaction.get('transactionIndex'), 'rpc.transactionIndex'),
        'block_hash': _hex(transaction.get('blockHash'), 'rpc.blockHash', size=32),
        'from': _hex(transaction.get('from'), 'rpc.from', size=20),
        'to': _hex(transaction.get('to'), 'rpc.to', size=20, creation=True),
        'input': _hex(transaction.get('input'), 'rpc.input'),
        'value': _quantity(transaction.get('value'), 'rpc.value'),
        'gas': _quantity(transaction.get('gas'), 'rpc.gas'),
        'gas_price': _quantity(transaction.get('gasPrice'), 'rpc.gasPrice'),
        'nonce': _quantity(transaction.get('nonce'), 'rpc.nonce'),
        'status': _status(receipt.get('status'), 'receipt.status'),
        'gas_used': _quantity(receipt.get('gasUsed'), 'receipt.gasUsed'),
    }
    _equal(_hex(transaction.get('hash'), 'rpc.hash', size=32), tx_hash, 'rpc.hash', 'receipt_mismatch')
    _equal(_hex(receipt.get('transactionHash'), 'receipt.transactionHash', size=32), tx_hash,
           'receipt.transactionHash', 'receipt_mismatch')
    for key, rpc_key in (('block_number', 'blockNumber'), ('transaction_index', 'transactionIndex')):
        _equal(_quantity(receipt.get(rpc_key), f'receipt.{rpc_key}'), context[key],
               f'receipt.{rpc_key}', 'receipt_mismatch')
    _equal(_hex(receipt.get('blockHash'), 'receipt.blockHash', size=32), context['block_hash'],
           'receipt.blockHash', 'receipt_mismatch')
    if 'chainId' in transaction and transaction['chainId'] is not None:
        _equal(_quantity(transaction['chainId'], 'rpc.chainId'), context['chain_id'], 'rpc.chainId')
    for key in ('from', 'to'):
        if key in receipt:
            _equal(_hex(receipt[key], f'receipt.{key}', size=20, creation=key == 'to'),
                   context[key], f'receipt.{key}', 'receipt_mismatch')
    if 'logs' not in receipt:
        _fail('unavailable', 'missing_evidence', 'receipt.logs')
    context['logs'] = _logs(receipt['logs'], 'receipt.logs')
    if context['to'] is None:
        context['contract_address'] = _hex(receipt.get('contractAddress'), 'receipt.contractAddress',
                                            size=20, creation=context['status'] == 0)
    if context['gas_used'] > context['gas'] or (context['status'] == 0 and context['logs']):
        _fail('inconsistent', 'receipt_mismatch', 'receipt.execution')
    # Receipt log metadata, when provided by RPC, must belong to this transaction.
    previous_index = -1
    for log in receipt['logs']:
        for key, expected, normalizer in (
            ('transactionHash', tx_hash, lambda value: _hex(value, 'receipt.logs.transactionHash', size=32)),
            ('blockHash', context['block_hash'], lambda value: _hex(value, 'receipt.logs.blockHash', size=32)),
            ('blockNumber', context['block_number'], lambda value: _quantity(value, 'receipt.logs.blockNumber')),
            ('transactionIndex', context['transaction_index'], lambda value: _quantity(value, 'receipt.logs.transactionIndex')),
        ):
            if key in log:
                _equal(normalizer(log[key]), expected, f'receipt.logs.{key}', 'receipt_mismatch')
        if 'logIndex' in log:
            index = _quantity(log['logIndex'], 'receipt.logs.logIndex')
            if index <= previous_index:
                _fail('inconsistent', 'receipt_mismatch', 'receipt.logs.order')
            previous_index = index
    return context


def validate_trace_root(context: dict, transaction: dict) -> None:
    """Bind the trace consumed by analysis to the actual transaction parameters.

    Matching a response's outer transaction/receipt fields does not establish
    that its nested trace belongs to that transaction. Tenderly's root address
    can denote the sender, so execution identity uses from/to, never address.
    """
    info = transaction.get('transaction_info')
    root = info.get('call_trace') if isinstance(info, dict) else None
    if not isinstance(root, dict) or not root:
        _fail('unavailable', 'missing_evidence', 'trace.root')
    kind = root.get('call_type', root.get('type'))
    expected_kind = 'CREATE' if context['to'] is None else 'CALL'
    if not isinstance(kind, str) or kind.upper() != expected_kind:
        _fail('inconsistent', 'context_mismatch', 'trace.call_type')
    if ('call_type' in root and 'type' in root
            and str(root['type']).upper() != kind.upper()):
        _fail('inconsistent', 'context_mismatch', 'trace.call_type')
    for key in ('from', 'input'):
        _equal(_hex(root.get(key), f'trace.{key}', size=20 if key == 'from' else None),
               context[key], f'trace.{key}')
    target = context['to'] if context['to'] is not None else context.get('contract_address')
    _equal(_hex(root.get('to'), 'trace.to', size=20, creation=target is None), target, 'trace.to')
    _equal(_quantity(root.get('value'), 'trace.value', empty_hex=True), context['value'], 'trace.value')
    for key, expected in (('network_id', context['chain_id']), ('block_number', context['block_number'])):
        if key in root:
            _equal(_quantity(root[key], f'trace.{key}'), expected, f'trace.{key}')
    expected_status = _status(transaction.get('status'), 'transaction.status')
    for key in ('status', 'success'):
        if key in root:
            value = root[key]
            if isinstance(value, str) and value.lower() in {'success', 'revert', 'reverted', 'failed'}:
                value = 1 if value.lower() == 'success' else 0
            _equal(_status(value, f'trace.{key}'), expected_status, f'trace.{key}', 'execution_mismatch')
    failed = any(root.get(key) not in (None, '', False) for key in ('error', 'error_reason', 'error_message', 'revert_reason'))
    failed = failed or str(root.get('error_op', '')).upper() in {'REVERT', 'INVALID'}
    if expected_status == 1 and failed:
        _fail('inconsistent', 'execution_mismatch', 'trace.error')


def validate_simulated_transaction(context: dict, full_result: Any) -> dict:
    """Return safe provenance only if all original replay checks pass.

    This gate must not be applied to patched, deployment, or bundle simulations,
    whose outputs are intentionally different from the original receipt.
    """
    if not isinstance(full_result, dict):
        _fail('unavailable', 'missing_evidence', 'simulation_result')
    simulation = full_result.get('simulation')
    transaction = full_result.get('transaction')
    if not isinstance(simulation, dict) or not isinstance(transaction, dict):
        _fail('unavailable', 'missing_evidence', 'simulation_context')
    # Validate the historical insertion position before examining execution
    # output; a stale start-of-block replay must never reach model analysis.
    _equal(_quantity(simulation.get('transaction_index'), 'simulation.transaction_index'),
           context['transaction_index'], 'simulation.transaction_index')
    for data, prefix in ((simulation, 'simulation'), (transaction, 'transaction')):
        if 'to' not in data:
            _fail('unavailable', 'missing_evidence', f'{prefix}.to')
        for key, expected in (('network_id', context['chain_id']), ('block_number', context['block_number'])):
            _equal(_quantity(data.get(key), f'{prefix}.{key}'), expected, f'{prefix}.{key}')
        for key in ('from', 'to', 'input'):
            _equal(_hex(data.get(key), f'{prefix}.{key}', size=20 if key != 'input' else None,
                        creation=key == 'to'), context[key], f'{prefix}.{key}')
        for key in ('gas', 'gas_price', 'value', 'nonce'):
            _equal(_quantity(data.get(key), f'{prefix}.{key}', empty_hex=key == 'value'),
                   context[key], f'{prefix}.{key}')
        _equal(_status(data.get('status'), f'{prefix}.status'), context['status'],
               f'{prefix}.status', 'execution_mismatch')
        _equal(_quantity(data.get('gas_used'), f'{prefix}.gas_used'), context['gas_used'],
               f'{prefix}.gas_used', 'execution_mismatch')
    # The simulation object's insertion context is authoritative. Its synthetic
    # transaction.hash/index/block_hash can legitimately differ from RPC values.
    header = simulation.get('block_header')
    if isinstance(header, dict) and header.get('hash'):
        _equal(_hex(header['hash'], 'simulation.block_header.hash', size=32), context['block_hash'],
               'simulation.block_header.hash')
    info = transaction.get('transaction_info')
    if not isinstance(info, dict) or 'logs' not in info:
        _fail('unavailable', 'missing_evidence', 'transaction.transaction_info.logs')
    simulated_logs = _logs(info['logs'], 'simulation.logs', simulation=True)
    _equal(simulated_logs, context['logs'], 'simulation.logs', 'event_mismatch')
    validate_trace_root(context, transaction)
    digest = hashlib.sha256(json.dumps(context['logs'], separators=(',', ':')).encode()).hexdigest()
    receipt_digest = hashlib.sha256(json.dumps({
        key: context[key] for key in ('transaction_hash', 'chain_id', 'block_hash', 'block_number',
                                     'transaction_index', 'status', 'gas_used', 'logs')
    }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    simulation_id = simulation.get('id')
    if not isinstance(simulation_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', simulation_id):
        simulation_id = None
    return {
        'schema_version': 1,
        'status': 'validated',
        'method': 'rpc_receipt_vs_tenderly_original_replay',
        'original_transaction_hash': context['transaction_hash'],
        'network_id': str(context['chain_id']),
        'block_number': context['block_number'],
        'block_hash': context['block_hash'],
        'transaction_index': context['transaction_index'],
        'simulation_id': simulation_id,
        'receipt_status': context['status'],
        'gas_used': context['gas_used'],
        'log_count': len(context['logs']),
        'ordered_logs_sha256': digest,
        'receipt_digest': receipt_digest,
    }
