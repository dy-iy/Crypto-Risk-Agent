"""Independent historical control/patch replays and durable execution evidence."""
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.attackpilot import settings
from app.attackpilot.errors import HistoricalReplayValidationError, TenderlyAPIError
from app.attackpilot.utils.replay_validation import (
    _hex, _logs, _quantity, _status, validate_original_transaction, validate_trace_root,
)

MAX_REPLAY_TRANSACTIONS = 4
MAX_REPLAY_REQUESTS = 8
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
TRACE_SUMMARY_POLICY_VERSION = 5
_HASH = re.compile(r'0x[0-9a-fA-F]{64}')
_ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')
_DIGEST = re.compile(r'[0-9a-f]{64}')
_CALL_TYPES = {'CALL', 'STATICCALL', 'DELEGATECALL', 'CALLCODE', 'CREATE', 'CREATE2'}
_TRACE_STEP_TYPES = {'JUMPDEST', 'SLOAD', 'SSTORE', 'LOG0', 'LOG1', 'LOG2', 'LOG3', 'LOG4'}


class PatchReplayBudgetError(RuntimeError):
    """A task's fixed simulation request budget has been exhausted."""

    def __init__(self, *, transaction_limit: bool = False):
        self.reason_code = 'replay_transaction_limit' if transaction_limit else 'replay_request_limit'
        message = ('本次任务需要回放的交易超过 4 笔，超过配对回放请求上限，未请求模拟服务。'
                   if transaction_limit else '本任务已达到补丁回放请求上限，未再请求模拟服务。')
        super().__init__(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _redact(value: Any, depth: int = 0) -> Any:
    if depth > 400:
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
            normalized = re.sub(r'[^a-z0-9]', '', key.lower())
            if normalized in {
                'authorization', 'headers', 'apikey', 'accesskey', 'xaccesskey',
                'password', 'secret', 'accesstoken', 'refreshtoken', 'credentials',
                'apitoken', 'clientsecret', 'privatekey', 'secretaccesskey',
            }:
                result[key] = '[REDACTED]'
            else:
                result[key] = _redact(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in value]
    if isinstance(value, str):
        for secret in (settings.TENDERLY_API_KEY, settings.LLM_API_KEY):
            if isinstance(secret, str) and secret and secret in value:
                value = value.replace(secret, '[REDACTED]')
    return value


class PatchReplayEvidenceStore:
    """Task-local immutable artifacts, successful response reuse, and call limits."""

    def __init__(self, cache_root: Path | str | None = None):
        self.cache_root = Path(cache_root if cache_root is not None else settings.CACHE_DIR)
        self.root = self.cache_root / 'patch_replay'

    def original_context(self, transaction_hash: str, chain_id: int) -> tuple[dict, dict]:
        if not isinstance(transaction_hash, str) or not _HASH.fullmatch(transaction_hash):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'original_transaction_hash'})
        transaction_hash = transaction_hash.lower()
        try:
            transaction = json.loads((self.cache_root / 'tx_detail' / 'tx' /
                                      f'{transaction_hash}.json').read_text(encoding='utf-8'))
            receipt = json.loads((self.cache_root / 'tx_detail' / 'tx_receipt' /
                                  f'{transaction_hash}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'original_rpc_cache'}) from None
        context = validate_original_transaction(transaction_hash, chain_id, transaction, receipt)
        try:
            timestamp = json.loads((self.cache_root / 'timestamp' /
                                    f"{context['block_number']}.json").read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeDecodeError):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'original_block_timestamp'}) from None
        if isinstance(timestamp, dict):
            if (type(timestamp.get('schema_version')) is not int or timestamp['schema_version'] != 1
                    or type(timestamp.get('block_number')) is not int
                    or timestamp['block_number'] != context['block_number']
                    or not isinstance(timestamp.get('block_hash'), str)
                    or timestamp['block_hash'].lower() != context['block_hash']
                    or type(timestamp.get('timestamp')) is not int):
                raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                      details={'field': 'original_block_timestamp'})
            timestamp = timestamp['timestamp']
        context['timestamp'] = _quantity(timestamp, 'original_block_timestamp')
        return context, transaction

    def cached_response(self, request: dict) -> tuple[dict, dict] | None:
        request_digest = _digest(request)
        pointer = self.root / 'index' / f'{request_digest}.json'
        try:
            index = json.loads(pointer.read_text(encoding='utf-8'))
            digest = index.get('sha256')
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                return None
            artifact_path = self.root / 'artifacts' / f'{digest}.json'
            with artifact_path.open('rb') as handle:
                data = handle.read(MAX_ARTIFACT_BYTES + 1)
            if len(data) > MAX_ARTIFACT_BYTES or hashlib.sha256(data).hexdigest() != digest:
                return None
            record = json.loads(data)
            if (type(record.get('schema_version')) is not int or record['schema_version'] != 1
                    or record.get('request_digest') != request_digest
                    or _digest(record.get('request')) != request_digest
                    or not isinstance(record.get('response'), dict)):
                return None
            return record['response'], self._reference(artifact_path, digest, request_digest, reused=True)
        except (OSError, ValueError, UnicodeDecodeError, AttributeError, TypeError):
            return None

    def reserve_request(self, request: dict) -> None:
        reservations = self.root / 'requests'
        reservations.mkdir(parents=True, exist_ok=True)
        for number in range(MAX_REPLAY_REQUESTS):
            path = reservations / f'{number + 1:02}.json'
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            with os.fdopen(fd, 'wb') as handle:
                handle.write(_canonical({'schema_version': 1, 'request_digest': _digest(request)}))
            return
        raise PatchReplayBudgetError()

    def invalidate_response(self, request: dict) -> None:
        """Keep the audit artifact, but never reuse a response rejected by validation."""
        try:
            (self.root / 'index' / f'{_digest(request)}.json').unlink(missing_ok=True)
        except OSError:
            # The original typed validation/service failure remains authoritative.
            pass

    def persist(self, request: dict, response: dict, *, role: str, original_hash: str) -> dict:
        request_digest = _digest(request)
        record = _redact({
            'schema_version': 1, 'role': role, 'original_transaction_hash': original_hash,
            'request_digest': request_digest, 'request': request, 'response': response,
        })
        try:
            data = _canonical(record)
        except (ValueError, TypeError, OverflowError):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_response') from None
        if len(data) > MAX_ARTIFACT_BYTES:
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
        digest = hashlib.sha256(data).hexdigest()
        artifact_path = self.root / 'artifacts' / f'{digest}.json'
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with artifact_path.open('xb') as handle:
                handle.write(data)
        except FileExistsError:
            if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != digest:
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_response') from None
        index_path = self.root / 'index' / f'{request_digest}.json'
        index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = index_path.parent / f'.{uuid.uuid4().hex}.tmp'
        try:
            with temporary.open('xb') as handle:
                handle.write(_canonical({'schema_version': 1, 'sha256': digest}))
            temporary.replace(index_path)
        finally:
            temporary.unlink(missing_ok=True)
        return self._reference(artifact_path, digest, request_digest, reused=False)

    def _reference(self, path: Path, digest: str, request_digest: str, *, reused: bool) -> dict:
        return {
            'relative_path': str(Path('cache') / 'patch_replay' / path.relative_to(self.root)),
            'sha256': digest, 'request_digest': request_digest, 'reused': reused,
        }


