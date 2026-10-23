"""Execution evidence used to distinguish patch outcomes from pipeline failures."""
import ast
import hashlib
import json
import re
from collections import Counter

VERIFICATION_POLICY_VERSION = 2


def replay_evidence_digest(value):
    """Bind a verdict to its complete recorded input, independently of key order."""
    if not isinstance(value, dict):
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def verification_state(status="not_run", *, stage="pending", reason_code="not_started",
                       reason="尚未执行补丁回放。", replay_attempted=False,
                       replay_completed=False, terminal=False, **evidence):
    return {
        "schema_version": 2,
        "status": status,
        "stage": stage,
        "reason_code": reason_code,
        "reason": reason,
        "replay_attempted": replay_attempted,
        "replay_completed": replay_completed,
        "terminal": terminal,
        **evidence,
    }


def patch_execution_state(patcher):
    """An agent's success flag alone never establishes that replay happened."""
    state = getattr(patcher, "verification", None)
    if not isinstance(state, dict) or state.get("schema_version") != 2:
        return verification_state(
            "unverified", stage="replay", reason_code="replay_evidence_missing",
            reason="缺少可确认的回放执行记录，尚未完成补丁验证。", terminal=True,
        )
    result = dict(state)
    completed = state.get("replay_completed") is True
    result["replay_completed"] = completed
    result["replay_attempted"] = state.get("replay_attempted") is True or completed
    if result.get("status") in {"verified", "failed"}:
        # Only the analysis coordinator may attach a verdict after the judge.
        result["status"] = "unverified"
    return result


_ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
_HASH = re.compile(r'0x[0-9a-fA-F]{64}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_SOLIDITY_TOKEN = re.compile(
    r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r'[A-Za-z_$][A-Za-z0-9_$]*|0[xX][0-9a-fA-F]+|[0-9]+|[^\s]',
    re.DOTALL,
)


def _guard_statements(source):
    """Extract literal require/revert reasons without treating comments as code."""
    tokens = [item.group() for item in _SOLIDITY_TOKEN.finditer(source)
              if not item.group().startswith(('//', '/*'))]
    guards = []
    for index, token in enumerate(tokens):
        if token not in {'require', 'revert'} or index + 1 >= len(tokens) or tokens[index + 1] != '(':
            continue
        if index and tokens[index - 1] in {'.', 'function'}:
            continue
        depth, end = 0, index + 1
        for end in range(index + 1, len(tokens)):
            if tokens[end] == '(':
                depth += 1
            elif tokens[end] == ')':
                depth -= 1
                if depth == 0:
                    break
        else:
            continue
        arguments, current, nesting = [], [], 0
        for item in tokens[index + 2:end]:
            if item in {'(', '[', '{'}:
                nesting += 1
            elif item in {')', ']', '}'}:
                nesting -= 1
            if item == ',' and nesting == 0:
                arguments.append(current)
                current = []
            else:
                current.append(item)
        arguments.append(current)
        if len(arguments) != (2 if token == 'require' else 1):
            continue
        literal = arguments[-1]
        if len(literal) == 2 and literal[0] == 'unicode':
            literal = literal[1:]
        if len(literal) != 1 or not literal[0].startswith(('"', "'")):
            continue
        try:
            reason = ast.literal_eval(literal[0])
        except (ValueError, SyntaxError):
            continue
        if isinstance(reason, str) and reason:
            guards.append((tuple(tokens[index:end + 1]), reason))
    return guards


def _modified_guard_reasons(patches):
    """Reasons belong to an address/file only when a real guard changed there."""
    if not isinstance(patches, str) or not patches or len(patches) > 2 * 1024 * 1024:
        return {}
    headers = list(re.finditer(r'^#\s*File:\s*(0x[0-9a-fA-F]{40})::([^\n]+)$',
                               patches, re.MULTILINE))
    block = re.compile(r'<<<<<<< SEARCH[ \t]*\n(.*?)\n=======[ \t]*\n(.*?)\n>>>>>>> REPLACE',
                       re.DOTALL)
    reasons = {}
    for index, header in enumerate(headers):
        address, file_path = header.group(1).lower(), header.group(2).strip()
        content = patches[header.end():headers[index + 1].start() if index + 1 < len(headers) else len(patches)]
        for match in block.finditer(content):
            original, replacement = match.groups()
            old_guards = Counter(signature for signature, _ in _guard_statements(original))
            for signature, reason in _guard_statements(replacement):
                if old_guards[signature]:
                    old_guards[signature] -= 1
                    continue
                reasons.setdefault(address, {}).setdefault(reason, []).append(file_path)
    return reasons


