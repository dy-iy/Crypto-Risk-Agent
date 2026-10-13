from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import tempfile
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api import daily_report, portfolio, risk_ranking, user_assets
from app.schemas_portfolio import PortfolioRefreshJob
from app.services import daily_report_subscription_service as subscriptions
from app.services import feishu_binding_service as bindings


USERS = {name: SimpleNamespace(id=name, display_name=name, is_admin=name == 'admin') for name in ('alice', 'bob', 'admin')}


class PermissionTest(TestCase):
    def setUp(self):
        app = FastAPI()
        for module in (portfolio, user_assets, daily_report, risk_ranking):
            app.include_router(module.router)
            patcher = patch.object(module, 'get_user_by_session', side_effect=lambda token: USERS.get(token))
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict('os.environ', {'ALLOW_USER_ID_QUERY_OVERRIDE': '0'})
        env.start(); self.addCleanup(env.stop)
        self.client = TestClient(app)

    def test_guest_cannot_modify_shared_assets_or_daily_settings(self):
        routes = [
            ('POST', '/api/user-assets', {'symbol': 'BTC'}),
            ('PATCH', '/api/user-assets/BTC', {'is_watched': False}),
            ('DELETE', '/api/user-assets/BTC', None),
            ('POST', '/api/portfolio/watchlist', {'symbol': 'BTC'}),
            ('PATCH', '/api/portfolio/watchlist/BTC', {'is_watched': False}),
            ('DELETE', '/api/portfolio/watchlist/BTC', None),
            ('POST', '/api/portfolio/refresh', None),
            ('POST', '/api/portfolio/refresh/jobs', None),
            ('POST', '/api/daily-report/generate', {'date': '24h'}),
            ('PATCH', '/api/daily-report/subscription', {'enabled': True}),
        ]
        for method, path, payload in routes:
            with self.subTest(path=path, method=method):
                response = self.client.request(method, path, json=payload)
                self.assertEqual(response.status_code, 401, response.text)

    def test_guest_read_and_authenticated_mutation_remain_supported(self):
        with patch.object(user_assets, 'list_user_assets', return_value=[]) as read:
            self.assertEqual(self.client.get('/api/user-assets').status_code, 200)
            read.assert_called_once_with('demo_user')
        with patch.object(daily_report, 'set_daily_report_subscription', return_value={'enabled': True}) as save:
            response = self.client.patch('/api/daily-report/subscription', json={'enabled': True}, headers={'cookie': 'cryptorisk_session=alice'})
            self.assertEqual(response.status_code, 200)
            save.assert_called_once_with('alice', True)

    def test_job_lookup_does_not_leak_another_users_job(self):
        job = PortfolioRefreshJob(job_id='private-job', user_id='alice', status='queued', stage='queued', message='private')
        with patch.dict(portfolio._refresh_jobs, {job.job_id: job}, clear=True):
            for token, status in [(None, 404), ('bob', 404), ('alice', 200)]:
                headers = {'cookie': f'cryptorisk_session={token}'} if token else {}
                response = self.client.get('/api/portfolio/refresh/jobs/private-job?user_id=alice', headers=headers)
                self.assertEqual(response.status_code, status, response.text)

    def test_global_news_updates_require_admin_before_work_starts(self):
        with patch.object(risk_ranking, '_new_update_job') as create:
            for path in ['/api/rankings/update-news', '/api/rankings/update-news/jobs']:
                for token, expected in [(None, 401), ('alice', 403)]:
                    headers = {'cookie': f'cryptorisk_session={token}'} if token else {}
                    self.assertEqual(self.client.post(path, headers=headers).status_code, expected)
            create.assert_not_called()
        with patch.object(risk_ranking, '_get_current_update_job', return_value={'job_id': 'existing', 'status': 'running'}):
            response = self.client.post('/api/rankings/update-news/jobs', headers={'cookie': 'cryptorisk_session=admin'})
            self.assertEqual(response.status_code, 200)


