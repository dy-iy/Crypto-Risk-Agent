"""Offline regressions for transaction failures and evidence-based verification."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

import httpx
from app.attackpilot.daos.tenderly import TenderlyDao
from app.attackpilot.daos.tx import TxDetailDao
from app.attackpilot.downloaders import contract
from app.attackpilot.errors import failure_message
from app.attackpilot.utils.patch_replay import _execution_effects, execution_summary, trace_summary
from app.attackpilot.utils.report_evidence import report_evidence
from app.attackpilot.utils.verification import adjudicate_patch_verification
from app.attackpilot.web.models import TaskResponse
from app.attackpilot.web.review_service import build_automated_review


class TransactionDetailFanoutTests(unittest.IsolatedAsyncioTestCase):
    async def check_stage_cleanup(self, stage, *, cancelled=False):
        from app.attackpilot.agents.TxDetailAgent import TxDetailAgent

        tx_hashes = ['0x' + 'a' * 64, '0x' + 'b' * 64]
        sibling_started, failure_ready = asyncio.Event(), asyncio.Event()
        trigger_failure, release_sibling = asyncio.Event(), asyncio.Event()
        sibling_finished = asyncio.Event()
        side_effects = []
        original_error = RuntimeError('synthetic transaction failure')

        async def collect(*, transaction_hash):
            if transaction_hash == tx_hashes[0]:
                await sibling_started.wait()
                failure_ready.set()
                await trigger_failure.wait()
                raise original_error
            try:
                sibling_started.set()
                await release_sibling.wait()
                side_effects.append('simulate_or_write')
            finally:
                # Cleanup itself can suspend; the parent must await it.
                await asyncio.sleep(0)
                sibling_finished.set()

        agent = TxDetailAgent.__new__(TxDetailAgent)
        agent.logger = Mock()
        agent._platform = 'Ethereum'
        agent.rpc_bucket = Mock(get=AsyncMock(return_value='offline-rpc'))
        agent.apikey_bucket = Mock(get=AsyncMock(return_value='offline-key'))
        agent.query = AsyncMock()
        agent.write_summary_to_cache = Mock()
        agent._check_cancelled = Mock()
        dao = Mock()
        module = 'app.attackpilot.agents.TxDetailAgent'
        if stage == 'metadata':
            dao.get_token_property_from_transaction = AsyncMock(side_effect=collect)
            agent._load_tx_detail_data = AsyncMock()
            factory = 'TokenPropertyDao'
        else:
            dao.get_tx_detail = AsyncMock(side_effect=collect)
            agent._load_token_properties = AsyncMock(return_value={tx: [] for tx in tx_hashes})
            factory = 'TxDetailDao'

        with patch(module + '.' + factory, return_value=dao), patch(module + '.TenderlyDao'):
            task = asyncio.create_task(agent.handle(tx_hashes))
            try:
                await asyncio.wait_for(failure_ready.wait(), timeout=1)
                if cancelled:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, timeout=1)
                else:
                    trigger_failure.set()
                    with self.assertRaises(RuntimeError) as raised:
                        await asyncio.wait_for(task, timeout=1)
                    self.assertIs(raised.exception, original_error)
                self.assertTrue(sibling_finished.is_set())
                release_sibling.set()
                await asyncio.sleep(0)
                self.assertEqual(side_effects, [])
                agent.query.assert_not_awaited()
                agent.write_summary_to_cache.assert_not_called()
                if stage == 'metadata':
                    agent._load_tx_detail_data.assert_not_awaited()
            finally:
                task.cancel()
                release_sibling.set()
                await asyncio.gather(task, return_exceptions=True)

    async def test_metadata_failure_drains_siblings_before_simulation(self):
        await self.check_stage_cleanup('metadata')

    async def test_metadata_cancellation_drains_siblings_before_simulation(self):
        await self.check_stage_cleanup('metadata', cancelled=True)

    async def test_detail_failure_drains_siblings_before_summary(self):
        await self.check_stage_cleanup('detail')

    async def test_detail_cancellation_drains_siblings_before_summary(self):
        await self.check_stage_cleanup('detail', cancelled=True)


class FailureTests(unittest.IsolatedAsyncioTestCase):
    def test_unattempted_replay_reports_not_run_and_names_classification_gate(self):
        from app.attackpilot.utils.report_evidence import render_verification_summary
        from app.attackpilot.utils.verification import verification_state

        for code, status, explanation in (
            ('no_attack_evidence', 'skipped', '初步分类未筛出攻击候选'),
            ('no_attack_hypothesis', 'unverified', '调查未形成可验证的攻击假设'),
        ):
            state = verification_state(status, stage='fault_localization', reason_code=code)
            evidence = report_evidence({'verdict': 'UNVERIFIED', 'verification': state}, None)
            text = render_verification_summary(evidence)
            self.assertIn('| 攻击路径拦截 | 未执行 |', text)
            self.assertIn('| 结构化证据校验 | 未执行回放 |', text)
            self.assertIn(explanation, text)
            self.assertFalse(evidence['evidence_trusted'])

    def dao(self):
        return TenderlyDao('Ethereum', AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), {})

    async def test_summary_uses_real_transaction_without_explorer_enrichment(self):
        dao = self.dao()
        tx_hash, block_hash = '0x' + 'a' * 64, '0x' + 'b' * 64
        sender, target = '0x' + '1' * 40, '0x' + '2' * 40
        dao.tx_downloader.download.return_value = {
            'hash': tx_hash, 'blockHash': block_hash, 'blockNumber': '0x1', 'transactionIndex': '0x0',
            'from': sender, 'to': target, 'input': '0x', 'value': '0x0',
            'gas': '0x5208', 'gasPrice': '0x1', 'nonce': '0x0',
        }
        dao.receipt_downloader = AsyncMock()
        dao.receipt_downloader.download.return_value = {
            'transactionHash': tx_hash, 'blockHash': block_hash, 'blockNumber': '0x1',
            'transactionIndex': '0x0', 'status': '0x1', 'gasUsed': '0x5208', 'logs': [],
        }
        transaction = {
            'hash': '0x' + 'c' * 64, 'network_id': '1', 'block_number': 1, 'transaction_index': 0,
            'from': sender, 'to': target, 'input': '0x', 'value': '0', 'gas': 21000,
            'gas_price': '1', 'nonce': 0, 'status': True, 'gas_used': 21000,
            'transaction_info': {'logs': [], 'call_trace': {'type': 'CALL', 'from': sender,
                'to': target, 'input': '0x', 'value': '0'}}, 'addresses': [sender],
        }
        dao.send_request = AsyncMock(return_value={
            'transaction': transaction, 'simulation': dict(transaction), 'contracts': [],
        })
        with patch.object(dao, '_supplement_missing_contracts', AsyncMock()) as supplement, patch.object(dao, '_load_contract_name', AsyncMock()) as names:
            result = await dao.simulate_tx_in_tenderly(tx_hash, enrich_contracts=False)
        self.assertEqual(result[0]['hash'], transaction['hash'])
        self.assertEqual(result[0]['original_transaction_hash'], tx_hash)
        self.assertEqual(result[0]['baseline_validation']['status'], 'validated')
        supplement.assert_not_awaited()
        names.assert_not_awaited()

    async def test_detail_stage_explicitly_skips_unused_source(self):
        dao = self.dao()
        dao.simulate_tx_in_tenderly = AsyncMock(return_value=({'hash': '0x' + 'a' * 64}, [], {}))
        await TxDetailDao(dao, {}).get_tx_detail('tx')
        dao.simulate_tx_in_tenderly.assert_awaited_once_with('tx', enrich_contracts=False)

    async def test_missing_required_transaction_still_fails(self):
        dao = self.dao()
        dao.simulate_tx_in_tenderly = AsyncMock(return_value=({}, [], {}))
        with self.assertRaisesRegex(Exception, 'Transaction data is empty'):
            await TxDetailDao(dao, {}).get_tx_detail('tx')

    async def test_name_timeout_keeps_successful_labels_and_trace_can_continue(self):
        dao = self.dao()
        with patch('app.attackpilot.daos.tenderly.ContractDao.get_contract_name', AsyncMock(side_effect=[httpx.ConnectTimeout(''), 'Token'])) as fetch:
            with self.assertLogs('app.attackpilot.daos.tenderly', level='WARNING') as logs:
                names = await dao._load_contract_name({'0xa', '0xb', '0xc'}, {'0xc': 'Known'})
        self.assertEqual(names, {'0xa': '', '0xb': 'Token', '0xc': 'Known'})
        self.assertEqual(fetch.await_count, 2)
        self.assertIn('ConnectTimeout', logs.output[0])

    async def test_name_lookup_does_not_swallow_cancellation(self):
        with patch('app.attackpilot.daos.tenderly.ContractDao.get_contract_name', AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await self.dao()._load_contract_name({'0xa'})

    async def test_explorer_error_is_not_cached_as_contract_source(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(contract, 'CACHE_DIR', temp):
            downloader = contract.ContractSourceDownloader('unused')
            for body in ('{"status":"0","result":"Max rate limit reached"}', '{"result":[]}', 'null'):
                with self.assertRaises(ValueError):
                    await downloader._process(body, contract_address='0xa')
            self.assertFalse((Path(temp) / 'source').exists())

    def test_incomplete_tasks_have_no_risk_score(self):
        for status in ('failed', 'running', 'pending', 'cancelled', 'completed'):
            task = TaskResponse(task_id='t', dapp_name='test', status=status, created_at=datetime.now(timezone.utc))
            review = build_automated_review(task, [{'agent': 'Workflow', 'message': 'failed'}])
            self.assertEqual(review['status'], 'unavailable')
            self.assertIsNone(review['score'])
            self.assertEqual(review['checks'], [])
        task.final_report = 'Root cause: withdraw() violates invariant.'
        self.assertIsInstance(build_automated_review(task, [])['score'], int)

    def test_safe_error_contains_stage_and_exception_type_not_private_url(self):
        message = failure_message(httpx.ConnectTimeout('https://private.example/?apikey=secret'), '读取交易')
        self.assertIn('ConnectTimeout', message)
        self.assertIn('读取交易', message)
        self.assertNotIn('secret', message)
        self.assertNotIn('private.example', message)

    async def test_workflow_timeout_emits_specific_structured_error(self):
        from app.attackpilot import workflow
        events = []
        with tempfile.TemporaryDirectory() as temp, patch.object(workflow, 'WORK_ROOT', Path(temp)), patch.object(workflow, 'PatchQualityMetrics'), patch.object(workflow, 'MCPClient') as mcp, patch.object(workflow, 'DAppProcess') as process:
            mcp.return_value.connect = AsyncMock()
            mcp.return_value.close = AsyncMock()
            process.return_value.process = AsyncMock(side_effect=httpx.ConnectTimeout(''))
            runner = workflow.WorkFlow(log_callback=events.append, use_report_cache=False)
            outcome = await runner.process_single_dapp({'name': 'case', 'enabled_modules': ['attack_detection']}, processed_path=str(Path(temp)/'processed.json'))
        self.assertTrue(outcome[1].startswith('RUNTIME_ERROR:'))
        self.assertIn('ConnectTimeout', runner.last_error)
        self.assertIn('读取交易数据', events[-1].message)
        self.assertEqual(events[-1].level, 'error')
        mcp.return_value.close.assert_awaited_once()

    async def test_worker_persists_specific_failure(self):
        from app.attackpilot import worker
        with patch.object(worker.settings, 'prepare_work_dir'), patch.object(worker.store, 'get_task', return_value={'status':'running','payload':{}}), patch.object(worker.store, 'append_log'), patch.object(worker.store, 'transition') as transition, patch('app.attackpilot.workflow.WorkFlow') as factory:
            factory.return_value.process_single_dapp = AsyncMock(return_value=('case', 'RUNTIME_ERROR: timeout'))
            factory.return_value.last_error = '读取交易数据失败（ConnectTimeout）'
            await worker.run('test')
        transition.assert_called_once_with('test', 'failed', error='读取交易数据失败（ConnectTimeout）')


class ReplayEvidenceRegressionTests(unittest.TestCase):
    """Small synthetic vendor responses exercise parsing and the final gate together.

    These cases use no private runtime artifacts, RPC calls, simulations or model.
    """

    patched_address = '0x' + '1' * 40
    router_address = '0x' + '2' * 40
    outer_address = '0x' + '3' * 40
    unrelated_address = '0x' + '4' * 40
    transaction_hash = '0x' + 'a' * 64
    second_hash = '0x' + 'b' * 64
    guard_reason = 'withdraw exceeds balance'
    # Exact CALL at PC 14; failed calls copy returndata and REVERT, while the
    # successful call branch reaches STOP. No error-string whitelist is used.
    forwarding_runtime = '0x6000600060006000600060006000f115601457005b3d5f5f3e3d5ffd'

    def setUp(self):
        self.patches = (
            f'# File: {self.patched_address}::Vault.sol\n'
            '<<<<<<< SEARCH\nuint256 amount = requested;\n=======\n'
            f'require(requested <= balance, "{self.guard_reason}");\n'
            'uint256 amount = requested;\n>>>>>>> REPLACE'
        )

    def digest(self, value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def frame(self, address=None, *, reason=None, calls=None, kind='CALL', position=1):
        result = {
            'type': kind, 'to': address or self.patched_address,
            'input': '0x12345678', 'status': reason is None,
            'absolute_position': position, 'calls': calls or [], 'error_pc': 7, 'caller_pc': 14,
        }
        if reason is not None:
            result.update(error=reason, error_op='REVERT')
        return result

    def wrapped_trace(self, *, kind='CALL'):
        leaf = self.frame(reason=self.guard_reason, kind=kind, position=3)
        middle = self.frame(self.router_address, reason=self.guard_reason, calls=[leaf], position=2)
        return self.frame(self.outer_address, reason=self.guard_reason, calls=[middle])

    def annotated_trace(self):
        source = {'error_code_start': 17, 'error_code_length': 31,
                  'error_file_index': 0, 'error_line_number': 8}
        marker = {
            'input': '0x', 'output': '0x', 'caller_op': '', 'function_op': '',
            'gas': 0, 'gas_used': 0, 'caller_pc': 0, 'function_pc': 0,
            'error': self.guard_reason, 'error_op': 'REVERT', 'calls': None,
            'address': self.patched_address, 'from': self.patched_address,
            'to': self.patched_address, 'absolute_position': 7, **source,
        }
        parent = self.frame(reason=self.guard_reason, calls=[marker])
        parent.update(error_absolute_position=7, **source)
        return parent

    def abi_error(self, reason):
        encoded = reason.encode()
        return ('0x08c379a0' + (32).to_bytes(32, 'big').hex()
                + len(encoded).to_bytes(32, 'big').hex()
                + encoded.hex().ljust(((len(encoded) + 31) // 32) * 64, '0'))

    def proxy_internal_revert_trace(self):
        """Tenderly's override trace omits source locations and outer errors."""
        leaf = self.annotated_trace()
        for node in (leaf, leaf['calls'][0]):
            for key in ('error_code_start', 'error_code_length',
                        'error_file_index', 'error_line_number'):
                del node[key]
        leaf.update(type='DELEGATECALL', absolute_position=8,
                    output=self.abi_error(self.guard_reason))
        inner = self.frame(self.router_address, kind='JUMPDEST',
                           reason=self.guard_reason, calls=[leaf], position=4)
        inner.update(error_absolute_position=9, gas=200, gas_used=130)
        outer = self.frame(self.router_address, kind='JUMPDEST', calls=[inner], position=3)
        outer.update(gas=230, gas_used=160)
        for node in (inner, outer):
            del node['status']
            node.update(caller_op='JUMP', function_op='JUMPDEST', output='0x',
                        address=self.router_address)
            node['from'] = self.router_address
        proxy = self.frame(self.router_address, calls=[outer], position=10)
        del proxy['status']
        proxy.update(gas=250, gas_used=180, output=self.abi_error(self.guard_reason))
        return proxy

    def execution(self, trace, *, success, role, transaction_hash):
        trace = deepcopy(trace)
        stack = [trace]
        contracts = {}
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            if node.get('type', node.get('call_type')) in ('CALL', 'DELEGATECALL') and 'output' not in node:
                node['output'] = self.abi_error(node['error']) if node.get('error') else '0x'
            if node.get('to') in (self.router_address, self.outer_address):
                child = node
                while isinstance(child, dict) and isinstance(child.get('calls'), list) and child['calls']:
                    child = child['calls'][-1]
                    if isinstance(child, dict) and child.get('type', child.get('call_type')) in ('CALL', 'DELEGATECALL'):
                        break
                opcode = ('f4' if isinstance(child, dict)
                          and child.get('type', child.get('call_type')) == 'DELEGATECALL' else 'f1')
                contracts[node['to']] = self.forwarding_runtime.replace('f115', opcode + '15')
            if isinstance(node.get('calls'), list):
                stack.extend(node['calls'])
        info = {'call_trace': trace, 'logs': [], 'balance_diff': [],
                'asset_changes': [], 'state_diff': []}
        status = {'status': success, 'gas_used': 42000 if success else 32000}
        response = {'simulation': dict(status),
                    'contracts': [{'address': address, 'deployed_bytecode': code}
                                  for address, code in contracts.items()],
                    'transaction': {**status, 'transaction_info': info}}
        sha = self.digest({'role': role, 'hash': transaction_hash, 'response': response})
        artifact = {'sha256': sha,
                    'request_digest': self.digest({'role': role, 'hash': transaction_hash}),
                    'relative_path': f'cache/patch_replay/artifacts/{sha}.json'}
        return execution_summary(response, artifact, [self.patched_address])

    def pair(self, trace, *, transaction_hash=None, success=False, control_trace=None):
        transaction_hash = transaction_hash or self.transaction_hash
        context = {'network_id': '1', 'block_number': 123, 'block_hash': '0x' + 'c' * 64,
                   'transaction_index': 4, 'timestamp': 1700000000}
        control = self.execution(control_trace or self.frame(), success=True,
                                 role='control', transaction_hash=transaction_hash)
        control['control_validation'] = 'validated'
        control['baseline_validation'] = {
            'schema_version': 1, 'status': 'validated',
            'method': 'rpc_receipt_vs_tenderly_original_replay',
            'original_transaction_hash': transaction_hash,
            **{key: value for key, value in context.items() if key != 'timestamp'},
            'receipt_status': 1, 'gas_used': control['gas_used'],
            'log_count': control['logs']['count'],
            'ordered_logs_sha256': control['logs']['ordered_logs_sha256'],
            'receipt_digest': self.digest({'hash': transaction_hash, 'status': 1}),
        }
        return {'original_transaction_hash': transaction_hash, 'context': context,
                'control': control,
                'patched': self.execution(trace, success=success, role='patched',
                                          transaction_hash=transaction_hash)}

    def report(self, pairs=None, *, patches=None):
        from app.attackpilot.utils.patch_attribution import attribution_digest

        pairs = pairs if pairs is not None else [self.pair(self.frame(reason=self.guard_reason))]
        patch_hash = hashlib.sha256((patches if patches is not None else self.patches).encode()).hexdigest()
        runtime_hash = hashlib.sha256(bytes.fromhex('6000600060005bfd')).hexdigest()
        source_hash = hashlib.sha256(b'synthetic Vault.sol compilation').hexdigest()
        # This is the compiler/gate boundary fixture. Actual AST/source-map
        # generation is separately exercised with native Solidity compilers.
        attribution = {'schema_version': 1, 'status': 'available',
                       'applied_patch_sha256': patch_hash, 'contracts': {self.patched_address: {
                           'patched_runtime_sha256': runtime_hash,
                           'compiled_runtime_sha256': runtime_hash,
                           'sources_sha256': {'Vault.sol': source_hash},
                           'guards': [{'file_path': 'Vault.sol', 'source_id': 0,
                                       'start': 17, 'length': 100, 'reason': self.guard_reason,
                                       'guard_sha256': hashlib.sha256(self.guard_reason.encode()).hexdigest(),
                                       'source_sha256': source_hash, 'revert_pcs': [7]}],
                       }}}
        attribution['evidence_sha256'] = attribution_digest(attribution)
        return {'schema_version': 1, 'scope': 'independent_historical_transaction_pairs',
                'status': 'completed', 'control_validation': 'validated',
                'transaction_count': len(pairs), 'transactions': pairs,
                'required_trigger_transaction_hashes': [self.transaction_hash],
                'patched_addresses': [self.patched_address],
                'applied_patch_sha256': patch_hash, 'patch_attribution': attribution,
                'runtime_integrity': {'schema_version': 1, 'status': 'validated',
                                      'applied_patch_sha256': patch_hash,
                                      'contracts': {self.patched_address: {
                                          'patched_runtime_sha256': runtime_hash,
                                          'original_runtime_sha256': 'a' * 64,
                                          'original_compiled_runtime_sha256': 'b' * 64,
                                          'storage_layout_checked': True, 'immutable_checked': True,
                                      }}}}

    def test_same_reason_in_unexecuted_helper_cannot_claim_old_guard_failure(self):
        from app.attackpilot.utils.patch_attribution import attribution_digest

        patches = (f'# File: {self.patched_address}::Vault.sol\n'
                   '<<<<<<< SEARCH\nuint amount = requested;\n=======\n'
                   'uint amount = requested + 1;\n>>>>>>> REPLACE\n'
                   f'# File: {self.patched_address}::UnusedHelper.sol\n'
                   '<<<<<<< SEARCH\nreturn true;\n=======\n'
                   f'require(requested <= balance, "{self.guard_reason}");\n'
                   'return true;\n>>>>>>> REPLACE')
        replay = self.report([self.pair(self.frame(reason=self.guard_reason))], patches=patches)
        proof = replay['patch_attribution']
        contract = proof['contracts'][self.patched_address]
        guard = contract['guards'][0]
        guard.update(file_path='UnusedHelper.sol', revert_pcs=[20])
        contract['sources_sha256'] = {'UnusedHelper.sol': guard['source_sha256']}
        proof['evidence_sha256'] = attribution_digest(proof)
        self.assert_unverified(self.adjudicate(replay, patches=patches), 'patch_guard_location_unproven')

    def test_guard_requires_actual_failure_pc_or_bound_source_identity(self):
        base = self.report()
        for mutation in ('missing_proof', 'missing_pc', 'entry_pc', 'wrong_pc', 'wrong_runtime',
                         'wrong_proof_digest', 'wrong_patch_digest', 'vendor_id_only', 'conflicting_source'):
            with self.subTest(mutation=mutation):
                replay = deepcopy(base)
                call = next(c for c in replay['transactions'][0]['patched']['trace']['reverted_calls']
                            if c['code_address'] == self.patched_address)
                location = call['failure_location']
                if mutation == 'missing_proof': del replay['patch_attribution']
                elif mutation in ('missing_pc', 'entry_pc', 'vendor_id_only'):
                    location.clear()
                    if mutation == 'entry_pc': location.update(caller_pc=7, function_pc=7)
                    if mutation == 'vendor_id_only': location.update(file_index=0, start=17, length=31)
                elif mutation == 'wrong_pc': location['pc'] = 20
                elif mutation == 'wrong_runtime':
                    replay['runtime_integrity']['contracts'][self.patched_address]['patched_runtime_sha256'] = 'f' * 64
                elif mutation == 'wrong_proof_digest': replay['patch_attribution']['evidence_sha256'] = 'f' * 64
                elif mutation == 'wrong_patch_digest': replay['patch_attribution']['applied_patch_sha256'] = 'f' * 64
                elif mutation == 'conflicting_source':
                    location.update(start=17, length=31, source_identity={'file_path': 'Other.sol', 'source_sha256': 'f' * 64})
                self.assert_unverified(self.adjudicate(replay), 'patch_guard_location_unproven')
        replay = deepcopy(base)
        call = next(c for c in replay['transactions'][0]['patched']['trace']['reverted_calls']
                    if c['code_address'] == self.patched_address)
        source_hash = replay['patch_attribution']['contracts'][self.patched_address]['sources_sha256']['Vault.sol']
        call['failure_location'] = {'file_index': 99, 'start': 17, 'length': 31,
                                   'source_identity': {'file_path': 'Vault.sol', 'source_sha256': source_hash}}
        self.assertEqual(self.adjudicate(replay)['status'], 'verified')

    def test_custom_parent_reason_is_evidence_gap_not_patch_revision(self):
        trace = self.wrapped_trace()
        trace['error'] = 'kj'
        replay = self.report([self.pair(trace)])
        result = self.adjudicate(replay)
        self.assert_unverified(result, 'revert_propagation_unproven')
        self.assertEqual(result['next_action'], 'collect_missing_evidence')
        self.assertFalse(result['retryable'])
        self.assertIn('revert_propagation_unproven', {i['code'] for i in result['attribution_issues']})

    def test_parent_runtime_proof_is_bound_to_overrides_and_caller_pc_is_not_failure_pc(self):
        child = self.frame(reason=self.guard_reason)
        child.update(caller_pc=14, output=self.abi_error(self.guard_reason))
        parent = self.frame(self.router_address, reason=self.guard_reason, calls=[child])
        parent['output'] = child['output']
        response = {'simulation': {'status': False, 'gas_used': 32000},
                    'transaction': {'status': False, 'gas_used': 32000, 'transaction_info': {
                        'call_trace': parent, 'logs': [], 'balance_diff': [], 'asset_changes': [], 'state_diff': []}},
                    'contracts': [{'address': self.router_address, 'deployed_bytecode': self.forwarding_runtime}]}
        artifact = {'sha256': 'a' * 64}
        def leaf(changed, runtime_codes=None):
            summary = execution_summary(response, artifact, changed, runtime_codes=runtime_codes)
            return next(call for call in summary['trace']['reverted_calls'] if call['path'] == [0])
        actual = leaf([self.patched_address])
        self.assertEqual(actual['revert_propagation']['source'], 'response_contract')
        self.assertEqual(actual['caller_pc'], 14)
        self.assertEqual(actual['failure_location']['pc'], 7)
        both = [self.patched_address, self.router_address]
        self.assertNotIn('revert_propagation', leaf(both))
        self.assertNotIn('revert_propagation', leaf(both, {self.router_address: '0x00'}))
        self.assertEqual(leaf(both, {self.router_address: self.forwarding_runtime})['revert_propagation']['source'], 'override')
        for invalid in (-1, True, '7'):
            child['error_pc'] = invalid
            location = leaf([self.patched_address])['failure_location']
            self.assertIn('pc', location['invalid_fields'])
            self.assertNotIn('pc', location)

    def test_familiar_wrapper_reason_without_runtime_proof_stays_unverified(self):
        for reason in ('call failed', 'execution reverted', self.guard_reason):
            with self.subTest(reason=reason):
                trace = self.frame(self.router_address, reason=reason,
                                   calls=[self.frame(reason=self.guard_reason)])
                pair = self.pair(trace)
                # Missing evidence cannot be replaced by a terminal call path
                # or a familiar error phrase, even if their text is identical.
                for call in pair['patched']['trace']['reverted_calls']:
                    call.pop('revert_propagation', None)
                result = self.adjudicate(self.report([pair]))
                self.assert_unverified(result, 'revert_propagation_unproven')

    def adjudicate(self, report=None, *, patches=None, verdict='VERIFIED'):
        return adjudicate_patch_verification(
            {'verdict': verdict}, self.report() if report is None else report,
            self.patches if patches is None else patches,
        )

    def assert_unverified(self, result, reason):
        self.assertEqual(result['status'], 'unverified')
        self.assertFalse(result['evidence_validated'])
        self.assertEqual(result['reason_code'], reason)
        self.assertEqual(result['dimensions']['attack_interception']['status'], 'unavailable')

    def test_multiple_revert_shapes_confirm_only_the_attack_interception(self):
        same_reason = self.wrapped_trace()
        same_reason['error'] = self.guard_reason
        same_reason['calls'][0]['error'] = self.guard_reason
        cases = {'direct': self.frame(reason=self.guard_reason),
                 'two_wrappers': self.wrapped_trace(),
                 'same_reason_wrappers': same_reason,
                 'delegatecall': self.wrapped_trace(kind='DELEGATECALL'),
                 'zero_gas_source_annotation': self.annotated_trace()}
        for name, trace in cases.items():
            with self.subTest(shape=name):
                pair = self.pair(trace)
                self.assertTrue(pair['patched']['trace']['complete'])
                result = self.adjudicate(self.report([pair]))
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['checked'][0]['patched_address'], self.patched_address)
                self.assertEqual(result['dimensions']['normal_regression']['status'], 'not_run')
                self.assertEqual(result['dimensions']['profit'], {'status': 'unavailable', 'usd': None})
                self.assertFalse(result['coverage']['sequence_replay_verified'])
                if name in {'two_wrappers', 'same_reason_wrappers', 'delegatecall'}:
                    self.assertEqual(result['checked'][0]['revert_propagation']['call_paths'],
                                     [[], [0], [0, 0]])

    def test_caught_child_followed_by_execution_is_not_propagation(self):
        trace = self.frame(self.router_address, reason='call failed', calls=[
            self.frame(reason=self.guard_reason), self.frame(self.unrelated_address),
        ])
        result = self.adjudicate(self.report([self.pair(trace)]))
        self.assert_unverified(result, 'patch_revert_not_matched')

    def test_caught_child_and_later_same_named_root_error_are_not_propagation(self):
        trace = self.frame(self.router_address, reason=self.guard_reason, calls=[
            self.frame(reason=self.guard_reason), self.frame(self.unrelated_address),
        ])
        result = self.adjudicate(self.report([self.pair(trace)]))
        self.assert_unverified(result, 'patch_revert_not_matched')

    def test_successful_internal_frame_breaks_revert_propagation(self):
        internal = self.frame(self.router_address, kind='JUMPDEST', calls=[
            self.frame(reason=self.guard_reason),
        ])
        trace = self.frame(self.router_address, reason='call failed', calls=[internal])
        self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                               'patch_revert_not_matched')

    def test_unrelated_explicit_parent_failure_does_not_prove_interception(self):
        trace = self.frame(self.router_address, reason='router deadline expired', calls=[
            self.frame(reason=self.guard_reason),
        ])
        self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                               'revert_propagation_unproven')

    def test_same_error_in_unmodified_contract_does_not_prove_interception(self):
        trace = self.frame(self.unrelated_address, reason=self.guard_reason)
        self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                               'patch_revert_not_matched')

    def test_root_error_text_cannot_override_a_different_failure_opcode(self):
        trace = self.frame(reason=self.guard_reason)
        trace['error_op'] = 'INVALID'
        self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                               'patch_revert_not_matched')

    def test_modified_parent_cannot_claim_an_unmodified_childs_bubbled_reason(self):
        for child_opcode in ('REVERT', 'INVALID'):
            with self.subTest(child_opcode=child_opcode):
                child = self.frame(self.unrelated_address, reason=self.guard_reason)
                child['error_op'] = child_opcode
                trace = self.frame(reason=self.guard_reason, calls=[child])
                self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                                       'patch_revert_not_matched')

    def test_same_reason_in_modified_calls_requires_actual_parent_runtime_proof(self):
        leaf = self.frame(reason=self.guard_reason, position=3)
        middle = self.frame(reason=self.guard_reason, calls=[leaf], position=2)
        trace = self.frame(reason=self.guard_reason, calls=[middle])
        result = self.adjudicate(self.report([self.pair(trace)]))
        self.assert_unverified(result, 'revert_propagation_unproven')
        self.assertEqual(result['checked'], [])

    def test_internal_source_frame_cannot_hide_an_unmodified_childs_bubbled_reason(self):
        internal = self.frame(kind='JUMPDEST', reason=self.guard_reason, calls=[
            self.frame(self.unrelated_address, reason=self.guard_reason),
        ])
        trace = self.frame(reason=self.guard_reason, calls=[internal])
        self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                               'patch_revert_not_matched')

    def test_abi_error_output_needs_an_actual_failed_call(self):
        encoded_reason = self.guard_reason.encode()
        output = ('0x08c379a0' + (32).to_bytes(32, 'big').hex()
                  + len(encoded_reason).to_bytes(32, 'big').hex()
                  + encoded_reason.hex().ljust(64, '0'))
        for success in (False, True):
            with self.subTest(child_succeeded=success):
                child = self.frame(reason=None if success else 'execution reverted')
                child['output'] = output
                trace = self.frame(self.router_address, reason=self.guard_reason, calls=[child])
                result = self.adjudicate(self.report([self.pair(trace)]))
                if success:
                    self.assert_unverified(result, 'patch_revert_not_matched')
                else:
                    self.assertEqual(result['status'], 'verified')
                    self.assertEqual(result['checked'][0]['revert_reason'], self.guard_reason)

    def test_missing_truncated_unknown_or_inconsistent_trace_is_not_verified(self):
        base = self.wrapped_trace()
        missing_children = deepcopy(base)
        del missing_children['calls'][0]['calls'][0]['calls']
        truncated = deepcopy(base)
        truncated['calls'][0]['truncated'] = True
        unknown = deepcopy(base)
        unknown['calls'].append(self.frame(kind='UNRECOGNIZED_OPCODE'))
        missing_node = deepcopy(base)
        missing_node['calls'].append(None)
        status_conflict = deepcopy(base)
        status_conflict['calls'][0]['status'] = True
        invalid_target = deepcopy(base)
        invalid_target['to'] = 'not-an-address'
        invalid_status = deepcopy(base)
        invalid_status['status'] = 2
        invalid_children = deepcopy(base)
        invalid_children['calls'] = {}
        cases = {
            'absent': (None, 'patched_trace_unavailable', 'trace_missing', []),
            'missing_children': (missing_children, 'patched_trace_unavailable', 'missing_children', [0, 0]),
            'truncated': (truncated, 'patched_trace_unavailable', 'trace_truncated', [0]),
            'unknown_opcode': (unknown, 'patched_trace_format_unsupported', 'unsupported_node_type', [1]),
            'missing_node': (missing_node, 'patched_trace_invalid', 'invalid_node', [1]),
            'status_conflict': (status_conflict, 'patched_trace_invalid', 'status_conflict', [0]),
            'invalid_target': (invalid_target, 'patched_trace_invalid', 'invalid_call_target', []),
            'invalid_status': (invalid_status, 'patched_trace_invalid', 'invalid_status', []),
            'invalid_children': (invalid_children, 'patched_trace_invalid', 'invalid_children', []),
            'invalid_root': ([], 'patched_trace_invalid', 'invalid_root', []),
        }
        for name, (trace, reason, issue, path) in cases.items():
            with self.subTest(shape=name):
                pair = self.pair(trace)
                self.assert_unverified(self.adjudicate(self.report([pair])), reason)
                self.assertIn({'code': issue, 'path': path}, pair['patched']['trace']['issues'])

    def test_trace_diagnostics_are_bounded_and_do_not_copy_provider_messages(self):
        trace = self.frame(self.router_address, reason='call failed', calls=[
            self.frame(kind='UNSUPPORTED_TYPE_WITH_PRIVATE_DATA_' + 'x' * 1000)
            for _ in range(40)
        ])
        summary = trace_summary({'call_trace': trace}, [self.patched_address], execution_status=0)
        self.assertFalse(summary['complete'])
        self.assertFalse(summary['call_targets_complete'])
        self.assertEqual(summary['issue_count'], 40)
        self.assertEqual(len(summary['issues']), 16)
        self.assertTrue(summary['issues_truncated'])
        self.assertEqual(summary['issues'], [
            {'code': 'unsupported_node_type', 'path': [index]} for index in range(16)
        ])
        self.assertEqual(summary['issue_codes'], ['unsupported_node_type'])
        self.assertNotIn('PRIVATE_DATA', json.dumps(summary))

    def test_issue_detail_limit_does_not_hide_later_invalid_execution_data(self):
        trace = self.frame(self.router_address, reason='call failed', calls=[
            *[self.frame(kind='UNSUPPORTED_TYPE') for _ in range(17)], None,
        ])
        pair = self.pair(trace)
        summary = pair['patched']['trace']
        self.assertEqual(summary['issue_count'], 18)
        self.assertTrue(summary['issues_truncated'])
        self.assertEqual({item['code'] for item in summary['issues']}, {'unsupported_node_type'})
        self.assertEqual(summary['issue_codes'], ['invalid_node', 'unsupported_node_type'])
        self.assert_unverified(self.adjudicate(self.report([pair])), 'patched_trace_invalid')

    def test_deep_trace_is_bounded_and_explicitly_incomplete(self):
        trace = self.frame()
        for _ in range(130):
            trace = self.frame(calls=[trace])
        summary = trace_summary({'call_trace': trace}, [self.patched_address], execution_status=1)
        self.assertFalse(summary['complete'])
        self.assertFalse(summary['call_targets_complete'])
        self.assertEqual(summary['issue_count'], 1)
        self.assertEqual(summary['issues'], [
            {'code': 'trace_limit_exceeded', 'path': [0] * 128},
        ])
        self.assertLessEqual(summary['node_count'], 130)

    def test_zero_gas_marker_requires_matching_parent_source_evidence(self):
        mutations = {'nonzero_gas': ('gas_used', 1), 'different_source': ('error_line_number', 9),
                     'different_address': ('to', self.unrelated_address),
                     'different_error': ('error', 'other guard'),
                     'different_position': ('absolute_position', 8)}
        for name, (field, value) in mutations.items():
            with self.subTest(shape=name):
                trace = self.annotated_trace()
                trace['calls'][0][field] = value
                pair = self.pair(trace)
                self.assert_unverified(self.adjudicate(self.report([pair])),
                                       'patched_trace_format_unsupported')
                self.assertIn({'code': 'unrecognized_untyped_node', 'path': [0]},
                              pair['patched']['trace']['issues'])

    def test_sourceless_override_marker_and_terminal_proxy_revert_are_validated(self):
        pair = self.pair(self.proxy_internal_revert_trace())
        self.assertTrue(pair['patched']['trace']['complete'])
        result = self.adjudicate(self.report([pair]))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['checked'][0]['revert_propagation']['call_paths'],
                         [[], [0, 0, 0]])
        self.assertEqual(result['checked'][0]['patched_address'], self.patched_address)

    def test_sourceless_marker_needs_terminal_position_and_parent_abi_error(self):
        mutations = (
            lambda leaf: leaf.update(output='0x'),
            lambda leaf: leaf.update(absolute_position=10),
            lambda leaf: leaf['calls'][0].update(error_line_number=1),
            lambda leaf: leaf['calls'][0].update(caller_op='CALL'),
            lambda leaf: leaf['calls'].append(self.frame(kind='SLOAD')),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                trace = self.proxy_internal_revert_trace()
                mutate(trace['calls'][0]['calls'][0]['calls'][0])
                self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                                       'patched_trace_format_unsupported')

    def test_proxy_revert_inference_requires_complete_same_frame_terminal_evidence(self):
        mutations = (
            lambda proxy: proxy.update(output=self.abi_error('unrelated reason')),
            lambda proxy: proxy.update(absolute_position=11),
            lambda proxy: proxy.update(gas_used=179),
            lambda proxy: proxy['calls'][0].update(gas_used=159),
            lambda proxy: proxy['calls'][0].pop('gas'),
            lambda proxy: proxy['calls'][0].update(address=self.unrelated_address),
            lambda proxy: proxy['calls'][0].update(caller_op='CALL'),
            lambda proxy: proxy['calls'][0]['calls'].append(self.frame(kind='SLOAD')),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                trace = self.proxy_internal_revert_trace()
                mutate(trace)
                self.assert_unverified(self.adjudicate(self.report([self.pair(trace)])),
                                       'revert_propagation_unproven' if index == 0 else 'patch_revert_not_matched')

    def test_terminal_internal_revert_conflicts_with_successful_transaction(self):
        summary = trace_summary({'call_trace': self.proxy_internal_revert_trace()},
                                [self.patched_address], execution_status=1)
        self.assertFalse(summary['complete'])
        self.assertIn({'code': 'status_conflict', 'path': []}, summary['issues'])

    def test_missing_control_and_mismatched_original_transaction_are_rejected(self):
        missing = self.report()
        del missing['transactions'][0]['control']
        self.assert_unverified(self.adjudicate(missing), 'paired_replay_incomplete')
        wrong_hash = self.report()
        wrong_hash['transactions'][0]['control']['baseline_validation']['original_transaction_hash'] = self.second_hash
        self.assert_unverified(self.adjudicate(wrong_hash), 'control_evidence_mismatch')
        wrong_receipt = self.report()
        wrong_receipt['transactions'][0]['control']['baseline_validation']['gas_used'] += 1
        self.assert_unverified(self.adjudicate(wrong_receipt), 'control_evidence_mismatch')

    def test_applied_patch_and_artifact_identity_are_required(self):
        wrong_patch = self.report()
        wrong_patch['applied_patch_sha256'] = '0' * 64
        self.assert_unverified(self.adjudicate(wrong_patch), 'applied_patch_evidence_mismatch')
        reused_control = self.report()
        pair = reused_control['transactions'][0]
        pair['patched']['artifact'] = deepcopy(pair['control']['artifact'])
        self.assert_unverified(self.adjudicate(reused_control), 'patch_artifact_missing')

    def test_missing_required_trigger_cannot_be_replaced_by_another_success(self):
        report = self.report()
        report['required_trigger_transaction_hashes'].append(self.second_hash)
        result = self.adjudicate(report)
        self.assert_unverified(result, 'required_trigger_replay_missing')
        self.assertEqual(result['next_action'], 'select_trigger_transactions')
        self.assertIn(self.second_hash, result['coverage']['unresolved_transaction_hashes'])

    def test_invalid_required_trigger_scope_is_rejected(self):
        for required in ([], ['not-a-transaction-hash'],
                         [self.transaction_hash, self.transaction_hash], None):
            with self.subTest(required=required):
                report = self.report()
                report['required_trigger_transaction_hashes'] = required
                self.assert_unverified(self.adjudicate(report), 'required_trigger_replay_missing')

    def test_unchanged_success_outside_modified_code_is_recorded_separately(self):
        outside = self.frame(self.unrelated_address)
        unaffected = self.pair(outside, transaction_hash=self.second_hash,
                               success=True, control_trace=outside)
        result = self.adjudicate(self.report([self.pair(self.wrapped_trace()), unaffected]))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['coverage']['intercepted_transaction_hashes'], [self.transaction_hash])
        self.assertEqual(result['coverage']['unaffected_transaction_hashes'], [self.second_hash])
        self.assertEqual(result['dimensions']['normal_regression']['status'], 'not_run')
        only_outside = self.report([unaffected])
        only_outside['required_trigger_transaction_hashes'] = [self.second_hash]
        result = self.adjudicate(only_outside)
        self.assert_unverified(result, 'modified_code_not_reached')
        self.assertEqual(result['next_action'], 'select_trigger_transactions')

    def test_outside_code_success_requires_observed_unchanged_execution_effects(self):
        outside = self.frame(self.unrelated_address)
        for name in ('missing_effects', 'changed_effects', 'changed_gas', 'missing_targets'):
            with self.subTest(evidence=name):
                pair = self.pair(outside, success=True, control_trace=outside)
                if name == 'missing_effects':
                    del pair['patched']['execution_effects']
                elif name == 'changed_effects':
                    pair['patched']['execution_effects']['fields']['balance_diff']['sha256'] = '0' * 64
                elif name == 'changed_gas':
                    pair['patched']['gas_used'] += 1
                else:
                    pair['patched']['trace']['call_targets_complete'] = False
                expected = ('patched_trace_unavailable' if name == 'missing_targets'
                            else 'unaffected_execution_mismatch')
                self.assert_unverified(self.adjudicate(self.report([pair])), expected)

    def test_success_through_modified_code_requests_revision_not_verified(self):
        result = self.adjudicate(self.report([self.pair(self.frame(), success=True)]))
        self.assert_unverified(result, 'patch_interception_not_established')
        self.assertEqual(result['next_action'], 'revise_patch')

    def test_comment_only_change_cannot_be_an_intervention(self):
        source = f'require(requested <= balance, "{self.guard_reason}");'
        patches = (f'# File: {self.patched_address}::Vault.sol\n<<<<<<< SEARCH\n{source}\n'
                   f'=======\n// patched\n{source}\n>>>>>>> REPLACE')
        self.assert_unverified(self.adjudicate(self.report(patches=patches), patches=patches),
                               'patch_target_missing')

    def test_model_verdict_never_supplies_missing_machine_evidence(self):
        self.assert_unverified(self.adjudicate({}), 'structured_replay_evidence_missing')
        report = self.report()
        report['transactions'][0]['patched']['trace']['reverted_calls_truncated'] = True
        self.assert_unverified(self.adjudicate(report), 'patched_trace_unavailable')
        report = self.report()
        report['transactions'][0]['patched']['logs']['count'] = 1
        self.assert_unverified(self.adjudicate(report), 'patched_events_unresolved')

    def test_negative_model_verdict_cannot_reverse_conclusive_execution_evidence(self):
        result = self.adjudicate(verdict='WRONG_ROOT_CAUSE')
        self.assert_unverified(result, 'judge_negative_unsubstantiated')
        self.assertEqual(result['next_action'], 'review_same_evidence')
        self.assertEqual(len(result['checked']), 1)

    def test_successful_status_with_failure_opcode_invalidates_the_trace(self):
        for opcode in ('REVERT', 'INVALID'):
            with self.subTest(opcode=opcode):
                child = self.frame(self.unrelated_address)
                child['error_op'] = opcode
                trace = self.frame(reason=self.guard_reason, calls=[child])
                pair = self.pair(trace)
                self.assertIn({'code': 'status_conflict', 'path': [0]},
                              pair['patched']['trace']['issues'])
                self.assert_unverified(self.adjudicate(self.report([pair])), 'patched_trace_invalid')

    def test_explicit_revert_opcode_can_confirm_abi_error_without_status_text(self):
        reason = self.guard_reason.encode()
        leaf = self.frame()
        del leaf['status']
        leaf.update(error_op='REVERT', output=(
            '0x08c379a0' + (32).to_bytes(32, 'big').hex()
            + len(reason).to_bytes(32, 'big').hex() + reason.hex().ljust(64, '0')))
        trace = self.frame(self.router_address, reason=self.guard_reason, calls=[leaf])
        result = self.adjudicate(self.report([self.pair(trace)]))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['checked'][0]['revert_reason'], self.guard_reason)

    def test_report_verdict_is_bound_to_the_same_complete_replay_evidence(self):
        replay = self.report()
        state = self.adjudicate(replay)
        judge = {'verdict': 'VERIFIED', 'verification': state}
        self.assertTrue(report_evidence(judge, replay)['evidence_trusted'])
        changed = deepcopy(replay)
        changed['transactions'][0]['patched']['gas_used'] += 1
        missing = deepcopy(replay)
        del missing['transactions'][0]['patched']['trace']
        expanded = deepcopy(replay)
        expanded['required_trigger_transaction_hashes'].append(self.second_hash)
        for evidence in ({'schema_version': 1}, changed, missing, expanded):
            with self.subTest(evidence=evidence):
                rendered = report_evidence(judge, evidence)
                self.assertFalse(rendered['evidence_trusted'])
                self.assertEqual(rendered['verification']['status'], 'unverified')
                self.assertFalse(rendered['verification']['evidence_validated'])
                self.assertEqual(rendered['verification']['dimensions']['attack_interception']['status'],
                                 'unavailable')
        self.assertTrue(state['evidence_validated'])
        self.assertEqual(state['status'], 'verified')
        # Serialization key order never changes which evidence was judged.
        reordered = json.loads(json.dumps(replay, sort_keys=True))
        self.assertTrue(report_evidence(judge, reordered)['evidence_trusted'])

    def test_report_does_not_promote_unmeasured_business_or_profit_dimensions(self):
        replay = self.report()
        state = self.adjudicate(replay)
        state['dimensions']['normal_regression'] = {'status': 'passed'}
        state['dimensions']['profit'] = {'status': 'available', 'usd': 0}
        rendered = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
        self.assertTrue(rendered['evidence_trusted'])
        self.assertEqual(rendered['verification']['dimensions']['normal_regression'], {'status': 'not_run'})
        self.assertEqual(rendered['verification']['dimensions']['profit'],
                         {'status': 'unavailable', 'usd': None})

    def test_report_rejects_legacy_markers_and_conflicting_judge_verdicts(self):
        replay = self.report()
        state = self.adjudicate(replay)
        legacy = deepcopy(state)
        del legacy['replay_evidence_sha256']
        bool_version = deepcopy(state)
        bool_version['evidence_version'] = True
        obsolete = [dict(state, verification_policy_version=value) for value in (None, 1, True, '2')]
        for verdict, verification in (('VERIFIED', legacy), ('VERIFIED', bool_version),
                                      ('WRONG_ROOT_CAUSE', state),
                                      *(('VERIFIED', value) for value in obsolete)):
            with self.subTest(verdict=verdict, verification=verification):
                rendered = report_evidence({'verdict': verdict, 'verification': verification}, replay)
                self.assertFalse(rendered['evidence_trusted'])
                self.assertEqual(rendered['verification']['status'], 'unverified')
                self.assertEqual(rendered['verification']['dimensions']['attack_interception']['status'],
                                 'unavailable')

    def test_non_serializable_replay_cannot_receive_a_verified_verdict(self):
        replay = self.report()
        replay['unexpected_nonfinite_value'] = float('nan')
        self.assert_unverified(self.adjudicate(replay), 'structured_replay_evidence_missing')

    def raw_effects(self):
        word = lambda value: '0x' + f'{value:064x}'
        return {
            'balance_diff': [{'address': self.patched_address, 'original': '10', 'dirty': '9'}],
            'asset_changes': [{
                'type': 'Transfer', 'from': self.patched_address, 'to': self.router_address,
                'raw_amount': '1', 'from_before_balance': '10', 'to_before_balance': '0',
                'trace_absolute_position': 3, 'amount': 0.0001, 'dollar_value': '1.23',
                'token_info': {'standard': 'ERC20', 'contract_address': self.unrelated_address,
                               'decimals': 4, 'symbol': 'TOKEN', 'name': 'Token'},
            }],
            'state_diff': [{
                'address': self.patched_address, 'name': 'balances', 'original': 'decoded old',
                'dirty': 'decoded new', 'raw': [
                    {'address': self.patched_address, 'key': word(1), 'original': word(10), 'dirty': word(9)},
                    {'address': self.patched_address, 'key': word(2), 'original': word(0), 'dirty': word(1)},
                ],
            }],
        }

    def test_raw_execution_effects_ignore_provider_metadata_and_storage_grouping(self):
        original = self.raw_effects()
        changed = deepcopy(original)
        changed['balance_diff'][0].update(original='0x0a', dirty=9, name='new label')
        changed['asset_changes'][0].update(amount=9999, dollar_value=9999, raw_amount='0x01')
        changed['asset_changes'][0]['token_info'].update(symbol='RENAMED', name='New label', decimals=18)
        storage = changed['state_diff'][0]
        changed['state_diff'] = [
            {'address': storage['address'], 'raw': [entry]}
            for entry in reversed(storage['raw'])
        ]
        expected = _execution_effects(original)
        self.assertTrue(expected['complete'])
        self.assertEqual(expected, _execution_effects(changed))
        self.assertEqual(expected['fields']['state_diff']['count'], 2)

    def test_raw_execution_effects_keep_actual_changes_and_duplicate_storage_words(self):
        original = self.raw_effects()
        expected = _execution_effects(original)
        for kind in ('balance', 'transfer', 'storage', 'duplicate_storage'):
            with self.subTest(change=kind):
                changed = deepcopy(original)
                if kind == 'balance':
                    changed['balance_diff'][0]['dirty'] = '8'
                elif kind == 'transfer':
                    changed['asset_changes'][0]['raw_amount'] = '2'
                elif kind == 'storage':
                    changed['state_diff'][0]['raw'][0]['dirty'] = '0x' + '0' * 63 + '8'
                else:
                    changed['state_diff'][0]['raw'].append(deepcopy(changed['state_diff'][0]['raw'][0]))
                actual = _execution_effects(changed)
                self.assertTrue(actual['complete'])
                self.assertNotEqual(expected, actual)

    def test_decoded_storage_without_raw_words_never_establishes_unchanged_state(self):
        effects = self.raw_effects()
        del effects['state_diff'][0]['raw']
        self.assertFalse(_execution_effects(effects)['complete'])

    def test_offline_review_rejects_malformed_records_with_an_explicit_error(self):
        from app.attackpilot.revalidate import revalidate_result

        for result in (None, [], {'verification': []}, {
            'verification': {'status': 'unverified', 'reason_code': 'patched_trace_unavailable'},
            'replay_evidence': [],
        }):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    revalidate_result(result, temp)

    def stored_legacy_result(self, root):
        """Build a real on-disk audit chain using synthetic local RPC records."""
        from app.attackpilot.utils.patch_replay import (
            PatchReplayEvidenceStore, historical_payload, public_context, runtime_overrides,
        )
        from app.attackpilot.utils.replay_validation import validate_simulated_transaction
        from app.attackpilot.utils.report_evidence import render_verification_summary

        transaction = {
            'hash': self.transaction_hash, 'blockNumber': '0x7b', 'transactionIndex': '0x4',
            'blockHash': '0x' + 'c' * 64, 'chainId': '0x1', 'from': self.router_address,
            'to': self.patched_address, 'input': '0x12345678', 'value': '0x0',
            'gas': '0x186a0', 'gasPrice': '0x1', 'nonce': '0x0',
        }
        receipt = {
            'transactionHash': self.transaction_hash, 'blockNumber': transaction['blockNumber'],
            'transactionIndex': transaction['transactionIndex'], 'blockHash': transaction['blockHash'],
            'status': '0x1', 'gasUsed': '0xa410', 'logs': [],
        }
        records = {
            f'tx_detail/tx/{self.transaction_hash}.json': transaction,
            f'tx_detail/tx_receipt/{self.transaction_hash}.json': receipt,
            'timestamp/123.json': {'schema_version': 1, 'block_number': 123,
                                   'block_hash': transaction['blockHash'], 'timestamp': 1700000000},
        }
        for relative, value in records.items():
            path = root / 'cache' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding='utf-8')
        evidence_store = PatchReplayEvidenceStore(root / 'cache')
        context, raw_transaction = evidence_store.original_context(self.transaction_hash, 1)
        pair = {'original_transaction_hash': self.transaction_hash,
                'context': public_context(context, raw_transaction),
                'patched_addresses': [self.patched_address]}
        for role in ('control', 'patched'):
            success = role == 'control'
            overrides = None if success else runtime_overrides({self.patched_address: '0x6000600060005bfd'})
            request = historical_payload(context, raw_transaction, overrides)
            shared = {
                'network_id': '1', 'block_number': 123, 'transaction_index': 4,
                'from': self.router_address, 'to': self.patched_address,
                'input': '0x12345678', 'value': '0', 'gas': 100000, 'gas_price': '1',
                'nonce': 0, 'status': success, 'gas_used': 42000 if success else 32000,
            }
            response = {
                'simulation': {**shared, 'id': f'synthetic-{role}', 'block_header': {
                    'number': 123, 'hash': transaction['blockHash'], 'timestamp': 1700000000,
                }},
                'transaction': {**shared, 'transaction_info': {
                    'logs': [], 'balance_diff': [], 'asset_changes': [], 'state_diff': [],
                    'call_trace': {**self.frame(reason=None if success else self.guard_reason),
                                   'from': self.router_address, 'value': '0'},
                }},
            }
            artifact = evidence_store.persist(request, response, role=role, original_hash=self.transaction_hash)
            pair[role] = execution_summary(response, artifact, [self.patched_address])
            if success:
                pair[role].update(control_validation='validated',
                                  baseline_validation=validate_simulated_transaction(context, response))
        pair['comparison'] = {'attack_transaction_reverted': True, 'logs_changed': False, 'gas_changed': True}
        replay = self.report([pair])
        state = self.adjudicate(replay)
        self.assertEqual(state['status'], 'verified')
        del state['replay_evidence_sha256'], state['applied_patch_sha256']
        # This is the former report envelope, before digest binding existed.
        prefix = render_verification_summary({
            'verification': state, 'label': '触发交易拦截通过', 'evidence_trusted': True,
        })
        return {'verification': state, 'replay_evidence': replay, 'applied_patches': self.patches,
                'report': prefix + '\n\n# 原始分析\n\n保留原始模型分析与记录。'}

    def test_offline_refresh_preserves_unverified_status_without_inventing_guard_location(self):
        from app.attackpilot.revalidate import revalidate_result
        from app.attackpilot.utils.report_evidence import render_verification_summary

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self.stored_legacy_result(root)
            replay = result['replay_evidence']
            del replay['patch_attribution']
            original = deepcopy(result['verification'])
            original.update(status='unverified', evidence_validated=False,
                            reason_code='patched_trace_format_unsupported')
            result['verification'] = original
            result['report'] = render_verification_summary(report_evidence(
                {'verdict': 'VERIFIED', 'verification': original}, replay)) + '\n\n原始正文'
            saved = deepcopy(result)
            with self.assertRaisesRegex(ValueError, 'remains unverified'):
                revalidate_result(result, root)
            revised = revalidate_result(result, root, refresh_unverified=True)
            self.assertEqual(result, saved)
            self.assertEqual(revised['verification']['status'], 'unverified')
            self.assertEqual(revised['verification']['reason_code'], 'patch_guard_location_unproven')
            self.assertFalse(revised['verification']['evidence_validated'])
            self.assertTrue(revised['evidence_revision']['diagnosis_only'])
            self.assertNotIn('patch_attribution', revised['replay_evidence'])
            reference = replay['transactions'][0]['patched']['artifact']
            (root / reference['relative_path']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                revalidate_result(result, root, refresh_unverified=True)

    def test_offline_review_can_upgrade_legacy_verified_from_immutable_artifacts(self):
        from app.attackpilot.revalidate import revalidate_result
        from app.attackpilot.utils.verification import replay_evidence_digest

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = self.stored_legacy_result(root)
            before = deepcopy(original)
            files = {str(path.relative_to(root)): path.read_bytes()
                     for path in root.rglob('*') if path.is_file()}
            revised = revalidate_result(original, root)
            self.assertEqual(original, before)
            self.assertEqual(files, {str(path.relative_to(root)): path.read_bytes()
                                     for path in root.rglob('*') if path.is_file()})
        state = revised['verification']
        self.assertEqual(state['status'], 'verified')
        self.assertEqual(state['replay_evidence_sha256'], replay_evidence_digest(revised['replay_evidence']))
        self.assertTrue(revised['evidence_revision']['upgraded_legacy_binding'])
        self.assertEqual(revised['evidence_revision']['previous_status'], 'verified')
        self.assertTrue(revised['report'].endswith('# 原始分析\n\n保留原始模型分析与记录。'))
        self.assertIn('未发起新模拟或模型调用', revised['report'])
        self.assertTrue(report_evidence({'verdict': 'VERIFIED', 'verification': state},
                                        revised['replay_evidence'])['evidence_trusted'])

    def test_legacy_upgrade_rejects_tampered_artifacts_requests_and_report_prefix(self):
        from app.attackpilot.revalidate import revalidate_result
        from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore

        for kind in ('artifact_bytes', 'historical_request', 'report_prefix', 'existing_invalid_binding'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                result = self.stored_legacy_result(root)
                pair = result['replay_evidence']['transactions'][0]
                if kind == 'artifact_bytes':
                    path = root / pair['patched']['artifact']['relative_path']
                    path.write_bytes(path.read_bytes() + b' ')
                elif kind == 'historical_request':
                    path = root / pair['patched']['artifact']['relative_path']
                    record = json.loads(path.read_bytes())
                    record['request']['simulations'][0]['block_number'] += 1
                    pair['patched']['artifact'] = PatchReplayEvidenceStore(root / 'cache').persist(
                        record['request'], record['response'], role='patched', original_hash=self.transaction_hash)
                elif kind == 'report_prefix':
                    result['report'] = result['report'].replace('触发交易拦截通过', '任意成功声明', 1)
                else:
                    result['verification']['replay_evidence_sha256'] = '0' * 64
                with self.assertRaises(ValueError):
                    revalidate_result(result, root)

    def test_offline_review_preserves_the_existing_unverified_trace_repair_path(self):
        from app.attackpilot.revalidate import revalidate_result
        from app.attackpilot.utils.report_evidence import render_verification_summary

        with tempfile.TemporaryDirectory() as temp:
            result = self.stored_legacy_result(Path(temp))
            replay = result['replay_evidence']
            replay['transactions'][0]['patched']['trace']['complete'] = False
            state = self.adjudicate(replay)
            self.assert_unverified(state, 'patched_trace_unavailable')
            result['verification'] = state
            result['report'] = render_verification_summary(report_evidence(
                {'verdict': 'VERIFIED', 'verification': state}, replay)) + '\n\n原分析保持。'
            revised = revalidate_result(result, temp)
        self.assertEqual(revised['verification']['status'], 'verified')
        self.assertFalse(revised['evidence_revision']['upgraded_legacy_binding'])

    def test_redaction_keeps_ordinary_binding_but_never_resigns_changed_evidence(self):
        from app.attackpilot import privacy
        from app.attackpilot.utils.verification import replay_evidence_digest

        with patch.multiple(privacy.settings, LLM_API_KEY='unit-private-credential',
                            TENDERLY_API_KEY='unit-tenderly-credential',
                            WEB3_PROVIDER='https://unit-rpc/private', JSONRPCS={}, SCAN_APIKEYS={}):
            for sensitive in (False, True):
                with self.subTest(redaction_changes_evidence=sensitive):
                    replay = self.report()
                    if sensitive:
                        replay['provider_note'] = 'api_key=do-not-display'
                    result = privacy.redact({'verification': self.adjudicate(replay), 'replay_evidence': replay})
                    state = result['verification']
                    rendered = report_evidence({'verdict': 'VERIFIED', 'verification': state}, result['replay_evidence'])
                    self.assertEqual(rendered['evidence_trusted'], not sensitive)
                    if sensitive:
                        self.assertNotIn('do-not-display', json.dumps(result))
                        self.assertNotEqual(state['replay_evidence_sha256'],
                                            replay_evidence_digest(result['replay_evidence']))


class PatchSourceRecoveryTests(unittest.IsolatedAsyncioTestCase):
    address = '0x' + '8' * 40
    hashes = ['0x' + digit * 64 for digit in 'cd']
    source = 'pragma solidity ^0.8.23; contract Synthetic { function ping() external {} }'

    def source_response(self):
        return {'SourceCode': json.dumps({'language': 'Solidity', 'sources': {
            'Other.sol': {'content': 'pragma solidity ^0.8.23; contract Other {}'},
            'Synthetic.sol': {'content': self.source}}, 'settings': {}}),
            'ContractName': 'Synthetic', 'CompilerVersion': 'v0.8.23+commit.f704f362', 'ABI': '[]'}

    @asynccontextmanager
    async def scenario(self, responses, *, initialize=False, lookup=None, configured=True):
        from types import SimpleNamespace
        from app.attackpilot.agents.FixAgent import FixAgent
        from app.attackpilot.daos.tenderly import MixTraceTree
        from app.attackpilot.mcp_tools import mcp_server as server
        downloader = Mock(download=AsyncMock(side_effect=responses))
        bytecode = Mock(download=AsyncMock(return_value='0x6001600055'))
        if initialize:
            dao = object.__new__(TenderlyDao)
            dao.source_downloader, dao.bytecode_downloader = downloader, bytecode
            rows = await dao._supplement_missing_contracts([self.address], [], block_number=42)
        else:
            rows = [{'address': self.address, 'public': False, 'deployed_bytecode': '0x6001600055',
                     'data': {'contract_info': [], 'states': [{'name': 'preserved state'}]},
                     'source_lookup': lookup or {'status': 'failed', 'reason_code': 'source_fetch_failed',
                                                 'retryable': True}}]
        trees = {}
        for tx in self.hashes:
            raw = {'call_type': 'CALL', 'absolute_position': 0, 'to': self.address,
                   'from': '0x' + '9' * 40, 'input': '0x01020304', 'value': '0',
                   'function_file_index': 0, 'function_code_start': 123,
                   'calls': [{'call_type': 'CALL', 'absolute_position': 1, 'to': self.address,
                              'input': '0x01020304'}]}
            tree = MixTraceTree(raw, deepcopy(rows), {})
            tree.original_trace = deepcopy(raw)
            tree.baseline_validation = {'receipt_digest': 'synthetic preserved receipt',
                                        'original_transaction_hash': tx, 'block_number': 42}
            tree._function_source_cache = {(self.address, '0x01020304', 'stale'): None,
                                           ('unrelated', 'selector', 'digest'): {'keep': True}}
            tree.root.source_resolution = {'file_index': 0, 'filename': 'stale.sol'}
            trees[tx] = tree
        session = object.__new__(server.SessionContext)
        session.tx2micro = trees
        session.current_tx = self.hashes[0]
        session.active_sessions = {tx: SimpleNamespace(node_map={
            index: SimpleNamespace(mix_trace_item=item) for index, item in tree.node_map.items()})
            for tx, tree in trees.items()}
        session.loader = (SimpleNamespace(apikey_bucket=Mock(get=AsyncMock(return_value='offline-source-key')))
                          if configured else None)
        agent = object.__new__(FixAgent)
        agent._check_cancelled = Mock(); agent.session_id = 'offline-source-refresh'
        agent.metrics_collector = None; agent.logger = Mock()
        agent._replay_selection = Mock()
        agent._load_compile_result = AsyncMock(return_value={self.address: SimpleNamespace(
            bytecode='', errors=[{'severity': 'error', 'reason_code': 'compiler_unavailable'}])})
        agent.query = AsyncMock(side_effect=AssertionError('No model call allowed'))
        agent.run_patch_verification_from_tenderly = AsyncMock(side_effect=AssertionError('No replay allowed'))

        async def call_tool(name, arguments):
            self.assertEqual(name, 'get_patch_items')
            return await server.get_patch_items.fn(**arguments)

        agent.mcp_client = Mock(call_tool=AsyncMock(side_effect=call_tool))
        resolution = {'filename': 'Synthetic.sol', 'code_start': self.source.index('function ping'),
                      'code_length': len('function ping() external {}'), 'function_name': 'ping',
                      'source_mapping': 'compiled_ast_function_selector', 'selector': '0x01020304'}
        with patch.object(server, '_get_session_context', return_value=session), patch.object(
                server, '_get_target_tree', side_effect=lambda context, tx: trees[tx]), patch.object(
                server, 'ContractSourceDownloader', return_value=downloader) as factory, patch.object(
                server.ContractDao, 'resolve_source_function', AsyncMock(return_value=resolution)) as resolver:
            yield SimpleNamespace(agent=agent, session=session, trees=trees, downloader=downloader,
                                  factory=factory, resolver=resolver, bytecode=bytecode, server=server)

    def fault_data(self):
        return {'fix_report': {'faulty_functions': [{'trigger_point': {
            'transaction_hash': self.hashes[0], 'index': 0}}]}}

    async def test_empty_placeholder_source_recovers_without_changing_metadata_or_historical_evidence(self):
        from app.attackpilot.entities.contract import ContractEntity

        for placeholder in ('', ' \n\t'):
            with self.subTest(placeholder=repr(placeholder)):
                async with self.scenario([self.source_response()]) as case:
                    tree = case.trees[self.hashes[0]]
                    raw = deepcopy(tree.contracts[self.address].to_dict())
                    raw['data']['contract_info'] = [
                        {'id': 7, 'path': 'Synthetic.sol', 'source': placeholder}]
                    raw['data']['abi'] = [{'type': 'function', 'name': 'ping', 'inputs': []}]
                    raw['data']['methods'] = [{'name': 'preserved method'}]
                    raw['creation_bytecode'], raw['src_map'] = '0x6000', '0:0:0'
                    old_contract = ContractEntity(raw)
                    tree.contracts[self.address] = old_contract
                    root, baseline = tree.root, tree.baseline_validation
                    historical = deepcopy((tree.original_trace, baseline, root.function_loc.__dict__,
                                           old_contract.deployed_bytecode, old_contract.creation_bytecode,
                                           old_contract.src_map))
                    metadata = deepcopy((old_contract.states, old_contract.methods, old_contract.abi))

                    outcome = await case.agent.handle(self.fault_data())

                    self.assertFalse(outcome[0])
                    self.assertEqual(case.agent.verification['reason_code'], 'compiler_unavailable')
                    case.agent._load_compile_result.assert_awaited_once()
                    entity = case.agent._load_compile_result.call_args.args[0][self.address]
                    self.assertEqual(entity.sources['Synthetic.sol'], self.source)
                    self.assertEqual(entity.full_file_map['7']['path'], 'Synthetic.sol')
                    recovered = tree.contracts[self.address]
                    self.assertEqual(recovered.source_lookup['status'], 'available')
                    self.assertTrue(recovered.source_lookup['refresh_attempted'])
                    self.assertEqual((recovered.states, recovered.methods, recovered.abi), metadata)
                    self.assertIs(tree.root, root)
                    self.assertIs(tree.baseline_validation, baseline)
                    self.assertEqual((tree.original_trace, baseline, root.function_loc.__dict__,
                                      recovered.deployed_bytecode, recovered.creation_bytecode,
                                      recovered.src_map), historical)
                    self.assertEqual(old_contract.contract_info[0]['source'], placeholder)
                    case.downloader.download.assert_awaited_once_with(contract_address=self.address)
                    self.assertEqual(case.agent.mcp_client.call_tool.await_count, 2)
                    self.assertTrue(case.agent.mcp_client.call_tool.await_args_list[1].args[1]['refresh_source'])
                    case.agent.query.assert_not_awaited()
                    case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_placeholder_source_refresh_failure_retains_failed_lookup_diagnostics(self):
        from app.attackpilot.entities.contract import ContractEntity

        for placeholder in ('', ' \n\t'):
            with self.subTest(placeholder=repr(placeholder)):
                async with self.scenario([httpx.ConnectTimeout('synthetic repeat failure')]) as case:
                    tree = case.trees[self.hashes[0]]
                    raw = deepcopy(tree.contracts[self.address].to_dict())
                    raw['data']['contract_info'] = [
                        {'id': 7, 'path': 'Synthetic.sol', 'source': placeholder}]
                    old_contract = ContractEntity(raw)
                    tree.contracts[self.address] = old_contract
                    historical = deepcopy((tree.original_trace, tree.baseline_validation,
                                           old_contract.data, old_contract.deployed_bytecode))

                    result = await case.agent.handle(self.fault_data())

                    self.assertFalse(result[0])
                    state = case.agent.verification
                    self.assertEqual(state['reason_code'], 'source_fetch_failed')
                    self.assertEqual(state['source_lookup']['status'], 'failed')
                    self.assertTrue(state['source_lookup']['refresh_attempted'])
                    self.assertTrue(state['retryable'])
                    self.assertIs(tree.contracts[self.address], old_contract)
                    self.assertEqual((tree.original_trace, tree.baseline_validation,
                                      old_contract.data, old_contract.deployed_bytecode), historical)
                    case.downloader.download.assert_awaited_once_with(contract_address=self.address)
                    self.assertEqual(case.agent.mcp_client.call_tool.await_count, 2)
                    case.agent._load_compile_result.assert_not_awaited()
                    case.agent.query.assert_not_awaited()
                    case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_refresh_preserves_existing_file_ids_and_reserves_removed_file_ids(self):
        from app.attackpilot.entities.contract import ContractEntity

        async with self.scenario([self.source_response()]) as case:
            tree = case.trees[self.hashes[0]]
            raw = deepcopy(tree.contracts[self.address].to_dict())
            raw['data']['contract_info'] = [
                {'id': 0, 'path': 'Synthetic.sol', 'source': ''},
                {'id': 1, 'path': 'Removed.sol', 'source': ''}]
            tree.contracts[self.address] = ContractEntity(raw)
            historical = deepcopy((tree.original_trace, tree.baseline_validation, tree.root.function_loc.__dict__))

            result = await case.agent.handle(self.fault_data())

            self.assertFalse(result[0])
            self.assertEqual(case.agent.verification['reason_code'], 'compiler_unavailable')
            case.agent._load_compile_result.assert_awaited_once()
            entity = case.agent._load_compile_result.call_args.args[0][self.address]
            self.assertEqual({file['path']: file['id'] for file in entity.full_file_map.values()},
                             {'Other.sol': 2, 'Synthetic.sol': 0})
            item = await case.server.get_patch_items.fn(case.agent.session_id, self.hashes[0] + '::0')
            self.assertEqual(item['file_index'], 0)
            self.assertEqual(item['source_mapping']['filename'], 'Synthetic.sol')
            self.assertEqual((tree.original_trace, tree.baseline_validation, tree.root.function_loc.__dict__),
                             historical)
            case.downloader.download.assert_awaited_once_with(contract_address=self.address)
            case.agent.query.assert_not_awaited()
            case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_refresh_rejects_ambiguous_existing_source_ids_without_changing_contract(self):
        from app.attackpilot.entities.contract import ContractEntity

        for files in ([{'id': 0, 'path': 'Synthetic.sol', 'source': ''},
                       {'id': 0, 'path': 'Other.sol', 'source': ''}],
                      [{'id': 0, 'path': 'Synthetic.sol', 'source': ''},
                       {'id': 1, 'path': 'Synthetic.sol', 'source': ''}]):
            with self.subTest(files=files):
                async with self.scenario([self.source_response()]) as case:
                    tree = case.trees[self.hashes[0]]
                    raw = deepcopy(tree.contracts[self.address].to_dict())
                    raw['data']['contract_info'] = files
                    old_contract = ContractEntity(raw)
                    tree.contracts[self.address] = old_contract
                    historical = deepcopy((tree.original_trace, tree.baseline_validation,
                                           old_contract.data, old_contract.deployed_bytecode))

                    result = await case.agent.handle(self.fault_data())

                    self.assertFalse(result[0])
                    self.assertEqual(case.agent.verification['reason_code'], 'source_fetch_failed')
                    self.assertIs(tree.contracts[self.address], old_contract)
                    self.assertEqual((tree.original_trace, tree.baseline_validation,
                                      old_contract.data, old_contract.deployed_bytecode), historical)
                    self.assertEqual(case.session._source_refresh_results, {})
                    case.agent._load_compile_result.assert_not_awaited()
                    case.agent.query.assert_not_awaited()
                    case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_timeout_then_source_recovery_resumes_preparation_without_changing_original_evidence(self):
        async with self.scenario([httpx.ConnectTimeout('synthetic timeout'), self.source_response()],
                                 initialize=True) as case:
            tree = case.trees[self.hashes[0]]
            root, baseline = tree.root, tree.baseline_validation
            original = deepcopy((tree.original_trace, baseline, root.function_loc.__dict__,
                                 tree.contracts[self.address].deployed_bytecode))
            outcome = await case.agent.handle(self.fault_data())
            self.assertFalse(outcome[0])
            self.assertEqual(case.agent.verification['reason_code'], 'compiler_unavailable')
            case.agent._load_compile_result.assert_awaited_once()
            compiled_entity = case.agent._load_compile_result.call_args.args[0][self.address]
            self.assertEqual(compiled_entity.sources['Synthetic.sol'], self.source)
            self.assertEqual(case.downloader.download.await_count, 2)
            case.bytecode.download.assert_awaited_once_with(contract_address=self.address, quantity=42)
            self.assertIs(tree.root, root)
            self.assertIs(tree.baseline_validation, baseline)
            self.assertEqual((tree.original_trace, baseline, root.function_loc.__dict__,
                              tree.contracts[self.address].deployed_bytecode), original)
            self.assertNotIn((self.address, '0x01020304', 'stale'), tree._function_source_cache)
            self.assertEqual(tree._function_source_cache[('unrelated', 'selector', 'digest')], {'keep': True})
            item = await case.server.get_patch_items.fn(case.agent.session_id, self.hashes[0] + '::0')
            self.assertEqual(item['file_index'], 1)
            self.assertEqual(item['source_mapping']['filename'], 'Synthetic.sol')
            self.assertEqual(root.function_source, 'function ping() external {}')
            self.assertEqual(case.agent.verification['patch_generation_budget']['requests_used'], 0)
            case.agent.query.assert_not_awaited()
            case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_repeated_failure_is_bounded_per_agent_and_session_address(self):
        async with self.scenario([httpx.ConnectTimeout('synthetic repeat failure')]) as case:
            for _ in range(2):
                result = await case.agent.handle(self.fault_data())
                self.assertFalse(result[0])
                self.assertEqual(case.agent.verification['reason_code'], 'source_fetch_failed')
            await case.server.get_patch_items.fn(case.agent.session_id, self.hashes[0] + '::1', refresh_source=True)
            self.assertEqual(case.downloader.download.await_count, 1)
            refresh_calls = [call for call in case.agent.mcp_client.call_tool.call_args_list
                             if call.args[1].get('refresh_source') is True]
            self.assertEqual(len(refresh_calls), 1)
            self.assertEqual(case.session._source_refresh_attempted_addresses, {self.address})
            case.agent._load_compile_result.assert_not_awaited()
            case.agent.query.assert_not_awaited()

    async def test_recovered_response_is_reused_for_same_address_in_another_transaction(self):
        async with self.scenario([self.source_response()]) as case:
            for tx in self.hashes:
                item = await case.agent._get_patch_item(tx + '::0')
                self.assertEqual(item['source_lookup']['status'], 'available')
                self.assertEqual(item['file_index'], 1)
                self.assertEqual(case.trees[tx].contracts[self.address].deployed_bytecode, '0x6001600055')
                self.assertEqual(case.trees[tx].baseline_validation['original_transaction_hash'], tx)
            self.assertEqual(case.downloader.download.await_count, 1)
            self.assertEqual(sum(call.args[1].get('refresh_source') is True
                                 for call in case.agent.mcp_client.call_tool.call_args_list), 1)

    async def test_unverified_and_permanent_failures_do_not_refresh(self):
        for lookup in ({'status': 'unverified', 'retryable': False},
                       {'status': 'failed', 'retryable': False}):
            with self.subTest(lookup=lookup):
                async with self.scenario([], lookup=lookup) as case:
                    result = await case.agent.handle(self.fault_data())
                    self.assertFalse(result[0])
                    self.assertEqual(case.agent.mcp_client.call_tool.await_count, 1)
                    case.factory.assert_not_called()
                    case.agent._load_compile_result.assert_not_awaited()
                    case.agent.query.assert_not_awaited()

    async def test_refresh_cancellation_propagates_and_preserves_original_contract(self):
        async with self.scenario([asyncio.CancelledError()]) as case:
            tree = case.trees[self.hashes[0]]
            old = tree.contracts[self.address]
            original = deepcopy(old.to_dict())
            with self.assertRaises(asyncio.CancelledError):
                await case.agent.handle(self.fault_data())
            self.assertIs(tree.contracts[self.address], old)
            self.assertEqual(old.to_dict(), original)
            self.assertEqual(case.downloader.download.await_count, 1)
            case.agent._load_compile_result.assert_not_awaited()
            case.agent.query.assert_not_awaited()

    async def test_missing_refresh_configuration_remains_a_failed_lookup(self):
        async with self.scenario([], configured=False) as case:
            result = await case.agent.handle(self.fault_data())
            lookup = case.trees[self.hashes[0]].contracts[self.address].source_lookup
            self.assertFalse(result[0])
            self.assertEqual(lookup['status'], 'failed')
            self.assertEqual(lookup['refresh_reason_code'], 'source_configuration_unavailable')
            self.assertEqual(case.agent.verification['source_lookup']['refresh_reason_code'],
                             'source_configuration_unavailable')
            self.assertFalse(lookup['retryable'])
            case.factory.assert_not_called()
            case.agent._load_compile_result.assert_not_awaited()
            case.agent.query.assert_not_awaited()

    async def test_investigation_function_recovery_is_reused_by_patch_preparation(self):
        async with self.scenario([self.source_response()]) as case:
            tree = case.trees[self.hashes[0]]
            original = deepcopy((tree.original_trace, tree.baseline_validation,
                                 tree.root.function_loc.__dict__))
            source = await case.server.get_function_source_code.fn(case.agent.session_id, 0)
            self.assertIn('File: Synthetic.sol', source)
            self.assertIn('function ping() external {}', source)
            self.assertIn('Source mapping: compiled_ast_function_selector', source)
            self.assertNotIn('stale.sol', source)
            item = await case.server.get_patch_items.fn(
                case.agent.session_id, self.hashes[0] + '::0', refresh_source=True)
            self.assertEqual(item['file_index'], 1)
            self.assertEqual(item['source_mapping']['filename'], 'Synthetic.sol')
            self.assertEqual(item['source_lookup']['status'], 'available')
            self.assertEqual(case.downloader.download.await_count, 1)
            case.resolver.assert_awaited_once()
            self.assertEqual((tree.original_trace, tree.baseline_validation,
                              tree.root.function_loc.__dict__), original)
            case.agent.query.assert_not_awaited()
            case.agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_investigation_contract_recovery_is_reused_across_transaction_trees(self):
        async with self.scenario([self.source_response()]) as case:
            for tx in self.hashes:
                case.session.current_tx = tx
                source = await case.server.get_contract_source_code.fn(case.agent.session_id, 0)
                self.assertEqual(source, self.source)
                function = await case.server.get_function_source_code.fn(case.agent.session_id, 0)
                self.assertIn('File: Synthetic.sol', function)
                item = await case.server.get_patch_items.fn(case.agent.session_id, tx + '::0')
                self.assertEqual(item['file_index'], 1)
                self.assertEqual(item['source_mapping']['filename'], 'Synthetic.sol')
                self.assertEqual(case.trees[tx].baseline_validation['original_transaction_hash'], tx)
            self.assertEqual(case.downloader.download.await_count, 1)
            self.assertEqual(case.resolver.await_count, 2)
            self.assertEqual(case.session._source_refresh_attempted_addresses, {self.address})
        async with self.scenario([self.source_response()]) as case:
            case.resolver.side_effect = ValueError('synthetic selector mapping unavailable')
            source = await case.server.get_function_source_code.fn(case.agent.session_id, 0)
            self.assertIn('Function source unavailable', source)
            self.assertIn('reason_code=function_source_mapping_unavailable', source)
            self.assertIn('source_status=available', source)
            contract = await case.server.get_contract_source_code.fn(case.agent.session_id, 0)
            self.assertIn('File: Synthetic.sol', contract)
            self.assertIn(self.source, contract)
            item = await case.server.get_patch_items.fn(case.agent.session_id, self.hashes[0] + '::0')
            self.assertEqual(item['file_index'], -1)
            self.assertIsNone(item['source_mapping'])
            self.assertEqual(case.downloader.download.await_count, 1)
            case.resolver.assert_awaited_once()

    async def test_investigation_failed_lookup_returns_diagnostics_with_one_shared_refresh(self):
        async with self.scenario([httpx.ConnectTimeout('synthetic investigation failure')]) as case:
            for tx in self.hashes:
                case.session.current_tx = tx
                for tool in (case.server.get_function_source_code, case.server.get_contract_source_code):
                    source = await tool.fn(case.agent.session_id, 0)
                    self.assertIn('source unavailable', source)
                    self.assertIn('reason_code=source_fetch_failed', source)
                    self.assertIn('source_status=failed', source)
                    self.assertNotIn('source_not_verified', source)
                    self.assertNotIn('File:', source)
            item = await case.server.get_patch_items.fn(
                case.agent.session_id, self.hashes[0] + '::0', refresh_source=True)
            self.assertEqual(item['source_lookup']['status'], 'failed')
            self.assertEqual(case.downloader.download.await_count, 1)
            case.resolver.assert_not_awaited()

    async def test_investigation_unverified_or_permanent_lookup_does_not_refresh(self):
        for lookup in ({'status': 'unverified', 'retryable': False},
                       {'status': 'failed', 'retryable': False}, {}):
            with self.subTest(lookup=lookup):
                async with self.scenario([], lookup=lookup) as case:
                    if not lookup:
                        for tree in case.trees.values():
                            tree.contracts[self.address].source_lookup = None
                    for tool in (case.server.get_function_source_code, case.server.get_contract_source_code):
                        source = await tool.fn(case.agent.session_id, 0)
                        self.assertIn('source unavailable', source)
                        self.assertIn(f"source_status={lookup.get('status', 'unknown')}", source)
                        if lookup.get('status') != 'unverified':
                            self.assertNotIn('source_not_verified', source)
                    case.factory.assert_not_called()
                    case.downloader.download.assert_not_awaited()
                    case.resolver.assert_not_awaited()

    async def test_investigation_refresh_cancellation_preserves_contract_and_propagates(self):
        for name in ('get_function_source_code', 'get_contract_source_code'):
            with self.subTest(tool=name):
                async with self.scenario([asyncio.CancelledError()]) as case:
                    tree = case.trees[self.hashes[0]]
                    original_contract = tree.contracts[self.address]
                    original = deepcopy(original_contract.to_dict())
                    with self.assertRaises(asyncio.CancelledError):
                        await getattr(case.server, name).fn(case.agent.session_id, 0)
                    self.assertIs(tree.contracts[self.address], original_contract)
                    self.assertEqual(original_contract.to_dict(), original)
                    self.assertEqual(case.downloader.download.await_count, 1)
                    case.resolver.assert_not_awaited()


class PatchCompilerRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Exercise compiler selection and the real patch preconditions without paid services."""

    address = '0x' + '1' * 40
    transaction_hash = '0x' + 'a' * 64
    version = 'v0.8.23+commit.f704f362'

    def entity(self, *, version=None):
        from app.attackpilot.entities.contract import ContractEntityForCompile

        return ContractEntityForCompile.from_dict({
            'address': self.address, 'contract_name': 'Vault',
            'compiler_version': version or self.version,
            'sources': {'Vault.sol': 'pragma solidity ^0.8.0; contract Vault {}'},
            'optimizations_used': False, 'optimization_runs': 200,
        })

    def agent(self):
        from app.attackpilot.agents.FixAgent import FixAgent

        agent = FixAgent.__new__(FixAgent)
        agent._check_cancelled = Mock()
        agent.session_id = 'offline-compiler-test'
        agent.metrics_collector = None
        agent.logger = Mock()
        agent.processed_data = {
            'transaction_hash_list': [self.transaction_hash],
            'transaction_to_detail': {self.transaction_hash: {'block_number': 1}},
            'attack_transactions': [self.transaction_hash],
        }
        agent.mcp_client = Mock()
        agent.mcp_client.call_tool = AsyncMock(return_value={
            'address': self.address, 'file_index': 0, 'contract_name': 'Vault',
            'compiler_version': self.version, 'optimizations_used': False,
            'optimization_runs': 200,
            'contract_info': [{'id': 0, 'path': 'Vault.sol',
                               'source': 'pragma solidity ^0.8.0; contract Vault {}'}],
        })
        for name in ('query', '_load_runtime_bytecode', 'compile_patched_codes',
                     'prepare_bundle_data', '_deploy_contracts', 'run_patch_verification_from_tenderly'):
            setattr(agent, name, AsyncMock(side_effect=AssertionError(f'Unexpected later stage: {name}')))
        return agent

    def fault_data(self):
        return {'fix_report': {'faulty_functions': [{
            'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 0},
        }]}}

    def assert_compile_stopped(self, agent, outcome, reason_code):
        self.assertFalse(outcome[0])
        self.assertEqual(outcome[2:], ('', 0))
        self.assertEqual(agent.verification['status'], 'blocked')
        self.assertEqual(agent.verification['stage'], 'compile')
        self.assertEqual(agent.verification['reason_code'], reason_code)
        self.assertFalse(agent.verification['replay_attempted'])
        self.assertFalse(agent.verification['replay_completed'])
        self.assertTrue(agent.verification['terminal'])
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 0)
        for name in ('query', '_load_runtime_bytecode', 'compile_patched_codes',
                     'prepare_bundle_data', '_deploy_contracts', 'run_patch_verification_from_tenderly'):
            getattr(agent, name).assert_not_awaited()
        diagnostic = agent.verification['compile_diagnostics'][0]
        self.assertEqual(diagnostic['address'], self.address)
        self.assertEqual(diagnostic['contract_name'], 'Vault')
        self.assertEqual(diagnostic['compiler_version'], self.version)
        self.assertEqual(diagnostic['reason_code'], reason_code)
        self.assertTrue(diagnostic['errors'])

    def runtime_proposal(self, body):
        return (f'# File: {self.address}::Vault.sol\n<<<<<<< SEARCH\n'
                'pragma solidity ^0.8.0; contract Vault {}\n=======\n'
                f'pragma solidity ^0.8.0; contract Vault {{{body}}}\n>>>>>>> REPLACE')

    @asynccontextmanager
    async def runtime_scenario(self, proposals, runtime_results):
        from types import SimpleNamespace
        from app.attackpilot.utils.bytecode_transplanter import BytecodeTransplanter

        agent = self.agent()
        original = SimpleNamespace(bytecode='6001600055', errors=[])
        changed = SimpleNamespace(bytecode='6002600055', errors=[])
        agent._load_compile_result = AsyncMock(return_value={self.address: original})
        agent._load_runtime_bytecode = AsyncMock(return_value={self.address: original.bytecode})
        agent.query = AsyncMock(side_effect=proposals) if isinstance(proposals, list) else AsyncMock(return_value=proposals)
        agent.compile_patched_codes = AsyncMock(return_value=(True, {self.address: changed}))
        agent.prepare_bundle_data = AsyncMock(return_value=[{'original_transaction_hash': self.transaction_hash}])
        agent.run_patch_verification_from_tenderly = AsyncMock(return_value=(True, {
            'schema_version': 1, 'status': 'completed', 'control_validation': 'validated',
            'transactions': [{'original_transaction_hash': self.transaction_hash}],
        }))
        transplant = Mock(side_effect=runtime_results) if isinstance(runtime_results, list) else Mock(return_value=runtime_results)
        with patch.object(BytecodeTransplanter, 'validate_original', return_value={}) as validate, patch.object(
            BytecodeTransplanter, '_storage_signature', return_value=[]
        ), patch.object(BytecodeTransplanter, 'transplant', transplant):
            yield agent, validate, transplant

    async def test_runtime_candidate_errors_are_revised_before_any_replay(self):
        good = self.runtime_proposal('function guard() external { require(msg.sender != address(0)); }')
        cases = (
            ('constructor_or_immutable_changed', self.runtime_proposal('constructor() {}')),
            ('storage_layout_changed', self.runtime_proposal('uint added;')),
            ('patch_runtime_unchanged', self.runtime_proposal('/* comment only */')),
        )
        for code, bad in cases:
            with self.subTest(code=code):
                first_result = ((True, '0x6001600055', 'unchanged') if code == 'patch_runtime_unchanged'
                                else (False, '', f'{code}: synthetic candidate diagnostic'))
                async with self.runtime_scenario([bad, good], [first_result, (True, '0x6002600055', 'validated')]) as (agent, _, transplant):
                    outcome = await agent.handle(self.fault_data())
                self.assertTrue(outcome[0])
                self.assertEqual(outcome[3], 1)
                self.assertEqual(agent.query.await_count, 2)
                self.assertIn(code, agent.query.await_args_list[1].args[0])
                self.assertIn('Do not repeat this rejected patch', agent.query.await_args_list[1].args[0])
                self.assertEqual(agent.compile_patched_codes.await_count, 2)
                self.assertEqual(transplant.call_count, 2)
                agent._load_compile_result.assert_awaited_once()
                agent._load_runtime_bytecode.assert_awaited_once()
                agent.prepare_bundle_data.assert_awaited_once()
                agent.run_patch_verification_from_tenderly.assert_awaited_once()
                agent._deploy_contracts.assert_not_awaited()
                self.assertEqual(agent.verification['status'], 'unverified')
                self.assertTrue(agent.verification['replay_completed'])
                rejection = agent.verification['rejected_patch_candidates'][0]
                self.assertEqual(rejection['reason_code'], code)
                self.assertEqual(rejection['generation_requests'], [1])
                self.assertNotIn(rejection['applied_patch_sha256'], {item[0] for item in agent._replayed_patch_digests})
                self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 2)

    async def test_repeated_rejected_candidate_consumes_generation_without_recompilation(self):
        bad = self.runtime_proposal('constructor() {}')
        good = self.runtime_proposal('function guard() external { require(msg.sender != address(0)); }')
        rejection = (False, '', 'constructor_or_immutable_changed: preserve initialization')
        async with self.runtime_scenario([bad, bad, good], [rejection, (True, '0x6002600055', 'validated')]) as (agent, _, transplant):
            outcome = await agent.handle(self.fault_data())
        self.assertTrue(outcome[0])
        self.assertEqual(outcome[3], 2)
        self.assertEqual(agent.query.await_count, 3)
        self.assertEqual(agent.compile_patched_codes.await_count, 2)
        self.assertEqual(transplant.call_count, 2)
        self.assertEqual(agent.verification['rejected_patch_candidates'][0]['generation_requests'], [1, 2])
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 3)
        agent.run_patch_verification_from_tenderly.assert_awaited_once()

    async def test_runtime_revision_discards_partial_codes_from_rejected_multicontract_patch(self):
        from types import SimpleNamespace

        second_address = '0x' + '2' * 40
        first_patch = self.runtime_proposal('function firstGuard() external {}')
        second_bad = self.runtime_proposal('uint added;').replace(self.address, second_address)
        second_good = self.runtime_proposal('function secondGuard() external {}').replace(self.address, second_address)
        results = [(True, '0x6002600055', 'first contract validated'),
                   (False, '', 'storage_layout_changed: second contract changed its slots'),
                   (True, '0x6003600055', 'second contract validated')]
        async with self.runtime_scenario([first_patch + '\n\n' + second_bad, second_good], results) as (agent, _, transplant):
            first_item = deepcopy(agent.mcp_client.call_tool.return_value)
            second_item = {**deepcopy(first_item), 'address': second_address}
            agent.mcp_client.call_tool.side_effect = [first_item, second_item]
            original = SimpleNamespace(bytecode='6001600055', errors=[])
            agent._load_compile_result.return_value = {self.address: original, second_address: original}
            agent._load_runtime_bytecode.return_value = {self.address: original.bytecode, second_address: original.bytecode}
            compiled = SimpleNamespace(bytecode='6002600055', errors=[])
            agent.compile_patched_codes.side_effect = [
                (True, {self.address: compiled, second_address: compiled}),
                (True, {second_address: compiled}),
            ]
            fault_data = self.fault_data()
            fault_data['fix_report']['faulty_functions'].append({
                'trigger_point': {'transaction_hash': self.transaction_hash, 'index': 1},
            })
            outcome = await agent.handle(fault_data)
        self.assertTrue(outcome[0])
        self.assertEqual(transplant.call_count, 3)
        self.assertEqual(agent.run_patch_verification_from_tenderly.await_args.args[1],
                         {second_address: '0x6003600055'})
        self.assertEqual(set(agent.verification['runtime_integrity']['contracts']), {second_address})
        self.assertEqual(len(agent._replayed_patch_digests), 1)
        agent.prepare_bundle_data.assert_awaited_once()
        agent._deploy_contracts.assert_not_awaited()

    async def test_analysis_preserves_rejection_history_after_replay_adjudication(self):
        from app.attackpilot.process import analyze
        from app.attackpilot.utils.verification import replay_evidence_digest

        fixture = ReplayEvidenceRegressionTests(); fixture.setUp()
        bad = self.runtime_proposal('constructor() {}')
        good = self.runtime_proposal(
            'function guard(uint requested, uint balance) external { '
            f'require(requested <= balance, "{fixture.guard_reason}"); }}')
        runtime_results = [(False, '', 'constructor_or_immutable_changed: preserve initialization'),
                           (True, '0x6000600060005bfd', 'validated')]
        for valid in (True, False):
            with self.subTest(valid_replay=valid):
                replay = fixture.report(patches=good)
                if not valid:
                    replay['scope'] = 'missing_paired_replay_scope'
                async with self.runtime_scenario([bad, good], runtime_results) as (agent, _, _):
                    agent.token = 0
                    agent.get_total_time = Mock(return_value=0)
                    agent.run_patch_verification_from_tenderly.return_value = (True, replay)
                    data = {**agent.processed_data, 'balance_change': {},
                            'dapp': {'name': 'offline-runtime-revision', 'platform': 'Ethereum'},
                            'transactions_need_analyze': [self.transaction_hash]}
                    trace = Mock(token=0)
                    trace.get_total_time.return_value = 0
                    trace.init_transactions = AsyncMock()
                    trace.handle = AsyncMock(return_value={
                        'reason': 'READY_FOR_PATCH',
                        'data': ['synthetic root cause', '[0] CALL Vault.guard', self.fault_data()['fix_report']],
                    })
                    judged_inputs = []

                    def adjudicate(judge_result, evidence, patches):
                        judged_inputs.append(deepcopy(evidence))
                        return adjudicate_patch_verification(judge_result, evidence, patches)

                    async def deliver(judge_result, hypothesis, evidence, patches):
                        return json.dumps(report_evidence(judge_result, evidence))

                    with patch.object(analyze, 'GlobalMemoryAgent') as memory_factory, patch.object(
                        analyze, 'TaskAgent'
                    ) as task_factory, patch.object(analyze, 'FixAgent', return_value=agent), patch.object(
                        analyze, 'JudgeAgent'
                    ) as judge_factory, patch.object(
                        analyze, 'adjudicate_patch_verification', side_effect=adjudicate
                    ), patch('app.attackpilot.agents.FixAgent.build_patch_attribution',
                             return_value=deepcopy(replay['patch_attribution'])):
                        memory = memory_factory.return_value
                        tasks = task_factory.return_value
                        judge = judge_factory.return_value
                        for boundary in (memory, tasks, judge):
                            boundary.token = 0
                            boundary.get_total_time.return_value = 0
                        memory.global_memory = {}
                        memory.update = AsyncMock()
                        memory.get_final_result = AsyncMock(side_effect=deliver)
                        tasks.handle = AsyncMock()
                        tasks.end_analyze = AsyncMock()
                        judge.handle = AsyncMock(return_value={'verdict': 'VERIFIED'})
                        runner = analyze.DAppAnalyze(
                            data, trace, {'Ethereum': None}, {'Ethereum': None}, None,
                            enabled_modules=['fault_localization', 'patch_generation', 'patch_verification'])
                        report, items = await runner.analyze()
                expected_status = 'verified' if valid else 'unverified'
                self.assertEqual(items['verification']['status'], expected_status)
                self.assertEqual(json.loads(report)['verification']['status'], expected_status)
                self.assertEqual(agent.query.await_count, 2)
                judge.handle.assert_awaited_once()
                memory.get_final_result.assert_awaited_once()
                history = items['verification']['rejected_patch_candidates']
                self.assertEqual(history, agent.verification['rejected_patch_candidates'])
                self.assertEqual(history, json.loads(report)['verification']['rejected_patch_candidates'])
                self.assertIsNot(history, agent.verification['rejected_patch_candidates'])
                self.assertIsNot(history[0], agent.verification['rejected_patch_candidates'][0])
                self.assertEqual(judged_inputs, [items['replay_evidence']])
                self.assertEqual(items['verification']['replay_evidence_sha256'],
                                 replay_evidence_digest(judged_inputs[0]))
                self.assertNotIn('rejected_patch_candidates', judged_inputs[0])
                history[0]['reason'] = 'downstream diagnostic edit'
                history[0]['generation_requests'].append(999)
                self.assertNotEqual(history, agent.verification['rejected_patch_candidates'])
                self.assertEqual(agent.verification['rejected_patch_candidates'][0]['generation_requests'], [1])
                self.assertEqual(judged_inputs, [items['replay_evidence']])
                self.assertEqual(replay_evidence_digest(items['replay_evidence']),
                                 items['verification']['replay_evidence_sha256'])

    async def test_runtime_rejection_exhaustion_preserves_reason_patch_and_task_budget(self):
        from app.attackpilot.agents.FixAgent import MAX_PATCH_GENERATION_REQUESTS

        bad = self.runtime_proposal('constructor() {}')
        rejection = (False, '', 'constructor_or_immutable_changed: preserve initialization')
        async with self.runtime_scenario(bad, rejection) as (agent, _, transplant):
            first = await agent.handle(self.fault_data())
            first_reason = agent.verification['reason']
            second = await agent.handle(self.fault_data())
        self.assertFalse(first[0])
        self.assertFalse(second[0])
        self.assertTrue(first[2])
        self.assertEqual(second[2], first[2])
        self.assertEqual(agent.query.await_count, MAX_PATCH_GENERATION_REQUESTS)
        agent.compile_patched_codes.assert_awaited_once()
        agent._load_compile_result.assert_awaited_once()
        agent._load_runtime_bytecode.assert_awaited_once()
        self.assertEqual(transplant.call_count, 1)
        self.assertEqual(agent.verification['reason_code'], 'constructor_or_immutable_changed')
        self.assertEqual(agent.verification['reason'], first_reason)
        self.assertEqual(agent.verification['generation_stop_reason_code'], 'patch_generation_request_limit')
        self.assertEqual(agent.verification['patch_generation_budget']['remaining_requests'], 0)
        self.assertEqual(agent.verification['rejected_patch_candidates'][0]['generation_requests'],
                         list(range(1, MAX_PATCH_GENERATION_REQUESTS + 1)))
        self.assertEqual(agent.verification['status'], 'blocked')
        self.assertTrue(agent.verification['terminal'])
        self.assertFalse(agent.verification['retryable'])
        self.assertFalse(agent.verification['replay_attempted'])
        self.assertFalse(agent.verification['replay_completed'])
        self.assertFalse(agent._replayed_patch_digests)
        self.assertIsNone(agent._runtime_integrity)
        for name in ('prepare_bundle_data', '_deploy_contracts', 'run_patch_verification_from_tenderly'):
            getattr(agent, name).assert_not_awaited()

    async def test_runtime_revision_budget_remains_cumulative_after_completed_handle(self):
        from app.attackpilot.agents.FixAgent import MAX_PATCH_GENERATION_REQUESTS

        good = self.runtime_proposal('function guard() external { require(msg.sender != address(0)); }')
        bad = self.runtime_proposal('uint added;')
        runtime_results = [(True, '0x6002600055', 'validated'),
                           (False, '', 'storage_layout_changed: preserve original slots')]
        async with self.runtime_scenario([good] + [bad] * (MAX_PATCH_GENERATION_REQUESTS - 1), runtime_results) as (agent, _, transplant):
            self.assertTrue((await agent.handle(self.fault_data()))[0])
            self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 1)
            outcome = await agent.handle(self.fault_data())
        self.assertFalse(outcome[0])
        self.assertEqual(agent.query.await_count, MAX_PATCH_GENERATION_REQUESTS)
        self.assertEqual(agent.compile_patched_codes.await_count, 2)
        self.assertEqual(transplant.call_count, 2)
        self.assertEqual(agent.verification['reason_code'], 'storage_layout_changed')
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], MAX_PATCH_GENERATION_REQUESTS)
        self.assertIsNone(agent._runtime_integrity)
        self.assertIsNone(agent.replay_evidence)
        agent.prepare_bundle_data.assert_awaited_once()
        agent.run_patch_verification_from_tenderly.assert_awaited_once()

    async def test_untrusted_runtime_integrity_errors_stay_terminal(self):
        bad = self.runtime_proposal('constructor() {}')
        for code in ('original_runtime_mismatch', 'storage_layout_unavailable', 'immutable_layout_mismatch', 'unknown_integrity_error'):
            with self.subTest(code=code):
                async with self.runtime_scenario(bad, (False, '', f'{code}: untrusted data')) as (agent, _, _):
                    outcome = await agent.handle(self.fault_data())
                self.assertFalse(outcome[0])
                self.assertEqual(agent.verification['reason_code'], code if code != 'unknown_integrity_error' else 'runtime_generation_failed')
                self.assertTrue(agent.verification['terminal'])
                self.assertFalse(agent.verification['replay_attempted'])
                self.assertNotIn('rejected_patch_candidates', agent.verification)
                agent.query.assert_awaited_once()
                agent.prepare_bundle_data.assert_not_awaited()
                agent.run_patch_verification_from_tenderly.assert_not_awaited()
                agent._deploy_contracts.assert_not_awaited()

    async def test_original_integrity_failure_never_requests_patch_revision(self):
        from app.attackpilot.utils.bytecode_transplanter import RuntimeIntegrityError

        async with self.runtime_scenario([], []) as (agent, validate, transplant):
            validate.side_effect = RuntimeIntegrityError('original_runtime_mismatch', 'historical evidence differs')
            outcome = await agent.handle(self.fault_data())
        self.assertFalse(outcome[0])
        self.assertEqual(agent.verification['reason_code'], 'original_runtime_mismatch')
        self.assertTrue(agent.verification['terminal'])
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 0)
        agent.query.assert_not_awaited()
        agent.compile_patched_codes.assert_not_awaited()
        transplant.assert_not_called()
        agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_cancellation_during_runtime_revision_propagates_without_replay(self):
        bad = self.runtime_proposal('constructor() {}')
        rejection = (False, '', 'constructor_or_immutable_changed: preserve initialization')
        async with self.runtime_scenario([bad, asyncio.CancelledError()], rejection) as (agent, _, transplant):
            with self.assertRaises(asyncio.CancelledError):
                await agent.handle(self.fault_data())
        self.assertEqual(agent.query.await_count, 2)
        self.assertEqual(agent._patch_generation_requests, 2)
        agent.compile_patched_codes.assert_awaited_once()
        self.assertEqual(transplant.call_count, 1)
        self.assertEqual(agent._rejected_patch_candidates[next(iter(agent._rejected_patch_candidates))]['generation_requests'], [1])
        self.assertFalse(agent._replayed_patch_digests)
        agent.prepare_bundle_data.assert_not_awaited()
        agent.run_patch_verification_from_tenderly.assert_not_awaited()

    def test_native_selection_matches_complete_version_commit_and_stable_build(self):
        from app.attackpilot.daos import contract as compiler_contract

        dao = compiler_contract.ContractDao(AsyncMock())
        with tempfile.TemporaryDirectory() as temp, patch.object(
            compiler_contract, 'COMPILER_ROOT', Path(temp)
        ), patch.object(compiler_contract.platform, 'system', return_value='Linux'):
            root = Path(temp)
            (root / 'solc-linux-amd64-v0.8.14+commit.80d49f37').write_bytes(b'fixture')
            self.assertEqual(dao._resolve_solc_path('v0.8.1'), '')
            exact = root / 'solc-linux-amd64-v0.8.1+commit.df193b15'
            exact.write_bytes(b'fixture')
            self.assertEqual(dao._resolve_solc_path('v0.8.1'), str(exact))
            self.assertEqual(dao._resolve_solc_path('v0.8.1+commit.df193b15'), str(exact))
            self.assertEqual(dao._resolve_solc_path('v0.8.1+commit.deadbeef'), '')
            nightly = root / 'solc-linux-amd64-v0.8.23-nightly.2023.10.20+commit.f704f362'
            nightly.write_bytes(b'fixture')
            self.assertEqual(dao._resolve_solc_path(self.version), '')
            self.assertEqual(dao._resolve_solc_path('v0.8.23-nightly.2023.10.20+commit.f704f362'), '')
            self.assertIsNone(dao._compiler_identity('v0.8.23-nightly.2023.10.20+commit.f704f362'))

    async def test_missing_native_and_javascript_compilers_never_start_subprocess(self):
        from app.attackpilot.daos import contract as compiler_contract
        from app.attackpilot.utils import solc

        with tempfile.TemporaryDirectory() as temp, patch.object(
            compiler_contract, 'COMPILER_ROOT', Path(temp) / 'compiler'
        ), patch.object(compiler_contract, 'PROJECT_PATH', temp), patch.object(
            solc.subprocess, 'create_subprocess_exec', AsyncMock(side_effect=AssertionError('No compiler may run'))
        ) as spawn:
            result = await compiler_contract.ContractDao(AsyncMock()).get_compile_item_from_entity(self.entity())
        self.assertFalse(result.is_success())
        self.assertEqual(len(result.errors), 2)
        self.assertEqual({error['reason_code'] for error in result.errors}, {'compiler_unavailable'})
        self.assertTrue(all(self.version in error['message'] for error in result.errors))
        spawn.assert_not_awaited()

    async def test_handle_preserves_compiler_unavailable_diagnostics_and_stops_before_paid_work(self):
        from app.attackpilot.daos import contract as compiler_contract
        from app.attackpilot.utils import solc

        agent = self.agent()
        with tempfile.TemporaryDirectory() as temp, patch.object(
            compiler_contract, 'COMPILER_ROOT', Path(temp) / 'compiler'
        ), patch.object(compiler_contract, 'PROJECT_PATH', temp), patch.object(
            solc.subprocess, 'create_subprocess_exec', AsyncMock(side_effect=AssertionError('No compiler may run'))
        ) as spawn, patch(
            'app.attackpilot.downloaders.contract.ContractSourceDownloader.download',
            AsyncMock(side_effect=AssertionError('No source network request is needed')),
        ) as download:
            outcome = await agent.handle(self.fault_data(), verify=True)
        self.assert_compile_stopped(agent, outcome, 'compiler_unavailable')
        self.assertIn(self.version, outcome[1])
        self.assertEqual(len(agent.verification['compile_diagnostics'][0]['errors']), 2)
        spawn.assert_not_awaited()
        download.assert_not_awaited()
        agent.mcp_client.call_tool.assert_awaited_once_with(
            'get_patch_items', {'session_id': agent.session_id,
                                'faulty_index': f'{self.transaction_hash}::0'})

    async def test_handle_syntax_failure_keeps_original_compile_failed_and_redacts_diagnostics(self):
        from app.attackpilot import privacy
        from app.attackpilot.daos import contract as compiler_contract
        from app.attackpilot.utils import solc, tmpfile

        agent = self.agent()
        agent.mcp_client.call_tool.return_value['contract_info'][0]['source'] = (
            'pragma solidity ^0.8.0; contract Vault { function broken( }'
        )
        compiler_error = solc.CompileResult('', '', {}, [], errors=[{
            'severity': 'error', 'message': 'ParserError: Expected identifier',
            'formattedMessage': 'ParserError: Vault.sol:1:2 api_key=compiler-secret '
                                'unit-private-key https://unit-private-rpc/path',
        }])
        with tempfile.TemporaryDirectory() as temp, patch.object(
            compiler_contract, 'COMPILER_ROOT', Path(temp)
        ), patch.object(compiler_contract, 'PROJECT_PATH', temp), patch.object(
            compiler_contract.platform, 'system', return_value='Linux'
        ), patch.object(tmpfile, 'TMP_FILE_DIR', temp), patch.object(
            solc.Solc, 'compile_json', AsyncMock(return_value=compiler_error)
        ) as compile_source, patch.multiple(
            privacy.settings, LLM_API_KEY='unit-private-key', TENDERLY_API_KEY='',
            WEB3_PROVIDER='https://unit-private-rpc/path', JSONRPCS={}, SCAN_APIKEYS={},
        ):
            executable = Path(temp) / f'solc-linux-amd64-{self.version}'
            executable.write_bytes(b'compiler-fixture')
            outcome = await agent.handle(self.fault_data(), verify=True)
            self.assertEqual(list(Path(temp).iterdir()), [executable])
        self.assert_compile_stopped(agent, outcome, 'original_compile_failed')
        compile_source.assert_awaited_once()
        diagnostic_text = json.dumps(agent.verification['compile_diagnostics'], ensure_ascii=False)
        self.assertIn('ParserError', diagnostic_text)
        self.assertIn('Vault.sol:1:2', diagnostic_text)
        for secret in ('compiler-secret', 'unit-private-key', 'https://unit-private-rpc/path'):
            self.assertNotIn(secret, diagnostic_text)
            self.assertNotIn(secret, str(agent.logger.warning.call_args))

    async def test_installed_javascript_compiler_rejects_wrong_commit_without_network(self):
        import shutil
        from app.attackpilot.daos import contract as compiler_contract
        from app.attackpilot.utils import tmpfile

        package = Path(compiler_contract.PROJECT_PATH) / 'node_modules' / 'solcv0.8.9' / 'package.json'
        if not package.is_file() or shutil.which(compiler_contract.NODE_PATH) is None:
            self.skipTest('Optional local solc 0.8.9 JavaScript package and Node are not installed')
        dao = compiler_contract.ContractDao(AsyncMock())
        source = {
            'ContractName': 'Vault', 'SourceCode': 'pragma solidity ^0.8.9; contract Vault {}',
            'OptimizationUsed': '0', 'Runs': '200', 'Library': '',
        }
        with tempfile.TemporaryDirectory() as temp, patch.object(tmpfile, 'TMP_FILE_DIR', temp):
            rejected = await dao._get_compile_item_by_solcjs(
                self.address, {**source, 'CompilerVersion': 'v0.8.9+commit.deadbeef'})
            accepted = await dao._get_compile_item_by_solcjs(
                self.address, {**source, 'CompilerVersion': 'v0.8.9+commit.e5eed63a'})
            self.assertEqual(list(Path(temp).iterdir()), [])
        self.assertFalse(rejected.is_success())
        self.assertEqual([error.get('reason_code') for error in rejected.errors], ['compiler_unavailable'])
        self.assertTrue(accepted.is_success(), accepted.errors)


class ReportDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """A failed prose service cannot erase prior analysis or upgrade its status."""

    def agent(self, transaction_hash):
        from app.attackpilot.agents.GlobalMemoryAgent import GlobalMemoryAgent
        agent = GlobalMemoryAgent.__new__(GlobalMemoryAgent)
        agent._serialize_memory_for_prompt = Mock(return_value='synthetic investigation')
        agent.global_memory = {'transactions_need_analyze': [transaction_hash]}
        agent.cancellation_checker = lambda: False
        agent.logger = Mock()
        return agent

    def hypothesis(self, transaction_hash):
        return {
            'fault_report': 'Hypothesis: withdraw may exceed the recorded balance.',
            'final_trace': f'{transaction_hash}\n  [4] Vault.withdraw(5)\n    [8] balanceOf(sender)',
            'fix_report': {'faulty_functions': [{
                'trigger_point': {'transaction_hash': transaction_hash, 'index': 4},
                'suggestion': 'Check the recorded balance before the transfer.',
            }]},
        }

    async def test_transport_failure_keeps_verified_or_unverified_evidence_without_replay(self):
        import uuid
        from app.attackpilot.errors import ModelDeadlineError
        for verified in (True, False):
            fixture = ReplayEvidenceRegressionTests()
            fixture.transaction_hash = '0x' + uuid.uuid4().hex + uuid.uuid4().hex
            fixture.setUp()
            replay = fixture.report()
            if not verified:
                replay['status'] = 'incomplete'
            state = fixture.adjudicate(replay)
            judge = {'verification': state, 'verdict': 'VERIFIED' if verified else 'UNVERIFIED'}
            hypothesis = self.hypothesis(fixture.transaction_hash)
            original = deepcopy((judge, replay, hypothesis, fixture.patches))
            agent = self.agent(fixture.transaction_hash)
            agent.query = AsyncMock(side_effect=ModelDeadlineError('private model endpoint'))
            with self.subTest(verified=verified):
                report = await agent.get_final_result(judge, hypothesis, replay, fixture.patches)
                self.assertEqual((judge, replay, hypothesis, fixture.patches), original)
                self.assertIn('已记录的复盘分析', report)
                self.assertIn(fixture.transaction_hash, report)
                self.assertIn(hypothesis['final_trace'], report)
                self.assertIn(fixture.patches, report)
                self.assertIn('正常功能回归 | 未执行', report)
                self.assertIn('整条攻击链顺序回放 | 未验证', report)
                self.assertNotIn('private model endpoint', report)
                self.assertEqual(agent.report_generation, {
                    'status': 'evidence_fallback', 'reason_code': 'report_model_error',
                    'error_type': 'ModelDeadlineError',
                })
                self.assertEqual(state['status'], 'verified' if verified else 'unverified')
                agent.query.assert_awaited_once()

    async def test_empty_or_unusable_prose_uses_complete_prior_analysis(self):
        tx = '0x' + '5' * 64
        for body in ('', ' ', None, {}, 'null', 'ERROR unavailable',
                     '```solidity\ncontract X {}\n```'):
            with self.subTest(body=body):
                agent = self.agent(tx)
                agent.query = AsyncMock(return_value=body)
                report = await agent.get_final_result(
                    {'verification': {'status': 'blocked'}}, self.hypothesis(tx), '', '',
                )
                self.assertIn('已记录的复盘分析', report)
                self.assertIn('无法验证', report)
                self.assertNotIn('触发交易拦截通过', report)
                self.assertEqual(agent.report_generation['reason_code'], 'report_model_output_invalid')
                agent.query.assert_awaited_once()

    async def test_missing_analysis_or_transaction_identity_cannot_be_filled_by_fallback(self):
        from app.attackpilot.errors import ModelDeadlineError
        tx = '0x' + '6' * 64
        for field in ('fault_report', 'final_trace', 'fix_report', 'transactions'):
            agent = self.agent(tx)
            hypothesis = self.hypothesis(tx)
            if field == 'transactions':
                agent.global_memory['transactions_need_analyze'] = ['invented transaction']
            else:
                hypothesis[field] = ''
            failure = ModelDeadlineError('offline timeout')
            agent.query = AsyncMock(side_effect=failure)
            with self.subTest(field=field), self.assertRaises(ModelDeadlineError) as raised:
                await agent.get_final_result({}, hypothesis, '', '')
            self.assertIs(raised.exception, failure)

    async def test_cancellation_and_evidence_errors_are_never_presentation_fallbacks(self):
        from app.attackpilot.errors import EvidencePersistenceError, HistoricalReplayValidationError
        from httpcore import ReadTimeout as CoreReadTimeout
        from openai import APITimeoutError
        tx = '0x' + '9' * 64
        evidence_error = EvidencePersistenceError('synthetic storage failure')
        evidence_error.__context__ = TimeoutError('earlier model timeout')
        failures = [asyncio.CancelledError(), evidence_error,
                    HistoricalReplayValidationError('inconsistent', 'context_mismatch'),
                    TypeError('synthetic programming failure')]
        for failure in (TypeError('programming failure while handling timeout'),
                        OSError('storage failure while handling timeout'),
                        ValueError('unknown failure while handling timeout')):
            failure.__context__ = TimeoutError('earlier model timeout')
            failures.append(failure)
        cancelled = asyncio.CancelledError('wrapped cancellation')
        cancelled.__context__ = TimeoutError('earlier model timeout')
        wrapped_cancel = RuntimeError('synthetic cancellation wrapper')
        wrapped_cancel.__cause__ = cancelled
        for failure in [*failures, wrapped_cancel]:
            expected = cancelled if failure is wrapped_cancel else failure
            agent = self.agent(tx)
            agent.query = AsyncMock(side_effect=failure)
            with self.subTest(error=str(failure)), self.assertRaises(type(expected)) as raised:
                await agent.get_final_result({}, self.hypothesis(tx), '', '')
            self.assertIs(raised.exception, expected)
            self.assertFalse(hasattr(agent, 'report_generation'))

        agent = self.agent(tx)
        agent.name = 'Synthetic report agent'
        agent.memory = []
        model_timeout = APITimeoutError(request=httpx.Request('POST', 'https://offline.invalid/model'))
        transport_timeout = httpx.ReadTimeout('synthetic HTTP timeout', request=model_timeout.request)
        transport_timeout.__cause__ = CoreReadTimeout('synthetic transport timeout')
        transport_timeout.__cause__.__context__ = OSError('synthetic transport internals')
        model_timeout.__cause__ = transport_timeout
        with self.assertRaises(RuntimeError) as wrapped:
            agent._handle_error(model_timeout)
        agent.query = AsyncMock(side_effect=wrapped.exception)
        report = await agent.get_final_result({}, self.hypothesis(tx), '', '')
        self.assertIn('已记录的复盘分析', report)
        self.assertEqual(agent.report_generation['status'], 'evidence_fallback')
        self.assertIs(wrapped.exception.__cause__, model_timeout)

        for translates_to_error in (True, False):
            agent = self.agent(tx)

            async def translate_user_cancel(*args, **kwargs):
                asyncio.current_task().cancel()
                try:
                    await asyncio.sleep(0)
                except asyncio.CancelledError as exc:
                    if translates_to_error:
                        raise APITimeoutError(request=model_timeout.request) from exc
                    return 'synthetic model prose after swallowed cancellation'

            agent.query = AsyncMock(side_effect=translate_user_cancel)
            delivery = asyncio.create_task(agent.get_final_result({}, self.hypothesis(tx), '', ''))
            with self.subTest(translates_to_error=translates_to_error), self.assertRaises(asyncio.CancelledError):
                await delivery
            self.assertTrue(delivery.cancelled())
            self.assertFalse(hasattr(agent, 'report_generation'))

        agent = self.agent(tx)
        agent.cancellation_checker = lambda: True
        agent.query = AsyncMock()
        with self.assertRaises(asyncio.CancelledError):
            await agent.get_final_result({}, self.hypothesis(tx), '', '')
        agent.query.assert_not_awaited()

    async def test_real_model_deadline_preserves_recorded_report_without_external_calls(self):
        from app.attackpilot.errors import ModelDeadlineError, exception_chain
        from app.attackpilot.utils.llm_client import LLMClient

        tx = '0x' + 'd' * 64
        client = object.__new__(LLMClient)
        client.deadline = 0.01
        client.semaphore = asyncio.Semaphore(0)
        client._complete = AsyncMock(side_effect=AssertionError('No external completion is allowed'))
        observed = []

        async def query(*args, **kwargs):
            try:
                return await client.create_chat_completion(messages=[{'role': 'user', 'content': 'synthetic'}])
            except ModelDeadlineError as exc:
                observed.append(exc)
                raise

        agent = self.agent(tx)
        agent.query = AsyncMock(side_effect=query)
        report = await agent.get_final_result({}, self.hypothesis(tx), '', '')
        self.assertIn('已记录的复盘分析', report)
        self.assertEqual(agent.report_generation['error_type'], 'ModelDeadlineError')
        self.assertEqual(len(observed), 1)
        self.assertTrue(any(isinstance(exc, asyncio.CancelledError) for exc in exception_chain(observed[0])))
        self.assertEqual(asyncio.current_task().cancelling(), 0)
        client._complete.assert_not_awaited()

    async def test_cancel_flag_during_timeout_wins_over_report_fallback(self):
        tx = '0x' + 'c' * 64
        agent = self.agent(tx)
        cancelled = False

        async def query(*args, **kwargs):
            nonlocal cancelled
            cancelled = True
            raise TimeoutError('synthetic deadline')

        agent.query = AsyncMock(side_effect=query)
        agent.cancellation_checker = lambda: cancelled
        with self.assertRaises(asyncio.CancelledError):
            await agent.get_final_result({}, self.hypothesis(tx), '', '')
        self.assertFalse(hasattr(agent, 'report_generation'))

    async def test_successful_prose_retains_existing_rendering_and_records_generation(self):
        tx = '0x' + 'd' * 64
        agent = self.agent(tx)
        agent.query = AsyncMock(return_value='Observed trace supports a balance-check hypothesis.')
        report = await agent.get_final_result({}, self.hypothesis(tx), '', '')
        self.assertIn('## 根因与路径分析', report)
        self.assertNotIn('已记录的复盘分析', report)
        self.assertEqual(agent.report_generation, {'status': 'model', 'reason_code': 'generated'})

    async def test_recorded_report_and_diagnostics_survive_workflow_and_worker_delivery(self):
        from types import SimpleNamespace
        from app.attackpilot import api, settings, store, worker, workflow
        from app.attackpilot.process.analyze import DAppAnalyze

        fixture = ReplayEvidenceRegressionTests(); fixture.setUp()
        replay = fixture.report(); replay['status'] = 'incomplete'
        state = fixture.adjudicate(replay)
        source = ResultIntegrityTests(); source.tx_hash = fixture.transaction_hash
        dapp, baseline_result = source.valid_result()
        dapp['enabled_modules'] = sorted(workflow.DEFAULT_ENABLED_MODULES)
        fingerprint = workflow.request_fingerprint(dapp)
        processed = {'dapp': dapp, 'request_fingerprint': fingerprint,
                     'baseline_validation': baseline_result['baseline_validation'],
                     'time_used': {}, 'token_used': {}}
        memory = self.agent(fixture.transaction_hash)
        memory.query = AsyncMock(side_effect=TimeoutError('synthetic prose deadline'))
        memory.get_total_time = Mock(return_value=0); memory.token = 0
        analyzer = DAppAnalyze.__new__(DAppAnalyze)
        analyzer.global_memory_administrator = memory
        analyzer.verification = state; analyzer.replay_evidence = replay
        analyzer.applied_patches = fixture.patches; analyzer.metrics_collector = None
        for name in ('transaction_debugger', 'task_organizer', 'code_patcher', 'transaction_judge'):
            agent = Mock(token=0)
            agent.get_total_time.return_value = 0
            setattr(analyzer, name, agent)

        async def deliver():
            return await analyzer._finish_unverified(self.hypothesis(fixture.transaction_hash),
                                                     replay, fixture.patches)

        analyzer.analyze = AsyncMock(side_effect=deliver)
        client = Mock(connect=AsyncMock(), close=AsyncMock())
        debugger = Mock(close=AsyncMock())
        with patch.object(workflow, 'PatchQualityMetrics'), patch.object(
            workflow, 'MCPClient', return_value=client
        ), patch.object(workflow, 'DAppAnalyze', return_value=analyzer):
            execution = workflow.WorkFlow(use_report_cache=False, write_report_cache=False)
            execution.check_cache = Mock(return_value=processed)
            execution.reload_debugger = AsyncMock(return_value=debugger)
            with tempfile.TemporaryDirectory(prefix='attackpilot-report-delivery-') as root, patch.object(
                settings, 'DATABASE_PATH', Path(root) / 'tasks.sqlite3'
            ), patch.object(settings, 'RUNTIME_ROOT', Path(root)), patch.object(
                workflow, 'WorkFlow', return_value=execution
            ), patch.object(worker.settings, 'prepare_work_dir'):
                task = store.create_task('offline-report-owner', dapp)
                self.assertTrue(store.transition(task['task_id'], 'running'))
                await worker.run(task['task_id'])
                saved = store.get_task(task['task_id'])
                delivered = saved['result']
                self.assertEqual(saved['status'], 'completed')
                self.assertEqual(saved['final_report'], delivered['report'])
                detail = api.task_detail(task['task_id'], SimpleNamespace(id='offline-report-owner'))
                self.assertEqual(detail['final_report'], delivered['report'])
                self.assertEqual(detail['result']['report_generation'], delivered['report_generation'])
                self.assertEqual(detail['result']['verification']['status'], 'unverified')
                final = [event['payload'] for event in store.events_after(task['task_id'], 0)
                         if event['payload']['type'] == 'TASK_FINAL']
                self.assertEqual(len(final), 1)
                self.assertEqual(final[0]['final_report'], delivered['report'])
                self.assertEqual(final[0]['result']['report_generation'], delivered['report_generation'])
                self.assertEqual(final[0]['result']['verification']['status'], 'unverified')
        self.assertIsNone(execution.last_error)
        self.assertEqual(delivered['verification'], state)
        self.assertEqual(delivered['verification']['status'], 'unverified')
        self.assertEqual(delivered['replay_evidence'], replay)
        self.assertEqual(delivered['applied_patches'], fixture.patches)
        self.assertEqual(delivered['report_generation'], memory.report_generation)
        self.assertEqual(delivered['report_generation']['status'], 'evidence_fallback')
        self.assertIn(fixture.transaction_hash, delivered['report'])
        self.assertIn('已记录的复盘分析', delivered['report'])
        memory.query.assert_awaited_once()
        client.close.assert_awaited_once(); debugger.close.assert_awaited_once()


class ResultIntegrityTests(unittest.IsolatedAsyncioTestCase):
    tx_hash = '0x' + '7' * 64
    sender, target = '0x' + '1' * 40, '0x' + '2' * 40

    def original(self):
        from app.attackpilot.utils.replay_validation import validate_original_transaction
        tx = {'hash': self.tx_hash, 'blockNumber': '0x64', 'transactionIndex': '0x3',
              'blockHash': '0x' + '8' * 64, 'from': self.sender, 'to': self.target,
              'input': '0x12345678', 'value': '0x1', 'gas': '0x186a0', 'gasPrice': '0x1', 'nonce': '0x0'}
        receipt = {'transactionHash': self.tx_hash, 'blockNumber': '0x64', 'transactionIndex': '0x3',
                   'blockHash': tx['blockHash'], 'status': '0x1', 'gasUsed': '0x5208', 'logs': []}
        context = validate_original_transaction(self.tx_hash, 1, tx, receipt)
        fields = {'network_id': '1', 'block_number': 100, 'transaction_index': 3,
                  'from': self.sender, 'to': self.target, 'input': tx['input'], 'value': '1',
                  'gas': 100000, 'gas_price': '1', 'nonce': 0, 'status': True, 'gas_used': 21000}
        response = {'simulation': dict(fields), 'transaction': {**fields, 'transaction_info': {
            'logs': [], 'call_trace': {'call_type': 'CALL', 'from': self.sender, 'to': self.target,
                                     'input': tx['input'], 'value': '1', 'calls': []},
        }}}
        return context, response

    def valid_result(self):
        from app.attackpilot.utils.replay_validation import validate_simulated_transaction
        from app.attackpilot.workflow import REPORT_POLICY_VERSION, request_fingerprint
        dapp = {'name': 'new synthetic transaction', 'platform': 'Ethereum',
                'transaction_hash': [self.tx_hash], 'enabled_modules': ['attack_detection']}
        context, response = self.original()
        baseline = validate_simulated_transaction(context, response)
        result = {'report': '当前证据未建立攻击假设，不代表交易安全。',
                  'report_policy_version': REPORT_POLICY_VERSION, 'request_fingerprint': request_fingerprint(dapp),
                  'enabled_modules': ['attack_detection'], 'verification': {'status': 'skipped'},
                  'baseline_validation': {'schema_version': 1, 'transactions': {self.tx_hash: baseline}}}
        return dapp, result

    def test_original_and_patched_root_trace_must_match_transaction_identity(self):
        from app.attackpilot.errors import HistoricalReplayValidationError
        from app.attackpilot.utils.replay_validation import validate_simulated_transaction
        from app.attackpilot.utils.patch_replay import validate_patch_context
        context, response = self.original()
        validate_simulated_transaction(context, response)
        validate_patch_context(context, response)
        mutations = {'from': self.target, 'to': self.sender, 'input': '0x', 'value': '16',
                     'call_type': 'DELEGATECALL', 'status': False, 'error_op': 'REVERT',
                     'network_id': '56', 'block_number': 99, 'type': 'STATICCALL'}
        for key, value in mutations.items():
            for validator in (validate_simulated_transaction, validate_patch_context):
                with self.subTest(field=key, validator=validator.__name__):
                    changed = deepcopy(response)
                    changed['transaction']['transaction_info']['call_trace'][key] = value
                    with self.assertRaises(HistoricalReplayValidationError):
                        validator(context, changed)
        for key in ('from', 'to', 'input', 'value', 'call_type'):
            changed = deepcopy(response)
            del changed['transaction']['transaction_info']['call_trace'][key]
            with self.subTest(missing=key), self.assertRaises(HistoricalReplayValidationError):
                validate_simulated_transaction(context, changed)
        patched = deepcopy(response)
        for part in ('simulation', 'transaction'):
            patched[part]['status'] = False
            patched[part]['gas_used'] = 22000
        patched['transaction']['transaction_info']['call_trace'].update(status=False, error_op='REVERT')
        validate_patch_context(context, patched)

    def test_result_gate_rejects_mismatched_or_incomplete_artifacts(self):
        from app.attackpilot.errors import AgentContractError
        from app.attackpilot.workflow import validate_completed_result, validated_baselines
        dapp, valid = self.valid_result()
        validate_completed_result(dapp, valid, valid['report'])
        for field, value in (('report', ''), ('request_fingerprint', 'other'), ('enabled_modules', []),
                             ('report_policy_version', 0), ('verification', {'status': 'verified'}),
                             ('baseline_validation', {})):
            result = deepcopy(valid); result[field] = value
            with self.subTest(field=field), self.assertRaises(AgentContractError):
                validate_completed_result(dapp, result, valid['report'])
        for field in ('receipt_digest', 'gas_used', 'method', 'block_hash'):
            result = deepcopy(valid)
            del result['baseline_validation']['transactions'][self.tx_hash][field]
            self.assertEqual(validated_baselines(result, dapp), {})
        result = deepcopy(valid)
        result['baseline_validation']['transactions'][self.tx_hash]['schema_version'] = True
        self.assertEqual(validated_baselines(result, dapp), {})

    async def test_worker_never_completes_a_malformed_output(self):
        from app.attackpilot import worker
        from app.attackpilot.errors import AgentContractError
        dapp, valid = self.valid_result()
        for result, report in ((None, 'report'), ({**valid, 'report': 'different'}, valid['report']),
                               (valid, {'report': valid['report']})):
            with self.subTest(report_type=type(report).__name__), patch.object(worker.settings, 'prepare_work_dir'), patch.object(
                worker.store, 'get_task', return_value={'status': 'running', 'payload': dapp}
            ), patch.object(worker.store, 'append_log'), patch.object(worker.store, 'transition') as transition, patch(
                'app.attackpilot.workflow.WorkFlow'
            ) as factory:
                factory.return_value.process_single_dapp = AsyncMock(return_value=('case', report))
                factory.return_value.last_result = result
                factory.return_value.last_error = None
                await worker.run('offline-result-test')
            self.assertEqual(transition.call_args.args[1], 'failed')
            self.assertIn('analysis_report_invalid', transition.call_args.kwargs['error'])

    async def test_empty_model_report_cannot_be_wrapped_as_a_complete_report(self):
        from app.attackpilot.agents.GlobalMemoryAgent import GlobalMemoryAgent
        from app.attackpilot.errors import AgentContractError
        agent = GlobalMemoryAgent.__new__(GlobalMemoryAgent)
        agent._serialize_memory_for_prompt = Mock(return_value='synthetic evidence')
        agent.cancellation_checker = lambda: False
        agent.global_memory = {}
        for body in ('', '   ', None, {}, 'null', 'ERROR unavailable', '```solidity\ncontract X {}\n```'):
            with self.subTest(body=body):
                agent.query = AsyncMock(return_value=body)
                with self.assertRaises(AgentContractError):
                    await agent.get_final_result({'verification': {'status': 'blocked'}}, {}, '', '')

    def test_review_cannot_treat_failure_mentions_or_a_report_as_independent_proof(self):
        task = TaskResponse(task_id='review', dapp_name='new transaction', status='completed',
                            created_at=datetime.now(timezone.utc),
                            final_report='Root cause: foo() bar(). Patch failed; verification unavailable.',
                            result={'verification': {'status': 'blocked', 'reason_code': 'compiler_unavailable'}})
        logs = [{'agent': name, 'message': 'Root cause foo() bar() patch failed verification unavailable ' + self.tx_hash}
                for name in ('TxFaultAgent', 'Code Patcher', 'Transaction Judge')]
        result = build_automated_review(task, logs)
        check = next(item for item in result['checks'] if item['id'] == 'verification-loop')
        self.assertNotEqual(check['status'], 'pass')
        self.assertNotEqual(result['status'], 'pass')
        self.assertEqual(result['shared_transactions'], [])
        self.assertEqual(result['score_scope'], 'text_reference_coverage_only')
        alone = build_automated_review(task, [])
        continuity = next(item for item in alone['checks'] if item['id'] == 'root-to-patch')
        self.assertEqual(continuity['score'], 25)

    def test_review_accepts_only_actual_patch_bound_replay_result(self):
        fixture = ReplayEvidenceRegressionTests(); fixture.setUp()
        replay = fixture.report(); state = fixture.adjudicate(replay)
        task = TaskResponse(task_id='review', dapp_name='synthetic evidence', status='completed',
                            created_at=datetime.now(timezone.utc), final_report='recorded analysis',
                            result={'verification': state, 'replay_evidence': replay, 'applied_patches': fixture.patches})
        def loop():
            return next(item for item in build_automated_review(task, [])['checks'] if item['id'] == 'verification-loop')
        self.assertEqual(loop()['status'], 'pass')
        task.result['applied_patches'] += '\nchanged'
        self.assertNotEqual(loop()['status'], 'pass')

    async def test_verified_final_result_requires_input_bound_runtime_integrity(self):
        from app.attackpilot.errors import AgentContractError
        from app.attackpilot import workflow
        from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore, historical_payload
        fixture = ReplayEvidenceRegressionTests(); fixture.transaction_hash = self.tx_hash; fixture.setUp()
        replay = fixture.report()
        runtime = '0x6000600060005bfd'
        replay['runtime_integrity'] = {
            'schema_version': 1, 'status': 'validated', 'applied_patch_sha256': replay['applied_patch_sha256'],
            'contracts': {fixture.patched_address: {
                'storage_layout_checked': True, 'immutable_checked': True,
                'original_runtime_sha256': '1' * 64, 'original_compiled_runtime_sha256': '2' * 64,
                'patched_runtime_sha256': hashlib.sha256(bytes.fromhex(runtime[2:])).hexdigest(),
            }},
        }
        pair = replay['transactions'][0]
        pair['context'].update({'from': self.sender, 'to': fixture.patched_address, 'input': '0x12345678',
                               'value': '0', 'gas': 100000, 'gas_price': '1', 'nonce': 0, 'access_list': []})
        context = {**pair['context'], 'chain_id': 1}
        with tempfile.TemporaryDirectory(prefix='attackpilot-final-artifacts-') as temp, patch.object(workflow, 'WORK_ROOT', Path(temp)):
            store = PatchReplayEvidenceStore(Path(temp) / 'cache')
            requests = {}
            for role in ('control', 'patched'):
                overrides = {fixture.patched_address: {'code': runtime}} if role == 'patched' else None
                requests[role] = historical_payload(context, {}, overrides)
                success = role == 'control'
                response = {
                    'simulation': {'id': role, 'status': success, 'gas_used': pair[role]['gas_used']},
                    'transaction': {'status': success, 'gas_used': pair[role]['gas_used'], 'transaction_info': {
                        'call_trace': fixture.frame() if success else fixture.frame(reason=fixture.guard_reason),
                        'logs': [], 'balance_diff': [], 'asset_changes': [], 'state_diff': [],
                    }},
                }
                reference = store.persist(requests[role], response, role=role, original_hash=self.tx_hash)
                rebuilt = execution_summary(response, reference, [fixture.patched_address])
                if success:
                    rebuilt.update(control_validation='validated', baseline_validation=pair[role]['baseline_validation'])
                pair[role] = rebuilt
            dapp, result = self.valid_result()
            dapp['enabled_modules'] = sorted(workflow.DEFAULT_ENABLED_MODULES)
            result.update(enabled_modules=dapp['enabled_modules'], request_fingerprint=workflow.request_fingerprint(dapp),
                          verification=fixture.adjudicate(replay), replay_evidence=replay, applied_patches=fixture.patches)
            result['baseline_validation']['transactions'][self.tx_hash] = deepcopy(pair['control']['baseline_validation'])
            workflow.validate_completed_result(dapp, result, result['report'])
            for mutation in ('missing', 'wrong_patch', 'wrong_contract', 'unchecked_layout', 'wrong_input', 'wrong_receipt',
                             'wrong_runtime_sha', 'changed_override', 'extra_storage', 'changed_request_input',
                             'artifact_identity', 'request_digest', 'artifact_bytes', 'missing_artifact', 'symlink',
                             'forged_failure_pc', 'forged_checked'):
                changed = deepcopy(result); changed_replay = changed['replay_evidence']
                integrity = changed_replay['runtime_integrity']
                reference = changed_replay['transactions'][0]['patched']['artifact']
                file = Path(temp) / reference['relative_path']
                saved = file.read_bytes()
                replacement_link = None
                try:
                    if mutation == 'missing': del changed_replay['runtime_integrity']
                    elif mutation == 'wrong_patch': integrity['applied_patch_sha256'] = '0' * 64
                    elif mutation == 'wrong_contract': integrity['contracts'] = {self.target: next(iter(integrity['contracts'].values()))}
                    elif mutation == 'unchecked_layout': integrity['contracts'][fixture.patched_address]['storage_layout_checked'] = False
                    elif mutation == 'wrong_input':
                        changed['baseline_validation']['transactions'] = {'0x' + 'f' * 64: changed['baseline_validation']['transactions'][self.tx_hash]}
                    elif mutation == 'wrong_receipt': changed['baseline_validation']['transactions'][self.tx_hash]['receipt_digest'] = '0' * 64
                    elif mutation == 'wrong_runtime_sha': integrity['contracts'][fixture.patched_address]['patched_runtime_sha256'] = '3' * 64
                    elif mutation == 'forged_failure_pc':
                        from app.attackpilot.utils.patch_attribution import attribution_digest
                        changed_replay['transactions'][0]['patched']['trace']['reverted_calls'][0]['failure_location']['pc'] = 6
                        proof = changed_replay['patch_attribution']
                        proof['contracts'][fixture.patched_address]['guards'][0]['revert_pcs'] = [6]
                        proof['evidence_sha256'] = attribution_digest(proof)
                    elif mutation == 'forged_checked':
                        pass
                    elif mutation in ('changed_override', 'extra_storage', 'changed_request_input', 'artifact_identity'):
                        request = deepcopy(requests['patched'])
                        if mutation == 'changed_override': request['simulations'][0]['state_objects'][fixture.patched_address]['code'] = '0x6001'
                        elif mutation == 'extra_storage': request['simulations'][0]['state_objects'][fixture.patched_address]['storage'] = {'0x00': '0x01'}
                        elif mutation == 'changed_request_input': request['simulations'][0]['input'] = '0xdeadbeef'
                        reference = store.persist(request, {'simulation': {'id': mutation}}, role='patched',
                                                  original_hash='0x' + 'f' * 64 if mutation == 'artifact_identity' else self.tx_hash)
                        changed_replay['transactions'][0]['patched']['artifact'] = reference
                    elif mutation == 'request_digest':
                        record = json.loads(saved)
                        record['request_digest'] = 'f' * 64
                        raw = json.dumps(record, sort_keys=True).encode()
                        sha = hashlib.sha256(raw).hexdigest()
                        path = file.with_name(sha + '.json'); path.write_bytes(raw)
                        changed_replay['transactions'][0]['patched']['artifact'] = {
                            **reference, 'sha256': sha, 'request_digest': record['request_digest'],
                            'relative_path': f'cache/patch_replay/artifacts/{sha}.json',
                        }
                    elif mutation == 'artifact_bytes': file.write_bytes(saved + b' ')
                    elif mutation == 'missing_artifact': file.unlink()
                    else:
                        replacement_link = file.with_name('symlink-target.json')
                        replacement_link.write_bytes(saved)
                        file.unlink(); file.symlink_to(replacement_link)
                    # Model/summary claims cannot bypass final validation even
                    # when the new attribution gate has already rejected them.
                    changed['verification'] = fixture.adjudicate(changed_replay)
                    if mutation == 'forged_checked':
                        changed['verification']['checked'][0]['patch_file'] = 'UnusedHelper.sol'
                    if mutation in ('forged_failure_pc', 'forged_checked'):
                        self.assertEqual(changed['verification']['status'], 'verified')
                    if changed['verification']['status'] != 'verified':
                        changed['verification'] = deepcopy(result['verification'])
                    with self.subTest(mutation=mutation), self.assertRaises(AgentContractError):
                        workflow.validate_completed_result(dapp, changed, changed['report'])
                finally:
                    if file.is_symlink(): file.unlink()
                    file.write_bytes(saved)
                    if replacement_link is not None: replacement_link.unlink(missing_ok=True)
            # Response cache reuse changes only this reference flag, not bytes or request identity.
            for role in ('control', 'patched'):
                result['replay_evidence']['transactions'][0][role]['artifact']['reused'] = True
            result['verification'] = fixture.adjudicate(result['replay_evidence'])
            workflow.validate_completed_result(dapp, result, result['report'])
            # Losing only the final prose service preserves the same evidence
            # gates, including the immutable on-disk artifact checks above.
            delivery = ReportDeliveryTests()
            memory = delivery.agent(self.tx_hash)
            memory.query = AsyncMock(side_effect=TimeoutError('synthetic final prose deadline'))
            delivered = deepcopy(result)
            delivered['report'] = await memory.get_final_result(
                {'verdict': 'VERIFIED', 'verification': delivered['verification']},
                delivery.hypothesis(self.tx_hash), delivered['replay_evidence'], delivered['applied_patches'],
            )
            delivered['report_generation'] = memory.report_generation
            workflow.validate_completed_result(dapp, delivered, delivered['report'])
            self.assertEqual(delivered['verification'], result['verification'])
            self.assertEqual(delivered['replay_evidence'], result['replay_evidence'])
            self.assertEqual(delivered['verification']['status'], 'verified')
            self.assertEqual(delivered['report_generation']['status'], 'evidence_fallback')
            self.assertIn('触发交易拦截通过', delivered['report'])
            memory.query.assert_awaited_once()