def _modified_code_addresses(patches):
    """Only source changes count; recompiling a dependency is not an intervention."""
    if not isinstance(patches, str) or not patches or len(patches) > 2 * 1024 * 1024:
        return set()
    headers = list(re.finditer(r'^#\s*File:\s*(0x[0-9a-fA-F]{40})::([^\n]+)$',
                               patches, re.MULTILINE))
    block = re.compile(r'<<<<<<< SEARCH[ \t]*\n(.*?)\n=======[ \t]*\n(.*?)\n>>>>>>> REPLACE',
                       re.DOTALL)
    addresses = set()
    for index, header in enumerate(headers):
        content = patches[header.end():headers[index + 1].start() if index + 1 < len(headers) else len(patches)]
        for match in block.finditer(content):
            before, after = ([token.group() for token in _SOLIDITY_TOKEN.finditer(source)
                              if not token.group().startswith(('//', '/*'))]
                             for source in match.groups())
            if before != after:
                addresses.add(header.group(1).lower())
                break
    return addresses


def _trace_call_targets(execution):
    """Unknown or incomplete reachability must never be treated as absence."""
    trace = execution.get('trace')
    if (not isinstance(trace, dict) or trace.get('available') is not True
            or trace.get('complete') is not True or trace.get('call_targets_complete') is not True):
        return None
    targets = trace.get('call_targets')
    if (not isinstance(targets, list) or not targets
            or any(not isinstance(target, str) or not _ADDRESS.fullmatch(target) for target in targets)):
        return None
    return {target.lower() for target in targets}


def _terminal_revert_chain(call, reverted_calls, *, diagnostics=None):
    """Match failures only along an uninterrupted terminal call chain.

    Every enclosing call must revert on its terminal child and carry a bounded
    EVM proof that the child's failure branch causes the observed REVERT while
    the success branch exits normally. Identical or familiar error strings do
    not prove this; post-call computations can fail independently of a child.
    """
    by_path = {}
    for item in reverted_calls:
        path = item.get('path') if isinstance(item, dict) else None
        if (not isinstance(path, list) or len(path) > 128
                or any(type(index) is not int or index < 0 for index in path)):
            return None
        key = tuple(path)
        if key in by_path:
            return None
        by_path[key] = item
    current, chain, transitions = call, [], []
    while True:
        if current.get('failure_confirmed') is not True or current.get('error_op') != 'REVERT':
            return None
        path = current.get('path')
        if not isinstance(path, list) or tuple(path) not in by_path:
            return None
        chain.append(path)
        if not path:
            if current.get('parent_call_path') is not None:
                return None
            return {'method': 'proven_reverted_ancestry',
                    'root_revert_reason': current.get('revert_reason'),
                    'call_paths': list(reversed(chain)),
                    'transitions': list(reversed(transitions))}
        parent_path = current.get('parent_call_path')
        if (current.get('terminal_in_parent') is not True
                or not isinstance(parent_path, list) or len(parent_path) >= len(path)
                or any(type(index) is not int or index < 0 for index in parent_path)
                or path[:len(parent_path)] != parent_path):
            return None
        parent = by_path.get(tuple(parent_path))
        proof = current.get('revert_propagation')
        if (parent is None or not isinstance(proof, dict)
                or proof.get('method') != 'evm_call_failure_branch'
                or type(proof.get('proof_version')) is not int or proof['proof_version'] != 1
                or proof.get('parent_path') != parent_path
                or proof.get('child_path') != path
                or proof.get('parent_code_address') != parent.get('code_address')
                or proof.get('source') not in {'override', 'response_contract'}
                or proof.get('child_call_type') != current.get('call_type')
                or type(proof.get('child_call_pc')) is not int
                or proof['child_call_pc'] != current.get('caller_pc')
                or any(type(proof.get(key)) is not int or proof[key] < 0
                       for key in ('child_call_pc', 'failure_revert_pc', 'success_exit_pc'))
                or any(not isinstance(proof.get(key), str) or not _DIGEST.fullmatch(proof[key])
                       for key in ('runtime_sha256', 'child_output_sha256', 'parent_output_sha256'))
                or not isinstance(proof.get('branch_pcs'), list) or not proof['branch_pcs']
                or any(type(pc) is not int or pc < 0 for pc in proof['branch_pcs'])
                or proof.get('child_output_sha256') != current.get('output_sha256')
                or proof.get('parent_output_sha256') != parent.get('output_sha256')):
            if diagnostics is not None and parent is not None:
                diagnostics.append({'code': 'revert_propagation_unproven',
                                    'child_path': path, 'parent_path': parent_path})
            return None
        transitions.append(proof)
        current = parent


