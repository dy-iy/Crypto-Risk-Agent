from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from starlette.requests import Request
from app.api.sim import BuyRequest, SellRequest
from app.schemas_portfolio import UserWatchlistCreate
from app.services import sim_engine as engine_module
from app.services.sim_engine import SimEngine, SimError
from app.services.runtime_json_store import write_runtime_json_atomic, load_runtime_json_or_quarantine
from app.services.request_body_limit_service import request_body_exceeds_limit
from app.services.request_security_service import request_client_identity
from app.services.llm_config_service import _parse_timeout


class HttpBoundaryTest(unittest.TestCase):
    def test_nonfinite_json_returns_validation_error_without_echoing_input(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        response = client.post('/api/user-assets', content='{"symbol":"BTC","amount":1e309}',
                               headers={'content-type': 'application/json'})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('input', response.json()['detail'][0])
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_request_id_is_bounded_and_safe_to_reflect(self):
        from fastapi.testclient import TestClient
        from main import app
        response = TestClient(app).get('/health', headers={'x-request-id': 'x' * 1000})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(response.headers['x-request-id']), 128)


class NumericInputTest(unittest.TestCase):
    def test_nonfinite_inputs_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            for model, payload in (
                (BuyRequest, {'symbol': 'BTC', 'amount_usdt': value}),
                (SellRequest, {'symbol': 'BTC', 'quantity': value}),
                (UserWatchlistCreate, {'symbol': 'BTC', 'amount': value}),
            ):
                with self.subTest(model=model.__name__, value=value), self.assertRaises(ValidationError):
                    model.model_validate(payload)
        self.assertFalse(_parse_timeout('NaN')[1])
        self.assertEqual(SellRequest(symbol='BTC', quantity='ALL').quantity, 'ALL')
        self.assertEqual(SellRequest(symbol='BTC', quantity='1.5').quantity, 1.5)

    def test_spoofed_forwarded_prefix_does_not_change_rate_limit_identity(self):
        with patch.dict('os.environ', {'TRUST_PROXY_HEADERS': '1'}):
            first = request_client_identity('127.0.0.1', {'x-forwarded-for': 'spoof1, 203.0.113.10'})
            second = request_client_identity('127.0.0.1', {'x-forwarded-for': 'spoof2, 203.0.113.10'})
            self.assertEqual(first, second)
            self.assertEqual(first, '203.0.113.10')


class RuntimeStoreTest(unittest.TestCase):
    def test_concurrent_atomic_writes_leave_a_complete_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda n: write_runtime_json_atomic(path, {'n': n, 'text': str(n) * 1000}), range(40)))
            self.assertTrue(all(results))
            data = json.loads(path.read_text())
            self.assertEqual(data['text'], str(data['n']) * 1000)
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_invalid_values_do_not_replace_saved_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            self.assertTrue(write_runtime_json_atomic(path, {'cash': 100}))
            with self.assertLogs('app.services.runtime_json_store', level='ERROR'):
                self.assertFalse(write_runtime_json_atomic(path, {'cash': float('nan')}))
            self.assertEqual(json.loads(path.read_text()), {'cash': 100})
            path.write_bytes(b'\xff')
            self.assertIsNone(load_runtime_json_or_quarantine(path))
            self.assertEqual(len(list(Path(directory).glob('*.bak'))), 1)

    def test_sim_failed_save_rolls_back_balance_and_positions(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(engine_module, 'SIM_ACCOUNTS_PATH', Path(directory) / 'sim.json'):
            engine = SimEngine()
            initial = engine.reset('alice')
            with patch.object(engine_module, 'write_runtime_json_atomic', return_value=False):
                with self.assertRaises(SimError): engine.buy('BTC', 100, 'alice')
            self.assertEqual(engine.state('alice')['cash'], initial['cash'])
            self.assertEqual(engine.state('alice')['positions'], initial['positions'])
            engine.buy('BTC', 100, 'alice')
            before = engine.state('alice')
            for value in ('NaN', 'Infinity', '-Infinity'):
                with self.assertRaises(SimError): engine.sell('BTC', value, account_id='alice')
            self.assertEqual(engine.state('alice')['cash'], before['cash'])
            restored = SimEngine()
            self.assertEqual(restored.state('alice')['cash'], before['cash'])


class BodyLimitRegressionTest(unittest.IsolatedAsyncioTestCase):
    def request(self, chunks, headers=None):
        pending = iter(chunks)
        async def receive():
            chunk = next(pending, None)
            return {'type': 'http.request', 'body': chunk or b'', 'more_body': chunk is not None}
        return Request({'type': 'http', 'method': 'POST', 'headers': headers or []}, receive)

    async def test_measures_body_even_with_small_declared_size(self):
        request = self.request([b'a' * 500, b'b' * 501], [(b'content-length', b'1')])
        self.assertTrue(await request_body_exceeds_limit(request, 1000))

    async def test_valid_stream_remains_readable_for_endpoint(self):
        request = self.request([b'{"x":', b'1}'])
        self.assertFalse(await request_body_exceeds_limit(request, 1000))
        self.assertEqual(await request.json(), {'x': 1})

    async def test_oversized_chunked_request_is_not_fully_buffered(self):
        reads = 0
        async def receive():
            nonlocal reads
            reads += 1
            return {'type': 'http.request', 'body': b'x' * 600, 'more_body': True}
        request = Request({'type': 'http', 'method': 'POST', 'headers': []}, receive)
        self.assertTrue(await asyncio.wait_for(request_body_exceeds_limit(request, 1000), 1))
        self.assertEqual(reads, 2)


if __name__ == '__main__':
    unittest.main()
