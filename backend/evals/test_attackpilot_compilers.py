"""Local compiler integration checks, using only synthetic Solidity source."""
import json
import copy
import hashlib
import asyncio
import os
import re
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock, AsyncMock
from app.attackpilot import settings
from app.attackpilot.utils.solc import Solc, SolcJS
from app.attackpilot.utils.typed_ast import get_typed_ast_items
from app.attackpilot.daos.contract import ContractCompileItem, ContractDao
from app.attackpilot.entities.contract import ContractEntityForCompile
from app.attackpilot.utils.bytecode_transplanter import BytecodeTransplanter, RuntimeIntegrityError
from app.attackpilot.utils.patch import SolidityCodePatcher

class CompilerTest(unittest.IsolatedAsyncioTestCase):
    def test_push0_preserves_instruction_offsets_and_source_locations(self):
        mappings = Solc("")._get_source_mappings(
            "PUSH0  PUSH1 0x2A ADD STOP ", "0:1:0;2:3:0;6:1:0;8:1:0", {0: "Example.sol"},
        )
        self.assertEqual([(item.opcode, item.pc, item.begin, item.offset, item.filename) for item in mappings], [
            ("PUSH0", 0, 0, 1, "Example.sol"), ("PUSH1", 1, 2, 3, "Example.sol"),
            ("ADD", 3, 6, 1, "Example.sol"), ("STOP", 4, 8, 1, "Example.sol"),
        ])

    async def test_timeout_and_cancellation_reap_compiler_process(self):
        create_process = asyncio.create_subprocess_exec
        for mode, has_input in [(mode, has_input) for mode in ('timeout', 'cancel')
                                for has_input in (False, True)]:
            with self.subTest(mode=mode, has_input=has_input):
                processes = []
                started = asyncio.Event()

                async def capture_process(*args, **kwargs):
                    process = await create_process(*args, **kwargs)
                    processes.append(process)
                    started.set()
                    return process

                compiler = Solc(sys.executable, timeout=0.05 if mode == "timeout" else 10)
                with patch("app.attackpilot.utils.solc.subprocess.create_subprocess_exec", capture_process):
                    task = asyncio.create_task(compiler._run_compiler([
                        sys.executable, "-c", "import time; time.sleep(60)",
                    ], input_data=b'x' * (4 * 1024 * 1024) if has_input else None))
                    try:
                        await asyncio.wait_for(started.wait(), timeout=5)
                        if mode == "cancel":
                            task.cancel()
                        with self.assertRaises(asyncio.CancelledError if mode == "cancel" else asyncio.TimeoutError):
                            await task
                        self.assertIsNotNone(processes[0].returncode)
                        if has_input:
                            self.assertTrue(processes[0].stdin.is_closing())
                    finally:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        for process in processes:
                            if process.returncode is None:
                                process.kill()
                                await process.communicate()

    async def test_standard_json_preserves_exact_file_bytes_through_child_stdin(self):
        create_process = asyncio.create_subprocess_exec
        # A child reports the bytes it actually received; this checks both file
        # transport and pipe transport without interpreting/reformatting JSON.
        child = (
            'import hashlib,json,sys; '
            'digest=hashlib.sha256(sys.stdin.buffer.read()).hexdigest(); '
            'print(json.dumps({"contracts":{},"sources":{},'
            '"errors":[{"severity":"info","message":digest}]}))'
        )
        received_commands = []

        async def capture_process(*args, **kwargs):
            received_commands.append(args)
            return await create_process(sys.executable, '-c', child, **kwargs)

        raw = ('{\r\n\t"language" : "Solidity", "sources" : {}, '
               '"settings" : {}, "sentinel" : "中文\u00a0\u3000\u200b"\r\n}\r\n').encode('utf-8')
        with tempfile.TemporaryDirectory(prefix='attackpilot-stdin-bytes-') as temp:
            input_path = Path(temp) / 'input with spaces.json'
            input_path.write_bytes(raw)
            with patch('app.attackpilot.utils.solc.subprocess.create_subprocess_exec', capture_process):
                compiled = await Solc('synthetic-solc').compile_json(str(input_path), 'Example')
        self.assertEqual(received_commands, [('synthetic-solc', '--standard-json')])
        self.assertEqual(compiled.errors, [{'severity': 'info', 'message': hashlib.sha256(raw).hexdigest()}])

    async def test_native_compiles_shanghai_push0_bytecode(self):
        binaries = list(settings.COMPILER_ROOT.glob("solc-linux-amd64-v0.8.23+*"))
        if not binaries:
            self.skipTest("The Solidity 0.8.23 native compiler is required")
        source = {"language": "Solidity", "sources": {"Example.sol": {"content": "pragma solidity 0.8.23; contract Example { function value() external pure returns(uint) { return 0; } }"}}, "settings": {"evmVersion": "shanghai", "outputSelection": {"*": {"*": ["evm.bytecode", "evm.deployedBytecode", "abi"], "": ["ast"]}}}}
        with tempfile.TemporaryDirectory(prefix="attackpilot compiler ") as temp:
            native_input = Path(temp) / "input.json"
            native_input.write_text(json.dumps(source))
            compiled = await Solc(str(binaries[0])).compile_json(str(native_input), "Example")
            self.assertTrue(compiled.bytecode, compiled.errors)
            self.assertTrue(any(item.opcode == "PUSH0" for item in compiled.source_mapping))

    async def test_legacy_solcjs_compiles_standard_json(self):
        if not (settings.PACKAGE_ROOT / "node_modules/solcv0.4.24").exists():
            self.skipTest("The Solidity 0.4.24 Node compiler is required")
        source = {"language": "Solidity", "sources": {"Example.sol": {"content": "pragma solidity 0.4.24; contract Example { function value() public pure returns(uint) { return 42; } }"}}, "settings": {"outputSelection": {"*": {"*": ["evm.bytecode", "evm.deployedBytecode", "abi"], "": ["ast"]}}}}
        with tempfile.TemporaryDirectory(prefix="attackpilot compiler ") as temp:
            script = Path(temp) / "compiler.js"
            script.write_text(settings.SOLCJS_CODE % ("v0.4.24", json.dumps(source)))
            js = await SolcJS(settings.NODE_PATH).compile_json(str(script), "Example")
            self.assertTrue(js.bytecode, js.errors)
            self.assertTrue(js.creation_bytecode)
            self.assertTrue(js.source_mapping)
            self.assertIn("value", {entry.get("name") for entry in js.abi})

    async def test_namespaced_mcp_subprocess_handshake_and_local_tool(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPClient
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ATTACKPILOT_WORK_DIR": temp}):
            client = MCPClient(settings.MCP_SERVER_PATH)
            async with asyncio.timeout(30):
                try:
                    await client.connect()
                    catalog = await client.list_tools()
                    self.assertIn("update_understanding", {tool.name for tool in catalog.tools})
                    response = await client.call_tool("update_understanding", {"insight": "offline synthetic evidence"})
                    self.assertIn("Added", response)
                finally:
                    await client.close()

    async def test_native_js_and_ast_in_isolated_work_directory(self):
        binaries = list(settings.COMPILER_ROOT.glob("solc-linux-amd64-v0.8.9+*"))
        if not binaries or not (settings.PACKAGE_ROOT / "node_modules/solcv0.8.9").exists():
            self.skipTest("Run AttackPilot prepare --compilers and install its Node dependencies first")
        source = {"language": "Solidity", "sources": {"Example.sol": {"content": "pragma solidity ^0.8.9; contract Example { function value() external pure returns(uint) { return 42; } }"}}, "settings": {"outputSelection": {"*": {"*": ["*"], "": ["ast"]}}}}
        with tempfile.TemporaryDirectory(prefix="attackpilot compiler ") as temp:
            native_input = Path(temp) / "input with spaces.json"
            native_input.write_text(json.dumps(source))
            compiled = await Solc(str(binaries[0])).compile_json(str(native_input), "Example")
            self.assertTrue(compiled.bytecode, compiled.errors)
            script = Path(temp) / "compiler with spaces.js"
            script.write_text(settings.SOLCJS_CODE % ("v0.8.9", json.dumps(source)))
            js = await SolcJS(settings.NODE_PATH).compile_json(str(script), "Example")
            self.assertEqual(js.bytecode, compiled.bytecode)
            with patch("app.attackpilot.utils.tmpfile.TMP_FILE_DIR", temp):
                nodes, edges = await get_typed_ast_items(next(iter(compiled.ast.values())))
            self.assertGreater(len(nodes), 3)
            self.assertTrue(edges)

    async def test_js_fallback_preserves_literals_and_utf8_source_locations(self):
        dao = ContractDao(AsyncMock())
        version = 'v0.8.9+commit.e5eed63a'
        native = dao._resolve_solc_path(version)
        if not native or not (settings.PACKAGE_ROOT / 'node_modules/solcv0.8.9').exists():
            self.skipTest('The Solidity 0.8.9 native and Node compilers are required')
        literal = 'A\tB\u00a0C\u3000D\u200bE'
        function = ('function text() external pure returns(string memory) {\r\n'
                    '\t\treturn unicode"' + literal + '";\r\n\t}')
        source = ('// 中文\u00a0\u3000\u200b\t偏移\r\npragma solidity 0.8.9;\r\n'
                  'contract Example {\r\n\t' + function + '\r\n}\r\n')
        standard = {
            'language': 'Solidity', 'sources': {'Example.sol': {'content': source}},
            'settings': {'optimizer': {'enabled': False, 'runs': 200},
                         'outputSelection': {'*': {'*': ['evm.bytecode', 'evm.deployedBytecode', 'abi', 'storageLayout'],
                                                   '': ['ast']}}},
        }
        entity = ContractEntityForCompile({
            'address': '0x' + '7' * 40, 'contract_name': 'Example', 'compiler_version': version,
            'sources': {'Example.sol': source}, 'compiler_settings': standard['settings'],
        })
        with tempfile.TemporaryDirectory(prefix='attackpilot-source-preservation-') as temp, \
                patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', temp):
            input_path = Path(temp) / 'input.json'
            input_path.write_text(json.dumps(standard), encoding='utf-8')
            expected = await Solc(native).compile_json(str(input_path), 'Example')
            with patch.object(dao, '_resolve_solc_path', return_value=''):
                actual = await dao.get_compile_item_from_entity(entity)
        self.assertTrue(expected.bytecode, expected.errors)
        self.assertTrue(actual.bytecode, actual.errors)
        self.assertEqual(actual.bytecode, expected.bytecode)
        self.assertEqual(actual.creation_bytecode, expected.creation_bytecode)
        self.assertEqual(actual.ast, expected.ast)
        contract = next(node for node in actual.ast['Example.sol']['nodes']
                        if node.get('nodeType') == 'ContractDefinition')
        compiled_function = next(node for node in contract['nodes']
                                 if node.get('nodeType') == 'FunctionDefinition')
        start, length, _ = map(int, compiled_function['src'].split(':'))
        self.assertEqual(source.encode('utf-8')[start:start + length].decode('utf-8'), function)
        compiled_literal = compiled_function['body']['statements'][0]['expression']
        self.assertEqual(compiled_literal['hexValue'], literal.encode('utf-8').hex())

    async def test_js_flattened_source_preserves_crlf_and_literal_bytes(self):
        if not (settings.PACKAGE_ROOT / 'node_modules/solcv0.8.9').exists():
            self.skipTest('The Solidity 0.8.9 Node compiler is required')
        literal = 'A\tB\u00a0C\u3000D\u200bE'
        source = ('pragma solidity 0.8.9;\r\ncontract Example {\r\n'
                  '\tfunction text() external pure returns(string memory) { return unicode"'
                  + literal + '"; }\r\n}\r\n')
        standard = {
            'language': 'Solidity',
            'sources': {'this_is_a_tmp_filename.sol': {'content': source}},
            'settings': {'optimizer': {'enabled': False, 'runs': 200},
                         'outputSelection': {'*': {'*': ['evm.bytecode', 'evm.deployedBytecode', 'abi', 'storageLayout'],
                                                   '': ['ast']}}},
        }
        with tempfile.TemporaryDirectory(prefix='attackpilot-flat-source-preservation-') as temp, \
                patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', temp):
            script = Path(temp) / 'compiler.js'
            script.write_text(settings.SOLCJS_CODE % ('v0.8.9', json.dumps(standard)), encoding='utf-8')
            expected = await SolcJS(settings.NODE_PATH).compile_json(str(script), 'Example')
            actual = await ContractDao(AsyncMock())._get_compile_item_by_solcjs('0x' + '7' * 40, {
                'CompilerVersion': 'v0.8.9+commit.e5eed63a', 'ContractName': 'Example',
                'SourceCode': source, 'OptimizationUsed': '0', 'Runs': '200',
            })
        self.assertTrue(expected.bytecode, expected.errors)
        self.assertTrue(actual.bytecode, actual.errors)
        self.assertEqual(actual.bytecode, expected.bytecode)
        self.assertEqual(actual.ast[''], expected.ast['this_is_a_tmp_filename.sol'])

class SourceFunctionMappingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dao = ContractDao(AsyncMock())
        if not self.dao._resolve_solc_path('v0.8.20+commit.a1b79de6'):
            self.skipTest('The Solidity 0.8.20 native compiler is required')
        self.temp = tempfile.TemporaryDirectory(prefix='attackpilot-source-map-')
        self.addCleanup(self.temp.cleanup)
        self.temp_patch = patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', self.temp.name)
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)

    def entity(self, sources):
        return ContractEntityForCompile({
            'address': '0x' + '7' * 40, 'contract_name': 'Token',
            'compiler_version': 'v0.8.20+commit.a1b79de6', 'sources': sources,
            'compiler_settings': {'optimizer': {'enabled': True, 'runs': 200}, 'evmVersion': 'paris'},
        })

    @staticmethod
    def selector(signature):
        from eth_utils import keccak
        return '0x' + keccak(text=signature)[:4].hex()

    async def test_ten_files_inheritance_overrides_and_overloads_use_ast_identity(self):
        sources = {'Base.sol': 'pragma solidity 0.8.20; abstract contract Base { '
                   'function move(uint256 x) public virtual returns(uint256) { return x; } '
                   'function move(address x) public pure returns(address) { return x; } }',
                   'unrelated-name.sol': 'pragma solidity 0.8.20; import "Base.sol"; contract Token is Base { '
                   'function move(uint256 x) public override returns(uint256) { return x + 1; } }'}
        sources.update({f'Library{i}.sol': f'pragma solidity 0.8.20; contract Library{i} {{}}' for i in range(8)})
        entity = self.entity(sources)
        for signature, filename, owner in [('move(uint256)', 'unrelated-name.sol', 'Token'),
                                            ('move(address)', 'Base.sol', 'Base')]:
            result = await self.dao.resolve_source_function(entity, self.selector(signature) + '00' * 32)
            self.assertEqual(result['filename'], filename)
            self.assertEqual(result['declaring_contract'], owner)
            self.assertEqual(result['function_name'], 'move')
            self.assertEqual(result['selector'], self.selector(signature))
            self.assertEqual(result['source_mapping'], 'compiled_ast_function_selector')
            self.assertEqual(len(result['compiled'].ast), 10)
            self.assertTrue(result['compiled'].is_success())

    async def test_utf8_offsets_extract_actual_function_bytes(self):
        function = 'function read() external pure returns(uint256) { return 7; }'
        source = '// 中文字节不能按字符计数\npragma solidity 0.8.20;\ncontract Token { ' + function + ' }'
        result = await self.dao.resolve_source_function(self.entity({'Actual.sol': source}), self.selector('read()'))
        self.assertEqual(result['code_start'], source.encode().index(function.encode()))
        self.assertEqual(result['code_length'], len(function.encode()))
        self.assertEqual(result['line_number'], 3)
        self.assertEqual(source.encode()[result['code_start']:result['code_start'] + result['code_length']].decode(), function)

    async def test_duplicate_target_contract_names_are_rejected(self):
        source = 'pragma solidity 0.8.20; contract Token { function read() external pure returns(uint) {return 1;} }'
        with self.assertRaisesRegex(ValueError, 'source_function_ambiguous_contract'):
            await self.dao.resolve_source_function(self.entity({'A.sol': source, 'B.sol': source}), self.selector('read()'))

    async def test_unknown_empty_and_getter_selectors_are_rejected(self):
        source = 'pragma solidity 0.8.20; abstract contract Base { function amount() external virtual returns(uint); } '
        source += 'contract Token is Base { uint public override amount; function read() external pure returns(uint) {return 1;} }'
        entity = self.entity({'Actual.sol': source})
        for calldata, reason in [('0x', 'selector_unavailable'), ('0x123', 'selector_unavailable'),
                                  ('0x01020304', 'selector_unmapped'), (self.selector('amount()'), 'getter_unsupported')]:
            with self.subTest(calldata=calldata), self.assertRaisesRegex(ValueError, reason):
                await self.dao.resolve_source_function(entity, calldata)

    async def test_selector_collision_compilation_is_rejected(self):
        source = 'pragma solidity 0.8.20; contract Token { function burn(uint256) external {} '
        source += 'function collate_propagate_storage(bytes16) external {} }'
        with self.assertRaisesRegex(ValueError, 'source_function_compilation_failed'):
            await self.dao.resolve_source_function(self.entity({'Actual.sol': source}), self.selector('burn(uint256)'))

    async def test_ambiguous_or_corrupt_compiler_locations_are_rejected(self):
        source = 'pragma solidity 0.8.20; contract Token { function read() external pure returns(uint) {return 1;} }'
        entity = self.entity({'Actual.sol': source})
        result = await self.dao.resolve_source_function(entity, self.selector('read()'))
        for mode, reason in [('duplicate', 'ambiguous_selector'), ('outside', 'location_unavailable')]:
            compiled = copy.deepcopy(result['compiled'])
            target = next(node for node in compiled.ast['Actual.sol']['nodes'] if node.get('nodeType') == 'ContractDefinition')
            function = next(node for node in target['nodes'] if node.get('nodeType') == 'FunctionDefinition')
            if mode == 'duplicate':
                target['nodes'].append(copy.deepcopy(function))
            else:
                function['src'] = '999999:42:0'
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, reason):
                self.dao._resolve_compiled_source_function(entity, self.selector('read()'), compiled)