def _matched_guard_location(report, call, address, reason, files):
    """A string match is only a candidate; bind the observed failure to code."""
    from app.attackpilot.utils.patch_attribution import attribution_digest

    evidence = report.get('patch_attribution')
    integrity = report.get('runtime_integrity')
    if (not isinstance(evidence, dict) or type(evidence.get('schema_version')) is not int
            or evidence['schema_version'] != 1 or evidence.get('status') != 'available'
            or evidence.get('applied_patch_sha256') != report.get('applied_patch_sha256')
            or not isinstance(integrity, dict) or integrity.get('status') != 'validated'
            or integrity.get('applied_patch_sha256') != report.get('applied_patch_sha256')):
        return None
    try:
        if evidence.get('evidence_sha256') != attribution_digest(evidence):
            return None
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None
    contracts, runtime_contracts = evidence.get('contracts'), integrity.get('contracts')
    if not isinstance(contracts, dict) or not isinstance(runtime_contracts, dict):
        return None
    contract, runtime = contracts.get(address), runtime_contracts.get(address)
    if (not isinstance(contract, dict) or not isinstance(runtime, dict)
            or not isinstance(contract.get('patched_runtime_sha256'), str)
            or not _DIGEST.fullmatch(contract['patched_runtime_sha256'])
            or contract['patched_runtime_sha256'] != runtime.get('patched_runtime_sha256')
            or call.get('call_type') not in {'CALL', 'STATICCALL', 'DELEGATECALL', 'CALLCODE'}):
        return None
    location = call.get('failure_location')
    candidates = contract.get('guards')
    if (not isinstance(location, dict) or location.get('invalid_fields')
            or not isinstance(candidates, list)):
        return None
    matches = []
    for guard in candidates:
        if (not isinstance(guard, dict) or guard.get('reason') != reason
                or guard.get('file_path') not in files
                or any(not isinstance(guard.get(key), str) or not _DIGEST.fullmatch(guard[key])
                       for key in ('guard_sha256', 'source_sha256'))
                or type(guard.get('start')) is not int or guard['start'] < 0
                or type(guard.get('length')) is not int or guard['length'] <= 0):
            continue
        source_hashes = contract.get('sources_sha256')
        if (not isinstance(source_hashes, dict)
                or source_hashes.get(guard['file_path']) != guard['source_sha256']):
            continue
        pcs = guard.get('revert_pcs')
        if (not isinstance(pcs, list) or not pcs
                or any(type(pc) is not int or pc < 0 for pc in pcs)):
            continue
        identity = location.get('source_identity')
        source_match = (isinstance(identity, dict)
                        and identity.get('file_path') == guard['file_path']
                        and identity.get('source_sha256') == guard['source_sha256']
                        and type(location.get('start')) is int
                        and type(location.get('length')) is int and location['length'] > 0
                        and guard['start'] <= location['start']
                        and location['start'] + location['length'] <= guard['start'] + guard['length'])
        # A present, conflicting PC or identified source location cannot be
        # bypassed by the other coordinate. A naked vendor file ID is not an ID
        # in our compilation and never supplies source identity.
        if 'pc' in location:
            if type(location['pc']) is not int or location['pc'] not in pcs:
                continue
            if identity is not None and not source_match:
                continue
            method = 'compiled_guard_revert_pc'
        elif source_match:
            method = 'compiled_guard_source_range'
        else:
            continue
        matches.append({'method': method, 'patch_file': guard['file_path'],
                        'guard_sha256': guard['guard_sha256'],
                        'source_sha256': guard['source_sha256'],
                        'guard_start': guard['start'], 'guard_length': guard['length'],
                        'failure_location': dict(location),
                        'patched_runtime_sha256': contract['patched_runtime_sha256'],
                        'attribution_sha256': evidence['evidence_sha256']})
    return matches[0] if len(matches) == 1 else None


