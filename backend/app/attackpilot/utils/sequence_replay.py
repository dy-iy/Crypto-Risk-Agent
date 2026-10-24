"""Stateful control/patch sequences with independently checkable raw evidence.

All steps use one historical state base. Header overrides advance the execution
block/time without loading a later real-world state. Tenderly documents stateful
bundles and per-step block/time overrides at:
https://docs.tenderly.co/simulations/bundled-simulations
https://tenderly.co/blog/changelog/preview-multi-step-flows-with-simulation-bundles/
The response must prove that the requested execution header was actually used;
providers that ignore header overrides cannot produce validated evidence.
"""
from copy import deepcopy
import hashlib
import json
import re

from app.attackpilot.errors import HistoricalReplayValidationError, TenderlyAPIError
from app.attackpilot.utils.patch_replay import (
    MAX_REPLAY_TRANSACTIONS, PatchReplayBudgetError, PatchReplayEvidenceStore,
    _digest, _hex, _logs, _quantity, _status, execution_summary, historical_payload,
    public_context, runtime_overrides,
)
from app.attackpilot.utils.replay_validation import validate_trace_root

SEQUENCE_SCOPE = 'sequential_attack_and_regression'
SEQUENCE_MODE = 'tenderly_stateful_bundle'


def _reject(field, code='context_mismatch'):
    raise HistoricalReplayValidationError('inconsistent', code, details={'field': field})


def resolve_sequence(store, transactions, chain_id):
    if not isinstance(transactions, list) or not transactions:
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
    if len(transactions) > MAX_REPLAY_TRANSACTIONS:
        raise PatchReplayBudgetError(transaction_limit=True)
    originals, seen, previous = [], set(), None
    for detail in transactions:
        tx_hash = (detail.get('original_transaction_hash') or detail.get('hash')) if isinstance(detail, dict) else None
        context, raw = store.original_context(tx_hash, chain_id)
        position = (context['block_number'], context['transaction_index'])
        if context['transaction_hash'] in seen or previous is not None and position <= previous:
            _reject('sequence.transaction_order')
        seen.add(context['transaction_hash'])
        originals.append((context, raw))
        previous = position
    return originals


def sequence_probe_rules(originals, plan):
    if not isinstance(plan, dict):
        return []
    hashes = [context['transaction_hash'] for context, _ in originals]
    rules = [rule for rule in plan.get('security_properties', [])
             if rule.get('kind') == 'call_result' and rule.get('transaction_hashes') == [hashes[-1]]]
    for case in plan.get('normal_regression_cases', []):
        if case.get('transaction_hashes') == hashes:
            rules.extend(rule for rule in case.get('assertions', [])
                         if rule.get('kind') == 'call_result' and rule.get('transaction_hashes') == [hashes[-1]])
    return rules


def sequence_payload(originals, overrides=None, plan=None):
    """The first insertion position is the only state base, for every step."""
    base = originals[0][0]
    simulations = []
    for index, (context, raw) in enumerate(originals):
        simulation = historical_payload(context, raw)['simulations'][0]
        simulation['block_number'] = base['block_number']
        simulation['transaction_index'] = base['transaction_index']
        # These override EVM execution context, not the historical state base.
        # Quantities are exact hexadecimal strings, including block timestamps.
        if context['block_number'] != base['block_number']:
            simulation['block_header'] = {'number': hex(context['block_number']),
                                          'timestamp': hex(context['timestamp'])}
        if index == 0 and overrides:
            simulation['state_objects'] = deepcopy(overrides)
        simulations.append(simulation)
    for rule in sequence_probe_rules(originals, plan):
        last = originals[-1][0]
        probe = {'network_id': str(base['chain_id']), 'block_number': base['block_number'],
                 'transaction_index': base['transaction_index'], 'from': base['from'],
                 'to': rule['account'], 'input': rule['calldata'], 'value': '0',
                 'gas': 300000, 'gas_price': '0', 'simulation_type': 'full',
                 'save': True, 'save_if_fails': True,
                 'generate_state_diff': True, 'generate_visual_trace': True}
        if last['block_number'] != base['block_number']:
            probe['block_header'] = {'number': hex(last['block_number']), 'timestamp': hex(last['timestamp'])}
        simulations.append(probe)
    # Downloader removes bundle_id before sending. Its deterministic protocol
    # namespace prevents reuse of older independent, single-result artifacts.
    return {'simulations': simulations, 'contracts': [], 'bundle_id': 'attackpilot-stateful-v2'}