def runtime_overrides(addr2bytecode: Any) -> dict:
    if not isinstance(addr2bytecode, dict) or not addr2bytecode:
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
    overrides = {}
    for address, bytecode in addr2bytecode.items():
        if (not isinstance(address, str) or not _ADDRESS.fullmatch(address)
                or not isinstance(bytecode, str)):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
        bytecode = bytecode if bytecode.startswith('0x') else f'0x{bytecode}'
        if (not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', bytecode)
                or len(bytecode) > 2 * 1024 * 1024):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
        if address.lower() in overrides:
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
        overrides[address.lower()] = {'code': bytecode.lower()}
    return overrides


def historical_payload(context: dict, transaction: dict, overrides: dict | None = None) -> dict:
    simulation = {
        'network_id': str(context['chain_id']),
        'block_number': context['block_number'], 'transaction_index': context['transaction_index'],
        'from': context['from'], 'to': context['to'], 'input': context['input'],
        'value': str(context['value']), 'gas': context['gas'], 'gas_price': str(context['gas_price']),
        'simulation_type': 'full', 'save': True, 'save_if_fails': True,
        'generate_state_diff': True, 'generate_visual_trace': True,
    }
    access_list = transaction.get('accessList')
    if access_list is not None:
        if not isinstance(access_list, list):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'original.accessList'})
        for entry in access_list:
            if not isinstance(entry, dict) or not isinstance(entry.get('storageKeys'), list):
                raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                      details={'field': 'original.accessList'})
            _hex(entry.get('address'), 'original.accessList.address', size=20)
            for storage_key in entry['storageKeys']:
                _hex(storage_key, 'original.accessList.storageKeys', size=32)
        simulation['access_list'] = access_list
    if overrides:
        simulation['state_objects'] = overrides
    return {'simulations': [simulation], 'contracts': []}


