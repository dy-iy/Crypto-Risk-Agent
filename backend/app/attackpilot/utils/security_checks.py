"""Declared, input-bound invariants measured from immutable simulation artifacts.

Provider prices, decoded labels and a model's opinion are never measurements.
Missing words remain unknown. A confirmed whole-transaction EVM revert can
preserve an explicitly recorded final native balance outside fee participants.
"""
import hashlib
import json
from pathlib import Path
import re

ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
WORD = re.compile(r'0x[0-9a-fA-F]{64}')
DIGEST = re.compile(r'[0-9a-f]{64}')
MAX_PROPERTIES = 64
MAX_TRANSACTIONS = 50
MAX_NORMAL_CASES = 16
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024

_PLAN_ERROR_FIELDS = {
    'network_id_invalid': 'network_id', 'network_id_mismatch': 'network_id',
    'execution_chain_unavailable': 'network_id',
    'reference_invalid': 'authority.evidence_refs', 'reference_conflict': 'authority.evidence_refs',
    'evidence_unavailable': 'authority.evidence_refs', 'evidence_hash_mismatch': 'authority.evidence_refs',
    'evidence_too_large': 'authority.evidence_refs', 'authority_invalid': 'authority',
    'attack_scope_mismatch': 'attack_transaction_hashes',
    'transaction_count_exceeded': 'attack_transaction_hashes',
    'observation_scope_invalid': 'security_properties.transaction_hashes',
    'normal_cases_invalid': 'normal_regression_cases', 'plan_invalid': 'verification_plan',
}
_PLAN_ERROR_MESSAGES = {
    'verification_plan.network_id must be a positive chain ID string': 'network_id_invalid',
    'verification_plan.network_id does not match the execution chain': 'network_id_mismatch',
    'verification_plan.authority is invalid': 'authority_invalid',
    'investigation verification plan requires evidence references': 'authority_invalid',
    'verification_plan.authority evidence digest is invalid': 'reference_invalid',
    'verification_plan.authority.evidence_refs is invalid': 'reference_invalid',
    'verification_plan.authority.evidence_refs.reference: expected nonempty text': 'reference_invalid',
    'call_result probes must observe the final transaction in their sequence': 'observation_scope_invalid',
    'normal regression requires executable assertions': 'normal_cases_invalid',
    'normal regression may not reuse an attack transaction': 'normal_cases_invalid',
}


class VerificationPlanValidationError(ValueError):
    def __init__(self, code, message):
        self.code = code if code in _PLAN_ERROR_FIELDS else 'plan_invalid'
        super().__init__(message)


def verification_plan_diagnostic(exc, *, origin='unknown'):
    """Only fixed code/field names may become public validation diagnostics."""
    code = exc.code if isinstance(exc, VerificationPlanValidationError) else _PLAN_ERROR_MESSAGES.get(str(exc), 'plan_invalid')
    return {'schema_version': 1, 'code': code, 'field': _PLAN_ERROR_FIELDS[code],
            'origin': origin if origin in {'user_declared', 'investigation_derived'} else 'unknown',
            'retryable': False}


def canonical_plan_diagnostic(value):
    if (not isinstance(value, dict)
            or set(value) != {'schema_version', 'code', 'field', 'origin', 'retryable'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or not isinstance(value['code'], str) or value['code'] not in _PLAN_ERROR_FIELDS
            or value['field'] != _PLAN_ERROR_FIELDS[value['code']]
            or not isinstance(value['origin'], str) or value['origin'] not in {'user_declared', 'investigation_derived', 'unknown'}
            or value['retryable'] is not False):
        return None
    return dict(value)


def legacy_verification_plan_diagnostic(state):
    """Describe known old failures without publishing arbitrary stored prose."""
    if (state.get('reason_code') != 'invalid_verification_plan'
            or state.get('stage') != 'preconditions'
            or state.get('replay_attempted') is not False or state.get('replay_completed') is not False):
        return None
    reason = state.get('reason')
    prefix, suffix = '验证计划未通过输入及证据校验：', '；尚未生成或回放补丁。'
    if not isinstance(reason, str) or not reason.startswith(prefix) or not reason.endswith(suffix):
        return None
    message = reason[len(prefix):-len(suffix)]
    if message not in _PLAN_ERROR_MESSAGES:
        return None
    return verification_plan_diagnostic(ValueError(message))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def plan_digest(plan):
    return _digest(plan)


rule_digest = plan_digest


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f'verification_plan.{field}: expected nonempty text')
    return value.strip()


