"""Bounded proofs for a call-result branch that directly forwards a failure.

This intentionally is not an EVM emulator. Pre-call stack/memory and successful
returndata are unknown; unsupported operations or data-dependent control flow
fail closed. In particular, source-level error strings are never a whitelist.
"""
import hashlib
import re


_CALL_OPS = {'CALL': 0xf1, 'CALLCODE': 0xf2, 'DELEGATECALL': 0xf4, 'STATICCALL': 0xfa}
_WORD = (1 << 256) - 1
_MAX_BYTES = 65_536
_MAX_STEPS = 512
_RETURN_SIZE = object()


class _UnknownExecution(Exception):
    pass


def _bytes(value, maximum):
    if (not isinstance(value, str) or not re.fullmatch(r'(?:0x)?(?:[0-9a-fA-F]{2})*', value)
            or len(value) > maximum * 2 + 2):
        raise _UnknownExecution
    return bytes.fromhex(value.removeprefix('0x'))


def _instructions(code):
    instructions, pc = {}, 0
    while pc < len(code):
        opcode = code[pc]
        width = opcode - 0x5f if 0x60 <= opcode <= 0x7f else 0
        end = pc + 1 + width
        argument = int.from_bytes(code[pc + 1:end].ljust(width, b'\0'), 'big') if width else None
        instructions[pc] = (opcode, end, argument)
        pc = end
    return instructions


def _call_context(instructions, call_pc, kind):
    """Recover only constants established in the call's own basic block."""
    block = []
    for pc, instruction in instructions.items():
        if pc >= call_pc:
            break
        opcode = instruction[0]
        if opcode == 0x5b:
            block = [(pc, instruction)]
        elif opcode in (0x00, 0x56, 0x57, 0xf0, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xfa, 0xfd, 0xfe, 0xff):
            block = []
        else:
            block.append((pc, instruction))
    stack, memory = [(None, False)] * 16, {}

    def pop():
        if not stack:
            raise _UnknownExecution
        return stack.pop()

    for pc, (opcode, _, argument) in block:
        if opcode == 0x5f:
            stack.append((0, False))
        elif 0x60 <= opcode <= 0x7f:
            stack.append((argument, False))
        elif 0x80 <= opcode <= 0x8f:
            depth = opcode - 0x7f
            if len(stack) < depth:
                raise _UnknownExecution
            stack.append(stack[-depth])
        elif 0x90 <= opcode <= 0x9f:
            depth = opcode - 0x8f
            if len(stack) <= depth:
                raise _UnknownExecution
            stack[-1], stack[-1 - depth] = stack[-1 - depth], stack[-1]
        elif opcode == 0x50:
            pop()
        elif opcode in (0x34, 0x36, 0x3d, 0x5a):
            stack.append((None, False))
        elif opcode in (0x35, 0x51):
            pop()
            stack.append((None, False))
        elif opcode == 0x52:
            offset, value = pop()[0], pop()[0]
            if offset is None:
                memory.clear()
            elif offset <= _MAX_BYTES - 32:
                data = value.to_bytes(32, 'big') if value is not None else [None] * 32
                memory.update({offset + index: byte for index, byte in enumerate(data)})
            else:
                raise _UnknownExecution
        elif opcode == 0x5b:
            pass
        else:
            raise _UnknownExecution
    arguments = [pop()[0] for _ in range(7 if kind in ('CALL', 'CALLCODE') else 6)]
    return stack, memory, arguments[-2:]


