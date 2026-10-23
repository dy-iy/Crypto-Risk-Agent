"""Bind changed Solidity guards to instructions in the actual override runtime.

Only compiler AST/source-map evidence is accepted. A call's address or error
text alone is deliberately insufficient, and unsupported mappings stay unknown.
"""
from collections import Counter
import hashlib
import json
import re

from app.attackpilot.utils.bytecode_transplanter import BytecodeTransplanter
from app.attackpilot.utils.patch import build_applied_patch_record


_TOKEN = re.compile(
    r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r'[A-Za-z_$][A-Za-z0-9_$]*|0[xX][0-9a-fA-F]+|[0-9]+|[^\s]', re.DOTALL,
)


def attribution_digest(value):
    """Digest a payload without its self-referential evidence_sha256 field."""
    return hashlib.sha256(json.dumps(
        {key: item for key, item in value.items() if key != 'evidence_sha256'},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
    ).encode('utf-8')).hexdigest()


def _tokens(source):
    return tuple(match.group() for match in _TOKEN.finditer(source)
                 if not match.group().startswith(('//', '/*')))


def _contains(tokens, needle):
    return any(tokens[index:index + len(needle)] == needle
               for index, token in enumerate(tokens) if token == needle[0])


def _span(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+:\d+:\d+', value):
        raise ValueError('guard_source_range_unavailable')
    return tuple(int(part) for part in value.split(':'))


def _guard_nodes(compiled, sources):
    """Read built-in Error(string) guards from complete compiler ASTs."""
    if not isinstance(compiled.ast, dict) or set(compiled.ast) != set(sources):
        raise ValueError('guard_source_ast_unavailable')
    guards, opaque_reverts = [], Counter()
    seen_ids = set()
    for path, root in compiled.ast.items():
        if not isinstance(root, dict) or root.get('nodeType') != 'SourceUnit':
            raise ValueError('guard_source_ast_unavailable')
        _, _, source_id = _span(root.get('src'))
        if source_id in seen_ids:
            raise ValueError('guard_source_identity_ambiguous')
        seen_ids.add(source_id)
        raw = sources[path].encode('utf-8')
        stack = [root]
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            for value in node.values():
                if isinstance(value, dict):
                    stack.append(value)
                elif isinstance(value, list):
                    stack.extend(item for item in value if isinstance(item, dict))
            if node.get('nodeType') == 'InlineAssembly' and not isinstance(node.get('AST'), dict):
                # Older compiler ASTs may omit the Yul tree entirely. We cannot
                # establish the absence of an arbitrary Error(string) path.
                opaque_reverts['assembly_body_unavailable'] += 1
            if (node.get('nodeType') == 'YulFunctionCall'
                    and isinstance(node.get('functionName'), dict)
                    and node['functionName'].get('name') == 'revert'):
                opaque_reverts['assembly_revert'] += 1
            expression = node.get('expression')
            if node.get('nodeType') != 'FunctionCall' or not isinstance(expression, dict):
                continue
            name = expression.get('name')
            if (expression.get('nodeType') != 'Identifier' or name not in {'require', 'revert'}
                    or type(expression.get('referencedDeclaration')) is not int
                    or expression['referencedDeclaration'] >= 0):
                continue
            arguments = node.get('arguments')
            if not isinstance(arguments, list) or len(arguments) != (2 if name == 'require' else 1):
                continue
            literal = arguments[-1]
            if (not isinstance(literal, dict) or literal.get('nodeType') != 'Literal'
                    or literal.get('kind') not in {'string', 'unicodeString'}
                    or not isinstance(literal.get('value'), str) or not literal['value']):
                # An unchanged require(x, variable) can emit the exact same
                # string as a newly-added literal guard. The optimizer may
                # merge their REVERT and attribute its source map to only the
                # new guard. Ignoring the dynamic guard would be unsound.
                opaque_reverts['dynamic_error_string'] += 1
                continue
            start, length, file_id = _span(node.get('src'))
            if length <= 0 or start + length > len(raw) or file_id != source_id:
                raise ValueError('guard_source_range_unavailable')
            source = raw[start:start + length].decode('utf-8')
            tokens = _tokens(source)
            if not tokens:
                raise ValueError('guard_source_range_unavailable')
            guards.append({
                'file_path': path, 'source_id': source_id, 'start': start, 'length': length,
                'reason': literal['value'], 'guard_sha256': hashlib.sha256(source.encode()).hexdigest(),
                'tokens': tokens,
            })
    return guards, opaque_reverts


def _instruction_boundaries(code):
    result, pc = set(), 0
    while pc < len(code):
        result.add(pc)
        opcode = code[pc]
        pc += 1 + (opcode - 0x5f if 0x60 <= opcode <= 0x7f else 0)
    return result


def _contract_attribution(original, patched, compiled, runtime):
    old_sources, sources = original.sources, patched.sources
    if (not isinstance(old_sources, dict) or not isinstance(sources, dict)
            or set(old_sources) != set(sources) or not sources
            or any(not isinstance(path, str) or not isinstance(value, str)
                   for collection in (old_sources, sources) for path, value in collection.items())):
        raise ValueError('guard_sources_unavailable')
    compiled_code, override_code = BytecodeTransplanter._code(compiled.bytecode), BytecodeTransplanter._code(runtime)
    executable_end, _ = BytecodeTransplanter._metadata(compiled_code)
    if len(compiled_code) != len(override_code):
        raise ValueError('guard_runtime_mismatch')
    # Transplantation may change only the immutable operands, never opcodes.
    slots = BytecodeTransplanter._slots(compiled, executable_end)
    mutable = {index for references in slots.values() for start, length in references
               for index in range(start, start + length)}
    if any(a != b and index not in mutable for index, (a, b) in enumerate(zip(compiled_code, override_code))):
        raise ValueError('guard_runtime_mismatch')
    guards, opaque_reverts = _guard_nodes(compiled, sources)
    old_tokens = [_tokens(source) for source in old_sources.values()]
    reason_counts = Counter(guard['reason'] for guard in guards)
    mappings = getattr(compiled, 'source_mapping', None)
    if not isinstance(mappings, list):
        raise ValueError('guard_source_map_unavailable')
    boundaries = _instruction_boundaries(override_code[:executable_end])
    by_pc = {}
    for mapping in mappings:
        pc = getattr(mapping, 'pc', None)
        if type(pc) is int:
            by_pc.setdefault(pc, []).append(mapping)
    accepted, rejected = [], Counter(opaque_reverts)
    for guard in guards:
        tokens = guard.pop('tokens')
        if any(_contains(original_tokens, tokens) for original_tokens in old_tokens):
            rejected['unchanged_guard'] += 1
            continue
        if opaque_reverts:
            rejected['opaque_revert_path'] += 1
            continue
        # Optimizers can share an Error(string) block across guards. Source maps
        # alone do not demonstrate which caller selected that shared block.
        if reason_counts[guard['reason']] != 1:
            rejected['ambiguous_guard_reason'] += 1
            continue
        pcs = []
        for pc, records in by_pc.items():
            if (len(records) != 1 or pc not in boundaries or pc >= executable_end
                    or override_code[pc] != 0xfd or compiled_code[pc] != 0xfd):
                continue
            mapping = records[0]
            start, length = getattr(mapping, 'begin', None), getattr(mapping, 'offset', None)
            if (getattr(mapping, 'filename', None) == guard['file_path']
                    and getattr(mapping, 'opcode', None) == 'REVERT'
                    and type(start) is int and type(length) is int and length > 0
                    and guard['start'] <= start
                    and start + length <= guard['start'] + guard['length']):
                pcs.append(pc)
        if not pcs:
            rejected['guard_revert_pc_unavailable'] += 1
            continue
        guard['revert_pcs'] = sorted(pcs)
        guard['source_sha256'] = hashlib.sha256(sources[guard['file_path']].encode()).hexdigest()
        accepted.append(guard)
    return {
        'patched_runtime_sha256': hashlib.sha256(override_code).hexdigest(),
        'compiled_runtime_sha256': hashlib.sha256(compiled_code).hexdigest(),
        'sources_sha256': {path: hashlib.sha256(source.encode()).hexdigest() for path, source in sorted(sources.items())},
        'original_sources_sha256': {path: hashlib.sha256(source.encode()).hexdigest() for path, source in sorted(old_sources.items())},
        'guards': sorted(accepted, key=lambda guard: (guard['file_path'], guard['start'])),
        'unresolved_guard_counts': dict(sorted(rejected.items())),
    }


def build_patch_attribution(original_contracts, patched_contracts, compiled_results, runtime_bytecodes, patches):
    """Produce bounded evidence; absent/ambiguous data cannot establish a match.

    Source offsets and IDs belong to this compilation. A vendor file ID is not
    interchangeable: trace source identity additionally needs the path/digest.
    """
    evidence = {'schema_version': 1, 'status': 'unavailable',
                'applied_patch_sha256': hashlib.sha256(patches.encode()).hexdigest(),
                'contracts': {}}
    try:
        if (not patched_contracts or set(patched_contracts) != set(compiled_results)
                or set(patched_contracts) != set(runtime_bytecodes)
                or not set(patched_contracts).issubset(original_contracts)):
            raise ValueError('guard_compilation_incomplete')
        before, after = {}, {}
        for address, entity in patched_contracts.items():
            if not isinstance(address, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
                raise ValueError('guard_contract_identity_invalid')
            for path, source in original_contracts[address].sources.items():
                before[f'{address}::{path}'] = source
            for path, source in entity.sources.items():
                after[f'{address}::{path}'] = source
        if build_applied_patch_record(before, after) != patches:
            raise ValueError('guard_applied_patch_mismatch')
        for address, entity in patched_contracts.items():
            evidence['contracts'][address.lower()] = _contract_attribution(
                original_contracts[address], entity, compiled_results[address], runtime_bytecodes[address])
        if any(contract['guards'] for contract in evidence['contracts'].values()):
            evidence['status'] = 'available'
        else:
            evidence['reason_code'] = 'modified_guard_location_unavailable'
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError) as exc:
        evidence['contracts'] = {}
        evidence['reason_code'] = str(exc) if isinstance(exc, ValueError) else 'guard_compilation_incomplete'
    evidence['evidence_sha256'] = attribution_digest(evidence)
    return evidence