def public_context(context: dict, transaction: dict) -> dict:
    return {
        'network_id': str(context['chain_id']), 'block_number': context['block_number'],
        'block_hash': context['block_hash'], 'transaction_index': context['transaction_index'],
        'timestamp': context['timestamp'],
        'from': context['from'], 'to': context['to'], 'input': context['input'],
        'value': str(context['value']), 'gas': context['gas'], 'gas_price': str(context['gas_price']),
        'nonce': context['nonce'], 'access_list': transaction.get('accessList', []),
    }


def validate_patch_context(context: dict, result: dict) -> None:
    for key in ('simulation', 'transaction'):
        data = result.get(key)
        if not isinstance(data, dict):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
        expected_numbers = {
            'network_id': context['chain_id'], 'block_number': context['block_number'],
            'gas': context['gas'], 'gas_price': context['gas_price'],
            'value': context['value'], 'nonce': context['nonce'],
        }
        if key == 'simulation':
            expected_numbers['transaction_index'] = context['transaction_index']
        for field, expected in expected_numbers.items():
            if _quantity(data.get(field), f'patched.{key}.{field}', empty_hex=field == 'value') != expected:
                raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                      details={'field': f'patched.{key}.{field}'})
        for field in ('from', 'to', 'input'):
            if field not in data or _hex(data[field], f'patched.{key}.{field}',
                                         size=20 if field != 'input' else None,
                                         creation=field == 'to') != context[field]:
                raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                      details={'field': f'patched.{key}.{field}'})
    validate_trace_root(context, result['transaction'])


def validate_historical_header(context: dict, result: dict) -> None:
    simulation = result.get('simulation')
    transaction = result.get('transaction')
    header = simulation.get('block_header') if isinstance(simulation, dict) else None
    if not isinstance(header, dict) or not isinstance(transaction, dict):
        raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                              details={'field': 'replay.block_header'})
    for field, expected in (('number', context['block_number']), ('timestamp', context['timestamp'])):
        if _quantity(header.get(field), f'replay.block_header.{field}') != expected:
            raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                  details={'field': f'replay.block_header.{field}'})
    if _hex(header.get('hash'), 'replay.block_header.hash', size=32) != context['block_hash']:
        raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                              details={'field': 'replay.block_header.hash'})
    if 'timestamp' in transaction:
        value = transaction['timestamp']
        if isinstance(value, str) and not re.fullmatch(r'(?:0x[0-9a-fA-F]+|[0-9]+)', value):
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError
                timestamp = parsed.timestamp()
                if timestamp != int(timestamp):
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                      details={'field': 'replay.transaction.timestamp'}) from None
        else:
            timestamp = _quantity(value, 'replay.transaction.timestamp')
        if timestamp != context['timestamp']:
            raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                  details={'field': 'replay.transaction.timestamp'})


def _availability(data: dict, field: str) -> str:
    if field not in data:
        return 'missing'
    if data[field] is None:
        return 'explicit_null'
    if isinstance(data[field], (dict, list)):
        return 'explicit_empty' if not data[field] else 'present'
    return 'invalid'


def _revert_reason(node: dict) -> tuple[str | None, str | None]:
    output = node.get('output')
    if isinstance(output, str) and output.lower().startswith('0x08c379a0'):
        try:
            raw = bytes.fromhex(output[10:])
            offset = int.from_bytes(raw[:32], 'big')
            length = int.from_bytes(raw[offset:offset + 32], 'big')
            if 0 <= offset <= len(raw) - 32 and 0 < length <= 2048 and offset + 32 + length <= len(raw):
                return raw[offset + 32:offset + 32 + length].decode('utf-8'), 'abi_error_output'
        except (ValueError, UnicodeDecodeError):
            pass
    for field in ('revert_reason', 'error_reason', 'error_message', 'error'):
        value = node.get(field)
        if isinstance(value, str) and value.strip():
            return value[:2048], field
    return None, None