class ConcurrentActionTest(TestCase):
    def test_portfolio_refresh_reuses_one_job_for_concurrent_requests(self):
        barrier = Barrier(8)
        original_uuid = portfolio.uuid.uuid4
        def slow_id():
            time.sleep(0.01)
            return original_uuid()
        def start(_):
            barrier.wait()
            return portfolio.start_portfolio_refresh_job(None, 'alice').job_id
        with patch.object(portfolio, 'get_user_by_session', return_value=USERS['alice']), \
             patch.dict(portfolio._refresh_jobs, {}, clear=True), \
             patch.dict(portfolio._latest_job_by_user, {}, clear=True), \
             patch.object(portfolio, '_persist_refresh_jobs'), \
             patch.object(portfolio, 'record_task_event'), \
             patch.object(portfolio, 'Thread') as thread, \
             patch.object(portfolio.uuid, 'uuid4', side_effect=slow_id):
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(start, range(8)))
            self.assertEqual(len(set(ids)), 1)
            self.assertEqual(thread.call_count, 1)

    def test_news_refresh_reuses_one_job_for_concurrent_requests(self):
        barrier = Barrier(8)
        original = risk_ranking._new_update_job
        def slow_create():
            time.sleep(0.01)
            return original()
        def start(_):
            barrier.wait()
            return risk_ranking.start_update_today_news_job('admin')['job_id']
        with patch.object(risk_ranking, 'get_user_by_session', return_value=USERS['admin']), \
             patch.dict(risk_ranking._update_jobs, {}, clear=True), \
             patch.object(risk_ranking, '_persist_update_jobs'), \
             patch.object(risk_ranking, 'record_task_event'), \
             patch.object(risk_ranking, 'Thread') as thread, \
             patch.object(risk_ranking, '_new_update_job', side_effect=slow_create):
            with ThreadPoolExecutor(max_workers=8) as pool:
                ids = list(pool.map(start, range(8)))
            self.assertEqual(len(set(ids)), 1)
            self.assertEqual(thread.call_count, 1)

    def test_daily_generation_rejects_duplicate_and_releases_after_failure(self):
        def generate(*args, **kwargs):
            with self.assertRaises(HTTPException) as duplicate:
                daily_report.generate_personal_daily_report(None, 'alice')
            self.assertEqual(duplicate.exception.status_code, 409)
            raise RuntimeError('upstream failure')
        with patch.object(daily_report, 'follow_snapshot', return_value={'items': [{'symbol': 'BTCUSDT'}]}), \
             patch.object(daily_report, 'get_user_by_session', return_value=USERS['alice']), \
             patch.object(daily_report, 'run_daily_report_agent', side_effect=generate):
            with self.assertRaises(RuntimeError): daily_report.generate_personal_daily_report(None, 'alice')
        self.assertNotIn('alice', daily_report._generating_users)
        with patch.object(daily_report, 'follow_snapshot', return_value={'items': [{'symbol': 'BTCUSDT'}]}), \
             patch.object(daily_report, 'get_user_by_session', return_value=USERS['alice']), \
             patch.object(daily_report, 'run_daily_report_agent', return_value={'range': '24h'}), \
             patch.object(daily_report, 'save_daily_report', return_value={'saved': True}):
            self.assertTrue(daily_report.generate_personal_daily_report(None, 'alice')['saved'])