def _hashes(value, field):
    if (not isinstance(value, list) or not 1 <= len(value) <= MAX_TRANSACTIONS
            or any(not isinstance(item, str) or not WORD.fullmatch(item) for item in value)):
        raise ValueError(f'verification_plan.{field}: expected transaction hashes')
    result = [item.lower() for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f'verification_plan.{field}: duplicate transaction')
    return result


def _number(value, *, signed=False):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r'-?[0-9]+|0x[0-9a-fA-F]+', value):
        number = int(value, 16 if value.startswith('0x') else 10)
    else:
        raise ValueError('expected an exact raw integer')
    if not (-2**256 < number < 2**256) or not signed and number < 0:
        raise ValueError('raw integer out of range')
    return number


def _rule(value, *, normal, transactions):
    if not isinstance(value, dict):
        raise ValueError('verification_plan property must be an object')
    result = {'id': _text(value.get('id'), 'property.id'),
              'rationale': _text(value.get('rationale'), 'property.rationale')}
    kind, operator = value.get('kind'), value.get('operator')
    if kind not in {'native_balance', 'token_balance', 'storage', 'call_result'}:
        raise ValueError('verification_plan property kind is unsupported')
    allowed = {'delta_lte', 'delta_gte', 'after_eq', 'unchanged'}
    if normal:
        allowed.add('matches_control')
    if (operator not in allowed or kind == 'storage' and operator in {'delta_lte', 'delta_gte'}
            or kind == 'call_result' and operator not in {'after_eq', 'matches_control'}):
        raise ValueError('verification_plan property operator is unsupported')
    account = value.get('account')
    if not isinstance(account, str) or not ADDRESS.fullmatch(account):
        raise ValueError('verification_plan property account is invalid')
    result.update(kind=kind, operator=operator, account=account.lower())
    if kind == 'call_result':
        calldata = value.get('calldata')
        if (not isinstance(calldata, str) or len(calldata) > 8194
                or re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){4,}', calldata) is None):
            raise ValueError('verification_plan call_result calldata is invalid')
        result['calldata'] = calldata.lower()
    if kind == 'token_balance':
        token = value.get('token')
        if not isinstance(token, str) or not ADDRESS.fullmatch(token):
            raise ValueError('verification_plan property token is invalid')
        result['token'] = token.lower()
    if kind == 'storage':
        slot = value.get('slot')
        if not isinstance(slot, str) or not WORD.fullmatch(slot):
            raise ValueError('verification_plan property storage slot is invalid')
        result['slot'] = slot.lower()
        if 'mask' in value:
            mask = value['mask']
            if not isinstance(mask, str) or not WORD.fullmatch(mask) or int(mask, 16) == 0:
                raise ValueError('verification_plan property storage mask is invalid')
            result['mask'] = mask.lower()
    if operator not in {'unchanged', 'matches_control'}:
        expected = value.get('expected')
        if kind in {'storage', 'call_result'}:
            if not isinstance(expected, str) or not WORD.fullmatch(expected):
                raise ValueError('verification_plan property expected storage word is invalid')
            result['expected'] = expected.lower()
        else:
            result['expected'] = str(_number(expected, signed=operator.startswith('delta_')))
    hashes = _hashes(value.get('transaction_hashes', transactions if normal else None),
                     'property.transaction_hashes')
    if not set(hashes).issubset(transactions):
        raise ValueError('verification_plan property references an undeclared transaction')
    result['transaction_hashes'] = hashes
    if kind == 'call_result' and hashes != [transactions[-1]]:
        raise ValueError('call_result probes must observe the final transaction in their sequence')
    return result


