"""Execution evidence used to distinguish patch outcomes from pipeline failures."""
import ast
import hashlib
import json
import re
from collections import Counter

VERIFICATION_POLICY_VERSION = 3


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


def _unavailable_trace_reason(trace):
    """Keep an unknown execution path distinct from proven target absence."""
    issues = trace.get('issues') if isinstance(trace, dict) else None
    codes = {item.get('code') for item in issues
             if isinstance(item, dict) and isinstance(item.get('code'), str)} if isinstance(issues, list) else set()
    all_codes = trace.get('issue_codes') if isinstance(trace, dict) else None
    if isinstance(all_codes, list):
        codes.update(code for code in all_codes if isinstance(code, str))
    if codes.intersection({'invalid_root', 'invalid_node', 'invalid_call_target',
                           'invalid_status', 'status_conflict', 'invalid_children'}):
        return ('patched_trace_invalid',
                '补丁执行轨迹的结构或执行状态不一致，需复核原始回放记录；当前不能确认补丁效果。')
    if codes.intersection({'unsupported_node_type', 'unrecognized_untyped_node'}):
        return ('patched_trace_format_unsupported',
                '补丁执行轨迹包含尚未支持的节点格式，需适配解析器后使用已有记录重新核验。')
    return ('patched_trace_unavailable', '缺少完整补丁执行轨迹，暂时无法核实修改代码的执行路径。')


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


def adjudicate_patch_verification(judge_result, replay_evidence, patches, *, cache_root=None):
    """Conservatively confirm recorded interception; model verdicts are not proof.

    At least one validated successful control must fail in modified code at an
    added/changed literal guard. A successful pair outside the modified code can
    be recorded separately only with complete unchanged execution evidence.
    Independent historical states never establish a sequential attack replay.
    Profit, normal functionality and root-cause rejection remain unmeasured.
    """
    report = replay_evidence if isinstance(replay_evidence, dict) else {}
    if report.get('scope') == 'sequential_attack_and_regression':
        return _adjudicate_complete_verification(judge_result, report, patches, cache_root=cache_root)
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
        from app.attackpilot.utils.native_profit import build_native_profit_evidence

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
                'profit': build_native_profit_evidence(report, execution_validated=verified),
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
        '原版对照与真实回执一致；触发交易在修改合约的实际校验中回滚。未执行修改代码且结果未变的独立历史交易另行记录；未验证前后状态传递或整条攻击链。',
        verified=True,
    )


