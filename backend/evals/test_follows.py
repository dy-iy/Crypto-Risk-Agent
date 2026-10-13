import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app.api import follows, daily_report
from app.services import follow_service as service, portfolio_watchlist_store as store
from app.schemas_portfolio import UserWatchlist
from app.agents.daily_report_agent import nodes


class FollowTest(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(store, 'PORTFOLIO_DB_PATH', Path(self.temp.name) / 'portfolio.sqlite3')
        self.patch.start(); self.addCleanup(self.patch.stop)
        app = FastAPI(); app.include_router(follows.router)
        self.client = TestClient(app)
        self.user = patch.object(follows, 'get_user_by_session', return_value=SimpleNamespace(id='alice'))
        self.user.start(); self.addCleanup(self.user.stop)

    def test_cancel_and_refollow_preserve_holdings_and_threshold(self):
        saved = store.upsert_watchlist_record(UserWatchlist(id='old', user_id='alice', symbol='BTCUSDT', base_asset='BTC',
            is_holding=True, amount=2, avg_buy_price=100, exposure_mode='exact', alert_threshold=0, created_at='old', updated_at='old'))
        before = service.follow_snapshot('alice')
        cancelled = service.mutate_follow('alice', 'BTC', 'remove')
        self.assertEqual(cancelled['items'], [])
        record = store.list_watchlist_records('alice')[0]
        self.assertTrue(record.is_holding); self.assertEqual(record.amount, saved.amount)
        self.assertNotEqual(before['revision'], cancelled['revision'])
        self.assertEqual(cancelled, service.mutate_follow('alice', 'BTC', 'remove'))
        added = service.mutate_follow('alice', 'BTC', 'add')
        self.assertEqual(added['items'][0]['alert_threshold'], 0)
        self.assertEqual(added, service.mutate_follow('alice', 'BTC', 'add'))
        record = store.list_watchlist_records('alice')[0]
        self.assertEqual(record.avg_buy_price, 100); self.assertEqual(record.id, 'old')

    def test_api_accepts_full_library_and_returns_no_holdings(self):
        with patch('app.services.portfolio_service.generate_risk_snapshot') as risk:
            added = self.client.post('/api/follows', json={'symbol': 'TON'}).json()
            self.assertEqual(added['items'][0]['symbol'], 'TONUSDT')
            self.assertEqual(set(added['items'][0]), {'symbol', 'base_asset', 'name', 'alert_threshold', 'created_at', 'updated_at'})
            self.assertEqual(added['items'][0]['alert_threshold'], 70)
            risk.assert_not_called()
        changed = self.client.patch('/api/follows/TON', json={'alert_threshold': 0}).json()
        self.assertEqual(changed['items'][0]['alert_threshold'], 0)
        self.assertNotEqual(added['revision'], changed['revision'])
        self.assertEqual(changed, self.client.patch('/api/follows/TON', json={'alert_threshold': 0}).json())

    def test_invalid_payloads_are_rejected_without_writes(self):
        for payload in ({'symbol': '../../etc/passwd'}, {'symbol': 'NOTACOIN'}, {'symbol': 'BTC', 'amount': 5}):
            self.assertEqual(self.client.post('/api/follows', json=payload).status_code, 422)
        for value in (-1, 101, None, 1.5, True, '70'):
            self.assertEqual(self.client.patch('/api/follows/BTC', json={'alert_threshold': value}).status_code, 422)
        self.assertEqual(service.follow_snapshot('alice')['items'], [])

    def test_auth_and_account_isolation(self):
        service.mutate_follow('bob', 'ETH', 'add')
        self.assertEqual(self.client.get('/api/follows?user_id=bob').json()['items'], [])
        self.client.delete('/api/follows/ETH?user_id=bob')
        self.assertEqual(len(service.follow_snapshot('bob')['items']), 1)
        with patch.object(follows, 'get_user_by_session', return_value=None):
            for method, path, body in [('get', '/api/follows', None), ('post', '/api/follows', {'symbol': 'BTC'}), ('patch', '/api/follows/BTC', {'alert_threshold': 40}), ('delete', '/api/follows/BTC', None)]:
                response = getattr(self.client, method)(path, **({'json': body} if body else {}))
                self.assertEqual(response.status_code, 401)

    def test_empty_follows_prevent_model_and_save(self):
        with patch.object(daily_report, 'get_user_by_session', return_value=SimpleNamespace(id='alice', display_name='Alice')), patch.object(daily_report, 'run_daily_report_agent') as agent, patch.object(daily_report, 'save_daily_report') as save:
            with self.assertRaises(HTTPException) as caught: daily_report.generate_personal_daily_report(None, 'token')
            self.assertEqual(caught.exception.status_code, 409)
            agent.assert_not_called(); save.assert_not_called()
        with self.assertRaises(service.NoFollowsError): nodes.load_user_profile_node({'user_id': 'alice'})

    def test_daily_profile_ignores_old_holdings_and_excludes_unfollowed(self):
        store.upsert_watchlist_record(UserWatchlist(id='old', user_id='alice', symbol='BTCUSDT', base_asset='BTC', is_holding=True, amount=99, avg_buy_price=12, created_at='old', updated_at='old'))
        service.mutate_follow('alice', 'TON', 'add')
        service.mutate_follow('alice', 'BTC', 'remove')
        with patch.object(nodes, 'list_favorites', return_value=[]):
            profile = nodes.load_user_profile_node({'user_id': 'alice'})['user_profile']
        self.assertEqual([row['symbol'] for row in profile['assets']], ['TONUSDT'])
        self.assertNotIn('amount', json.dumps(profile)); self.assertNotIn('is_holding', json.dumps(profile))
        self.assertEqual(profile['follows_revision'], service.follow_snapshot('alice')['revision'])

    def test_risk_score_and_prompt_have_no_exposure_dependency(self):
        follow = {'symbol': 'BTCUSDT', 'base_asset': 'BTC'}
        holding = {**follow, 'is_holding': True, 'market_value': 999999, 'exposure_mode': 'custom', 'custom_exposure_pct': 1}
        self.assertEqual(nodes._personal_news_score({'risk_score': 90}, ['BTC'], [follow], .9), nodes._personal_news_score({'risk_score': 90}, ['BTC'], [holding], .9))
        with patch.object(nodes, 'call_llm_json', return_value={'source': 'llm'}) as llm:
            nodes.llm_daily_writer_node({'signals': {'user_assets_count': 1, 'user_profile': {'assets': [holding]}}})
        prompt = llm.call_args.args[0]
        for field in ('is_holding', 'market_value', 'exposure_mode', 'custom_exposure_pct'): self.assertNotIn(field, prompt)

    def test_report_keeps_follow_revision_and_version(self):
        result = nodes.finalize_daily_report_node({'user_id': 'alice', 'signals': {'user_assets_count': 1, 'user_profile': {'follows_revision': 'revision-1'}, 'asset_reports': []}})['report']
        self.assertEqual(result['report_kind'], 'follows_v1')
        self.assertEqual(result['follows_revision'], 'revision-1')

    def test_follow_mutations_are_rate_limited_and_csrf_protected(self):
        from app.services.rate_limit_service import match_rate_limit_rule
        from app.services.csrf_service import csrf_request_allowed
        for method in ('POST', 'PATCH', 'DELETE'):
            self.assertEqual(match_rate_limit_rule('/api/follows/BTC', method).name, 'mutation')
            self.assertFalse(csrf_request_allowed(method=method, cookies={'session':'x'}, headers={}, session_cookie_name='session'))

    def test_concurrent_adds_create_one_record_without_a_shared_process_lock(self):
        from contextlib import nullcontext
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        import time
        barrier = Barrier(6)
        created = []
        original_write = store._write_watchlist_item
        def slow_write(connection, item):
            created.append(item.id)
            time.sleep(.02)
            return original_write(connection, item)
        def add(_):
            barrier.wait()
            return service.mutate_follow('alice', 'BTC', 'add')
        # Independent workers do not share Python locks; SQLite must serialize the upsert.
        with patch.object(store, '_db_lock', nullcontext()), patch.object(store, '_write_watchlist_item', side_effect=slow_write):
            with ThreadPoolExecutor(max_workers=6) as executor:
                results = list(executor.map(add, range(6)))
        self.assertEqual(len(created), 1)
        self.assertTrue(all(result['items'][0]['symbol'] == 'BTCUSDT' for result in results))
        self.assertEqual(len(store.list_watchlist_records('alice')), 1)