def validate_verification_plan(value, *, network_id=None):
    """Return one canonical schema for API, model output, replay and adjudication."""
    if value is None:
        return None
    if (not isinstance(value, dict) or type(value.get('schema_version')) is not int
            or value['schema_version'] != 1):
        raise ValueError('verification_plan.schema_version must be 1')
    network = value.get('network_id')
    if type(network) is int and network > 0:
        network = str(network)
    if not isinstance(network, str) or re.fullmatch(r'[0-9]+', network) is None or int(network) <= 0:
        raise VerificationPlanValidationError('network_id_invalid', 'verification_plan.network_id must be a positive chain ID string')
    network = str(int(network))
    if network_id is not None and network != str(network_id):
        raise VerificationPlanValidationError('network_id_mismatch', 'verification_plan.network_id does not match the execution chain')
    attacks = _hashes(value.get('attack_transaction_hashes'), 'attack_transaction_hashes')
    authority = value.get('authority')
    if not isinstance(authority, dict) or authority.get('kind') not in {'user_declared', 'investigation_derived'}:
        raise ValueError('verification_plan.authority is invalid')
    refs = authority.get('evidence_refs')
    if refs is None:
        refs = []
    if not isinstance(refs, list) or len(refs) > MAX_PROPERTIES:
        raise ValueError('verification_plan.authority.evidence_refs is invalid')
    normalized_refs = []
    for ref in refs:
        if (not isinstance(ref, dict) or not isinstance(ref.get('sha256'), str)
                or re.fullmatch(r'[0-9a-fA-F]{64}', ref['sha256']) is None):
            raise ValueError('verification_plan.authority evidence digest is invalid')
        if 'reference' in ref and 'path' in ref and ref['reference'] != ref['path']:
            raise VerificationPlanValidationError('reference_conflict', 'verification_plan authority reference and path disagree')
        reference = ref.get('reference', ref.get('path'))
        normalized_refs.append({'reference': _text(reference, 'authority.evidence_refs.reference'),
                                'sha256': ref['sha256'].lower()})
    if authority['kind'] == 'investigation_derived' and not refs:
        raise ValueError('investigation verification plan requires evidence references')
    properties = value.get('security_properties')
    properties = [] if properties is None else properties
    cases = value.get('normal_regression_cases')
    cases = [] if cases is None else cases
    if (not isinstance(properties, list) or len(properties) > MAX_PROPERTIES
            or not isinstance(cases, list) or len(cases) > MAX_NORMAL_CASES):
        raise ValueError('verification_plan property/case limit exceeded')
    properties = [_rule(rule, normal=False, transactions=attacks) for rule in properties]
    normalized_cases = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError('verification_plan normal case must be an object')
        hashes = _hashes(case.get('transaction_hashes'), 'normal_regression_cases.transaction_hashes')
        if set(hashes).intersection(attacks):
            raise ValueError('normal regression may not reuse an attack transaction')
        assertions = case.get('assertions')
        if not isinstance(assertions, list) or not 1 <= len(assertions) <= MAX_PROPERTIES:
            raise ValueError('normal regression requires executable assertions')
        normalized_case = {'id': _text(case.get('id'), 'normal_regression_cases.id'),
                           'transaction_hashes': hashes,
                           'assertions': [_rule(rule, normal=True, transactions=hashes) for rule in assertions]}
        if 'name' in case:
            normalized_case['name'] = _text(case['name'], 'normal_regression_cases.name')
        normalized_cases.append(normalized_case)
    ids = [rule['id'] for rule in properties]
    case_ids = [case['id'] for case in normalized_cases]
    if len(set(ids)) != len(ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError('verification_plan contains duplicate IDs')
    for case in normalized_cases:
        ids = [rule['id'] for rule in case['assertions']]
        if len(set(ids)) != len(ids):
            raise ValueError('verification_plan normal case contains duplicate assertion IDs')
    return {'schema_version': 1, 'network_id': network, 'attack_transaction_hashes': attacks,
            'authority': {'kind': authority['kind'], 'reference': _text(authority.get('reference'), 'authority.reference'),
                          'evidence_refs': normalized_refs},
            'security_properties': properties, 'normal_regression_cases': normalized_cases}


normalize_verification_plan = validate_verification_plan


def _validate_plan_evidence(plan, *, cache_root=None):
    """One path, size and digest policy for investigation, patching and review."""
    if plan['authority']['kind'] == 'user_declared':
        return True
    from app.attackpilot import settings
    cache = Path(settings.CACHE_DIR if cache_root is None else cache_root).absolute()
    for ref in plan['authority']['evidence_refs']:
        relative = Path(ref['reference'])
        if relative.is_absolute() or not relative.parts or relative.parts[0] != 'cache' or '..' in relative.parts:
            raise VerificationPlanValidationError('reference_invalid', 'verification_plan evidence reference must identify this task cache')
        candidate = cache.joinpath(*relative.parts[1:])
        try:
            if (not candidate.is_file() or candidate.is_symlink() or cache.is_symlink()
                    or not candidate.resolve().is_relative_to(cache.resolve())
                    or any(parent.is_symlink() for parent in candidate.parents)):
                raise VerificationPlanValidationError('evidence_unavailable', 'verification_plan task evidence is unavailable or uses a symbolic link')
            if candidate.stat().st_size > MAX_EVIDENCE_BYTES:
                raise VerificationPlanValidationError('evidence_too_large', 'verification_plan task evidence exceeds the size limit')
            with candidate.open('rb') as stream:
                data = stream.read(MAX_EVIDENCE_BYTES + 1)
            if len(data) > MAX_EVIDENCE_BYTES:
                raise VerificationPlanValidationError('evidence_too_large', 'verification_plan task evidence exceeds the size limit')
            if hashlib.sha256(data).hexdigest() != ref['sha256']:
                raise VerificationPlanValidationError('evidence_hash_mismatch', 'verification_plan evidence digest does not match the task artifact')
        except OSError as exc:
            raise VerificationPlanValidationError('evidence_unavailable', 'verification_plan task evidence cannot be read') from exc
    return True


def validate_plan_authority(plan, *, cache_root=None):
    """Investigation references must exist in this task's immutable cache."""
    try:
        return _validate_plan_evidence(plan, cache_root=cache_root)
    except (ValueError, TypeError, KeyError, OSError):
        return False


def resolve_task_verification_plan(proposed, *, explicit=None, network_id, transaction_hashes, cache_root=None):
    """Resolve once by the same rules before investigation ends and patching starts."""
    selected = explicit if explicit is not None else proposed
    if selected is None:
        return None
    if network_id is None:
        raise VerificationPlanValidationError('execution_chain_unavailable', 'verification_plan execution chain is unavailable')
    plan = validate_verification_plan(selected, network_id=network_id)
    expected_authority = 'user_declared' if explicit is not None else 'investigation_derived'
    if plan['authority']['kind'] != expected_authority:
        raise VerificationPlanValidationError('authority_invalid', 'verification_plan authority does not match its actual source')
    ordered = _hashes(transaction_hashes, 'attack_transaction_hashes')
    if set(plan['attack_transaction_hashes']) != set(ordered):
        raise VerificationPlanValidationError('attack_scope_mismatch', 'verification_plan must cover all submitted attack transactions')
    if any(rule['kind'] == 'call_result' and rule['transaction_hashes'] != [ordered[-1]]
           for rule in plan['security_properties']):
        raise VerificationPlanValidationError('observation_scope_invalid', 'call_result probes must observe the final transaction in their sequence')
    plan['attack_transaction_hashes'] = ordered
    _validate_plan_evidence(plan, cache_root=cache_root)
    return plan


def _observation(info, rule):
    from app.attackpilot.utils.patch_replay import _effect_record
    kind, account = rule['kind'], rule['account']
    if kind == 'call_result':
        return None  # These values require a separate executed, read-only tail probe.
    if kind == 'native_balance':
        records = info.get('balance_diff')
        if not isinstance(records, list) or not all(_effect_record('balance_diff', item) for item in records):
            return None
        selected = [item for item in records if isinstance(item, dict)
                    and isinstance(item.get('address'), str) and item['address'].lower() == account]
        if len(selected) != 1:
            return None
        return (_number(selected[0].get('original')), _number(selected[0].get('dirty')))
    if kind == 'storage':
        records = info.get('state_diff')
        if not isinstance(records, list) or not all(_effect_record('state_diff', item) for item in records):
            return None
        selected = []
        for item in records:
            if not isinstance(item, dict) or not isinstance(item.get('raw'), list):
                return None
            for entry in item['raw']:
                if (isinstance(entry, dict) and isinstance(entry.get('address'), str)
                        and entry['address'].lower() == account and entry.get('key', '').lower() == rule['slot']):
                    selected.append(entry)
        if (len(selected) != 1 or any(not isinstance(selected[0].get(key), str)
                                     or not WORD.fullmatch(selected[0][key]) for key in ('original', 'dirty'))):
            return None
        mask = int(rule.get('mask', '0x' + 'f' * 64), 16)
        return tuple(int(selected[0][key], 16) & mask for key in ('original', 'dirty'))
    records = info.get('asset_changes')
    if not isinstance(records, list) or not all(_effect_record('asset_changes', item) for item in records):
        return None
    selected = []
    for item in records:
        token = item.get('token_info') if isinstance(item, dict) else None
        if (isinstance(token, dict) and token.get('standard') == 'ERC20'
                and isinstance(token.get('contract_address'), str)
                and token['contract_address'].lower() == rule['token']
                and account in {str(item.get('from')).lower(), str(item.get('to')).lower()}):
            selected.append(item)
    if not selected or any(type(item.get('trace_absolute_position')) is not int for item in selected):
        return None
    selected.sort(key=lambda item: item['trace_absolute_position'])
    positions = [item['trace_absolute_position'] for item in selected]
    if len(set(positions)) != len(positions):
        return None
    initial, current = None, None
    for item in selected:
        sender = str(item.get('from')).lower() == account
        receiver = str(item.get('to')).lower() == account
        transfer = item.get('type')
        if transfer not in {'Transfer', 'Mint', 'Burn'} or sender and transfer == 'Mint' or receiver and transfer == 'Burn':
            return None
        before = _number(item.get('from_before_balance') if sender else item.get('to_before_balance'))
        if current is not None and before != current:
            return None
        if initial is None:
            initial = before
        amount = _number(item.get('raw_amount'))
        current = before + (amount if receiver else 0) - (amount if sender else 0)
        if current < 0 or current >= 2**256:
            return None
    return initial, current


def _reverted_native_observation(raw_result, rule):
    """Measure committed balances, or establish non-fee-account preservation.

    Tenderly's response state_overrides contains the state for the next bundle
    step, including balances after gas charging. It is not the request's code
    override. Never borrow the control branch's balance: successful patched
    prefixes can legitimately leave a different pre-state. Explicit balance_diff
    records measure sender fees and miner rewards even though EVM writes revert;
    a final snapshot alone cannot establish those accounts' previous balances.
    """
    from app.attackpilot.utils.patch_replay import _effect_record, trace_summary
    from app.attackpilot.utils.replay_validation import _status

    if rule['kind'] != 'native_balance':
        return None
    simulation, transaction = raw_result.get('simulation'), raw_result.get('transaction')
    if not isinstance(simulation, dict) or not isinstance(transaction, dict):
        return None
    if any(_status(data.get('status'), 'rollback.status') != 0 for data in (simulation, transaction)):
        return None
    # Restrict this inference to supported L1 native-fee execution. Other
    # networks and special transactions need their own fee/state proof.
    network = _number(simulation.get('network_id'))
    if network not in {1, 56} or _number(transaction.get('network_id')) != network:
        return None
    if any(data.get(field) is not False for data in (simulation, transaction)
           for field in ('system_tx', 'deposit_tx')):
        return None
    if _number(simulation.get('gas_used')) != _number(transaction.get('gas_used')):
        return None
    sender, target = simulation.get('from'), simulation.get('to')
    if any(not isinstance(address, str) or not ADDRESS.fullmatch(address) for address in (sender, target)):
        return None
    sender, target = sender.lower(), target.lower()
    if any(not isinstance(transaction.get(field), str) or transaction[field].lower() != value
           for field, value in (('from', sender), ('to', target))):
        return None
    header = simulation.get('block_header')
    miner = header.get('miner') if isinstance(header, dict) else None
    if not isinstance(miner, str) or not ADDRESS.fullmatch(miner):
        return None
    miner = miner.lower()
    account = rule['account']
    info = transaction.get('transaction_info')
    if not isinstance(info, dict) or any(field not in info or info[field] not in (None, [])
                                       for field in ('logs', 'asset_changes', 'state_diff')):
        return None
    root = info.get('call_trace')
    if (not isinstance(root, dict) or root.get('error_op') != 'REVERT'
            or any(not isinstance(root.get(field), str) or root[field].lower() != value
                   for field, value in (('from', sender), ('to', target)))):
        return None
    trace = trace_summary(info, [], execution_status=0)
    if (trace.get('complete') is not True or not any(
            call.get('path') == [] and call.get('failure_confirmed') is True
            and call.get('error_op') == 'REVERT' for call in trace.get('reverted_calls', []))):
        return None
    records = info.get('balance_diff')
    if not isinstance(records, list) or not all(_effect_record('balance_diff', item) for item in records):
        return None
    observed, seen = {}, set()
    for item in records:
        address = item['address'].lower()
        if address in seen or item.get('is_miner') is True and address != miner:
            return None
        seen.add(address)
        before, after = _number(item['original']), _number(item['dirty'])
        if address not in {sender, miner} and before != after:
            return None  # Contradictory committed effect, not an empty diff.
        observed[address] = (before, after)
    snapshot = simulation.get('state_overrides')
    if snapshot is not None and not isinstance(snapshot, dict):
        return None
    balances = []
    for address, state in (snapshot or {}).items():
        if not isinstance(address, str):
            continue
        address = address.lower()
        if address == account and not isinstance(state, dict):
            return None
        if isinstance(state, dict) and 'balance' in state and address in observed:
            if _number(state['balance']) != observed[address][1]:
                return None  # A pre-state or contradictory snapshot is not final state.
        if address == account and isinstance(state, dict) and 'balance' in state:
            balances.append(_number(state['balance']))
    # Providers may repeat the account with a code-only, differently cased key.
    # Multiple recorded balances must agree, including with an explicit diff.
    if len(set(balances)) > 1:
        return None
    if account in observed:
        before, after = observed[account]
        return before, after, 'native_balance_diff'
    if not balances or account in {sender, miner}:
        return None  # Fees survive a revert; never infer their absence.
    balance = balances[0]
    return balance, balance, 'evm_revert_post_balance_snapshot'


def extract_security_observations(raw_result, artifact, plan, *, transaction_hash=None):
    """Extract explicit quantities, including confirmed native-balance rollback."""
    from app.attackpilot.utils.replay_validation import _status
    try:
        plan = validate_verification_plan(plan)
        if plan is None:
            return {'schema_version': 1, 'status': 'unavailable', 'reason_code': 'verification_plan_missing'}
        transaction = raw_result.get('transaction') if isinstance(raw_result, dict) else None
        info = transaction.get('transaction_info') if isinstance(transaction, dict) else None
        if not isinstance(info, dict):
            return {'schema_version': 1, 'status': 'unavailable', 'reason_code': 'raw_state_unavailable'}
        rules = list(plan['security_properties'])
        for case in plan['normal_regression_cases']:
            rules.extend(case['assertions'])
        observations = []
        for rule in rules:
            if transaction_hash is not None and transaction_hash.lower() not in rule['transaction_hashes']:
                continue
            reverted = False
            method = None
            try:
                reverted = _status(transaction.get('status'), 'observation.status') == 0
                if reverted:
                    measurement = _reverted_native_observation(raw_result, rule)
                    value = measurement[:2] if measurement is not None else None
                    method = measurement[2] if measurement is not None else None
                else:
                    value = _observation(info, rule)
            except (ValueError, TypeError, AttributeError, OverflowError):
                value = None
            observations.append({'property_id': rule['id'], 'rule_sha256': _digest(rule),
                                 'status': 'available' if value is not None else 'unknown',
                                 'before': str(value[0]) if value is not None else None,
                                 'after': str(value[1]) if value is not None else None})
            if method is not None:
                observations[-1]['method'] = method
        return {'schema_version': 1, 'status': 'available', 'plan_sha256': plan_digest(plan),
                'artifact_sha256': artifact.get('sha256'), 'request_digest': artifact.get('request_digest'),
                'result_index': artifact.get('result_index'), 'observations': observations}
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        return {'schema_version': 1, 'status': 'unavailable', 'reason_code': 'invalid_verification_plan'}


def _measured_rule(execution, rule, plan, transaction_hash, *, cache_root=None):
    """Recompute from the content-addressed artifact; summary flags are untrusted."""
    from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore
    if (not isinstance(execution, dict) or execution.get('completed') is not True
            or execution.get('status') not in {'success', 'revert'}):
        return None
    if rule['kind'] == 'call_result':
        return _measured_probe(execution, rule, cache_root=cache_root) if execution['status'] == 'success' else None
    artifact = execution.get('artifact') if isinstance(execution, dict) else None
    if not isinstance(artifact, dict):
        return None
    try:
        _request, raw = PatchReplayEvidenceStore(cache_root).read_artifact(artifact)
        # read_artifact resolves a bundle result_index to its actual step.
        if not isinstance(raw, dict):
            return None
        from app.attackpilot.utils.replay_validation import _status
        expected_status = int(execution['status'] == 'success')
        if any(_status(raw.get(key, {}).get('status'), 'observation.execution_status') != expected_status
               for key in ('simulation', 'transaction')):
            return None
        measured = extract_security_observations(raw, artifact, plan, transaction_hash=transaction_hash)
        expected = execution.get('security_observations')
        if expected is not None and expected != measured:
            return None
        for item in measured.get('observations', []):
            if item['rule_sha256'] == _digest(rule) and item['status'] == 'available':
                return int(item['before']), int(item['after'])
    except (OSError, ValueError, TypeError, AttributeError, ImportError, KeyError):
        return None
    return None


def _measured_probe(execution, rule, *, cache_root=None):
    """Read a real getter result from the same bundle's final state."""
    from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore
    from app.attackpilot.utils.replay_validation import _status
    from app.attackpilot.errors import HistoricalReplayValidationError
    probes = execution.get('security_probes') if isinstance(execution, dict) else None
    if not isinstance(probes, list):
        return None
    selected = [probe for probe in probes if isinstance(probe, dict)
                and probe.get('rule_sha256') == rule_digest(rule)
                and probe.get('property_id') == rule['id']]
    if len(selected) != 1:
        return None
    probe = selected[0]
    try:
        request, raw = PatchReplayEvidenceStore(cache_root).read_artifact(probe.get('artifact'))
        index = probe['artifact']['result_index']
        simulation = request['simulations'][index]
        if (simulation.get('to') != rule['account'] or simulation.get('input') != rule['calldata']
                or _number(simulation.get('value')) != 0 or _number(simulation.get('gas_price')) != 0):
            return None
        if (_status(raw.get('simulation', {}).get('status'), 'probe.simulation.status') != 1
                or _status(raw.get('transaction', {}).get('status'), 'probe.transaction.status') != 1):
            return None
        info = raw['transaction']['transaction_info']
        if any(info.get(field) != [] for field in ('state_diff', 'balance_diff', 'asset_changes')):
            return None
        if info.get('logs') != []:
            return None
        trace = info.get('call_trace')
        output = trace.get('output') if isinstance(trace, dict) else None
        if (not isinstance(output, str) or not WORD.fullmatch(output)
                or probe.get('output') != output.lower()):
            return None
        return int(output, 16), int(output, 16)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, IndexError, HistoricalReplayValidationError):
        return None