class PatchGuardAttributionCompilerTest(unittest.IsolatedAsyncioTestCase):
    address = '0x' + '7' * 40
    original_source = (
        '// 中文注释使 AST 范围必须使用 UTF-8 字节偏移\n'
        'pragma solidity 0.8.23; contract Example { '
        'function existing(uint x) external pure { require(x > 1, "denied"); } '
        'function added(uint x) external pure { } }'
    )

    async def compile_attribution(self, reason, *, optimized, new_function='added'):
        from app.attackpilot.utils.patch import build_applied_patch_record
        from app.attackpilot.utils.patch_attribution import build_patch_attribution

        dao = ContractDao(AsyncMock())
        if not dao._resolve_solc_path('v0.8.23+commit.f704f362'):
            self.skipTest('The Solidity 0.8.23 native compiler is required')
        source = self.original_source.replace(
            f'function {new_function}(uint x) external pure {{ }}',
            f'function {new_function}(uint x) external pure {{ require(x > 2, ' + json.dumps(reason) + '); }',
        )

        def entity(contents):
            return ContractEntityForCompile({
                'address': self.address, 'contract_name': 'Example',
                'compiler_version': 'v0.8.23+commit.f704f362',
                'sources': {'Example.sol': contents},
                'compiler_settings': {
                    'optimizer': {'enabled': optimized, 'runs': 200}, 'evmVersion': 'paris',
                },
            })

        original, patched = entity(self.original_source), entity(source)
        with tempfile.TemporaryDirectory(prefix='attackpilot-guard-attribution-') as temp, \
                patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', temp):
            compiled = await dao.get_compile_item_from_entity(patched)
        self.assertTrue(compiled.bytecode, compiled.errors)
        patches = build_applied_patch_record(
            {f'{self.address}::Example.sol': self.original_source},
            {f'{self.address}::Example.sol': source},
        )
        evidence = build_patch_attribution(
            {self.address: original}, {self.address: patched}, {self.address: compiled},
            {self.address: compiled.bytecode}, patches,
        )
        return evidence, compiled, source

    async def test_old_and_new_guards_with_the_same_error_remain_ambiguous(self):
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                evidence, compiled, _ = await self.compile_attribution('denied', optimized=optimized)
                self.assertTrue(any(item.opcode == 'REVERT' for item in compiled.source_mapping))
                contract = evidence['contracts'][self.address]
                self.assertEqual(evidence['status'], 'unavailable')
                self.assertEqual(contract['guards'], [])
                self.assertEqual(contract['unresolved_guard_counts']['unchanged_guard'], 1)
                self.assertEqual(contract['unresolved_guard_counts']['ambiguous_guard_reason'], 1)

    async def test_unique_new_guard_binds_to_its_actual_runtime_revert_and_utf8_range(self):
        evidence, compiled, source = await self.compile_attribution('new denied', optimized=False)
        self.assertEqual(evidence['status'], 'available', evidence)
        guards = evidence['contracts'][self.address]['guards']
        self.assertEqual(len(guards), 1)
        guard = guards[0]
        self.assertEqual(guard['reason'], 'new denied')
        raw = source.encode('utf-8')
        self.assertEqual(raw[guard['start']:guard['start'] + guard['length']],
                         b'require(x > 2, "new denied")')
        runtime = bytes.fromhex(compiled.bytecode.removeprefix('0x'))
        self.assertTrue(guard['revert_pcs'])
        for pc in guard['revert_pcs']:
            self.assertEqual(runtime[pc], 0xfd)
            mapped = [item for item in compiled.source_mapping if item.pc == pc]
            self.assertEqual(len(mapped), 1)
            self.assertEqual(mapped[0].opcode, 'REVERT')
            self.assertEqual(mapped[0].filename, 'Example.sol')
            self.assertGreaterEqual(mapped[0].begin, guard['start'])
            self.assertLessEqual(mapped[0].begin + mapped[0].offset,
                                 guard['start'] + guard['length'])

    async def test_optimizer_shared_revert_does_not_inherit_a_new_guards_attribution(self):
        evidence, compiled, _ = await self.compile_attribution('new denied', optimized=True)
        # This pinned compiler shares the final REVERT instruction with the old
        # guard. Its source map cannot prove which guard selected that block.
        self.assertTrue(any(item.opcode == 'REVERT' for item in compiled.source_mapping))
        contract = evidence['contracts'][self.address]
        self.assertEqual(evidence['status'], 'unavailable')
        self.assertEqual(contract['guards'], [])
        self.assertEqual(contract['unresolved_guard_counts']['guard_revert_pc_unavailable'], 1)

    async def test_old_dynamic_error_cannot_borrow_the_new_guards_shared_revert(self):
        self.original_source = (
            'pragma solidity 0.8.23; contract Example { '
            'function added(uint x) external pure { '
            'string memory why = "denied"; require(x > 1, why); } '
            'function existing(uint x) external pure { } }'
        )
        evidence, compiled, source = await self.compile_attribution(
            'denied', optimized=True, new_function='existing',
        )
        # The optimizer assigns the shared REVERT to the new literal guard,
        # although the unchanged dynamic-message guard can also reach it.
        self.assertTrue(any(
            item.opcode == 'REVERT'
            and source.encode()[item.begin:item.begin + item.offset] == b'require(x > 2, "denied")'
            for item in compiled.source_mapping
        ))
        self.assertEqual(evidence['status'], 'unavailable', evidence)
        self.assertFalse(any(contract['guards'] for contract in evidence['contracts'].values()))

    async def test_assembly_revert_cannot_supply_unattributed_error_data(self):
        self.original_source = (
            'pragma solidity 0.8.23; contract Example { '
            'function existing(bytes memory reason) external pure { '
            'assembly { revert(add(reason, 32), mload(reason)) } } '
            'function added(uint x) external pure { } }'
        )
        evidence, _, _ = await self.compile_attribution('new denied', optimized=False)
        self.assertEqual(evidence['status'], 'unavailable', evidence)
        self.assertFalse(any(contract['guards'] for contract in evidence['contracts'].values()))