def _is_revert_annotation(node: dict, parent: dict | None) -> bool:
    """Recognize Tenderly's zero-gas source marker beneath a reverted frame.

    This marker has no call type because it is not another EVM call. Require
    its parent to identify the same source failure and exact trace position;
    an otherwise untyped call must still make the trace incomplete.
    """
    if (not isinstance(parent, dict)
            or any(node.get(key) not in (None, '') for key in ('call_type', 'type'))
            or node.get('calls', False) is not None
            or node.get('truncated') is True
            or any(node.get(key) != '0x' for key in ('input', 'output'))
            or any(node.get(key) != '' for key in ('caller_op', 'function_op'))
            or any(type(node.get(key)) is not int or node[key] != 0
                   for key in ('gas', 'gas_used', 'caller_pc', 'function_pc'))):
        return False
    # Tenderly uses either the generic EVM error or the decoded require reason.
    # The marker and its parent must agree; a nonempty error alone is not proof
    # that an untyped node is merely a source annotation.
    error = node.get('error')
    if (not isinstance(error, str) or not error.strip() or parent.get('error') != error):
        return False
    if any(frame.get('error_op') != 'REVERT'
           or ('status' in frame and frame['status'] not in
               (False, 0, '0', '0x0', 'revert', 'reverted', 'failed'))
           for frame in (node, parent)):
        return False
    parent_kind = parent.get('call_type') or parent.get('type')
    if not isinstance(parent_kind, str) or parent_kind.upper() not in _CALL_TYPES | {'JUMPDEST'}:
        return False
    address = node.get('address')
    if (not isinstance(address, str) or not _ADDRESS.fullmatch(address)
            or any(not isinstance(value, str) or value.lower() != address.lower()
                   for value in (node.get('from'), node.get('to'), parent.get('to')))):
        return False
    position = node.get('absolute_position')
    if (type(position) is not int or position < 0
            or type(parent.get('error_absolute_position')) is not int
            or position != parent['error_absolute_position']):
        return False
    source_keys = ('error_code_start', 'error_code_length', 'error_file_index', 'error_line_number')
    if all(key not in frame for frame in (node, parent) for key in source_keys):
        # State-override bytecode has no source map. Tenderly still emits its
        # terminal zero-gas marker at the parent's exact failure position.
        # Require the parent to carry the same ABI-encoded error and to end
        # immediately afterwards; error text alone is not enough.
        reason, source = _revert_reason(parent)
        return (parent_kind.upper() in _CALL_TYPES
                and type(parent.get('absolute_position')) is int
                and parent['absolute_position'] == position + 1
                and source == 'abi_error_output' and reason == error
                and isinstance(parent.get('calls'), list)
                and bool(parent['calls']) and parent['calls'][-1] is node)
    for key in source_keys:
        value = node.get(key)
        if (type(value) is not int or value < 0 or type(parent.get(key)) is not int
                or parent[key] != value):
            return False
    return node['error_code_length'] > 0 and node['error_line_number'] > 0


def _failure_location(node: dict) -> dict:
    """Keep observed failure coordinates; call-entry PCs are not failure PCs."""
    location = {}
    for source, target in (
        ('error_pc', 'pc'), ('error_code_start', 'start'),
        ('error_code_length', 'length'), ('error_file_index', 'file_index'),
        ('error_line_number', 'line_number'),
    ):
        value = node.get(source)
        if type(value) is int and value >= 0:
            location[target] = value
        elif source in node:
            location.setdefault('invalid_fields', []).append(target)
    return location


def _terminal_internal_revert(node: dict) -> dict | None:
    """Recover an omitted call error from a terminal same-frame REVERT.

    Tenderly can put the error only on the deepest Solidity JUMPDEST frame.
    REVERT cannot be caught by an internal function in the same EVM frame.
    Require an uninterrupted terminal chain, the same execution address and
    ending gas, and (for an external call) matching ABI output and end position.
    A reverted external child or successful Error(string) return is insufficient.
    """
    address = node.get('to')
    kind = node.get('call_type') or node.get('type')
    if (not isinstance(address, str) or not _ADDRESS.fullmatch(address)
            or not isinstance(kind, str) or kind.upper() not in _CALL_TYPES | {'JUMPDEST'}):
        return None
    current = node
    for _ in range(128):
        children = current.get('calls')
        if not isinstance(children, list) or not children or not isinstance(children[-1], dict):
            return None
        child = children[-1]
        child_kind = child.get('call_type') or child.get('type')
        if (child_kind != 'JUMPDEST' or child.get('caller_op') != 'JUMP'
                or child.get('function_op') != 'JUMPDEST'
                or child.get('truncated') is True
                or child.get('output') != '0x'
                or any(not isinstance(child.get(key), str)
                       or child[key].lower() != address.lower()
                       for key in ('from', 'to', 'address'))
                or ('status' in child and child['status'] not in
                    (False, 0, '0', '0x0', 'false', 'revert', 'reverted', 'failed'))):
            return None
        if (any(type(frame.get(key)) is not int or frame[key] < 0
                for frame in (current, child) for key in ('gas', 'gas_used'))
                or current['gas_used'] > current['gas'] or child['gas_used'] > child['gas']
                or child['gas'] > current['gas']
                or current['gas'] - current['gas_used'] != child['gas'] - child['gas_used']):
            return None
        position = child.get('absolute_position')
        if type(position) is not int or position < 0:
            return None
        if (current.get('call_type', current.get('type')) == 'JUMPDEST'
                and (type(current.get('absolute_position')) is not int
                     or current['absolute_position'] < 0
                     or current['absolute_position'] > position)):
            return None
        if child.get('error_op') == 'REVERT':
            error_position, error = child.get('error_absolute_position'), child.get('error')
            if (type(error_position) is not int or error_position < position
                    or not isinstance(error, str) or not error.strip()):
                return None
            if kind.upper() in _CALL_TYPES:
                reason, source = _revert_reason(node)
                if (type(node.get('absolute_position')) is not int
                        or node['absolute_position'] != error_position + 1
                        or source != 'abi_error_output' or reason != error):
                    return None
            return {'reason': error, 'position': error_position,
                    'failure_location': _failure_location(child)}
        if (child.get('error_op') not in (None, '')
                or any(child.get(key) not in (None, '') for key in
                       ('error', 'revert_reason', 'error_reason', 'error_message'))):
            return None
        current = child
    return None