def _satisfies(rule, value, *, control=None):
    if value is None:
        return None
    before, after = value
    operator = rule['operator']
    if operator == 'matches_control':
        return None if control is None else after == control[1]
    if operator == 'unchanged':
        return before == after
    expected = int(rule['expected'], 16 if rule['kind'] in {'storage', 'call_result'} else 10)
    if rule['kind'] == 'storage':
        expected &= int(rule.get('mask', '0x' + 'f' * 64), 16)
    return {'delta_lte': lambda: after - before <= expected,
            'delta_gte': lambda: after - before >= expected,
            'after_eq': lambda: after == expected}[operator]()


def evaluate_security_properties(plan, pairs, *, cache_root=None):
    """Preserve every invariant and eliminate at least one observed violation."""
    properties = plan['security_properties']
    if not properties:
        return {'status': 'unavailable', 'reason_code': 'security_properties_missing', 'checks': []}
    by_hash = {pair.get('original_transaction_hash', '').lower(): pair for pair in pairs if isinstance(pair, dict)}
    checks = []
    for rule in properties:
        for tx_hash in rule['transaction_hashes']:
            pair = by_hash.get(tx_hash, {})
            control = _measured_rule(pair.get('control'), rule, plan, tx_hash, cache_root=cache_root)
            patched = _measured_rule(pair.get('patched'), rule, plan, tx_hash, cache_root=cache_root)
            original_pass = _satisfies(rule, control)
            patched_pass = _satisfies(rule, patched)
            status = ('failed' if patched_pass is False else
                      'unknown' if original_pass is None or patched_pass is None else 'passed')
            effect = ('preserved' if original_pass is True and patched_pass is True else
                      'repaired' if original_pass is False and patched_pass is True else
                      'violated' if patched_pass is False else 'unknown')
            checks.append({'property_id': rule['id'], 'kind': rule['kind'], 'transaction_hash': tx_hash,
                           'status': status, 'effect': effect,
                           'control_satisfies': original_pass, 'patched_satisfies': patched_pass,
                           'control': {'before': str(control[0]), 'after': str(control[1])} if control else None,
                           'patched': {'before': str(patched[0]), 'after': str(patched[1])} if patched else None})
            if rule['kind'] == 'call_result':
                for role in ('control', 'patched'):
                    if checks[-1][role] is not None:
                        checks[-1][role].pop('before', None)  # Getter measured only the final value.
    complete = bool(checks) and all(item['status'] == 'passed' for item in checks)
    repaired = sum(item['effect'] == 'repaired' for item in checks)
    status = ('passed' if complete and repaired else
              'failed' if complete or any(item['status'] == 'failed' for item in checks) else 'unavailable')
    reason = ('control_violation_not_observed' if complete and not repaired else
              'declared_security_properties_' + status)
    return {'status': status, 'reason_code': reason,
            'plan_sha256': plan_digest(plan), 'checks': checks,
            'repaired_check_count': repaired,
            'preserved_check_count': sum(item['effect'] == 'preserved' for item in checks),
            'scope': 'declared_properties_and_recorded_inputs'}


