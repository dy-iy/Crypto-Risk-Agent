"""Per-transaction sender native-currency changes from validated replay evidence.

This is deliberately not a multi-account attack profit calculator. A balance
diff already includes transaction fees; subtracting gas again would double count
them. Source validation belongs to the replay coordinator, which reconstructs
execution summaries from immutable artifacts before enabling the report builder.
"""
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


_ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
_HASH = re.compile(r'0x[0-9a-fA-F]{64}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_QUANTITY = re.compile(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)')
_DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)')
_SIGNED_DECIMAL = re.compile(r'(?:0|-?[1-9][0-9]*)')
_MAX_UINT256 = (1 << 256) - 1
_SYMBOLS = {'1': 'ETH', '56': 'BNB'}
NATIVE_PROFIT_REASON_CODES = frozenset({
    'missing_execution_context', 'invalid_execution_context', 'execution_context_mismatch',
    'unsupported_network', 'missing_balance_diff', 'invalid_balance_diff',
    'sender_balance_missing', 'sender_balance_ambiguous', 'invalid_sender_balance',
    'native_measurement_missing', 'invalid_native_measurement', 'measurement_context_mismatch',
    'artifact_reference_invalid', 'execution_not_completed', 'transaction_pair_missing',
    'sequence_stopped_after_revert', 'invalid_transaction_context',
})


def _uint256(value):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and _QUANTITY.fullmatch(value):
        # Bound before conversion so an untrusted quantity cannot ask Python to
        # parse an arbitrarily large integer or hit its decimal digit limit.
        hexadecimal = value.lower().startswith('0x')
        digits = (value[2:] if hexadecimal else value).lstrip('0') or '0'
        if len(digits) > (64 if hexadecimal else 78):
            return None
        number = int(digits, 16 if hexadecimal else 10)
    else:
        return None
    return number if 0 <= number <= _MAX_UINT256 else None


def _status(value):
    number = int(value) if type(value) is bool else _uint256(value)
    return number if number in (0, 1) else None


def _unavailable(reason_code):
    return {'schema_version': 1, 'status': 'unavailable', 'reason_code': reason_code}


def extract_native_balance_change(result):
    """Read the sender's unique raw balance diff, never the truncated sample."""
    if not isinstance(result, dict):
        return _unavailable('missing_execution_context')
    simulation, transaction = result.get('simulation'), result.get('transaction')
    if not isinstance(simulation, dict) or not isinstance(transaction, dict):
        return _unavailable('missing_execution_context')
    contexts = []
    for data in (simulation, transaction):
        if any(key not in data for key in ('from', 'network_id', 'status', 'gas_used')):
            return _unavailable('missing_execution_context')
        sender = data['from']
        network, status, gas_used = (_uint256(data['network_id']), _status(data['status']),
                                     _uint256(data['gas_used']))
        if (not isinstance(sender, str) or _ADDRESS.fullmatch(sender) is None
                or network is None or status is None or gas_used is None):
            return _unavailable('invalid_execution_context')
        contexts.append((sender.lower(), str(network), status, gas_used))
    if contexts[0] != contexts[1]:
        return _unavailable('execution_context_mismatch')
    sender, network, _, _ = contexts[0]
    if network not in _SYMBOLS:
        return _unavailable('unsupported_network')
    info = transaction.get('transaction_info')
    if not isinstance(info, dict) or info.get('balance_diff') is None:
        return _unavailable('missing_balance_diff')
    records = info['balance_diff']
    if not isinstance(records, list):
        return _unavailable('invalid_balance_diff')
    matching, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            return _unavailable('invalid_balance_diff')
        address = record.get('address')
        if not isinstance(address, str) or _ADDRESS.fullmatch(address) is None:
            return _unavailable('invalid_balance_diff')
        address = address.lower()
        before, after = _uint256(record.get('original')), _uint256(record.get('dirty'))
        if before is None or after is None:
            return _unavailable('invalid_sender_balance' if address == sender else 'invalid_balance_diff')
        if address in seen and address != sender:
            return _unavailable('invalid_balance_diff')
        seen.add(address)
        if address == sender:
            matching.append((before, after))
    if not matching:
        return _unavailable('sender_balance_missing')
    if len(matching) != 1:
        return _unavailable('sender_balance_ambiguous')
    before, after = matching[0]
    return {
        'schema_version': 1, 'status': 'available', 'account': sender,
        'network_id': network, 'symbol': _SYMBOLS[network], 'decimals': 18,
        'gas_included': True, 'before_wei': str(before), 'after_wei': str(after),
        'delta_wei': str(after - before),
    }


def _report_digest(report):
    try:
        return hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None


