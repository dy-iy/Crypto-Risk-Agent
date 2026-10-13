"""Regression coverage for early explorer failure and unsupported risk scores."""
import asyncio
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

import httpx
from app.attackpilot.daos.tenderly import TenderlyDao
from app.attackpilot.daos.tx import TxDetailDao
from app.attackpilot.downloaders import contract
from app.attackpilot.errors import failure_message
from app.attackpilot.web.models import TaskResponse
from app.attackpilot.web.review_service import build_automated_review


class FailureTests(unittest.IsolatedAsyncioTestCase):
    def dao(self):
        return TenderlyDao('Ethereum', AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), {})

    async def test_summary_uses_real_transaction_without_explorer_enrichment(self):
        dao = self.dao()
        dao.tx_downloader.download.return_value = {'from': '0x1', 'blockNumber': '0x1'}
        transaction = {'hash': '0x' + 'a' * 64, 'addresses': ['0x1']}
        dao.send_request = AsyncMock(return_value={'transaction': transaction, 'contracts': []})
        with patch.object(dao, '_supplement_missing_contracts', AsyncMock()) as supplement, patch.object(dao, '_load_contract_name', AsyncMock()) as names:
            result = await dao.simulate_tx_in_tenderly(transaction['hash'], enrich_contracts=False)
        self.assertEqual(result[0], transaction)
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