def sequence_validation_diagnostic(context, base, result, *, role, index, error):
    """Describe every receipt disagreement without copying raw provider data.

    Collect observations independently: a first gas failure must not hide a
    simultaneous event mismatch. Diagnostic parsing never replaces that error.
    """
    context = context if isinstance(context, dict) else {}
    base = base if isinstance(base, dict) else {}
    result = result if isinstance(result, dict) else {}

    def safe(parse, value):
        try:
            return parse(value)
        except Exception:
            return None

    def quantity(value):
        return safe(lambda raw: _quantity(raw, 'sequence.diagnostic'), value)

    def status(value):
        return safe(lambda raw: _status(raw, 'sequence.diagnostic'), value)

    def observed(key):
        data = result.get(key)
        data = data if isinstance(data, dict) else {}
        return {'status': status(data.get('status')), 'gas_used': quantity(data.get('gas_used'))}

    expected_logs = context.get('logs')
    expected = {'status': status(context.get('status')), 'gas_used': quantity(context.get('gas_used')),
                'log_count': len(expected_logs) if isinstance(expected_logs, list) else None,
                'ordered_logs_sha256': safe(_digest, expected_logs) if isinstance(expected_logs, list) else None}
    simulation, transaction = observed('simulation'), observed('transaction')
    raw_transaction = result.get('transaction')
    info = raw_transaction.get('transaction_info') if isinstance(raw_transaction, dict) else None
    logs = (safe(lambda raw: _logs(raw, 'sequence.diagnostic.logs', simulation=True), info['logs'])
            if isinstance(info, dict) and 'logs' in info else None)
    transaction.update(log_count=len(logs) if logs is not None else None,
                       ordered_logs_sha256=safe(_digest, logs) if logs is not None else None)

    def matched(field):
        target = expected[field]
        values = [simulation[field], transaction[field]]
        if target is None:
            return None
        if any(value is not None and value != target for value in values):
            return False
        return True if all(value is not None for value in values) else None

    events_match = None
    if expected['ordered_logs_sha256'] is not None and transaction['ordered_logs_sha256'] is not None:
        events_match = (expected['log_count'] == transaction['log_count']
                        and expected['ordered_logs_sha256'] == transaction['ordered_logs_sha256'])
    details = getattr(error, 'details', None)
    field = details.get('field') if isinstance(details, dict) else None
    if not isinstance(field, str) or re.fullmatch(r'[A-Za-z0-9_.]{1,120}', field) is None:
        field = None
    error_code = getattr(error, 'reason_code', None)
    if error_code not in {'missing_evidence', 'receipt_mismatch', 'context_mismatch',
                          'execution_mismatch', 'event_mismatch'}:
        error_code = None
    return {
        'schema_version': 1, 'role': role if role in {'control', 'patched'} else None,
        'sequence_index': index if type(index) is int and index >= 0 else None,
        'transaction_hash': safe(lambda raw: _hex(raw, 'sequence.diagnostic.hash', size=32),
                                 context.get('transaction_hash')),
        'field': field, 'error_code': error_code,
        'state_base': {key: quantity(base.get(key)) for key in ('block_number', 'transaction_index')},
        'execution_position': {key: quantity(context.get(key)) for key in ('block_number', 'transaction_index')},
        'receipt_comparison': {'expected': expected, 'simulation': simulation, 'transaction': transaction,
                               'events_match': events_match, 'gas_match': matched('gas_used'),
                               'status_match': matched('status')},
    }