def trace_summary(info: dict, patched_addresses: list[str], *, execution_status: int | None = None) -> dict:
    root = info.get('call_trace')
    if not isinstance(root, dict) or not root:
        code = 'trace_missing' if root is None or root == {} else 'invalid_root'
        return {'policy_version': TRACE_SUMMARY_POLICY_VERSION,
                'available': False, 'complete': False, 'reverted_calls': [],
                'call_targets': [], 'call_targets_complete': False,
                'issues': [{'code': code, 'path': []}], 'issue_codes': [code],
                'issue_count': 1, 'issues_truncated': False}
    complete, visited, reverted = True, 0, []
    call_targets, targets_complete = set(), True
    issues, issue_codes, issue_count = [], set(), 0

    def issue(code, path):
        nonlocal complete, targets_complete, issue_count
        complete = targets_complete = False
        issue_count += 1
        issue_codes.add(code)
        # Keep bounded, machine-readable diagnostics without copying arbitrary
        # provider messages or large trace nodes into every report.
        if len(issues) < 16:
            issues.append({'code': code, 'path': path[:128]})

    stack = [(root, [], None, None, True)]
    while stack:
        node, path, parent, parent_call_path, terminal_in_parent = stack.pop()
        visited += 1
        if visited > 100_000 or len(path) > 128:
            issue('trace_limit_exceeded', path)
            break
        if not isinstance(node, dict):
            issue('invalid_node', path)
            continue
        raw_kind = node.get('call_type') or node.get('type')
        kind = raw_kind.upper() if isinstance(raw_kind, str) else ''
        annotation = not kind and bool(path) and _is_revert_annotation(node, parent)
        if kind in _CALL_TYPES:
            target = node.get('to')
            if isinstance(target, str) and _ADDRESS.fullmatch(target):
                call_targets.add(target.lower())
            else:
                issue('invalid_call_target', path)
        elif not annotation and kind not in _TRACE_STEP_TYPES:
            issue('unsupported_node_type' if kind else 'unrecognized_untyped_node', path)
        if not path and kind not in _CALL_TYPES:
            issue('invalid_root', path)
        reason, source = _revert_reason(node)
        raw_status = node.get('status')
        explicit_error = any(isinstance(node.get(field), str) and node[field].strip()
                             for field in ('revert_reason', 'error_reason', 'error_message', 'error'))
        failure_opcode = node.get('error_op') in ('REVERT', 'INVALID')
        node_status = None
        valid_status = True
        if 'status' in node:
            if type(raw_status) in (bool, int) and raw_status in (0, 1):
                node_status = bool(raw_status)
            elif isinstance(raw_status, str) and raw_status.lower() in {
                    '0', '0x0', 'false', 'revert', 'reverted', 'failed',
                    '1', '0x1', 'true', 'success'}:
                node_status = raw_status.lower() in {'1', '0x1', 'true', 'success'}
            else:
                valid_status = False
        status_conflict = (node_status is True and (bool(explicit_error) or failure_opcode)
                           or not path and execution_status == 1 and (bool(explicit_error) or failure_opcode)
                           or not path and node_status is not None and execution_status is not None
                           and node_status != bool(execution_status))
        if not valid_status or status_conflict:
            issue('invalid_status' if not valid_status else 'status_conflict', path)
        internal_revert = (_terminal_internal_revert(node)
                           if valid_status and not status_conflict and node_status is not True
                           and not explicit_error and not failure_opcode else None)
        if internal_revert and not path and execution_status == 1:
            status_conflict = True
            issue('status_conflict', path)
        error_op = 'REVERT' if internal_revert else node.get('error_op')
        if internal_revert and reason is None:
            reason, source = internal_revert['reason'], 'terminal_internal_revert'
        failed = (valid_status and not status_conflict and node_status is not True
                  and (node_status is False or explicit_error or failure_opcode
                       or internal_revert or not path and execution_status == 0))
        # Error(string) bytes alone may also be returned by a successful call;
        # identify a reverted call only when its execution failure is established.
        if kind in _CALL_TYPES and failed:
            address = node.get('to')
            if not isinstance(address, str) or not _ADDRESS.fullmatch(address):
                address = None
            selector = node.get('input')
            selector = selector[:10].lower() if isinstance(selector, str) and re.match(r'0x[0-9a-fA-F]{8}', selector) else None
            position = node.get('absolute_position')
            reverted.append({
                'address': address.lower() if address else None,
                'code_address': address.lower() if address else None,
                'error_message': reason, 'revert_reason': reason, 'reason_source': source,
                'failure_confirmed': True,
                'call_type': kind, 'path': path,
                'parent_call_path': parent_call_path,
                'terminal_in_parent': terminal_in_parent,
                'error_op': error_op,
                'position': position if type(position) is int and position >= 0 else None,
                'input_selector': selector,
                'failure_location': (internal_revert['failure_location']
                                     if internal_revert else _failure_location(node)),
            })
        children = node.get('calls')
        if 'calls' not in node or (children is not None and not isinstance(children, list)):
            issue('missing_children' if 'calls' not in node else 'invalid_children', path)
        if isinstance(children, list):
            for index in range(len(children) - 1, -1, -1):
                # A wrapped error can still identify interception when every
                # enclosing call reverted immediately after this last branch.
                # Internal source frames must also have failed; a caught child
                # error followed by a successful frame is not propagation.
                call_parent = path if kind in _CALL_TYPES else parent_call_path
                terminal = (True if kind in _CALL_TYPES else
                            terminal_in_parent and failed and error_op == 'REVERT')
                stack.append((children[index], path + [index], node, call_parent,
                              terminal and index == len(children) - 1))
        if node.get('truncated') is True:
            issue('trace_truncated', path)
    reverted.sort(key=lambda item: item['code_address'] not in patched_addresses)
    return {
        'policy_version': TRACE_SUMMARY_POLICY_VERSION,
        'available': True, 'complete': complete, 'node_count': visited,
        'reverted_calls': reverted[:64], 'reverted_calls_truncated': len(reverted) > 64,
        'call_targets': sorted(call_targets),
        'call_targets_complete': complete and targets_complete and bool(call_targets),
        'issues': issues, 'issue_codes': sorted(issue_codes), 'issue_count': issue_count,
        'issues_truncated': issue_count > len(issues),
    }