def _unchanged_success(control, patched):
    """An unrelated historical pair must also preserve its observed execution."""
    if (control.get('status') != 'success' or patched.get('status') != 'success'
            or type(patched.get('gas_used')) is not int
            or patched['gas_used'] != control.get('gas_used')):
        return False
    original_logs, patched_logs = control.get('logs'), patched.get('logs')
    if (not isinstance(original_logs, dict) or not isinstance(patched_logs, dict)
            or patched_logs.get('available') is not True
            or type(patched_logs.get('count')) is not int
            or patched_logs['count'] != original_logs.get('count')
            or patched_logs.get('ordered_logs_sha256') != original_logs.get('ordered_logs_sha256')):
        return False
    # Raw execution effects exclude vendor USD estimates and canonicalize
    # unordered storage records. Explicitly observed empty lists are valid;
    # two missing measurements must never establish equivalence.
    fingerprints = []
    for execution in (control, patched):
        effects = execution.get('execution_effects')
        if (not isinstance(effects, dict) or type(effects.get('schema_version')) is not int
                or effects['schema_version'] != 1 or effects.get('complete') is not True):
            return False
        fields = effects.get('fields')
        if not isinstance(fields, dict):
            return False
        fingerprint = {}
        for name in ('balance_diff', 'asset_changes', 'state_diff'):
            value = fields.get(name)
            if (not isinstance(value, dict) or type(value.get('count')) is not int
                    or value['count'] < 0 or not isinstance(value.get('sha256'), str)
                    or not _DIGEST.fullmatch(value['sha256'])
                    or value.get('availability') != ('present' if value['count'] else 'explicit_empty')):
                return False
            fingerprint[name] = (value['count'], value['sha256'])
        fingerprints.append(fingerprint)
    return fingerprints[0] == fingerprints[1]


def _artifact_reference(value):
    return (isinstance(value, dict)
            and isinstance(value.get('sha256'), str) and _DIGEST.fullmatch(value['sha256']) is not None
            and isinstance(value.get('request_digest'), str)
            and _DIGEST.fullmatch(value['request_digest']) is not None
            and isinstance(value.get('relative_path'), str)
            and value['relative_path'] == f"cache/patch_replay/artifacts/{value['sha256']}.json")


def _validated_control(pair):
    context, control = pair.get('context'), pair.get('control')
    if not isinstance(context, dict) or not isinstance(control, dict):
        return False
    baseline = control.get('baseline_validation')
    if (not isinstance(baseline, dict) or type(baseline.get('schema_version')) is not int
            or baseline.get('schema_version') != 1
            or baseline.get('status') != 'validated'
            or baseline.get('method') != 'rpc_receipt_vs_tenderly_original_replay'
            or control.get('control_validation') != 'validated'
            or control.get('completed') is not True or control.get('status') != 'success'
            or baseline.get('receipt_status') != 1 or type(baseline.get('receipt_status')) is not int
            or not _artifact_reference(control.get('artifact'))):
        return False
    original_hash = pair.get('original_transaction_hash')
    if not isinstance(original_hash, str) or not _HASH.fullmatch(original_hash):
        return False
    if baseline.get('original_transaction_hash') != original_hash:
        return False
    if any(baseline.get(key) != context.get(key) for key in
           ('network_id', 'block_number', 'block_hash', 'transaction_index')):
        return False
    if (not isinstance(context.get('network_id'), str) or not context['network_id'].isdigit()
            or int(context['network_id']) <= 0
            or not isinstance(context.get('block_hash'), str) or not _HASH.fullmatch(context['block_hash'])
            or any(type(context.get(key)) is not int or context[key] < 0
                   for key in ('block_number', 'transaction_index', 'timestamp'))):
        return False
    logs = control.get('logs')
    if (not isinstance(logs, dict) or logs.get('available') is not True
            or type(logs.get('count')) is not int or logs['count'] < 0
            or logs.get('count') != baseline.get('log_count')
            or logs.get('ordered_logs_sha256') != baseline.get('ordered_logs_sha256')
            or not isinstance(logs.get('ordered_logs_sha256'), str)
            or not _DIGEST.fullmatch(logs['ordered_logs_sha256'])
            or type(control.get('gas_used')) is not int or control['gas_used'] < 0
            or control.get('gas_used') != baseline.get('gas_used')
            or not isinstance(baseline.get('receipt_digest'), str)
            or not _DIGEST.fullmatch(baseline['receipt_digest'])):
        return False
    return True


