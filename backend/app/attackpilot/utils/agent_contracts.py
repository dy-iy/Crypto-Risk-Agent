"""Pure shape and identity checks at model/coordinator boundaries."""
import re

from app.attackpilot.errors import AgentContractError

_HASH = re.compile(r'0x[0-9a-fA-F]{64}')
_ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')


def hash_list(value, known, *, stage, reason_code, nonempty=False):
    if (not isinstance(value, list) or not isinstance(known, (list, tuple, set))
            or any(not isinstance(tx, str) or not _HASH.fullmatch(tx) for tx in known)
            or nonempty and not value
            or any(not isinstance(tx, str) or not _HASH.fullmatch(tx) for tx in value)):
        raise AgentContractError(stage, reason_code)
    selected = {tx.lower() for tx in value}
    ordered = list(dict.fromkeys(tx.lower() for tx in known))
    if not selected.issubset(ordered):
        raise AgentContractError(stage, reason_code)
    return [tx for tx in ordered if tx in selected]


def observed_addresses(*evidence):
    """Collect full addresses from supplied chain evidence, never model summaries."""
    addresses = set()
    pending = list(evidence)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)
        elif isinstance(value, str):
            addresses.update(match.lower() for match in re.findall(
                r'(?<![0-9a-fA-F])0x[0-9a-fA-F]{40}(?![0-9a-fA-F])', value))
    return addresses


def classification(value, known, *, addresses=None):
    fail = lambda: AgentContractError('classification', 'agent_classification_invalid')
    if not isinstance(value, dict) or not isinstance(value.get('transaction'), dict):
        raise fail()
    txs = value['transaction']
    attack = hash_list(txs.get('attack_transactions'), known, stage='classification', reason_code='agent_classification_invalid')
    auxiliary = hash_list(txs.get('auxiliary_transactions'), known, stage='classification', reason_code='agent_classification_invalid')
    if set(attack) & set(auxiliary) or set(attack + auxiliary) != {tx.lower() for tx in known}:
        raise fail()
    roles = value.get('address_role')
    if not isinstance(roles, dict):
        raise fail()
    normalized = {}
    for address, role in roles.items():
        if (not isinstance(address, str) or not _ADDRESS.fullmatch(address)
                or not isinstance(role, dict)
                or any(not isinstance(role.get(key), str) or not role[key].strip() for key in ('role', 'description'))
                or addresses is not None and address.lower() not in addresses
                or address.lower() in normalized):
            raise fail()
        normalized[address.lower()] = dict(role)
    return normalized, attack, auxiliary


def trace_tree(value):
    if (not isinstance(value, str) or not value.strip()
            or re.match(r'^\s*(?:Error(?:\s|:|$)|Tool execution failed:)', value, re.I)):
        raise AgentContractError('trace', 'agent_trace_evidence_invalid')
    return value


def task_plan(value):
    fail = lambda: AgentContractError('task', 'agent_task_invalid')
    if (not isinstance(value, dict) or not isinstance(value.get('task_tree'), str)
            or not value['task_tree'].strip()
            or not isinstance(value.get('status', 'CONTINUE_DEBUGGING'), str)
            or value.get('status', 'CONTINUE_DEBUGGING') not in {'CONTINUE_DEBUGGING', 'READY_FOR_PATCH'}
            or not isinstance(value.get('thought_process', ''), str)
            or not isinstance(value.get('suspicious_functions', []), list)):
        raise fail()
    for item in value.get('suspicious_functions', []):
        if not isinstance(item, dict):
            raise fail()
        index = item.get('function_index')
        if not ((type(index) is int and index >= 0) or isinstance(index, str) and index.isdecimal()):
            raise fail()
        if (not isinstance(item.get('function_name'), str) or not item['function_name'].strip()
                or type(item.get('score')) not in (int, float) or not 0 <= item['score'] <= 100
                or not isinstance(item.get('reason'), str)):
            raise fail()
    return value


def patch_hypothesis(fault_report, fix_report, known):
    from app.attackpilot.utils.agent_helpers import ResponseParser, JSONParsingError
    fail = lambda: AgentContractError('trace', 'agent_hypothesis_invalid')
    if not isinstance(fault_report, str) or not fault_report.strip():
        raise fail()
    if isinstance(fix_report, str):
        try:
            fix_report = ResponseParser.process_response(fix_report, 'json', strict=True)
        except JSONParsingError:
            raise fail() from None
    if not isinstance(fix_report, dict):
        raise fail()
    functions = fix_report.get('faulty_functions')
    if not isinstance(functions, list) or not functions:
        raise fail()
    for function in functions:
        point = function.get('trigger_point') if isinstance(function, dict) else None
        if not isinstance(point, dict):
            raise fail()
        hash_list([point.get('transaction_hash')], known, stage='trace', reason_code='agent_hypothesis_invalid', nonempty=True)
        index = point.get('index')
        if not ((type(index) is int and index >= 0) or isinstance(index, str) and index.isdecimal()):
            raise fail()
    return fix_report


def memory_update(value):
    if (not isinstance(value, dict)
            or not isinstance(value.get('thought_process', ''), str)
            or not isinstance(value.get('action_directive', 'CONTINUE'), str)
            or not isinstance(value.get('global_fault_understanding'), dict)):
        raise AgentContractError('memory', 'agent_memory_invalid')
    understanding = value.get('global_fault_understanding', {})
    for key in ('attack_stages', 'key_trace_nodes', 'key_evidences', 'rejected_hypotheses', 'pending_questions'):
        if key in understanding and not isinstance(understanding[key], list):
            raise AgentContractError('memory', 'agent_memory_invalid')
    # All original facts, transaction focus and analysis history stay owned by
    # the coordinator. A model may update only its explicitly named analysis.
    return {key: value[key] for key in ('thought_process', 'global_fault_understanding', 'action_directive') if key in value}