def _effect_quantity(value: Any) -> bool:
    return (type(value) is int and value >= 0 or isinstance(value, str)
            and re.fullmatch(r'(?:0[xX][0-9a-fA-F]+|[0-9]+)', value) is not None)


def _effect_address(value: Any) -> bool:
    return isinstance(value, str) and _ADDRESS.fullmatch(value) is not None


def _effect_record(field: str, item: Any) -> bool:
    """Require underlying quantities and identities, not decoded/USD summaries."""
    if not isinstance(item, dict):
        return False
    if field == 'balance_diff':
        return (_effect_address(item.get('address'))
                and all(_effect_quantity(item.get(key)) for key in ('original', 'dirty')))
    if field == 'asset_changes':
        token = item.get('token_info')
        if (not isinstance(token, dict) or not _effect_quantity(item.get('raw_amount'))
                or type(item.get('trace_absolute_position')) is not int
                or item['trace_absolute_position'] < 0
                or any(not _effect_quantity(item.get(key))
                       for key in ('from_before_balance', 'to_before_balance'))):
            return False
        standard = token.get('standard')
        if standard not in ('ERC20', 'NativeCurrency'):
            return False
        if (type(token.get('decimals')) is not int or not 0 <= token['decimals'] <= 255
                or standard == 'ERC20' and not _effect_address(token.get('contract_address'))):
            return False
        transfer_type = item.get('type')
        if not isinstance(transfer_type, str):
            return False
        required = {'Transfer': ('from', 'to'), 'Mint': ('to',), 'Burn': ('from',)}.get(transfer_type)
        return (required is not None
                and all(_effect_address(item.get(key)) for key in required)
                and all(key not in item or _effect_address(item[key]) for key in ('from', 'to')))
    if field == 'state_diff':
        raw = item.get('raw')
        return (_effect_address(item.get('address'))
                and isinstance(raw, list) and bool(raw)
                and all(isinstance(entry, dict) and _effect_address(entry.get('address'))
                        and all(isinstance(entry.get(key), str)
                                and re.fullmatch(r'0x[0-9a-fA-F]{64}', entry[key]) is not None
                                for key in ('key', 'original', 'dirty')) for entry in raw))
    return False