def _run(instructions, code_length, start, returned, child_output, context):
    # The arbitrary pre-call stack is deliberately opaque. No unknown value may
    # select a jump, determine failure bytes, or be treated as a concrete zero.
    stack = list(context[0]) + [(returned, True)]
    memory, branches, visited = dict(context[1]), {}, set()
    returndata = child_output if returned == 0 else None
    output_offset, output_size = context[2]
    if output_offset is None or output_size is None:
        memory.clear()
    elif output_size:
        if output_offset > _MAX_BYTES or output_size > _MAX_BYTES - output_offset:
            raise _UnknownExecution
        copied = min(output_size, len(child_output)) if returned == 0 else output_size
        memory.update({output_offset + index: child_output[index] if returned == 0 else None
                       for index in range(copied)})
    copied_return_area = None
    pc = start

    def pop():
        if not stack:
            raise _UnknownExecution
        return stack.pop()

    def concrete(value):
        if type(value) is not int:
            raise _UnknownExecution
        return value

    def area(offset, size):
        offset, size = concrete(offset), concrete(size)
        if offset < 0 or size < 0 or offset > _MAX_BYTES or size > _MAX_BYTES - offset:
            raise _UnknownExecution
        return offset, size

    def jump(target):
        target = concrete(target)
        if target not in instructions or instructions[target][0] != 0x5b:
            raise _UnknownExecution
        return target

    for _ in range(_MAX_STEPS):
        if pc >= code_length:
            return {'exit': 'STOP', 'pc': pc, 'branches': branches}
        if pc in visited or pc not in instructions:
            raise _UnknownExecution
        visited.add(pc)
        opcode, next_pc, argument = instructions[pc]
        if opcode == 0x00:
            return {'exit': 'STOP', 'pc': pc, 'branches': branches}
        if opcode in (0xf3, 0xfd):
            offset, size = pop()[0], pop()[0]
            if opcode == 0xf3:
                if size is _RETURN_SIZE:
                    if type(offset) is not int or offset != copied_return_area:
                        raise _UnknownExecution
                elif size != 0:
                    area(offset, size)
                # The successful-return alternative bypasses this explicit
                # REVERT. This is not a gas model or a business-regression test.
                return {'exit': 'RETURN', 'pc': pc, 'branches': branches}
            offset, size = area(offset, size)
            output = []
            for index in range(offset, offset + size):
                value = memory.get(index)
                if value is None:
                    raise _UnknownExecution
                output.append(value)
            return {'exit': 'REVERT', 'pc': pc, 'branches': branches, 'output': bytes(output)}
        if opcode == 0x5f:
            stack.append((0, False))
        elif 0x60 <= opcode <= 0x7f:
            stack.append((argument, False))
        elif 0x80 <= opcode <= 0x8f:
            depth = opcode - 0x7f
            if len(stack) < depth:
                raise _UnknownExecution
            stack.append(stack[-depth])
        elif 0x90 <= opcode <= 0x9f:
            depth = opcode - 0x8f
            if len(stack) <= depth:
                raise _UnknownExecution
            stack[-1], stack[-1 - depth] = stack[-1 - depth], stack[-1]
        elif opcode == 0x50:
            pop()
        elif opcode == 0x5b:
            pass
        elif opcode == 0x58:
            stack.append((pc, False))
        elif opcode == 0x3d:
            stack.append((len(returndata) if returndata is not None else _RETURN_SIZE, False))
        elif opcode in (0x15, 0x19):
            value, taint = pop()
            result = None if type(value) is not int else (int(value == 0) if opcode == 0x15 else value ^ _WORD)
            stack.append((result, taint))
        elif opcode in (0x01, 0x02, 0x03, 0x04, 0x06, 0x10, 0x11, 0x14,
                        0x16, 0x17, 0x18, 0x1b, 0x1c):
            left, taint_left = pop()
            right, taint_right = pop()
            result = None
            if type(left) is int and type(right) is int:
                if opcode == 0x01:
                    result = (left + right) & _WORD
                elif opcode == 0x02:
                    result = (left * right) & _WORD
                elif opcode == 0x03:
                    result = (left - right) & _WORD
                elif opcode == 0x04:
                    result = left // right if right else 0
                elif opcode == 0x06:
                    result = left % right if right else 0
                elif opcode == 0x10:
                    result = int(left < right)
                elif opcode == 0x11:
                    result = int(left > right)
                elif opcode == 0x14:
                    result = int(left == right)
                elif opcode == 0x16:
                    result = left & right
                elif opcode == 0x17:
                    result = left | right
                elif opcode == 0x18:
                    result = left ^ right
                elif opcode == 0x1b:
                    result = (right << left) & _WORD if left < 256 else 0
                elif opcode == 0x1c:
                    result = right >> left if left < 256 else 0
            stack.append((result, taint_left or taint_right))
        elif opcode == 0x56:
            next_pc = jump(pop()[0])
        elif opcode == 0x57:
            destination = pop()[0]
            condition, taint = pop()
            condition = concrete(condition)
            branches[pc] = (bool(condition), taint)
            if condition:
                next_pc = jump(destination)
        elif opcode == 0x51:
            offset = pop()[0]
            if type(offset) is not int or offset > _MAX_BYTES - 32:
                stack.append((None, False))
            else:
                values = [memory.get(index) for index in range(offset, offset + 32)]
                stack.append((int.from_bytes(bytes(values), 'big')
                              if all(value is not None for value in values) else None, False))
        elif opcode in (0x52, 0x53):
            offset, value = pop()[0], pop()[0]
            size = 32 if opcode == 0x52 else 1
            if type(offset) is not int:
                # Any pre-existing bytes may have been overwritten. In the
                # failure run, this cannot supply concrete REVERT output.
                memory.clear()
            else:
                offset, size = area(offset, size)
                data = value.to_bytes(32, 'big')[-size:] if type(value) is int else [None] * size
                memory.update({offset + index: byte for index, byte in enumerate(data)})
        elif opcode == 0x3e:
            offset, source, size = pop()[0], pop()[0], pop()[0]
            if returndata is None:
                # Only the entire successful returndata or a zero-byte copy is
                # in bounds for every unknown successful return-data length.
                if source != 0 or (size is not _RETURN_SIZE and size != 0):
                    raise _UnknownExecution
                if size is _RETURN_SIZE:
                    area(offset, 0)
                    memory.clear()
                    copied_return_area = offset
            else:
                offset, size = area(offset, size)
                source = concrete(source)
                if source > len(returndata) or size > len(returndata) - source:
                    raise _UnknownExecution
                memory.update({offset + index: byte
                               for index, byte in enumerate(returndata[source:source + size])})
        else:
            # Includes external calls, storage/environment reads, LOGs, dynamic
            # code execution and any opcode whose semantics are not modeled.
            raise _UnknownExecution
        if len(stack) > 1024:
            raise _UnknownExecution
        pc = next_pc
    raise _UnknownExecution