def _adjudicate_complete_verification(judge_result, report, patches, *, cache_root=None):
    """Combine executed chain, declared attack effects and normal-case assertions.

    Full verification is scoped to the recorded inputs and declared properties;
    it never claims arbitrary transactions or all business behavior are safe.
    """
    from copy import deepcopy
    from app.attackpilot.utils.security_checks import (
        evaluate_normal_regression, evaluate_security_properties, plan_digest,
        validate_plan_authority, validate_verification_plan,
    )
    from app.attackpilot.utils.patch_replay import validate_sequential_evidence

    pairs = report.get('transactions')
    pairs = pairs if isinstance(pairs, list) else []
    verdict = judge_result.get('verdict') if isinstance(judge_result, dict) else None
    verdict = verdict if isinstance(verdict, str) and verdict in {
        'VERIFIED', 'INEFFECTIVE_PATCH', 'WRONG_ROOT_CAUSE', 'BROKEN_LOGIC', 'UNVERIFIED'} else None
    modified = _modified_code_addresses(patches)
    digest = replay_evidence_digest(report)
    plan = None
    checked = []
    sequence = {'status': 'unavailable', 'reason_code': 'sequence_evidence_missing'}
    security = {'status': 'unavailable', 'reason_code': 'security_properties_not_measured', 'checks': []}
    normal = {'status': 'not_run', 'reason_code': 'normal_regression_not_measured', 'checks': []}
    attack = {'status': 'unavailable'}
    native_profit = {'status': 'unavailable', 'usd': None}
    attempted = any(isinstance(pair, dict) and any(isinstance(pair.get(role), dict)
                    and (pair[role].get('completed') is True or pair[role].get('artifact'))
                    for role in ('control', 'patched')) for pair in pairs)
    complete = bool(pairs) and all(isinstance(pair, dict) and all(
        isinstance(pair.get(role), dict) and pair[role].get('completed') is True
        for role in ('control', 'patched')) for pair in pairs)

    def outcome(code, reason, *, verified=False, next_action=None):
        return verification_state(
            'verified' if verified else 'unverified', stage='judge', reason_code=code,
            reason=reason, replay_attempted=attempted, replay_completed=complete,
            terminal=next_action is None, retryable=next_action is not None,
            next_action=next_action or ('complete' if verified else 'collect_missing_evidence'),
            scope=('declared_attack_chain_and_normal_cases' if plan and plan['normal_regression_cases']
                   else 'declared_attack_chain'), evidence_version=2,
            evidence_validated=verified, verification_policy_version=VERIFICATION_POLICY_VERSION,
            decision_authority='validated_execution_evidence',
            execution_evidence_validated=sequence.get('status') in {'passed', 'partial'},
            replay_evidence_sha256=digest, applied_patch_sha256=report.get('applied_patch_sha256'),
            judge_verdict=verdict, checked=list(checked), unaffected=[],
            verification_plan_sha256=plan_digest(plan) if plan else None,
            coverage={'mode': 'sequential_attack_and_regression',
                      'modified_addresses': sorted(modified),
                      'required_trigger_transaction_hashes': report.get('required_trigger_transaction_hashes', []),
                      'ordered_transaction_hashes': plan['attack_transaction_hashes'] if plan else [],
                      'sequence_replay_verified': sequence.get('status') == 'passed',
                      'declared_security_property_ids': [item['id'] for item in plan['security_properties']] if plan else [],
                      'normal_regression_case_ids': [item['id'] for item in plan['normal_regression_cases']] if plan else [],
                      'unexecuted_transaction_hashes': [pair.get('original_transaction_hash') for pair in pairs
                          if isinstance(pair, dict) and isinstance(pair.get('patched'), dict)
                          and pair['patched'].get('completed') is not True]},
            dimensions={'sequence_replay': deepcopy(sequence), 'attack_interception': deepcopy(attack),
                        'security_properties': deepcopy(security), 'normal_regression': deepcopy(normal),
                        'profit': deepcopy(native_profit)},
        )

    if type(report.get('schema_version')) is not int or report['schema_version'] != 2 or digest is None:
        return outcome('structured_replay_evidence_missing', '缺少完整连续回放的结构化执行证据。')
    try:
        plan = validate_verification_plan(report.get('verification_plan'))
    except (ValueError, TypeError, OverflowError, RecursionError):
        return outcome('verification_plan_invalid', '声明的安全条件或验证计划无效，不能据此判定补丁通过。')
    if plan is None or not (validate_plan_authority(plan) if cache_root is None else
                            validate_plan_authority(plan, cache_root=cache_root)):
        return outcome('verification_plan_unbound', '缺少用户声明的验证条件，或调查计划未绑定本任务的实际证据。')
    if (report.get('verification_plan_sha256') != plan_digest(plan)
            or plan != report.get('verification_plan')):
        return outcome('verification_plan_mismatch', '执行记录中的验证计划与实际安全条件不一致。')
    if (not isinstance(patches, str) or report.get('applied_patch_sha256') != hashlib.sha256(patches.encode()).hexdigest()):
        return outcome('applied_patch_evidence_mismatch', '回放记录未绑定本次实际应用的补丁代码。')
    addresses = report.get('patched_addresses')
    if (not isinstance(addresses, list) or not addresses or not modified
            or any(not isinstance(address, str) or not _ADDRESS.fullmatch(address) for address in addresses)
            or not modified.issubset({address.lower() for address in addresses})):
        return outcome('patch_target_missing', '实际源码修改地址未对应回放中的代码替换地址。')
    integrity = report.get('runtime_integrity')
    if (not isinstance(integrity, dict) or integrity.get('status') != 'validated'
            or integrity.get('applied_patch_sha256') != report.get('applied_patch_sha256')
            or not isinstance(integrity.get('contracts'), dict)):
        return outcome('runtime_integrity_missing', '未确认历史字节码、存储布局和 immutable 与本次补丁一致。')
    for address in modified:
        contract = integrity['contracts'].get(address)
        if (not isinstance(contract, dict) or contract.get('storage_layout_checked') is not True
                or contract.get('immutable_checked') is not True
                or any(not isinstance(contract.get(key), str) or not _DIGEST.fullmatch(contract[key])
                       for key in ('patched_runtime_sha256', 'original_runtime_sha256',
                                   'original_compiled_runtime_sha256'))):
            return outcome('runtime_integrity_missing', '源码修改地址缺少完整的运行时完整性检查。')
    try:
        validation = (validate_sequential_evidence(report) if cache_root is None else
                      validate_sequential_evidence(report, cache_root=cache_root))
    except (ValueError, TypeError, OSError, KeyError, AttributeError):
        validation = {'status': 'unavailable', 'reason_code': 'sequence_evidence_invalid'}
    if not isinstance(validation, dict) or validation.get('status') != 'validated':
        sequence = {'status': 'unavailable', 'reason_code': validation.get('reason_code', 'sequence_evidence_invalid')
                    if isinstance(validation, dict) else 'sequence_evidence_invalid'}
        return outcome(sequence['reason_code'], '连续回放的原始响应、交易顺序、初始状态或实际请求未通过核验。')
    sequence = {'status': 'passed' if complete else 'partial',
                'reason_code': 'stateful_sequence_completed' if complete else 'stateful_sequence_stopped',
                'ordered_transaction_hashes': list(plan['attack_transaction_hashes'])}
    hashes = [pair.get('original_transaction_hash') for pair in pairs if isinstance(pair, dict)]
    if hashes != plan['attack_transaction_hashes']:
        return outcome('attack_sequence_input_mismatch', '实际连续回放交易与计划声明的攻击链不一致。')
    if any(pair.get('context', {}).get('network_id') != plan['network_id'] for pair in pairs):
        return outcome('verification_plan_network_mismatch', '验证条件与执行链不一致。')
    from app.attackpilot.utils.native_profit import build_native_profit_evidence
    native_profit = build_native_profit_evidence(report, execution_validated=True)
    required = report.get('required_trigger_transaction_hashes', [])
    if (not isinstance(required, list) or not required
            or any(not isinstance(tx, str) or not _HASH.fullmatch(tx) for tx in required)
            or not {tx.lower() for tx in required}.issubset(hashes)):
        return outcome('required_trigger_replay_missing', '源码定位要求的触发交易没有全部纳入连续回放。')
    target_sets = [_trace_call_targets(pair.get('patched', {})) for pair in pairs]
    reached = any(targets is not None and modified.intersection(targets) for targets in target_sets)
    if not reached:
        unknown = [_unavailable_trace_reason(pair.get('patched', {}).get('trace'))
                   for pair, targets in zip(pairs, target_sets) if targets is None]
        if unknown:
            priority = {'patched_trace_invalid': 0, 'patched_trace_format_unsupported': 1,
                        'patched_trace_unavailable': 2}
            code, reason = min(unknown, key=lambda item: priority[item[0]])
            return outcome(code, reason)
        return outcome('modified_code_not_reached', '连续回放没有完整轨迹证明执行了实际修改代码。',
                       next_action='select_trigger_transactions')
    if cache_root is None:
        security = evaluate_security_properties(plan, pairs)
        normal = evaluate_normal_regression(plan, report.get('normal_regression', {}), modified)
    else:
        security = evaluate_security_properties(plan, pairs, cache_root=cache_root)
        normal = evaluate_normal_regression(plan, report.get('normal_regression', {}), modified,
                                            cache_root=cache_root)
    if security.get('status') == 'passed':
        attack = {'status': 'passed', 'method': 'declared_security_properties',
                  'scope': 'declared_properties_and_recorded_inputs'}
        checked.extend({'original_transaction_hash': item['transaction_hash'],
                        'property_id': item['property_id'], 'method': 'declared_security_property'}
                       for item in security['checks'])
    else:
        # Guard interception remains independently useful. Reuse the existing
        # source/PC/terminal-propagation gate after the stateful validator has
        # established the stronger control baseline and artifact identities.
        guarded = []
        for pair in pairs:
            if pair.get('patched', {}).get('status') != 'revert':
                continue
            shadow = deepcopy(report)
            shadow.update(schema_version=1, scope='independent_historical_transaction_pairs',
                          status='completed', control_validation='validated', transaction_count=1,
                          transactions=[deepcopy(pair)],
                          required_trigger_transaction_hashes=[pair['original_transaction_hash']])
            control = shadow['transactions'][0]['control']
            baseline = control.get('baseline_validation')
            if isinstance(baseline, dict):
                baseline['method'] = 'rpc_receipt_vs_tenderly_original_replay'
            local = adjudicate_patch_verification({'verdict': 'VERIFIED'}, shadow, patches)
            if local.get('status') == 'verified':
                guarded.extend(local.get('checked', []))
        if guarded:
            checked.extend(guarded)
            attack = {'status': 'passed', 'method': 'matched_guard',
                      'scope': 'recorded_guard_interceptions'}
        else:
            attack = {'status': 'unavailable', 'reason_code': 'attack_effect_not_established'}
    if not complete:
        return outcome('attack_sequence_incomplete', '补丁链在回滚后停止，后续交易没有实际执行；已记录的前缀证据不能证明整条攻击链通过。')
    if security.get('status') == 'failed':
        return outcome('declared_security_property_failed', '声明的安全条件未形成原版违反、补丁版消除的执行对照。',
                       next_action='revise_patch')
    if attack.get('status') != 'passed':
        return outcome('attack_effect_not_established', '缺少可确认的补丁回滚归因或原版违反而补丁消除的实际安全结果。',
                       next_action='revise_patch' if security.get('status') == 'failed' else None)
    if security.get('status') != 'passed':
        return outcome('security_observations_unavailable', '声明的资金、权限或状态条件缺少完整原始观测，不能把缺失数据当安全。')
    if plan['normal_regression_cases'] and normal.get('status') != 'passed':
        return outcome('normal_regression_failed' if normal.get('status') == 'failed' else 'normal_regression_unavailable',
                       '正常业务尚未同时完成原版与补丁版执行、修改代码覆盖及业务断言。',
                       next_action='revise_patch' if normal.get('status') == 'failed' else None)
    if plan['normal_regression_cases']:
        return outcome('declared_chain_and_regression_verified',
                       '连续攻击链及声明的验证条件均已执行并通过；结论仅覆盖所声明条件与记录输入。', verified=True)
    return outcome('declared_attack_chain_verified',
                   '攻击交易已连续回放，原版违反而补丁消除了声明的安全条件违规；结论覆盖本次攻击输入。',
                   verified=True)
