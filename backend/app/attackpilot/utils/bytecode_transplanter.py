"""Preserve historical contract state when replacing runtime code."""
from typing import Tuple

from app.attackpilot.daos.contract import ContractCompileItem


class RuntimeIntegrityError(ValueError):
    def __init__(self, reason_code, message):
        self.reason_code = reason_code
        super().__init__(message)


class BytecodeTransplanter:
    @staticmethod
    def _code(value):
        if not isinstance(value, str):
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Runtime bytecode is missing.')
        value = value.removeprefix('0x')
        if len(value) % 2 or any(char not in '0123456789abcdefABCDEF' for char in value):
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Runtime bytecode is not valid hexadecimal.')
        try:
            code = bytes.fromhex(value)
        except ValueError:
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Runtime bytecode is not valid hexadecimal.') from None
        if not code:
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Runtime bytecode is empty.')
        return code

    @staticmethod
    def _metadata(code):
        """Recognize Solidity's bounded CBOR trailer, never arbitrary suffix data."""
        if len(code) < 3:
            return len(code), None
        length = int.from_bytes(code[-2:], 'big')
        start = len(code) - length - 2
        if start < 0 or not length:
            return len(code), None
        raw = bytes(code[start:-2])
        position = 0

        def read():
            nonlocal position
            if position >= len(raw):
                raise ValueError
            head = raw[position]
            position += 1
            major, size = head >> 5, head & 31
            if major == 7 and size in (20, 21):
                return size == 21
            if major not in (2, 3):
                raise ValueError
            if size == 24:
                if position >= len(raw):
                    raise ValueError
                size = raw[position]
                position += 1
            elif size >= 24:
                raise ValueError
            end = position + size
            if end > len(raw):
                raise ValueError
            data = raw[position:end]
            position = end
            return data.decode('utf-8') if major == 3 else data

        try:
            count = raw[0] - 0xa0
            if not 1 <= count <= 5:
                raise ValueError
            position = 1
            metadata = {}
            for _ in range(count):
                key, value = read(), read()
                if not isinstance(key, str) or key in metadata:
                    raise ValueError
                if key in ('bzzr0', 'bzzr1'):
                    if not isinstance(value, bytes) or len(value) != 32:
                        raise ValueError
                elif key == 'ipfs':
                    if not isinstance(value, bytes) or len(value) != 34 or value[:2] != b'\x12\x20':
                        raise ValueError
                elif key == 'solc':
                    if not isinstance(value, bytes) or len(value) != 3:
                        raise ValueError
                elif key == 'experimental':
                    if type(value) is not bool:
                        raise ValueError
                else:
                    raise ValueError
                metadata[key] = value
            if position != len(raw):
                raise ValueError
            return start, metadata
        except (ValueError, UnicodeDecodeError, IndexError):
            return len(code), None

    @staticmethod
    def _declarations(ast, *, immutable_only=True):
        mapping = {}

        def walk(node, path, contract=None):
            if not isinstance(node, dict):
                return
            if node.get('nodeType') == 'ContractDefinition':
                contract = node.get('name')
            if (node.get('nodeType') == 'VariableDeclaration'
                    and (node.get('mutability') == 'immutable' if immutable_only else node.get('stateVariable') is True)):
                name = node.get('name')
                type_name = node.get('typeDescriptions', {}).get('typeString')
                if contract and name and type_name and type(node.get('id')) is int:
                    mapping[node['id']] = (path, contract, name, type_name)
            for value in node.values():
                if isinstance(value, dict):
                    walk(value, path, contract)
                elif isinstance(value, list):
                    for item in value:
                        walk(item, path, contract)

        for path, root in (ast or {}).items():
            walk(root, path)
        return mapping

    @staticmethod
    def _slots(item, code_length):
        declarations = BytecodeTransplanter._declarations(item.ast)
        slots, occupied = {}, set()
        for ast_id, references in (item.immutable_references or {}).items():
            try:
                key = declarations[int(ast_id)]
            except (KeyError, TypeError, ValueError):
                raise RuntimeIntegrityError('immutable_layout_mismatch', 'An immutable reference has no unique qualified declaration.') from None
            if key in slots or not isinstance(references, list) or not references:
                raise RuntimeIntegrityError('immutable_layout_mismatch', 'Immutable references are missing or ambiguous.')
            slots[key] = []
            for reference in references:
                start, length = reference.get('start'), reference.get('length')
                if (type(start) is not int or type(length) is not int or start < 0 or length <= 0
                        or start + length > code_length):
                    raise RuntimeIntegrityError('immutable_layout_mismatch', 'An immutable reference exceeds the executable runtime boundary.')
                offsets = set(range(start, start + length))
                if offsets & occupied:
                    raise RuntimeIntegrityError('immutable_layout_mismatch', 'Immutable references overlap.')
                occupied.update(offsets)
                slots[key].append((start, length))
        return slots

    @staticmethod
    def validate_original(item, on_chain_runtime):
        if item is None:
            raise RuntimeIntegrityError('original_runtime_mismatch', 'The original compilation is missing.')
        compiled, historical = BytecodeTransplanter._code(item.bytecode), BytecodeTransplanter._code(on_chain_runtime)
        compiled_end, compiled_metadata = BytecodeTransplanter._metadata(compiled)
        historical_end, historical_metadata = BytecodeTransplanter._metadata(historical)
        if len(compiled) != len(historical) or compiled_end != historical_end:
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Compiled source does not match the historical runtime length.')
        if compiled_metadata != historical_metadata:
            hashes = {'ipfs', 'bzzr0', 'bzzr1'}
            if (compiled_metadata is None or historical_metadata is None
                    or compiled_metadata.keys() != historical_metadata.keys()
                    or any(compiled_metadata[key] != historical_metadata[key]
                           for key in compiled_metadata.keys() - hashes)):
                raise RuntimeIntegrityError('original_runtime_mismatch', 'Compiled and historical metadata are incompatible.')
        slots = BytecodeTransplanter._slots(item, compiled_end)
        expected = bytearray(compiled[:compiled_end])
        values = {}
        for key, references in slots.items():
            observed = {historical[start:start + length] for start, length in references}
            if len(observed) != 1:
                raise RuntimeIntegrityError('immutable_layout_mismatch', 'Repeated references to one immutable contain different historical values.')
            values[key] = observed.pop()
            for start, length in references:
                expected[start:start + length] = values[key]
        if bytes(expected) != historical[:historical_end]:
            raise RuntimeIntegrityError('original_runtime_mismatch', 'Original compiled instructions differ from the historical deployed code outside immutable slots and metadata hashes.')
        return values

    @staticmethod
    def _storage_signature(item):
        layout = getattr(item, 'storage_layout', None)
        if not isinstance(layout, dict) or not isinstance(layout.get('storage'), list):
            raise RuntimeIntegrityError('storage_layout_unavailable', 'The compiler did not provide a storage layout; safe runtime replacement cannot be established.')
        types = layout.get('types') or {}
        declarations = BytecodeTransplanter._declarations(item.ast, immutable_only=False)

        def type_signature(type_id, seen=()):
            if type_id not in types:
                raise RuntimeIntegrityError('storage_layout_unavailable', 'A storage type is missing from compiler output.')
            value = types[type_id]
            if type_id in seen:
                return ('recursive', value.get('label'))
            shape = {key: value.get(key) for key in ('encoding', 'label', 'numberOfBytes')}
            for key in ('base', 'key', 'value'):
                if key in value:
                    shape[key] = type_signature(value[key], (*seen, type_id))
            if 'members' in value:
                shape['members'] = [(member.get('label'), member.get('slot'), member.get('offset'),
                                     type_signature(member.get('type'), (*seen, type_id)))
                                    for member in value['members']]
            return shape

        result = []
        for entry in layout['storage']:
            declaration = declarations.get(entry.get('astId'))
            if declaration is None:
                raise RuntimeIntegrityError('storage_layout_unavailable', 'A storage slot cannot be mapped to its qualified declaration.')
            result.append((declaration, entry.get('slot'), entry.get('offset'), type_signature(entry.get('type'))))
        return result

    @staticmethod
    def _initialization_signature(ast):
        ignored = {'id', 'src', 'nameLocation', 'nativeSrc', 'scope', 'referencedDeclaration',
                   'typeDescriptions', 'functionReturnParameters', 'overloadedDeclarations',
                   'baseFunctions', 'documentation'}

        def stable(value):
            if isinstance(value, dict):
                # This statement's assignments field repeats the IDs of ordered
                # declarations (including tuple holes). Those IDs move when an
                # earlier runtime function changes; declarations and initialValue
                # already preserve the actual initialization semantics.
                # IdentifierPath.nameLocations contains source coordinates only;
                # keep the identifier name and constructor arguments instead.
                return {key: stable(item) for key, item in value.items()
                        if key not in ignored and not (
                            value.get('nodeType') == 'VariableDeclarationStatement'
                            and key == 'assignments') and not (
                            value.get('nodeType') == 'IdentifierPath'
                            and key == 'nameLocations')}
            if isinstance(value, list):
                return [stable(item) for item in value]
            return value

        result = {}
        for path, root in (ast or {}).items():
            for contract in root.get('nodes', []):
                if contract.get('nodeType') != 'ContractDefinition':
                    continue
                selected = [stable(node) for node in contract.get('nodes', [])
                            if (node.get('nodeType') == 'FunctionDefinition'
                                and (node.get('kind') == 'constructor' or node.get('isConstructor') is True))
                            or (node.get('nodeType') == 'VariableDeclaration'
                                and node.get('mutability') == 'immutable')]
                for node in contract.get('nodes', []):
                    if (node.get('nodeType') == 'VariableDeclaration' and node.get('stateVariable') is True
                            and node.get('value') is not None and node.get('constant') is not True
                            and node.get('mutability') not in ('constant', 'immutable')):
                        selected.append({'state_initializer': node.get('name'), 'value': stable(node['value'])})
                for base in contract.get('baseContracts', []):
                    if base.get('arguments'):
                        selected.append({'base_constructor': stable(base)})
                if selected:
                    result[(path, contract.get('name'))] = selected
        return result

    @staticmethod
    def transplant(original_compile_item: ContractCompileItem, on_chain_runtime_bytecode_hex: str,
                   patched_compile_item: ContractCompileItem) -> Tuple[bool, str, str]:
        try:
            values = BytecodeTransplanter.validate_original(original_compile_item, on_chain_runtime_bytecode_hex)
            if BytecodeTransplanter._initialization_signature(original_compile_item.ast) != BytecodeTransplanter._initialization_signature(patched_compile_item.ast):
                raise RuntimeIntegrityError('constructor_or_immutable_changed', 'The patch changes a constructor, state initializer, or immutable declaration. Historical state cannot be reinitialized by runtime replacement.')
            if BytecodeTransplanter._storage_signature(original_compile_item) != BytecodeTransplanter._storage_signature(patched_compile_item):
                raise RuntimeIntegrityError('storage_layout_changed', 'The patch changes existing storage slots or types. Preserve the original storage layout.')
            patched = bytearray(BytecodeTransplanter._code(patched_compile_item.bytecode))
            executable_end, _ = BytecodeTransplanter._metadata(patched)
            slots = BytecodeTransplanter._slots(patched_compile_item, executable_end)
            if slots.keys() != values.keys():
                raise RuntimeIntegrityError('immutable_layout_mismatch', 'The patch adds, removes, renames, or changes the type of an immutable value.')
            for key, references in slots.items():
                for start, length in references:
                    if len(values[key]) != length:
                        raise RuntimeIntegrityError('immutable_layout_mismatch', 'An immutable reference changed width; padding or truncation is not permitted.')
                    patched[start:start + length] = values[key]
            return True, '0x' + patched.hex(), 'Historical runtime, storage layout, and all immutable values validated.'
        except RuntimeIntegrityError as exc:
            return False, '', f'{exc.reason_code}: {exc}'
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            return False, '', f'immutable_layout_mismatch: Invalid compiler integrity data ({type(exc).__name__}).'