def adjudicate_patch_verification(judge_result, replay_evidence, patches):
    """Conservatively confirm recorded interception; model verdicts are not proof.

    At least one validated successful control must fail in modified code at an
    added/changed literal guard. A successful pair outside the modified code can
    be recorded separately only with complete unchanged execution evidence.
    Independent historical states never establish a sequential attack replay.
    Profit, normal functionality and root-cause rejection remain unmeasured.
    """
    report = replay_evidence if isinstance(replay_evidence, dict) else {}
    pairs = report.get('transactions')
    pairs = pairs if isinstance(pairs, list) else []
    attempted = any(isinstance(pair, dict) and any(
        isinstance(pair.get(role), dict) and
        (pair[role].get('completed') is True or isinstance(pair[role].get('artifact'), dict))
        for role in ('control', 'patched')
    ) for pair in pairs)
    completed = bool(pairs) and report.get('status') == 'completed' and all(
        isinstance(pair, dict) and all(isinstance(pair.get(role), dict) and
                                      pair[role].get('completed') is True
                                      for role in ('control', 'patched')) for pair in pairs)
    result = judge_result if isinstance(judge_result, dict) else {}
    verdict = result.get('verdict')
    allowed_verdicts = {'VERIFIED', 'INEFFECTIVE_PATCH', 'WRONG_ROOT_CAUSE', 'BROKEN_LOGIC', 'UNVERIFIED'}
    verdict = verdict if isinstance(verdict, str) and verdict in allowed_verdicts else None
    checked = []
    unaffected = []
    attribution_issues = []
    modified_addresses = _modified_code_addresses(patches)
    # Current FixAgent reports carry every source-mapped required trigger.
    # Legacy reports remain usable for their recorded-input scope only. An
    # offline re-review must restore known requirements from the actual source
    # mapping/hypothesis; a missing field never proves no other trigger exists.
    required = report.get('required_trigger_transaction_hashes')
    required_valid = ('required_trigger_transaction_hashes' not in report
                      or isinstance(required, list) and 1 <= len(required) <= 4
                      and all(isinstance(tx, str) and _HASH.fullmatch(tx) for tx in required)
                      and len({tx.lower() for tx in required}) == len(required))
    required_hashes = list(dict.fromkeys(tx.lower() for tx in required
                                        if isinstance(tx, str) and _HASH.fullmatch(tx))) if isinstance(required, list) else []
    evidence_digest = replay_evidence_digest(report)

    def outcome(reason_code, reason, *, verified=False, next_action=None):
        intercepted = [item['original_transaction_hash'] for item in checked]
        outside_code = [item['original_transaction_hash'] for item in unaffected]
        resolved = {tx.lower() for tx in intercepted + outside_code}
        expected = list(dict.fromkeys([
            pair['original_transaction_hash'].lower() for pair in pairs
            if isinstance(pair, dict) and isinstance(pair.get('original_transaction_hash'), str)
        ] + required_hashes))
        return verification_state(
            'verified' if verified else 'unverified', stage='judge', reason_code=reason_code,
            reason=reason, replay_attempted=attempted or completed,
            replay_completed=completed, terminal=next_action is None, judge_verdict=verdict,
            retryable=next_action is not None,
            next_action=next_action or ('complete' if verified else 'collect_missing_evidence'),
            scope='attack_path_only', evidence_version=1, evidence_validated=verified,
            verification_policy_version=VERIFICATION_POLICY_VERSION,
            replay_evidence_sha256=evidence_digest,
            applied_patch_sha256=report.get('applied_patch_sha256'),
            checked=list(checked), unaffected=list(unaffected),
            attribution_issues=list(attribution_issues[:16]), coverage={
                'mode': 'independent_historical_transaction_pairs',
                'modified_addresses': sorted(modified_addresses),
                'required_trigger_transaction_hashes': list(required_hashes),
                'intercepted_transaction_hashes': intercepted,
                'unaffected_transaction_hashes': outside_code,
                'unresolved_transaction_hashes': [tx for tx in expected if tx not in resolved],
                'sequence_replay_verified': False,
            }, dimensions={
                'attack_interception': {'status': 'passed' if verified else 'unavailable'},
                'normal_regression': {'status': 'not_run'},
                'profit': {'status': 'unavailable', 'usd': None},
            },
        )

    if (type(report.get('schema_version')) is not int or report.get('schema_version') != 1
            or report.get('scope') != 'independent_historical_transaction_pairs'
            or evidence_digest is None):
        return outcome('structured_replay_evidence_missing', '缺少已记录的原版与补丁版独立历史回放证据。')
    if (not completed or report.get('control_validation') != 'validated'
            or not 1 <= len(pairs) <= 4 or type(report.get('transaction_count')) is not int
            or report.get('transaction_count') != len(pairs)):
        return outcome('paired_replay_incomplete', '对照或补丁回放未完成，无法确认补丁有效性。')
    if (not isinstance(patches, str) or not isinstance(report.get('applied_patch_sha256'), str)
            or report['applied_patch_sha256'] != hashlib.sha256(patches.encode('utf-8')).hexdigest()):
        return outcome('applied_patch_evidence_mismatch', '回放记录未能绑定本次实际应用的补丁代码。')
    addresses = report.get('patched_addresses')
    if (not isinstance(addresses, list) or not addresses
            or any(not isinstance(address, str) or not _ADDRESS.fullmatch(address) for address in addresses)):
        return outcome('patch_target_missing', '缺少实际修改的合约地址，无法确认拦截位置。')
    addresses = {address.lower() for address in addresses}
    if not modified_addresses or not modified_addresses.issubset(addresses):
        return outcome('patch_target_missing', '实际源码修改地址未能对应本次补丁回放的代码替换地址。')
    guards = _modified_guard_reasons(patches)
    if not guards:
        return outcome('modified_guard_missing', '实际补丁中没有可与回放错误精确对应的新增或修改校验。')
    seen = set()
    for pair in pairs:
        if not _validated_control(pair):
            return outcome('control_evidence_mismatch', '原版对照未能完整对应真实成功交易及其回执。')
        original_hash = pair['original_transaction_hash']
        if original_hash.lower() in seen:
            return outcome('duplicate_replay_transaction', '回放证据包含重复交易，验证范围无法确认。')
        seen.add(original_hash.lower())
        patched = pair.get('patched')
        if not isinstance(patched, dict) or patched.get('completed') is not True:
            return outcome('patch_interception_not_established', '回放没有提供可确认的补丁拦截证据；收益值不能代替该证据。')
        if (not _artifact_reference(patched.get('artifact'))
                or patched['artifact']['request_digest'] == pair['control']['artifact']['request_digest']
                or patched['artifact']['sha256'] == pair['control']['artifact']['sha256']):
            return outcome('patch_artifact_missing', '缺少独立补丁回放的可追溯响应记录。')
    # Validate every input pair before proposing another paid repair round;
    # an early successful transaction must not hide a later invalid baseline.
    if not required_valid:
        return outcome('required_trigger_replay_missing', '源码定位要求的触发交易记录缺失或格式无效，需要重新确认回放范围。',
                       next_action='select_trigger_transactions')
    if set(required_hashes) - seen:
        # Preserve independently proven outside-code observations, but never
        # treat a subset of mapped trigger inputs as the complete verification.
        for pair in pairs:
            control_targets = _trace_call_targets(pair['control'])
            patched_targets = _trace_call_targets(pair['patched'])
            if (control_targets is not None and patched_targets is not None
                    and not modified_addresses & (control_targets | patched_targets)
                    and _unchanged_success(pair['control'], pair['patched'])):
                unaffected.append({
                    'original_transaction_hash': pair['original_transaction_hash'],
                    'reason_code': 'modified_code_not_observed',
                    'control_artifact_sha256': pair['control']['artifact']['sha256'],
                    'patched_artifact_sha256': pair['patched']['artifact']['sha256'],
                })
        return outcome('required_trigger_replay_missing', '缺少源码定位要求的触发交易回放，需要补全验证范围；不能以其他交易成功代替触发交易验证。',
                       next_action='select_trigger_transactions')
    for pair in pairs:
        original_hash = pair['original_transaction_hash']
        patched = pair['patched']
        if patched.get('status') == 'success':
            control_targets = _trace_call_targets(pair['control'])
            patched_targets = _trace_call_targets(patched)
            if control_targets is None or patched_targets is None:
                return outcome('patched_trace_unavailable', '独立历史交易缺少完整调用目标证据，无法确认是否执行了修改代码。')
            if modified_addresses & (control_targets | patched_targets):
                return outcome('patch_interception_not_established',
                               '执行修改代码的交易仍然成功，尚无可确认的补丁拦截证据；可根据本次执行反馈修订补丁，但未据此推翻根因。',
                               next_action='revise_patch')
            if not _unchanged_success(pair['control'], patched):
                return outcome('unaffected_execution_mismatch', '未观察到修改代码的独立历史回放存在结果变化，不能将其排除出验证范围。')
            unaffected.append({
                'original_transaction_hash': original_hash,
                'reason_code': 'modified_code_not_observed',
                'control_artifact_sha256': pair['control']['artifact']['sha256'],
                'patched_artifact_sha256': patched['artifact']['sha256'],
            })
            continue
        if patched.get('status') != 'revert':
            return outcome('patch_interception_not_established', '回放没有提供可确认的补丁拦截证据；收益值不能代替该证据。')
        logs = patched.get('logs')
        if (not isinstance(logs, dict) or logs.get('available') is not True
                or type(logs.get('count')) is not int or logs['count'] != 0):
            return outcome('patched_events_unresolved', '补丁回放的回滚事件证据缺失或不一致。')
        trace = patched.get('trace')
        if (not isinstance(trace, dict) or trace.get('available') is not True
                or trace.get('complete') is not True or trace.get('reverted_calls_truncated') is True
                or not isinstance(trace.get('reverted_calls'), list)):
            issues = trace.get('issues') if isinstance(trace, dict) else None
            codes = {item.get('code') for item in issues
                     if isinstance(item, dict) and isinstance(item.get('code'), str)} if isinstance(issues, list) else set()
            all_codes = trace.get('issue_codes') if isinstance(trace, dict) else None
            if isinstance(all_codes, list):
                codes.update(code for code in all_codes if isinstance(code, str))
            if codes.intersection({'invalid_root', 'invalid_node', 'invalid_call_target',
                                   'invalid_status', 'status_conflict', 'invalid_children'}):
                return outcome('patched_trace_invalid', '补丁执行轨迹的结构或执行状态不一致，需复核原始回放记录；当前不能确认拦截。')
            if codes.intersection({'unsupported_node_type', 'unrecognized_untyped_node'}):
                return outcome('patched_trace_format_unsupported', '补丁执行轨迹包含尚未支持的节点格式，需适配解析器后使用已有记录重新核验。')
            return outcome('patched_trace_unavailable', '缺少完整补丁执行轨迹，无法确认实际回滚位置。')
        matched = None
        pair_issues = []
        for call in trace['reverted_calls']:
            if not isinstance(call, dict) or call.get('failure_confirmed') is not True:
                continue
            address, reason = call.get('code_address'), call.get('revert_reason')
            if not isinstance(address, str) or not isinstance(reason, str):
                continue
            address = address.lower()
            if address not in addresses or address not in guards or reason not in guards[address]:
                continue
            location = _matched_guard_location(report, call, address, reason, guards[address][reason])
            issue_count = len(pair_issues)
            propagation = _terminal_revert_chain(call, trace['reverted_calls'], diagnostics=pair_issues)
            if propagation is None:
                if len(pair_issues) > issue_count and location is None:
                    pair_issues.append({'code': 'patch_guard_location_unproven', 'path': call.get('path')})
                continue
            if any(marker in reason.lower() for marker in (
                'out of gas', 'invalid opcode', 'stack underflow', 'stack overflow',
                'insufficient funds', 'insufficient balance', 'intrinsic gas', 'nonce too low',
            )):
                continue
            path = call.get('path')
            if (not isinstance(path, list) or len(path) > 128
                    or any(type(index) is not int or index < 0 for index in path)):
                continue
            # A modified caller can merely forward an unchanged callee's
            # Error(string). Equal text in the caller is not proof that its
            # newly added guard ran. Attribute the failure to the deepest
            # terminal call carrying it, which must itself match modified code.
            if any(isinstance(child, dict) and child.get('failure_confirmed') is True
                   and child.get('parent_call_path') == path
                   and child.get('terminal_in_parent') is True
                   and child.get('revert_reason') == reason
                   for child in trace['reverted_calls']):
                continue
            if location is None:
                pair_issues.append({'code': 'patch_guard_location_unproven', 'path': call.get('path')})
                continue
            matched = {
                'original_transaction_hash': original_hash,
                'control_receipt_digest': pair['control']['baseline_validation']['receipt_digest'],
                'control_artifact_sha256': pair['control']['artifact']['sha256'],
                'patched_artifact_sha256': patched['artifact']['sha256'],
                'patched_address': address, 'patch_file': location['patch_file'],
                'revert_reason': reason, 'trace_path': path, 'trace_position': call.get('position'),
                'guard_attribution': location,
            }
            if propagation is not None:
                matched['revert_propagation'] = propagation
            break
        if matched is None:
            attribution_issues.extend({'original_transaction_hash': original_hash, **issue}
                                      for issue in pair_issues[:16])
            if any(issue['code'] == 'revert_propagation_unproven' for issue in pair_issues):
                return outcome('revert_propagation_unproven',
                               '内层回滚文案与补丁校验相符，但缺少字节码证据证明其传播到外层回滚；末端调用关系或相同文案不能代替执行位置及控制流证据。')
            if any(issue['code'] == 'patch_guard_location_unproven' for issue in pair_issues):
                return outcome('patch_guard_location_unproven',
                               '回滚文案与补丁校验相符，但缺少绑定实际补丁运行时代码的失败 PC 或源码范围，不能确认修改校验已执行。')
            return outcome('patch_revert_not_matched',
                           '实际回滚地址及原因未能对应本次补丁新增或修改的校验；可检查实现并修订，当前效果仍未确认。',
                           next_action='revise_patch')
        checked.append(matched)
    if not checked:
        return outcome('modified_code_not_reached', '本轮回放均未观察到实际修改代码，需要重新定位并选择触发交易；尚不能判断补丁有效性。',
                       next_action='select_trigger_transactions')
    if verdict != 'VERIFIED':
        reason_code = ('judge_negative_unsubstantiated' if verdict in
                       {'INEFFECTIVE_PATCH', 'WRONG_ROOT_CAUSE', 'BROKEN_LOGIC'} else 'judge_unresolved')
        return outcome(reason_code, '模型解释尚未与机器证据形成一致结论；应复核同一份证据，未据此认定补丁无效或推翻根因。',
                       next_action='review_same_evidence')
    return outcome(
        'attack_path_intercepted',
        '原版对照与真实回执一致；触发交易在修改合约的实际校验中回滚。未执行修改代码且结果未变的独立历史交易另行记录；未验证前后状态传递、整条攻击链或正常功能。',
        verified=True,
    )