class PersistenceFeedbackTest(TestCase):
    def test_failed_subscription_save_does_not_claim_success_or_change_saved_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subscriptions, 'SUBSCRIPTIONS_PATH', Path(directory) / 'subscriptions.json'):
            subscriptions.set_daily_report_subscription('alice', False)
            with patch.object(subscriptions, 'write_runtime_json_atomic', return_value=False), self.assertRaises(OSError):
                subscriptions.set_daily_report_subscription('alice', True)
            self.assertFalse(subscriptions.get_daily_report_subscription('alice')['enabled'])

    def test_failed_oauth_state_consumption_cannot_proceed_to_binding(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(bindings, 'FEISHU_OAUTH_STATES_PATH', Path(directory) / 'states.json'):
            state = bindings.create_feishu_oauth_state('alice')
            with patch.object(bindings, 'write_runtime_json_atomic', return_value=False), self.assertRaises(OSError):
                bindings.consume_feishu_oauth_state(state, 'alice')
            self.assertTrue(bindings.consume_feishu_oauth_state(state, 'alice'))
            self.assertFalse(bindings.consume_feishu_oauth_state(state, 'alice'))


class HoldingIntegrityTest(TestCase):
    def test_repeated_add_preserves_holdings_and_zero_threshold(self):
        from app.services import portfolio_service, portfolio_watchlist_store
        from app.schemas_portfolio import UserWatchlistCreate, UserWatchlistUpdate
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(portfolio_watchlist_store, 'PORTFOLIO_DB_PATH', Path(directory) / 'portfolio.sqlite3'), \
             patch.object(portfolio_service, '_seed_watchlist_store_if_needed'):
            portfolio_service.add_watchlist_item(UserWatchlistCreate(symbol='BTC', is_holding=True, amount=2, avg_buy_price=100, alert_threshold=0, exposure_mode='exact'), 'alice')
            repeated = portfolio_service.add_watchlist_item(UserWatchlistCreate(symbol='BTC'), 'alice')
            self.assertEqual(repeated.amount, 2)
            self.assertEqual(repeated.avg_buy_price, 100)
            self.assertTrue(repeated.is_holding)
            self.assertEqual(repeated.alert_threshold, 0)
            patched = portfolio_service.update_watchlist_item('BTC', UserWatchlistUpdate(is_holding=True), 'alice')
            self.assertEqual(patched.exposure_mode, 'exact')
            self.assertEqual(patched.exposure_bucket, 'none')
            unwatched = portfolio_service.update_watchlist_item('BTC', UserWatchlistUpdate(is_holding=False, is_watched=False), 'alice')
            self.assertFalse(unwatched.is_watched)
            self.assertEqual(portfolio_watchlist_store.list_watchlist_records('alice')[0].alert_threshold, 0)

    def test_partial_update_rejects_null_required_fields_but_allows_clearing_custom_exposure(self):
        from pydantic import ValidationError
        from app.schemas_portfolio import UserWatchlistUpdate
        for field in ('amount', 'avg_buy_price', 'is_watched', 'is_holding', 'exposure_mode', 'exposure_bucket', 'alert_threshold'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                UserWatchlistUpdate.model_validate({field: None})
        self.assertEqual(UserWatchlistUpdate().model_dump(exclude_unset=True), {})
        self.assertEqual(UserWatchlistUpdate(custom_exposure_pct=None).model_dump(exclude_unset=True), {'custom_exposure_pct': None})


class InterruptedJobTest(TestCase):
    def test_portfolio_jobs_loaded_after_restart_are_retryable(self):
        job = PortfolioRefreshJob(job_id='interrupted', user_id='alice', status='running', stage='news', message='running')
        with patch.dict(portfolio._refresh_jobs, {}, clear=True), \
             patch.dict(portfolio._latest_job_by_user, {}, clear=True), \
             patch.object(portfolio, 'load_runtime_json_or_quarantine', return_value={job.job_id: job.model_dump()}):
            portfolio._load_refresh_jobs()
            self.assertEqual(portfolio._refresh_jobs[job.job_id].status, 'error')
            self.assertIsNone(portfolio._active_refresh_job('alice'))

    def test_news_jobs_loaded_after_restart_do_not_block_new_updates(self):
        saved = {'pending': {'job_id': 'pending', 'status': 'queued', 'updated_at': '2026-01-01'}, 'done': {'job_id': 'done', 'status': 'success'}}
        with patch.dict(risk_ranking._update_jobs, {}, clear=True), \
             patch.object(risk_ranking, 'load_runtime_json_or_quarantine', return_value=saved):
            risk_ranking._load_update_jobs()
            self.assertEqual(risk_ranking._update_jobs['pending']['status'], 'error')
            self.assertEqual(risk_ranking._update_jobs['done']['status'], 'success')
            self.assertEqual(saved['pending']['status'], 'queued')