def _raw_effects(field: str, records: list) -> list:
    """Compare observed EVM effects, not labels, decoding, or price estimates."""
    def quantity(value):
        return int(value, 16 if value.lower().startswith('0x') else 10) if isinstance(value, str) else value

    if field == 'balance_diff':
        normalized = [
            {'address': item['address'].lower(),
             'original': quantity(item['original']), 'dirty': quantity(item['dirty'])}
            for item in records
        ]
        return sorted(normalized, key=_canonical)
    if field == 'state_diff':
        # Decoded variables can group or order the same storage words
        # differently. Flatten that presentation while retaining duplicates.
        normalized = [
            {key: entry[key].lower() for key in ('address', 'key', 'original', 'dirty')}
            for item in records for entry in item['raw']
        ]
        return sorted(normalized, key=_canonical)
    normalized = []
    for item in records:
        token = item['token_info']
        normalized.append({
            'type': item['type'], 'trace_absolute_position': item['trace_absolute_position'],
            **{key: quantity(item[key]) for key in ('raw_amount', 'from_before_balance', 'to_before_balance')},
            **{key: item[key].lower() for key in ('from', 'to') if key in item},
            'token': {'standard': token['standard'],
                      'contract_address': token['contract_address'].lower()
                      if token['standard'] == 'ERC20' else None},
        })
    return normalized


def _execution_effects(info: dict) -> dict:
    """Fingerprint observed raw effects without changing their audit artifacts."""
    fields, complete = {}, True
    for field in ('balance_diff', 'asset_changes', 'state_diff'):
        value = info.get(field)
        availability = _availability(info, field)
        valid = isinstance(value, list) and all(_effect_record(field, item) for item in value)
        digest = None
        count = len(value) if isinstance(value, list) else None
        if valid:
            try:
                normalized = _raw_effects(field, value)
                count = len(normalized)
                digest = _digest(normalized)
            except (ValueError, TypeError, OverflowError, RecursionError):
                valid = False
        if not valid:
            complete = False
            if availability not in ('missing', 'explicit_null'):
                availability = 'invalid'
        fields[field] = {
            'availability': availability,
            'count': count,
            'sha256': digest if valid else None,
        }
    return {'schema_version': 1, 'complete': complete, 'fields': fields}


def _raw_trace_node(root, path):
    """Resolve a summary path without traversing unbounded provider structures."""
    if (not isinstance(path, list) or len(path) > 128
            or any(type(index) is not int or index < 0 for index in path)):
        return None
    node = root
    for index in path:
        children = node.get('calls') if isinstance(node, dict) else None
        if not isinstance(children, list) or index >= len(children):
            return None
        node = children[index]
    return node if isinstance(node, dict) else None


def _output_digest(value):
    if not isinstance(value, str) or re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', value) is None:
        return None
    return hashlib.sha256(bytes.fromhex(value[2:])).hexdigest()


def _bind_revert_propagation(trace, result, info, patched_addresses, runtime_codes):
    """Attach only runtime-proven call-result branches, never infer from text."""
    root = info.get('call_trace')
    changed = {address.lower() for address in patched_addresses if isinstance(address, str)}
    overrides = {address.lower(): code for address, code in runtime_codes.items()
                 if isinstance(address, str)} if isinstance(runtime_codes, dict) else {}
    contracts = result.get('contracts')
    calls = trace.get('reverted_calls', [])
    by_path = {tuple(call['path']): call for call in calls if isinstance(call, dict)
               and isinstance(call.get('path'), list)}
    for call in calls:
        raw = _raw_trace_node(root, call.get('path'))
        if raw is None:
            continue
        output_hash = _output_digest(raw.get('output'))
        if output_hash is not None:
            call['output_sha256'] = output_hash
        pc = raw.get('caller_pc')
        if type(pc) is int and pc >= 0:
            # This is the parent's call instruction, never the child's failed
            # instruction. It must not populate failure_location.pc.
            call['caller_pc'] = pc
        parent_path = call.get('parent_call_path')
        parent = _raw_trace_node(root, parent_path)
        parent_call = by_path.get(tuple(parent_path)) if isinstance(parent_path, list) else None
        if parent is None or parent_call is None:
            continue
        parent_hash = _output_digest(parent.get('output'))
        if parent_hash is not None:
            call['parent_output_sha256'] = parent_hash
        if (type(pc) is not int or pc < 0 or output_hash is None or parent_hash is None
                or call.get('terminal_in_parent') is not True
                or parent_call.get('call_type') not in {'CALL', 'STATICCALL', 'DELEGATECALL', 'CALLCODE'}):
            # CREATE parents execute init code; deployed_bytecode is not their
            # execution image and cannot prove a constructor's failure path.
            continue
        address = parent_call.get('code_address')
        if not isinstance(address, str) or _ADDRESS.fullmatch(address) is None:
            continue
        if address in changed:
            runtime, source = overrides.get(address), 'override'
        else:
            candidates = [contract.get('deployed_bytecode') for contract in
                          (contracts if isinstance(contracts, list) else [])
                          if isinstance(contract, dict) and isinstance(contract.get('address'), str)
                          and contract['address'].lower() == address]
            runtime = candidates[0] if len(candidates) == 1 else None
            source = 'response_contract'
        if not isinstance(runtime, str) or re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', runtime) is None:
            continue
        from app.attackpilot.utils.revert_propagation import prove_revert_propagation
        proof = prove_revert_propagation(runtime, pc, call.get('call_type'),
                                        raw['output'], parent['output'])
        if isinstance(proof, dict):
            call['revert_propagation'] = {
                **proof, 'parent_path': list(parent_path), 'child_path': list(call['path']),
                'parent_code_address': address, 'source': source,
            }