def _side(execution, account, network, *, patched=False):
    def unavailable(reason):
        return {'status': 'unavailable', 'reason_code': reason}

    if not isinstance(execution, dict):
        return unavailable('native_measurement_missing')
    if execution.get('status') == 'not_executed' and patched and execution.get('completed') is False:
        reason = execution.get('reason_code')
        return {'status': 'not_executed', 'reason_code': (
            reason if reason == 'sequence_stopped_after_revert' else 'execution_not_completed')}
    if execution.get('completed') is not True or execution.get('status') not in ('success', 'revert'):
        return unavailable('execution_not_completed')
    artifact = execution.get('artifact')
    sha256 = artifact.get('sha256') if isinstance(artifact, dict) else None
    if not isinstance(sha256, str) or _DIGEST.fullmatch(sha256) is None:
        return unavailable('artifact_reference_invalid')
    measurement = execution.get('native_balance_change')
    if not isinstance(measurement, dict):
        return unavailable('native_measurement_missing')
    if (type(measurement.get('schema_version')) is not int or measurement['schema_version'] != 1):
        return unavailable('invalid_native_measurement')
    if measurement.get('status') == 'unavailable':
        reason = measurement.get('reason_code')
        if (set(measurement) != {'schema_version', 'status', 'reason_code'}
                or not isinstance(reason, str) or reason not in NATIVE_PROFIT_REASON_CODES):
            reason = 'invalid_native_measurement'
        return unavailable(reason)
    expected_keys = {'schema_version', 'status', 'account', 'network_id', 'symbol', 'decimals',
                     'gas_included', 'before_wei', 'after_wei', 'delta_wei'}
    if (set(measurement) != expected_keys or measurement.get('status') != 'available'
            or measurement.get('gas_included') is not True
            or type(measurement.get('decimals')) is not int or measurement['decimals'] != 18):
        return unavailable('invalid_native_measurement')
    if (measurement.get('account') != account or measurement.get('network_id') != network
            or measurement.get('symbol') != _SYMBOLS[network]):
        return unavailable('measurement_context_mismatch')
    before, after, delta = (measurement.get(key) for key in ('before_wei', 'after_wei', 'delta_wei'))
    if (not isinstance(before, str) or _DECIMAL.fullmatch(before) is None
            or not isinstance(after, str) or _DECIMAL.fullmatch(after) is None
            or not isinstance(delta, str) or _SIGNED_DECIMAL.fullmatch(delta) is None
            or len(delta.lstrip('-')) > 78):
        return unavailable('invalid_native_measurement')
    before_number, after_number = _uint256(before), _uint256(after)
    if (before_number is None or after_number is None
            or after_number - before_number != int(delta)):
        return unavailable('invalid_native_measurement')
    return {'status': 'available', 'before_wei': before, 'after_wei': after, 'delta_wei': delta,
            'artifact_sha256': sha256}


def build_native_profit_evidence(report, *, execution_validated=False):
    """Build display data only after immutable-artifact reconstruction succeeds.

    Validating the arithmetic here does not validate its source. Callers must not
    set ``execution_validated`` based on a model verdict or summary-only checks.
    Missing legacy summaries deliberately preserve the old unavailable response.
    """
    legacy_unavailable = {'status': 'unavailable', 'usd': None}
    if execution_validated is not True or not isinstance(report, dict):
        return legacy_unavailable
    digest = _report_digest(report)
    pairs = report.get('transactions')
    if digest is None or not isinstance(pairs, list) or not pairs:
        return legacy_unavailable
    if not any(isinstance(pair, dict) and any(
            isinstance(pair.get(role), dict) and 'native_balance_change' in pair[role]
            for role in ('control', 'patched')) for pair in pairs):
        return legacy_unavailable
    rows = []
    hashes = [pair.get('original_transaction_hash') if isinstance(pair, dict) else None for pair in pairs]
    plan = report.get('verification_plan')
    planned = plan.get('attack_transaction_hashes') if isinstance(plan, dict) else None
    # The coordinator must retain every planned transaction. A missing pair
    # cannot acquire a fabricated sender/context just to fill a display row.
    if isinstance(planned, list) and planned != hashes:
        return legacy_unavailable
    for pair, tx_hash in zip(pairs, hashes):
        context = pair.get('context') if isinstance(pair, dict) else None
        context = context if isinstance(context, dict) else {}
        sender, network = context.get('from'), context.get('network_id')
        valid_hash = isinstance(tx_hash, str) and _HASH.fullmatch(tx_hash) is not None
        valid_account = isinstance(sender, str) and _ADDRESS.fullmatch(sender) is not None
        valid_network = network in _SYMBOLS if isinstance(network, str) else False
        canonical_hash = tx_hash.lower() if valid_hash else None
        account = sender.lower() if valid_account else None
        row = {'transaction_hash': canonical_hash, 'account': account,
               'network_id': network if valid_network else None,
               'symbol': _SYMBOLS.get(network) if isinstance(network, str) else None}
        context_hash = context.get('transaction_hash', context.get('hash', tx_hash))
        identity_valid = (valid_hash and valid_account and valid_network
                          and isinstance(context_hash, str) and context_hash.lower() == canonical_hash
                          and sum(isinstance(other, str) and other.lower() == canonical_hash for other in hashes) == 1)
        if not identity_valid:
            return legacy_unavailable
        for role in ('control', 'patched'):
            row[role] = _side(pair.get(role), account, network, patched=role == 'patched')
        rows.append(row)
    available = sum(row[role]['status'] == 'available' for row in rows for role in ('control', 'patched'))
    return {
        'schema_version': 1, 'status': ('available' if rows and available == 2 * len(rows)
                                      else 'partial' if available else 'unavailable'),
        'usd': None, 'metric': 'transaction_sender_native_balance_change',
        'scope': 'per_transaction_senders', 'gas_included': True,
        'replay_evidence_sha256': digest, 'transactions': rows,
    }