def validate_sequence_result(context, base, result, *, control=False):
    """Validate identity/header, then the original receipt for control steps."""
    if not isinstance(result, dict):
        _reject('sequence.result', 'missing_evidence')
    for key in ('simulation', 'transaction'):
        data = result.get(key)
        if not isinstance(data, dict):
            _reject(f'sequence.{key}', 'missing_evidence')
        expected = {'network_id': context['chain_id'], 'gas': context['gas'],
                    'gas_price': context['gas_price'], 'value': context['value'], 'nonce': context['nonce']}
        if key == 'simulation':
            expected.update(block_number=base['block_number'], transaction_index=base['transaction_index'])
        for field, value in expected.items():
            if _quantity(data.get(field), f'sequence.{key}.{field}', empty_hex=field == 'value') != value:
                _reject(f'sequence.{key}.{field}')
        if key == 'transaction' and _quantity(data.get('block_number'), 'sequence.transaction.block_number') not in {
                base['block_number'], context['block_number']}:
            _reject('sequence.transaction.block_number')
        for field in ('from', 'to', 'input'):
            if _hex(data.get(field), f'sequence.{key}.{field}', size=20 if field != 'input' else None,
                    creation=field == 'to') != context[field]:
                _reject(f'sequence.{key}.{field}')
        if 'access_list' in data and data['access_list'] not in (None, []) and data['access_list'] != context.get('access_list', []):
            _reject(f'sequence.{key}.access_list')
    simulation, transaction = result['simulation'], result['transaction']
    header = simulation.get('block_header')
    if not isinstance(header, dict):
        _reject('sequence.block_header', 'missing_evidence')
    for field, expected in (('number', context['block_number']), ('timestamp', context['timestamp'])):
        if _quantity(header.get(field), f'sequence.block_header.{field}') != expected:
            _reject(f'sequence.block_header.{field}')
    # Header overrides change execution number/time, while the provider may
    # retain the historical state-base hash. Both contexts come from validated
    # RPC records; no other nonzero hash is accepted. Without a cross-block
    # override, only the execution block's real hash (or synthetic zero) is valid.
    observed_hash = _hex(header.get('hash'), 'sequence.block_header.hash', size=32)
    accepted_hashes = {context['block_hash'], '0x' + '0' * 64}
    if context['block_number'] != base['block_number']:
        accepted_hashes.add(base['block_hash'])
    if observed_hash not in accepted_hashes:
        _reject('sequence.block_header.hash')
    # The response transaction may describe the synthetic state base. The trace
    # executes under the number/time just independently verified in the header.
    validate_trace_root(context, transaction)
    if not control:
        return None
    for key in ('simulation', 'transaction'):
        if (_status(result[key].get('status'), f'{key}.status') != context['status']
                or _quantity(result[key].get('gas_used'), f'{key}.gas_used') != context['gas_used']):
            _reject(f'sequence.{key}.receipt', 'execution_mismatch')
    info = transaction.get('transaction_info')
    if not isinstance(info, dict) or 'logs' not in info:
        _reject('sequence.logs', 'missing_evidence')
    logs = _logs(info['logs'], 'sequence.logs', simulation=True)
    if logs != context['logs']:
        _reject('sequence.logs', 'event_mismatch')
    return {
        'schema_version': 1, 'status': 'validated',
        'method': 'rpc_receipt_vs_tenderly_stateful_sequence',
        'original_transaction_hash': context['transaction_hash'], 'network_id': str(context['chain_id']),
        'block_number': context['block_number'], 'block_hash': context['block_hash'],
        'transaction_index': context['transaction_index'], 'receipt_status': context['status'],
        'gas_used': context['gas_used'], 'log_count': len(logs),
        'ordered_logs_sha256': _digest(logs),
        'receipt_digest': hashlib.sha256(json.dumps({
            key: context[key] for key in ('transaction_hash', 'chain_id', 'block_hash', 'block_number',
                                         'transaction_index', 'status', 'gas_used', 'logs')
        }, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
    }


def validate_bundle_results(results, requested_count):
    if (not isinstance(results, list) or not 1 <= len(results) <= requested_count
            or any(not isinstance(item, dict) for item in results)):
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    failed = []
    for index, result in enumerate(results):
        simulation, transaction = result.get('simulation'), result.get('transaction')
        if not isinstance(simulation, dict) or not isinstance(transaction, dict):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
        status = _status(simulation.get('status'), 'sequence.status')
        if status != _status(transaction.get('status'), 'sequence.transaction.status'):
            _reject('sequence.status')
        if not status:
            failed.append(index)
    if failed and failed != [len(results) - 1] or len(results) < requested_count and not failed:
        _reject('sequence.early_return')
    return failed[0] if failed else None


def validate_state_continuity(results):
    """Check every repeatedly observed balance/storage word across steps."""
    storage, balances = {}, {}
    for result in results:
        info = result.get('transaction', {}).get('transaction_info', {})
        if not isinstance(info, dict):
            _reject('sequence.state_evidence', 'missing_evidence')
        if not _status(result['transaction'].get('status'), 'sequence.state.status'):
            # A reverted transaction commits no storage/asset writes. Its gas
            # fee and nonce may still change; no suffix is executed afterwards.
            continue
        current = {}
        for item in info.get('state_diff', []) or []:
            if not isinstance(item, dict):
                _reject('sequence.state_diff', 'missing_evidence')
            for entry in item.get('raw', []) or []:
                if not isinstance(entry, dict):
                    _reject('sequence.state_diff.raw', 'missing_evidence')
                key = (_hex(entry.get('address'), 'sequence.state.address', size=20),
                       _hex(entry.get('key'), 'sequence.state.key', size=32))
                value = (_hex(entry.get('original'), 'sequence.state.original', size=32),
                         _hex(entry.get('dirty'), 'sequence.state.dirty', size=32))
                if key in current and current[key] != value or key in storage and storage[key] != value[0]:
                    _reject('sequence.storage_state_not_carried')
                current[key] = value
        storage.update({key: value[1] for key, value in current.items()})
        current = {}
        for item in info.get('balance_diff', []) or []:
            if not isinstance(item, dict):
                _reject('sequence.balance_diff', 'missing_evidence')
            key = _hex(item.get('address'), 'sequence.balance.address', size=20)
            value = (_quantity(item.get('original'), 'sequence.balance.original'),
                     _quantity(item.get('dirty'), 'sequence.balance.dirty'))
            if key in current and current[key] != value or key in balances and balances[key] != value[0]:
                _reject('sequence.balance_state_not_carried')
            current[key] = value
        balances.update({key: value[1] for key, value in current.items()})


def sequence_descriptor(originals, artifact, results, plan=None):
    rules = sequence_probe_rules(originals, plan)
    stopped = validate_bundle_results(results, len(originals) + len(rules))
    validate_state_continuity(results)
    probes = []
    for index, rule in enumerate(rules, len(originals)):
        probe = {'property_id': rule['id'], 'rule_sha256': _digest(rule), 'result_index': index,
                 'completed': index < len(results)}
        if index < len(results):
            raw = results[index]
            root = raw.get('transaction', {}).get('transaction_info', {}).get('call_trace', {})
            base, last = originals[0][0], originals[-1][0]
            nonce = base['nonce'] + sum(context['from'] == base['from'] for context, _ in originals) + index - len(originals)
            probe_context = {**last, 'from': base['from'], 'to': rule['account'], 'input': rule['calldata'],
                             'value': 0, 'gas': 300000, 'gas_price': 0, 'nonce': nonce}
            validate_sequence_result(probe_context, base, raw)
            info = raw['transaction']['transaction_info']
            if (_status(raw['simulation'].get('status'), 'sequence.probe.status') != 1
                    or any(info.get(field) != [] for field in ('balance_diff', 'asset_changes', 'state_diff', 'logs'))
                    or re.fullmatch(r'0x[0-9a-fA-F]{64}', str(root.get('output', ''))) is None):
                _reject('sequence.probe_read_only_evidence', 'missing_evidence')
            trace = execution_summary(raw, {**artifact, 'result_index': index}, [])['trace']
            if not trace.get('complete'):
                _reject('sequence.probe_trace', 'missing_evidence')
            probe.update(artifact={**artifact, 'result_index': index}, output=root['output'].lower())
        probes.append(probe)
    return {'artifact': artifact, 'requested_count': len(originals) + len(rules),
            'executed_count': len(results), 'transaction_count': min(len(results), len(originals)),
            'probe_count': len(rules), 'probes': probes,
            'stopped_at': stopped, 'status': 'stopped_after_revert' if stopped is not None else 'completed'}


def sequence_pairs(originals, bundles, artifacts, addresses, overrides, plan):
    from app.attackpilot.utils.security_checks import extract_security_observations
    base = originals[0][0]
    pairs = []
    for index, (context, raw) in enumerate(originals):
        context = {**context, 'access_list': raw.get('accessList', [])}
        pair = {'original_transaction_hash': context['transaction_hash'], 'sequence_index': index,
                'context': public_context(context, raw), 'patched_addresses': addresses}
        for role in ('control', 'patched'):
            results, reference = bundles[role], artifacts[role]
            if index >= len(results):
                pair[role] = {'completed': False, 'status': 'not_executed',
                              'reason_code': 'sequence_stopped_after_revert'}
                continue
            result = results[index]
            artifact = {**reference, 'result_index': index}
            baseline = validate_sequence_result(context, base, result, control=role == 'control')
            summary = execution_summary(result, artifact, addresses, runtime_codes=(
                {address: item['code'] for address, item in overrides.items()} if role == 'patched' else None))
            if role == 'control':
                summary.update(control_validation='validated', baseline_validation=baseline)
            if plan is not None:
                summary['security_observations'] = extract_security_observations(
                    result, artifact, plan, transaction_hash=context['transaction_hash'])
            if index == len(originals) - 1:
                summary['security_probes'] = [
                    {key: item[key] for key in ('property_id', 'rule_sha256', 'artifact', 'output')}
                    for item in sequence_descriptor(originals, reference, results, plan)['probes']
                    if item.get('completed')]
            pair[role] = summary
        control, patched = pair['control'], pair['patched']
        if control.get('completed') and patched.get('completed'):
            pair['comparison'] = {
                'attack_transaction_reverted': control['status'] == 'success' and patched['status'] == 'revert',
                'logs_changed': control['logs']['ordered_logs_sha256'] != patched['logs']['ordered_logs_sha256'],
                'gas_changed': control['gas_used'] != patched['gas_used'], 'profit_usd': None}
        else:
            pair['comparison'] = {'status': 'not_executed', 'profit_usd': None}
        pairs.append(pair)
    return pairs


def _validate_sequence(store, sequence, pairs, addresses, plan, integrity=None):
    if not isinstance(sequence, dict) or sequence.get('mode') != SEQUENCE_MODE:
        raise ValueError('Missing stateful sequence evidence')
    hashes = sequence.get('ordered_transaction_hashes')
    originals = resolve_sequence(store, [{'hash': tx} for tx in hashes], int(pairs[0]['context']['network_id']))
    if ([pair['original_transaction_hash'] for pair in pairs] != hashes
            or sequence.get('base_context') != public_context(*originals[0])):
        raise ValueError('Sequence scope/base mismatch')
    bundles, artifacts, overrides = {}, {}, None
    for role in ('control', 'patched'):
        descriptor = sequence.get(role)
        if not isinstance(descriptor, dict):
            raise ValueError('Missing sequence execution')
        reference = descriptor.get('artifact')
        request, response = store.read_artifact(reference, whole_response=True,
                                              expected_role=role, original_hash=hashes[0])
        results = response.get('simulation_results')
        validate_bundle_results(results, len(sequence_payload(originals, plan=plan)['simulations']))
        if role == 'patched':
            objects = request.get('simulations', [{}])[0].get('state_objects')
            if not isinstance(objects, dict) or any(set(item) != {'code'} for item in objects.values() if isinstance(item, dict)):
                raise ValueError('Sequence may override only patched runtime code')
            overrides = runtime_overrides({address: item['code'] for address, item in objects.items()})
            if sorted(overrides) != addresses:
                raise ValueError('Sequence runtime scope mismatch')
        if request != sequence_payload(originals, overrides if role == 'patched' else None, plan):
            raise ValueError('Stateful sequence request mismatch')
        if descriptor != sequence_descriptor(originals, reference, results, plan):
            raise ValueError('Sequence count/early-stop mismatch')
        bundles[role], artifacts[role] = results, reference
        if role == 'control' and isinstance(integrity, dict):
            contracts = integrity.get('contracts', {})
            for raw_result in results[:len(originals)]:
                observed = execution_summary(raw_result, reference, addresses)['trace'].get('call_targets', [])
                records = raw_result.get('contracts')
                for address in set(observed).intersection(addresses):
                    candidates = [item.get('deployed_bytecode') for item in records if isinstance(item, dict)
                                  and isinstance(item.get('address'), str) and item['address'].lower() == address]
                    candidates = [code for code in candidates if isinstance(code, str)
                                  and re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', code)]
                    if (len(candidates) != 1 or contracts.get(address, {}).get('original_runtime_sha256')
                            != hashlib.sha256(bytes.fromhex(candidates[0][2:])).hexdigest()):
                        raise ValueError('Historical control runtime differs from patched contract version')
    rebuilt = sequence_pairs(originals, bundles, artifacts, addresses, overrides, plan)
    if rebuilt != pairs:
        raise ValueError('Sequence execution summary changed from immutable evidence')
    return {'control_complete': len(bundles['control']) >= len(originals),
            'patched_complete': len(bundles['patched']) >= len(originals),
            'patched_stopped_at': sequence['patched']['stopped_at'], 'transaction_count': len(originals),
            'runtime_codes': {address: item['code'] for address, item in overrides.items()}}


def validate_sequential_evidence(report, *, cache_root=None):
    """Rebuild reports from immutable bundle artifacts; never trust summaries."""
    try:
        if (not isinstance(report, dict) or report.get('schema_version') != 2
                or report.get('scope') != SEQUENCE_SCOPE or report.get('status') != 'completed'
                or report.get('control_validation') != 'validated'):
            raise ValueError('Invalid stateful replay envelope')
        store = PatchReplayEvidenceStore(cache_root)
        plan = report.get('verification_plan')
        if plan is not None:
            from app.attackpilot.utils.security_checks import validate_verification_plan
            if validate_verification_plan(plan) != plan or report.get('verification_plan_sha256') != _digest(plan):
                raise ValueError('Sequence verification plan identity mismatch')
        addresses = report.get('patched_addresses')
        if (not isinstance(addresses, list) or not addresses or addresses != sorted(set(addresses))
                or any(not isinstance(address, str) or re.fullmatch(r'0x[0-9a-f]{40}', address) is None for address in addresses)):
            raise ValueError('Invalid sequence patched addresses')
        pairs = report.get('transactions')
        if not isinstance(pairs, list) or not pairs:
            raise ValueError('Missing sequential transactions')
        if isinstance(plan, dict) and plan['attack_transaction_hashes'] != [pair['original_transaction_hash'] for pair in pairs]:
            raise ValueError('Sequence attack plan order mismatch')
        integrity = report.get('runtime_integrity')
        attack = _validate_sequence(store, report.get('sequence'), pairs, addresses, plan, integrity)
        if report.get('transaction_count') != len(pairs) or not attack['control_complete']:
            raise ValueError('Control sequence is incomplete')
        normal = report.get('normal_regression')
        cases = normal.get('cases') if isinstance(normal, dict) else None
        expected = plan.get('normal_regression_cases', []) if isinstance(plan, dict) else []
        if not isinstance(cases, list) or len(cases) != len(expected):
            raise ValueError('Normal regression case scope mismatch')
        if (normal.get('transaction_count') != sum(len(case['transaction_hashes']) for case in expected)
                or normal.get('status') != ('completed' if expected else 'not_run')):
            raise ValueError('Normal regression execution envelope mismatch')
        for case, declared in zip(cases, expected):
            if (case.get('id') != declared['id']
                    or [pair['original_transaction_hash'] for pair in case['transactions']] != declared['transaction_hashes']):
                raise ValueError('Normal regression input scope mismatch')
            checked = _validate_sequence(store, case.get('sequence'), case['transactions'], addresses, plan, integrity)
            if checked['runtime_codes'] != attack['runtime_codes']:
                raise ValueError('Normal regression uses a different patch')
        if isinstance(integrity, dict):
            contracts = integrity.get('contracts', {})
            for address, code in attack['runtime_codes'].items():
                if contracts.get(address, {}).get('patched_runtime_sha256') != hashlib.sha256(bytes.fromhex(code[2:])).hexdigest():
                    raise ValueError('Sequence runtime integrity digest mismatch')
        return {'status': 'validated', 'reason_code': 'stateful_sequence_validated',
                'complete': True, **attack, 'normal_case_count': len(cases)}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, OSError, HistoricalReplayValidationError, TenderlyAPIError) as exc:
        return {'status': 'unavailable', 'reason_code': 'sequential_evidence_invalid',
                'complete': False, 'detail': str(exc)[:512]}