def prove_revert_propagation(parent_runtime, child_call_pc, child_kind, child_output, parent_output):
    """Return a pure, replayable proof or None; never guess a missing coordinate.

    The caller must bind runtime bytes to the actual parent code address in the
    response/request, and both outputs and the call PC to that same raw trace.
    CREATE/CREATE2, caller-PC offsets, unknown memory and opaque continuations
    intentionally remain unproved. This accepts terminal assembly forwarding
    and bounded constant-memory checks, without assuming Solidity's free-memory
    pointer or treating a generic revert string as evidence.
    """
    try:
        code = _bytes(parent_runtime, 131_072)
        child_bytes = _bytes(child_output, _MAX_BYTES)
        parent_bytes = _bytes(parent_output, _MAX_BYTES)
        if (not code or type(child_call_pc) is not int or child_call_pc < 0
                or child_kind not in _CALL_OPS):
            return None
        instructions = _instructions(code)
        instruction = instructions.get(child_call_pc)
        if instruction is None or instruction[0] != _CALL_OPS[child_kind]:
            return None
        context = _call_context(instructions, child_call_pc, child_kind)
        failure = _run(instructions, len(code), instruction[1], 0, child_bytes, context)
        success = _run(instructions, len(code), instruction[1], 1, child_bytes, context)
        branches = sorted(pc for pc, (taken, tainted) in failure['branches'].items()
                          if tainted and pc in success['branches']
                          and success['branches'][pc][1]
                          and success['branches'][pc][0] != taken)
        if (failure['exit'] != 'REVERT' or failure['output'] != parent_bytes
                or success['exit'] not in ('RETURN', 'STOP') or not branches):
            return None
        return {
            'method': 'evm_call_failure_branch', 'proof_version': 1,
            'runtime_sha256': hashlib.sha256(code).hexdigest(),
            'child_call_pc': child_call_pc, 'child_call_type': child_kind,
            'failure_revert_pc': failure['pc'], 'success_exit_pc': success['pc'],
            'branch_pcs': branches,
            'child_output_sha256': hashlib.sha256(child_bytes).hexdigest(),
            'parent_output_sha256': hashlib.sha256(parent_bytes).hexdigest(),
        }
    except (_UnknownExecution, TypeError, ValueError, OverflowError):
        return None