def execution_summary(result: dict, artifact: dict, patched_addresses: list[str],
                      runtime_codes: dict[str, str] | None = None) -> dict:
    transaction = result.get('transaction')
    simulation = result.get('simulation')
    if not isinstance(transaction, dict) or not isinstance(simulation, dict):
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    status = _status(simulation.get('status'), 'replay.simulation.status')
    gas_used = _quantity(simulation.get('gas_used'), 'replay.simulation.gas_used')
    if (_status(transaction.get('status'), 'replay.transaction.status') != status
            or _quantity(transaction.get('gas_used'), 'replay.transaction.gas_used') != gas_used):
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    info = transaction.get('transaction_info')
    if not isinstance(info, dict):
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    log_availability = _availability(info, 'logs')
    if log_availability in {'missing', 'invalid'}:
        raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
    logs = _logs(info['logs'], 'replay.logs', simulation=True)
    changes = {}
    for field in ('balance_diff', 'balance_changes', 'asset_changes', 'state_diff'):
        availability = _availability(info, field)
        value = info.get(field)
        changes[field] = {
            'availability': availability,
            'available': availability in {'present', 'explicit_empty'},
            'count': len(value) if isinstance(value, (list, dict)) else None,
            'sha256': _digest(value) if isinstance(value, (list, dict)) else None,
            # Nested storage diffs can contain an entire contract state. Their
            # durable artifact, count and digest suffice for the model summary.
            'sample': _redact(value[:20]) if field != 'state_diff' and isinstance(value, list) else None,
            'sample_truncated': isinstance(value, list) and
                                (field == 'state_diff' and bool(value) or len(value) > 20),
        }
    reason = None
    for data in (simulation, transaction):
        reason, _ = _revert_reason(data)
        if reason:
            break
    simulation_id = simulation.get('id')
    if not isinstance(simulation_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', simulation_id):
        simulation_id = None
    trace = trace_summary(info, patched_addresses, execution_status=status)
    # Provider file IDs belong to the provider, not to our compilation. Resolve
    # them only through the actual response's address-specific source records.
    for call in trace.get('reverted_calls', []):
        location = call.get('failure_location', {})
        file_id = location.get('file_index')
        if type(file_id) is not int:
            continue
        candidates = []
        contracts = result.get('contracts')
        for contract in contracts if isinstance(contracts, list) else []:
            if (not isinstance(contract, dict) or not isinstance(contract.get('address'), str)
                    or contract['address'].lower() != call['code_address']):
                continue
            data = contract.get('data')
            sources = data.get('contract_info') if isinstance(data, dict) else None
            for entry in sources if isinstance(sources, list) else []:
                if (not isinstance(entry, dict) or type(entry.get('id')) is not int
                        or entry['id'] != file_id or not isinstance(entry.get('source'), str)):
                    continue
                name = entry.get('path') or entry.get('name')
                if isinstance(name, str) and name:
                    candidates.append({'file_path': name, 'source_sha256': hashlib.sha256(
                        entry['source'].encode('utf-8')).hexdigest()})
        if len(candidates) == 1:
            location['source_identity'] = candidates[0]
    _bind_revert_propagation(trace, result, info, patched_addresses, runtime_codes)
    return {
        'completed': True, 'status': 'success' if status else 'revert',
        'gas_used': gas_used, 'error_message': reason,
        'simulation_id': simulation_id, 'artifact': {**artifact, 'simulation_id': simulation_id},
        'logs': {'available': True, 'availability': log_availability,
                 'count': len(logs), 'ordered_logs_sha256': _digest(logs)},
        'balances': {'available': any(changes[field]['available'] for field in
                                     ('balance_diff', 'balance_changes', 'asset_changes')),
                     'changes': {key: value for key, value in changes.items() if key != 'state_diff'}},
        'storage': changes['state_diff'],
        'execution_effects': _execution_effects(info),
        'trace': trace,
        'profit_usd': None,
    }