def evaluate_normal_regression(plan, report, modified_addresses, *, cache_root=None):
    cases = plan['normal_regression_cases']
    if not cases:
        return {'status': 'not_run', 'reason_code': 'normal_regression_cases_missing', 'checks': []}
    from app.attackpilot.utils.verification import _trace_call_targets
    by_id = {case.get('id'): case for case in report.get('cases', []) if isinstance(case, dict)}
    checks = []
    for case in cases:
        observed = by_id.get(case['id'], {})
        pairs = observed.get('transactions', [])
        by_hash = {pair.get('original_transaction_hash', '').lower(): pair for pair in pairs if isinstance(pair, dict)}
        reached = False
        for tx_hash in case['transaction_hashes']:
            pair = by_hash.get(tx_hash, {})
            control, patched = pair.get('control', {}), pair.get('patched', {})
            targets = _trace_call_targets(patched)
            if targets is not None and modified_addresses.intersection(targets):
                reached = True
            valid = all(execution.get('completed') is True and execution.get('status') == 'success'
                        for execution in (control, patched))
            for rule in case['assertions']:
                if tx_hash not in rule['transaction_hashes']:
                    continue
                original_value = _measured_rule(control, rule, plan, tx_hash, cache_root=cache_root)
                patched_value = _measured_rule(patched, rule, plan, tx_hash, cache_root=cache_root)
                original_pass = _satisfies(rule, original_value, control=original_value)
                patched_pass = _satisfies(rule, patched_value, control=original_value)
                status = ('failed' if not valid or original_pass is False or patched_pass is False else
                          'unknown' if original_pass is None or patched_pass is None else 'passed')
                checks.append({'case_id': case['id'], 'property_id': rule['id'], 'transaction_hash': tx_hash,
                               'status': status, 'control_satisfies': original_pass, 'patched_satisfies': patched_pass})
        if not reached:
            checks.append({'case_id': case['id'], 'status': 'unknown', 'reason_code': 'modified_code_not_reached'})
    status = 'passed' if checks and all(item['status'] == 'passed' for item in checks) else (
        'failed' if any(item['status'] == 'failed' for item in checks) else 'unavailable')
    return {'status': status, 'reason_code': 'normal_regression_' + status,
            'plan_sha256': plan_digest(plan), 'checks': checks,
            'scope': 'declared_normal_cases_and_assertions'}