def build_saved_native_profit_evidence(report, cache_root):
    """Read native changes for an old v2 report without changing saved evidence.

    The caller first checks the saved coordinator envelope's digest binding.
    Here every source artifact and the complete sequence are independently
    validated. Native changes and security observations are derived afresh in a
    temporary copy, accommodating older observation extractors. Traces from
    the recognized previous parser policy are also rebuilt from raw responses
    and the patched request's runtime code. Current or unrecognized trace
    policies retain their recorded trace for strict comparison. All other
    recorded fields must still match immutable raw reconstruction. This helper
    neither re-adjudicates nor changes the saved defense verdict.
    The returned comparison binds to the original, unchanged report digest.
    """
    unavailable = {'status': 'unavailable', 'usd': None}
    if (not isinstance(report, dict) or type(report.get('schema_version')) is not int
            or report['schema_version'] != 2 or report.get('scope') != 'sequential_attack_and_regression'
            or cache_root is None):
        return unavailable
    from app.attackpilot.errors import HistoricalReplayValidationError, TenderlyAPIError
    try:
        cache = Path(cache_root)
        if not cache.is_dir():
            return unavailable
        original_digest = _report_digest(report)
        if original_digest is None:
            return unavailable
        from app.attackpilot.utils.patch_replay import (
            PatchReplayEvidenceStore, execution_summary, runtime_overrides,
            validate_sequential_evidence,
        )
        from app.attackpilot.utils.security_checks import extract_security_observations

        refreshed = deepcopy(report)
        cases = refreshed.get('normal_regression', {}).get('cases')
        if not isinstance(cases, list):
            return unavailable
        groups = [refreshed, *cases]
        store = PatchReplayEvidenceStore(cache)
        for group in groups:
            if not isinstance(group, dict):
                return unavailable
            pairs, sequence = group.get('transactions'), group.get('sequence')
            if not isinstance(pairs, list) or not pairs or not isinstance(sequence, dict):
                return unavailable
            hashes = sequence.get('ordered_transaction_hashes')
            if (not isinstance(hashes, list) or not hashes
                    or not isinstance(hashes[0], str) or _HASH.fullmatch(hashes[0]) is None):
                return unavailable
            for pair in pairs:
                if not isinstance(pair, dict):
                    return unavailable
                for role in ('control', 'patched'):
                    execution = pair.get(role)
                    if not isinstance(execution, dict) or 'native_balance_change' in execution:
                        return unavailable
                    if execution.get('completed') is not True:
                        continue
                    request, raw = store.read_artifact(execution.get('artifact'), expected_role=role,
                                                       original_hash=hashes[0])
                    execution['native_balance_change'] = extract_native_balance_change(raw)
                    old_trace = execution.get('trace')
                    if (isinstance(old_trace, dict)
                            and type(old_trace.get('policy_version')) is int
                            and old_trace['policy_version'] == 5):
                        runtime_codes = None
                        if role == 'patched':
                            objects = request['simulations'][0]['state_objects']
                            if (not isinstance(objects, dict)
                                    or any(not isinstance(item, dict) or set(item) != {'code'}
                                           for item in objects.values())):
                                return unavailable
                            overrides = runtime_overrides({address: item['code']
                                                           for address, item in objects.items()})
                            if sorted(overrides) != refreshed.get('patched_addresses'):
                                return unavailable
                            runtime_codes = {address: item['code'] for address, item in overrides.items()}
                        execution['trace'] = execution_summary(
                            raw, execution['artifact'], refreshed['patched_addresses'],
                            runtime_codes=runtime_codes)['trace']
                    if refreshed.get('verification_plan') is not None:
                        execution['security_observations'] = extract_security_observations(
                            raw, execution['artifact'], refreshed['verification_plan'],
                            transaction_hash=pair.get('original_transaction_hash'))
        validated = validate_sequential_evidence(refreshed, cache_root=cache)
        if not isinstance(validated, dict) or validated.get('status') != 'validated':
            return unavailable
        result = build_native_profit_evidence(refreshed, execution_validated=True)
        if result.get('schema_version') != 1:
            return unavailable
        result['replay_evidence_sha256'] = original_digest
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError,
            OverflowError, RecursionError, UnicodeError, HistoricalReplayValidationError, TenderlyAPIError):
        return unavailable