class RevertPropagationCompilerTest(unittest.IsolatedAsyncioTestCase):
    async def compile_parent(self, assembly, *, optimized=True):
        dao = ContractDao(AsyncMock())
        if not dao._resolve_solc_path('v0.8.23+commit.f704f362'):
            self.skipTest('The Solidity 0.8.23 native compiler is required')
        source = ('pragma solidity 0.8.23; contract Example { '
                  'fallback() external payable { assembly { ' + assembly + ' } } }')
        entity = ContractEntityForCompile({
            'address': '0x' + '1' * 40, 'contract_name': 'Example',
            'compiler_version': 'v0.8.23+commit.f704f362', 'sources': {'Example.sol': source},
            'compiler_settings': {'optimizer': {'enabled': optimized, 'runs': 200}, 'evmVersion': 'paris'},
        })
        with tempfile.TemporaryDirectory(prefix='attackpilot-revert-proof-') as temp, \
                patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', temp):
            compiled = await dao.get_compile_item_from_entity(entity)
        self.assertTrue(compiled.bytecode, compiled.errors)
        calls = [item for item in compiled.source_mapping if item.opcode == 'DELEGATECALL']
        self.assertEqual(len(calls), 1)
        return compiled.bytecode, calls[0].pc

    @staticmethod
    def error_bytes(reason):
        value = reason.encode()
        return (bytes.fromhex('08c379a0') + (32).to_bytes(32, 'big')
                + len(value).to_bytes(32, 'big')
                + value.ljust(((len(value) + 31) // 32) * 32, b'\0'))

    @staticmethod
    def write_output(data):
        return ' '.join(f'mstore({offset}, 0x{data[offset:offset + 32].ljust(32, bytes([0])).hex()})'
                        for offset in range(0, len(data), 32))

    async def test_real_assembly_forwarder_proves_both_call_result_branches(self):
        from app.attackpilot.utils.revert_propagation import prove_revert_propagation

        assembly = ('let ok := delegatecall(gas(), 1, 0, 0, 0, 0) '
                    'returndatacopy(0, 0, returndatasize()) '
                    'switch ok case 0 { revert(0, returndatasize()) } '
                    'default { return(0, returndatasize()) }')
        output = '0x' + self.error_bytes('child guard').hex()
        for optimized in (False, True):
            with self.subTest(optimized=optimized):
                runtime, pc = await self.compile_parent(assembly, optimized=optimized)
                proof = prove_revert_propagation(runtime, pc, 'DELEGATECALL', output, output)
                self.assertIsNotNone(proof)
                self.assertEqual(proof['method'], 'evm_call_failure_branch')
                self.assertEqual(proof['proof_version'], 1)
                self.assertTrue(proof['branch_pcs'])
                self.assertEqual(bytes.fromhex(runtime)[proof['failure_revert_pc']], 0xfd)
                self.assertEqual(bytes.fromhex(runtime)[proof['success_exit_pc']], 0xf3)
                self.assertEqual(proof['runtime_sha256'], hashlib.sha256(bytes.fromhex(runtime)).hexdigest())

    async def test_constant_memory_failure_check_accepts_arbitrary_wrapper_text(self):
        from app.attackpilot.utils.revert_propagation import prove_revert_propagation

        for reason in ('call failed', 'kj', 'not a known wrapper'):
            with self.subTest(reason=reason):
                output = self.error_bytes(reason)
                assembly = ('let ok := delegatecall(gas(), 1, 0, 0, 0, 0) '
                            'if iszero(ok) { ' + self.write_output(output)
                            + f' revert(0, {len(output)}) }} return(0, 0)')
                runtime, pc = await self.compile_parent(assembly, optimized=False)
                proof = prove_revert_propagation(runtime, pc, 'DELEGATECALL', '0x1234', '0x' + output.hex())
                self.assertIsNotNone(proof)

    async def test_independent_generic_revert_unknown_state_and_wrong_evidence_stay_unproved(self):
        from app.attackpilot.utils.revert_propagation import prove_revert_propagation

        output = self.error_bytes('call failed')
        write = self.write_output(output)
        bodies = {
            'ignored_result': 'pop(ok) ' + write + f' revert(0, {len(output)})',
            'storage_condition': 'if iszero(ok) { if iszero(sload(0)) { ' + write
                                 + f' revert(0, {len(output)}) }} }} return(0, 0)',
        }
        for name, body in bodies.items():
            with self.subTest(case=name):
                runtime, pc = await self.compile_parent(
                    'let ok := delegatecall(gas(), 1, 0, 0, 0, 0) ' + body, optimized=False,
                )
                self.assertIsNone(prove_revert_propagation(
                    runtime, pc, 'DELEGATECALL', '0x1234', '0x' + output.hex(),
                ))
        runtime, pc = await self.compile_parent(
            'let ok := delegatecall(gas(), 1, 0, 0, 0, 0) '
            'returndatacopy(0, 0, returndatasize()) '
            'switch ok case 0 { revert(0, returndatasize()) } default { return(0, returndatasize()) }',
        )
        for call_pc, kind, child, parent in (
            (pc + 1, 'DELEGATECALL', '0x1234', '0x1234'),
            (pc, 'CALL', '0x1234', '0x1234'),
            (pc, 'CREATE2', '0x1234', '0x1234'),
            (pc, 'DELEGATECALL', '0x1234', '0xabcd'),
            (pc, 'DELEGATECALL', None, '0x1234'),
        ):
            with self.subTest(call_pc=call_pc, kind=kind, child=child, parent=parent):
                self.assertIsNone(prove_revert_propagation(runtime, call_pc, kind, child, parent))

    async def test_unknown_success_returndata_bounds_do_not_count_as_a_proof(self):
        from app.attackpilot.utils.revert_propagation import prove_revert_propagation

        output = self.error_bytes('call failed')
        assembly = ('let ok := delegatecall(gas(), 1, 0, 0, 0, 0) '
                    'if iszero(ok) { ' + self.write_output(output)
                    + f' revert(0, {len(output)}) }} '
                    'returndatacopy(0, 1000000, 1) return(0, 0)')
        runtime, pc = await self.compile_parent(assembly, optimized=False)
        self.assertIsNone(prove_revert_propagation(
            runtime, pc, 'DELEGATECALL', '0x1234', '0x' + output.hex(),
        ))


class RuntimeIntegrityTest(unittest.IsolatedAsyncioTestCase):
    address = '0x' + '1' * 40
    transaction_hash = '0x' + 'a' * 64

    def item(self, bytecode='6000600055', *, references=None, ast=None):
        return ContractCompileItem(self.address, bytecode, ast or {}, [],
                                   immutable_references=references,
                                   storage_layout={'storage': [], 'types': None})

    def immutable_item(self):
        ast = {'Example.sol': {'nodes': [
            {'nodeType': 'ContractDefinition', 'name': name, 'nodes': [
                {'nodeType': 'VariableDeclaration', 'id': ident, 'name': 'owner',
                 'mutability': 'immutable', 'typeDescriptions': {'typeString': 'address'}}]}
            for ident, name in [(1, 'A'), (2, 'B')]]}}
        return self.item('00' * 64, ast=ast, references={
            '1': [{'start': 0, 'length': 32}], '2': [{'start': 32, 'length': 32}],
        })

    def test_same_name_immutables_keep_their_qualified_historical_values(self):
        item = self.immutable_item()
        historical = '0x' + '11' * 32 + '22' * 32
        success, code, diagnostic = BytecodeTransplanter.transplant(item, historical, item)
        self.assertTrue(success, diagnostic)
        self.assertEqual(code, historical)

    def test_original_instruction_mismatch_or_missing_code_never_transplants(self):
        item = self.item()
        for runtime in ('0x6001600055', '0x', '', '0xzz', '0x60 00 600055'):
            with self.subTest(runtime=runtime):
                ok, code, diagnostic = BytecodeTransplanter.transplant(item, runtime, item)
                self.assertFalse(ok)
                self.assertEqual(code, '')
                self.assertIn('original_runtime_mismatch', diagnostic)

    def test_metadata_only_hash_difference_is_allowed_but_compiler_or_code_changes_are_not(self):
        def bytecode(hash_byte, version='000817', prefix='6000600055'):
            metadata = 'a2646970667358221220' + hash_byte * 32 + '64736f6c6343' + version
            return prefix + metadata + (len(metadata) // 2).to_bytes(2, 'big').hex()
        item = self.item(bytecode('11'))
        self.assertTrue(BytecodeTransplanter.transplant(item, bytecode('22'), item)[0])
        for code in (bytecode('22', version='000816'), bytecode('22', prefix='6001600055'),
                     bytecode('22')[:-4] + 'ffff'):
            self.assertFalse(BytecodeTransplanter.transplant(item, code, item)[0])

    def test_missing_immutable_values_or_invalid_references_are_rejected(self):
        original = self.immutable_item()
        historical = '11' * 32 + '22' * 32
        variants = []
        changed = copy.deepcopy(original); changed.immutable_references['1'][0]['start'] = 100; variants.append(changed)
        changed = copy.deepcopy(original); changed.immutable_references['1'][0]['start'] = -1; variants.append(changed)
        changed = copy.deepcopy(original); changed.immutable_references['1'][0]['length'] = 16; variants.append(changed)
        changed = copy.deepcopy(original); changed.immutable_references['2'][0]['start'] = 0; variants.append(changed)
        changed = copy.deepcopy(original); changed.immutable_references['3'] = changed.immutable_references.pop('2'); variants.append(changed)
        changed = copy.deepcopy(original); del changed.immutable_references['2']; variants.append(changed)
        for changed in variants:
            with self.subTest(references=changed.immutable_references):
                ok, code, diagnostic = BytecodeTransplanter.transplant(original, historical, changed)
                self.assertFalse(ok)
                self.assertEqual(code, '')
                self.assertIn('immutable_layout_mismatch', diagnostic)

    def test_all_historical_occurrences_of_immutable_must_agree(self):
        item = self.immutable_item()
        del item.immutable_references['2']
        item.immutable_references['1'].append({'start': 32, 'length': 32})
        with self.assertRaisesRegex(RuntimeIntegrityError, 'different historical values'):
            BytecodeTransplanter.validate_original(item, '11' * 32 + '22' * 32)

    def test_storage_layout_missing_or_different_is_not_accepted(self):
        original = self.item()
        changed = self.item()
        changed.storage_layout = None
        self.assertIn('storage_layout_unavailable', BytecodeTransplanter.transplant(original, original.bytecode, changed)[2])
        changed.ast = {'Example.sol': {'nodes': [{'nodeType': 'ContractDefinition', 'name': 'Example', 'nodes': [{'nodeType': 'VariableDeclaration', 'id': 1, 'name': 'owner', 'stateVariable': True, 'typeDescriptions': {'typeString': 'address'}}]}]}}
        changed.storage_layout = {'storage': [{'astId': 1, 'contract': 'Example.sol:Example', 'label': 'owner',
                                             'slot': '0', 'offset': 0, 'type': 't_address'}],
                                  'types': {'t_address': {'encoding': 'inplace', 'label': 'address', 'numberOfBytes': '20'}}}
        self.assertIn('storage_layout_changed', BytecodeTransplanter.transplant(original, original.bytecode, changed)[2])

    async def compile(self, source, *, version='v0.8.23+commit.f704f362', name='Example'):
        entity = ContractEntityForCompile.from_dict({
            'address': self.address, 'contract_name': name, 'compiler_version': version,
            'sources': {'Example.sol': source}, 'optimizations_used': True, 'optimization_runs': 200,
        })
        with tempfile.TemporaryDirectory(prefix='attackpilot-integrity-') as temp, patch('app.attackpilot.utils.tmpfile.TMP_FILE_DIR', temp):
            compiled = await ContractDao(AsyncMock()).get_compile_item_from_entity(entity)
        self.assertTrue(compiled.bytecode, compiled.errors)
        return compiled

    async def test_real_compiler_preserves_inherited_immutables_after_ast_ids_move(self):
        source = ('pragma solidity 0.8.23; '
                  'contract A { uint private immutable value; constructor(){value=1;} function a() public view returns(uint){return value;} } '
                  'contract B { uint private immutable value; constructor(){value=2;} function b() public view returns(uint){return value;} } '
                  'contract Example is A, B {}')
        original = await self.compile(source)
        changed = await self.compile(source.replace('return value;', 'require(value > 0, "guard"); return value;'))
        historical = bytearray.fromhex(original.bytecode)
        expected = {}
        for key, references in BytecodeTransplanter._slots(original, len(historical)).items():
            value = (11 if key[1] == 'A' else 22).to_bytes(32, 'big')
            expected[key] = value
            for start, length in references:
                historical[start:start + length] = value
        ok, code, diagnostic = BytecodeTransplanter.transplant(original, historical.hex(), changed)
        self.assertTrue(ok, diagnostic)
        patched = bytes.fromhex(code[2:])
        for key, references in BytecodeTransplanter._slots(changed, len(patched)).items():
            for start, length in references:
                self.assertEqual(patched[start:start + length], expected[key])
        self.assertEqual(ContractCompileItem.from_dict(original.to_dict()).storage_layout, original.storage_layout)

    async def test_real_compiler_rejects_storage_reordering_type_change_and_constructor_change(self):
        source = ('pragma solidity 0.8.23; contract Example { uint128 first; uint128 second; '
                  'constructor(){ first = 1; } function value() public view returns(uint){return first;} }')
        original = await self.compile(source)
        for replacement, reason in [
                (source.replace('uint128 first; uint128 second;', 'uint128 second; uint128 first;'), 'storage_layout_changed'),
                (source.replace('uint128 first;', 'uint64 first;'), 'storage_layout_changed'),
                (source.replace('first = 1', 'first = 2'), 'constructor_or_immutable_changed')]:
            with self.subTest(reason=reason):
                changed = await self.compile(replacement)
                ok, _, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
                self.assertFalse(ok)
                self.assertIn(reason, diagnostic)
        changed = await self.compile(source.replace('return first;', 'require(first > 0, "guard"); return first;'))
        self.assertTrue(BytecodeTransplanter.transplant(original, original.bytecode, changed)[0])

    async def test_inline_state_initializer_change_requires_constructor_execution(self):
        source = 'pragma solidity 0.8.23; contract Example { uint public value = 1; }'
        original = await self.compile(source)
        changed = await self.compile(source.replace('value = 1', 'value = 2'))
        ok, _, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
        self.assertFalse(ok)
        self.assertIn('constructor_or_immutable_changed', diagnostic)

    async def test_runtime_guards_preserve_constructor_locals_when_ast_ids_move(self):
        runtime = 'function f() public {value=1;}'
        constructor = 'constructor(){uint x=1;value=x;}'
        cases = [
            ('runtime_before_constructor',
             f'contract Example {{uint value; {runtime} {constructor}}}', True),
            ('constructor_before_runtime',
             f'contract Example {{uint value; {constructor} {runtime}}}', False),
            ('tuple_local_declarations',
             f'contract Example {{uint value; {runtime} '
             'constructor(){(uint x,,uint y)=(uint(1),uint(2),uint(3));value=x+y;}}', True),
            ('inherited_constructor',
             f'contract Base {{uint value; {runtime} {constructor}}} contract Example is Base {{}}', True),
        ]

        def constructor_assignments(value):
            if isinstance(value, dict):
                own = [value['assignments']] if value.get('nodeType') == 'VariableDeclarationStatement' else []
                return own + [item for child in value.values() for item in constructor_assignments(child)]
            if isinstance(value, list):
                return [item for child in value for item in constructor_assignments(child)]
            return []

        for label, body, ids_move in cases:
            with self.subTest(case=label):
                source = 'pragma solidity 0.8.23; ' + body
                original = await self.compile(source)
                changed = await self.compile(source.replace(runtime, runtime.replace('value=1;', 'require(value>0);value=1;')))
                if ids_move:
                    self.assertNotEqual(constructor_assignments(original.ast), constructor_assignments(changed.ast))
                self.assertEqual(BytecodeTransplanter._initialization_signature(original.ast),
                                 BytecodeTransplanter._initialization_signature(changed.ast))
                ok, code, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
                self.assertTrue(ok, diagnostic)
                self.assertEqual(code, '0x' + changed.bytecode)

    async def test_constructor_local_and_initialization_changes_remain_rejected_after_ast_ids_move(self):
        source = ('pragma solidity 0.8.23; contract Example {uint public value = 1; '
                  'uint public immutable initial = 3; function f() public {value=1;} '
                  'constructor(){uint x=1;value=x;} }')
        original = await self.compile(source)
        guarded = source.replace('function f() public {value=1;}',
                                 'function f() public {require(value>0);value=1;}')
        for before, after in [('uint x=1', 'uint x=2'),
                              ('uint public value = 1', 'uint public value = 2'),
                              ('immutable initial = 3', 'immutable initial = 4'),
                              ('uint public immutable initial', 'uint128 public immutable initial')]:
            with self.subTest(change=before):
                changed = await self.compile(guarded.replace(before, after))
                ok, code, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
                self.assertFalse(ok)
                self.assertEqual(code, '')
                self.assertIn('constructor_or_immutable_changed', diagnostic)

    async def test_base_constructor_identifier_locations_can_move_but_calls_cannot_change(self):
        source = ('pragma solidity 0.8.23; '
                  'contract Base {uint base; constructor(uint n){base=n;}} '
                  'contract Other {uint other; constructor(uint n){other=n;}} '
                  'contract Example is Base, Other {function f() public {base=1;} '
                  'constructor() Base(1) Other(2) {}}')
        original = await self.compile(source)
        guarded = source.replace('function f() public {base=1;}',
                                 'function f() public {require(base>0);base=1;}')
        changed = await self.compile(guarded)

        def base_call_locations(item):
            target = next(node for node in item.ast['Example.sol']['nodes']
                          if node.get('nodeType') == 'ContractDefinition' and node.get('name') == 'Example')
            constructor = next(node for node in target['nodes']
                               if node.get('nodeType') == 'FunctionDefinition' and node.get('kind') == 'constructor')
            return [modifier['modifierName']['nameLocations'] for modifier in constructor['modifiers']]

        self.assertNotEqual(base_call_locations(original), base_call_locations(changed))
        ok, code, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
        self.assertTrue(ok, diagnostic)
        self.assertEqual(code, '0x' + changed.bytecode)
        for before, after in [('Base(1)', 'Base(3)'),
                              ('Base(1) Other(2)', 'Other(1) Base(2)')]:
            with self.subTest(change=after):
                changed = await self.compile(guarded.replace(before, after))
                ok, code, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
                self.assertFalse(ok)
                self.assertEqual(code, '')
                self.assertIn('constructor_or_immutable_changed', diagnostic)

    def test_only_contracts_with_actual_applied_source_changes_are_overridden(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        other = '0x' + '2' * 40
        contracts = {address: ContractEntityForCompile.from_dict({
            'address': address, 'sources': {'Example.sol': 'contract Example {}'},
            'full_file_map': {'0': {'path': 'Example.sol', 'source': 'contract Example {}'}},
        }) for address in [self.address, other]}
        updated = FixAgent.__new__(FixAgent)._update_contracts_with_patch(contracts, {
            f'{self.address}::Example.sol': 'contract Example {function guard() public {}}',
            f'{other}::Example.sol': 'contract Example {}',
        })
        self.assertEqual(set(updated), {self.address})
        self.assertEqual(contracts[self.address].sources['Example.sol'], 'contract Example {}')
        emptied = FixAgent.__new__(FixAgent)._update_contracts_with_patch(contracts, {f'{self.address}::Example.sol': ''})
        self.assertEqual(emptied[self.address].sources['Example.sol'], '')

    async def test_real_compiler_rejects_reordering_same_name_private_storage_in_base_contracts(self):
        source = ('pragma solidity 0.8.23; '
                  'contract A { uint private value; function a() public view returns(uint){return value;} } '
                  'contract B { uint private value; function b() public view returns(uint){return value;} } '
                  'contract Example is A, B {}')
        original = await self.compile(source)
        changed = await self.compile(source.replace('Example is A, B', 'Example is B, A'))
        ok, _, diagnostic = BytecodeTransplanter.transplant(original, original.bytecode, changed)
        self.assertFalse(ok)
        self.assertIn('storage_layout_changed', diagnostic)

    async def test_legacy_compiler_missing_storage_layout_is_explicitly_unavailable(self):
        original = await self.compile('pragma solidity 0.4.24; contract Example { function value() public pure returns(uint){return 1;} }',
                                      version='v0.4.24+commit.e67f0147')
        self.assertIsNone(original.storage_layout)
        self.assertIn('storage_layout_unavailable', BytecodeTransplanter.transplant(original, original.bytecode, original)[2])

    async def test_source_download_failure_is_distinct_from_unverified_or_unknown_source(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        for lookup, code, retryable in (
            ({'status': 'failed', 'retryable': True}, 'source_fetch_failed', True),
            ({'status': 'unverified', 'retryable': False}, 'source_not_verified', False),
            ({}, 'missing_source', None),
        ):
            with self.subTest(code=code):
                agent = FixAgent.__new__(FixAgent)
                agent._check_cancelled = Mock()
                agent.session_id = 'offline-source-preconditions'
                agent.mcp_client = Mock()
                agent.mcp_client.call_tool = AsyncMock(return_value={
                    'address': self.address, 'contract_info': [], 'source_lookup': lookup,
                })
                agent._load_compile_result = AsyncMock(side_effect=AssertionError('No source to compile'))
                agent.query = AsyncMock(side_effect=AssertionError('No source to patch'))
                outcome = await agent.handle({'fix_report': {'faulty_functions': [{
                    'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
                }]}})
                self.assertFalse(outcome[0])
                self.assertEqual(agent.verification['reason_code'], code)
                self.assertEqual(agent.verification.get('retryable'), retryable)
                self.assertFalse(agent.verification['replay_attempted'])
                agent._load_compile_result.assert_not_awaited()
                agent.query.assert_not_awaited()

    async def test_original_runtime_mismatch_stops_before_generation_or_remote_replay(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        agent = FixAgent.__new__(FixAgent)
        agent._check_cancelled = Mock()
        agent.session_id = 'offline-integrity'
        agent.processed_data = {'transaction_hash_list': [self.transaction_hash],
                                'attack_transactions': [self.transaction_hash],
                                'transaction_to_detail': {self.transaction_hash: {'block_number': 1}}}
        agent.mcp_client = Mock()
        agent.mcp_client.call_tool = AsyncMock(return_value={
            'address': self.address, 'file_index': 0, 'contract_name': 'Example',
            'contract_info': [{'id': 0, 'path': 'Example.sol', 'source': 'contract Example {}'}],
        })
        agent._load_compile_result = AsyncMock(return_value={self.address: self.item()})
        agent._load_runtime_bytecode = AsyncMock(return_value={self.address: '6001600055'})
        agent.query = AsyncMock(side_effect=AssertionError('Generation must not run'))
        agent.prepare_bundle_data = AsyncMock(side_effect=AssertionError('Replay must not run'))
        outcome = await agent.handle({'fix_report': {'faulty_functions': [{
            'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
        }]}})
        self.assertFalse(outcome[0])
        self.assertEqual(agent.verification['reason_code'], 'original_runtime_mismatch')
        self.assertEqual(agent.verification['status'], 'blocked')
        self.assertFalse(agent.verification['replay_attempted'])
        agent.query.assert_not_awaited()
        agent.prepare_bundle_data.assert_not_awaited()

    async def test_changed_storage_with_creation_code_cannot_fall_back_to_deployment(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        agent = FixAgent.__new__(FixAgent)
        agent._check_cancelled = Mock()
        agent.session_id = 'offline-integrity'
        agent.metrics_collector = None
        agent.processed_data = {'transaction_hash_list': [self.transaction_hash],
                                'attack_transactions': [self.transaction_hash],
                                'transaction_to_detail': {self.transaction_hash: {'block_number': 1}}}
        agent.mcp_client = Mock()
        agent.mcp_client.call_tool = AsyncMock(return_value={
            'address': self.address, 'file_index': 0, 'contract_name': 'Example',
            'contract_info': [{'id': 0, 'path': 'Example.sol', 'source': 'contract Example {}'}],
        })
        original = self.item()
        changed = self.item()
        changed.storage_layout = None
        changed.creation_bytecode = '6000600055'
        agent._load_compile_result = AsyncMock(return_value={self.address: original})
        agent._load_runtime_bytecode = AsyncMock(return_value={self.address: original.bytecode})
        agent.query = AsyncMock(return_value=f'# File: {self.address}::Example.sol\n<<<<<<< SEARCH\ncontract Example {{}}\n=======\ncontract Example {{uint added;}}\n>>>>>>> REPLACE')
        agent.compile_patched_codes = AsyncMock(return_value=(True, {self.address: changed}))
        agent._deploy_contracts = AsyncMock(side_effect=AssertionError('Deployment must not run'))
        agent.prepare_bundle_data = AsyncMock(side_effect=AssertionError('Replay must not run'))
        outcome = await agent.handle({'fix_report': {'faulty_functions': [{
            'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
        }]}})
        self.assertFalse(outcome[0])
        self.assertEqual(agent.verification['reason_code'], 'storage_layout_unavailable')
        self.assertEqual(agent.verification['status'], 'blocked')
        self.assertFalse(agent.verification['replay_attempted'])
        agent._deploy_contracts.assert_not_awaited()
        agent.prepare_bundle_data.assert_not_awaited()
        agent.query.assert_awaited_once()

    async def test_successful_runtime_preparation_binds_exact_codes_and_applied_patch(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        agent = FixAgent.__new__(FixAgent)
        agent._check_cancelled = Mock()
        agent.session_id = 'offline-integrity'
        agent.metrics_collector = None
        agent.processed_data = {'transaction_hash_list': [self.transaction_hash],
                                'attack_transactions': [self.transaction_hash],
                                'transaction_to_detail': {self.transaction_hash: {'block_number': 1}}}
        agent.mcp_client = Mock()
        agent.mcp_client.call_tool = AsyncMock(return_value={
            'address': self.address, 'file_index': 0, 'contract_name': 'Example',
            'contract_info': [{'id': 0, 'path': 'Example.sol', 'source': 'contract Example {}'}],
        })
        original, changed = self.item(), self.item('6001600055')
        agent._load_compile_result = AsyncMock(return_value={self.address: original})
        agent._load_runtime_bytecode = AsyncMock(return_value={self.address: original.bytecode})
        agent.query = AsyncMock(return_value=f'# File: {self.address}::Example.sol\n<<<<<<< SEARCH\ncontract Example {{}}\n=======\ncontract Example {{function guard() public {{}}}}\n>>>>>>> REPLACE')
        agent.compile_patched_codes = AsyncMock(return_value=(True, {self.address: changed}))
        agent.prepare_bundle_data = AsyncMock(return_value=[{'original_transaction_hash': self.transaction_hash}])
        agent.run_patch_verification_from_tenderly = AsyncMock(return_value=(True, {
            'schema_version': 1, 'status': 'completed', 'control_validation': 'validated',
            'transactions': [{'original_transaction_hash': self.transaction_hash}],
        }))
        outcome = await agent.handle({'fix_report': {'faulty_functions': [{
            'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
        }]}})
        self.assertTrue(outcome[0])
        evidence = outcome[1]['runtime_integrity']
        self.assertEqual(evidence['schema_version'], 1)
        self.assertEqual(evidence['status'], 'validated')
        self.assertEqual(evidence['applied_patch_sha256'], hashlib.sha256(outcome[2].encode()).hexdigest())
        self.assertEqual(evidence, agent.replay_evidence['runtime_integrity'])
        self.assertEqual(evidence, agent.verification['runtime_integrity'])
        self.assertEqual(set(evidence['contracts']), {self.address})
        self.assertEqual(evidence['contracts'][self.address], {
            'original_runtime_sha256': hashlib.sha256(bytes.fromhex(original.bytecode)).hexdigest(),
            'original_compiled_runtime_sha256': hashlib.sha256(bytes.fromhex(original.bytecode)).hexdigest(),
            'patched_runtime_sha256': hashlib.sha256(bytes.fromhex(changed.bytecode)).hexdigest(),
            'storage_layout_checked': True, 'immutable_checked': True,
        })
        self.assertEqual(agent.run_patch_verification_from_tenderly.await_args.args[1], {self.address: '0x' + changed.bytecode})
        # Comment-only / constructor-only code changes must not become changed
        # runtime targets merely because their Solidity metadata hash changed.
        agent._replayed_patch_digests.clear()
        agent.compile_patched_codes.return_value = (True, {self.address: original})
        agent.run_patch_verification_from_tenderly.reset_mock()
        agent.prepare_bundle_data.reset_mock()
        outcome = await agent.handle({'fix_report': {'faulty_functions': [{
            'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
        }]}})
        self.assertFalse(outcome[0])
        self.assertEqual(agent.verification['reason_code'], 'patch_runtime_unchanged')
        agent.run_patch_verification_from_tenderly.assert_not_awaited()
        agent.prepare_bundle_data.assert_not_awaited()


class PatchPromptCompilerTest(unittest.IsolatedAsyncioTestCase):
    def prompt_examples(self):
        from app.attackpilot.prompt.fix_prompt import FIX_SP
        examples = FIX_SP.split('### Examples\n', 1)[1]
        matches = list(re.finditer(
            r'^# File: (?P<file>[^\n]+)\n<<<<<<< SEARCH\n(?P<source>.*?)\n=======\n'
            r'(?P<replacement>.*?)\n>>>>>>> REPLACE', examples, re.MULTILINE | re.DOTALL,
        ))
        self.assertEqual(len(matches), 3, 'Every complete prompt example must be exercised')
        return {match.group('file').split('::', 1)[1]: match for match in matches}

    def test_examples_initialize_unlocked_without_resetting_business_state(self):
        for path, match in self.prompt_examples().items():
            with self.subTest(path=path):
                replacement = match.group('replacement')
                initializer = re.search(
                    r'function __ensurePatchInit\(\) internal \{(.*?)\n    \}', replacement, re.DOTALL,
                ).group(1)
                self.assertNotRegex(initializer, r'\b(owner|limit|totalSupply|balances)\b')
                self.assertNotIn('100 ether', replacement)
                self.assertNotIn('0xAdmin', replacement)
                if path.endswith('OldBank.sol'):
                    self.assertIn('_pSetBool(_SLOT_LOCKED, false);', initializer)
                    self.assertNotIn('_pSetBool(_SLOT_LOCKED, true)', initializer)
                    self.assertLess(initializer.index('_SLOT_LOCKED'), initializer.index('_SLOT_INIT, true'))
                    self.assertNotIn('__PatchState', replacement)
                else:
                    self.assertIn('s.locked = false;', initializer)
                    self.assertNotIn('s.locked = true', initializer)
                    self.assertLess(initializer.index('s.locked = false'), initializer.index('s.initialized = true'))
                    pointer = 's_slot := slot' if path.endswith('Vault06.sol') else 's.slot := slot'
                    self.assertIn(pointer, replacement)

    async def test_complete_prompt_patches_apply_and_compile_across_compiler_generations(self):
        examples = self.prompt_examples()
        targets = [
            ('src/OldBank.sol', 'v0.5.17+commit.d19bba13', 'OldBank', 'istanbul'),
            ('src/Vault06.sol', 'v0.6.12+commit.27d51765', 'Vault06', 'istanbul'),
            ('src/VaultModern.sol', 'v0.7.6+commit.7338295f', 'VaultModern', 'istanbul'),
            ('src/VaultModern.sol', 'v0.8.23+commit.f704f362', 'VaultModern', 'paris'),
        ]
        dao = ContractDao(AsyncMock())
        for path, version, name, evm in targets:
            compiler = dao._resolve_solc_path(version)
            if not compiler:
                self.skipTest(f'The local Solidity compiler {version} is required')
            example = examples[path]
            source = example.group('source')
            file_id = example.group('file')
            ok, message, patched = SolidityCodePatcher({file_id: source}).apply_patches(example.group(0))
            self.assertTrue(ok, message)
            self.assertEqual(patched[file_id], example.group('replacement'))
            for optimized in (False, True):
                with self.subTest(version=version, optimized=optimized), tempfile.TemporaryDirectory(
                    prefix='attackpilot-prompt-compiler-',
                ) as temp:
                    products = []
                    for contents in (source, patched[file_id]):
                        standard = {
                            'language': 'Solidity', 'sources': {path: {'content': contents}},
                            'settings': {
                                'optimizer': {'enabled': optimized, 'runs': 200}, 'evmVersion': evm,
                                'outputSelection': {'*': {'*': ['evm.bytecode', 'evm.deployedBytecode',
                                                               'abi', 'storageLayout'], '': ['ast']}},
                            },
                        }
                        input_path = Path(temp) / 'input.json'
                        input_path.write_text(json.dumps(standard), encoding='utf-8')
                        compiled = await Solc(compiler).compile_json(str(input_path), name)
                        self.assertTrue(compiled.bytecode, compiled.errors)
                        self.assertFalse(any(item.get('severity') == 'error' for item in compiled.errors))
                        products.append(compiled)
                    original, changed = products
                    self.assertEqual(original.abi, changed.abi)
                    layout = lambda item: [{key: row[key] for key in ('label', 'slot', 'offset', 'type')}
                                           for row in item.storage_layout['storage']]
                    self.assertEqual(layout(original), layout(changed))
                    self.assertNotEqual(original.bytecode, changed.bytecode)

    def test_every_source_gets_actual_compiler_and_effective_settings(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        addresses = ['0x' + character * 40 for character in '123']
        contracts = {
            addresses[0]: ContractEntityForCompile({
                'compiler_version': 'v0.8.23+commit.f704f362', 'evm_version': 'istanbul',
                'optimizations_used': False, 'optimization_runs': 1,
                'compiler_settings': {'evmVersion': 'paris', 'optimizer': {
                    'enabled': True, 'runs': 4321, 'details': {'yul': False},
                }},
            }),
            addresses[1]: ContractEntityForCompile({
                'compiler_version': 'v0.5.17+commit.d19bba13', 'evm_version': 'petersburg',
                'optimizations_used': False, 'optimization_runs': 250,
            }),
            addresses[2]: ContractEntityForCompile({
                'compiler_version': 'v0.8.23+commit.f704f362', 'evm_version': 'shanghai',
                'optimizations_used': True, 'optimization_runs': 999,
                'compiler_settings': {'metadata': {'bytecodeHash': 'none'}},
            }),
        }
        sources = {f'{address}::{path}': 'pragma solidity >=0.5.0 <0.9.0; contract Example {}'
                   for address, paths in [(addresses[0], ['One.sol', 'Two.sol']),
                                          (addresses[1], ['Legacy.sol']), (addresses[2], ['Defaults.sol'])]
                   for path in paths}
        formatted = FixAgent.get_format_contracts(object.__new__(FixAgent), {}, sources, contracts)
        targets = [json.loads(line.split(': ', 1)[1]) for line in formatted.splitlines()
                   if line.startswith('Compilation target: ')]
        self.assertEqual(len(targets), len(sources))
        self.assertEqual(targets[:2], [{
            'compiler_version': contracts[addresses[0]].compiler_version, 'evm_version': 'paris',
            'optimizer': {'enabled': True, 'runs': 4321, 'details': {'yul': False}},
        }] * 2)
        self.assertEqual(targets[2], {
            'compiler_version': contracts[addresses[1]].compiler_version, 'evm_version': 'petersburg',
            'optimizer': {'enabled': False, 'runs': 250},
        })
        self.assertEqual(targets[3], {
            'compiler_version': contracts[addresses[2]].compiler_version, 'evm_version': 'compiler default',
            'optimizer': {'enabled': False, 'runs': 200},
        })


class PatchApplicationIntegrityTest(unittest.TestCase):
    def proposal(self, search, replacement, file='Example.sol'):
        return f'# File: {file}\n<<<<<<< SEARCH\n{search}\n=======\n{replacement}\n>>>>>>> REPLACE'

    def test_literal_whitespace_and_comment_markers_cannot_change_search_meaning(self):
        for source, search in [('require(ok, "a b");', 'require(ok, "ab");'),
                               ('require(ok, "https://real");', 'require(ok, "https://wrong");'),
                               ('require(ok, "a/*b*/");', 'require(ok, "a/*c*/");')]:
            with self.subTest(source=source):
                ok, _, updated = SolidityCodePatcher({'Example.sol': source}).apply_patches(self.proposal(search, 'revert();'))
                self.assertFalse(ok)
                self.assertEqual(updated['Example.sol'], source)
        source = '    require(ok, "https://real a b");'
        ok, _, updated = SolidityCodePatcher({'Example.sol': source}).apply_patches(self.proposal(source.strip(), 'require(ok, "guard");'))
        self.assertTrue(ok)
        self.assertEqual(updated['Example.sol'], '    require(ok, "guard");')

    def test_partial_failure_rolls_back_all_files_and_patcher_can_be_reused(self):
        sources = {'Example.sol': 'uint first;', 'Other.sol': 'uint second;'}
        patcher = SolidityCodePatcher(sources)
        text = self.proposal('uint first;', 'uint changed;') + '\n' + self.proposal('missing;', 'uint wrong;', 'Other.sol')
        ok, _, updated = patcher.apply_patches(text)
        self.assertFalse(ok)
        self.assertEqual(updated, sources)
        ok, _, updated = patcher.apply_patches(self.proposal('uint first;', 'uint final;'))
        self.assertTrue(ok)
        self.assertEqual(updated['Example.sol'], 'uint final;')
        self.assertEqual(sources['Example.sol'], 'uint first;')

    def test_malformed_empty_or_ambiguous_blocks_are_not_success(self):
        sources = {'Example.sol': 'uint first;\nuint first;'}
        for text in ('# File: Example.sol\nexplanation only',
                     self.proposal('uint first;', 'uint changed;'),
                     self.proposal('uint first;\nuint first;', 'uint changed;') + '\n<<<<<<< SEARCH\nunfinished'):
            with self.subTest(text=text):
                ok, _, updated = SolidityCodePatcher(sources).apply_patches(text)
                self.assertFalse(ok)
                self.assertEqual(updated, sources)


if __name__ == "__main__": unittest.main()
