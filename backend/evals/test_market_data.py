from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import TestCase
from unittest.mock import patch
import time
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.market import router
from app.services import market_data_service as market


class MarketDataTest(TestCase):
    def setUp(self):
        market._cache.clear(); market._retry_after.clear()
        app=FastAPI(); app.include_router(router)
        self.client=TestClient(app)

    def test_readonly_routes_reject_mutations_and_invalid_parameters(self):
        with patch.object(market, '_get') as upstream:
            for url in ['/api/market/candles?symbol=../../etc/passwd', '/api/market/candles?symbol=BTCUSDT&interval=2m', '/api/market/candles?symbol=BTCUSDT&limit=1001', '/api/market/candles?symbol=BTCUSDT&end_time=-1', '/api/market/depth?symbol=FAKEUSDT']:
                self.assertEqual(self.client.get(url).status_code, 422, url)
            self.assertEqual(self.client.post('/api/market/candles?symbol=BTCUSDT').status_code, 405)
            upstream.assert_not_called()

    def test_source_failure_is_503_without_synthetic_prices(self):
        with patch.object(market, '_get', side_effect=httpx.ConnectError('unavailable')):
            response=self.client.get('/api/market/candles?symbol=BTCUSDT')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('data',response.json())
            self.assertEqual(response.headers['retry-after'],'10')

    def test_candles_are_sorted_deduplicated_and_validated(self):
        rows=[[2000,'10','12','9','11','2'],[1000,'9','11','8','10','3'],[2000,'10','13','9','12','4']]
        with patch.object(market,'_get',return_value=rows):
            result=market.candles('BTCUSDT','15m',3)
            self.assertEqual([item['time'] for item in result['data']],[1,2])
            self.assertEqual(result['data'][1]['close'],12)
            self.assertFalse(result['stale'])
        market._cache.clear()
        with patch.object(market,'_get',return_value=[[1000,'10','11','12','9','1']]):
            with self.assertRaises(market.MarketDataUnavailable): market.candles('BTCUSDT','15m',3)

    def test_invalid_numbers_do_not_enter_market_responses(self):
        for value in ('NaN','Infinity',-1,0):
            with self.subTest(value=value), self.assertRaises(ValueError): market.number(value,positive=True)

    def test_stale_cache_retains_original_timestamp_and_eventually_expires(self):
        clock=[1.0]
        with patch.object(market,'monotonic',side_effect=lambda:clock[0]):
            first=market._cached('test',5,lambda:[{'price':100}])
            clock[0]=7
            def fail(): raise httpx.ConnectError('offline')
            stale=market._cached('test',5,fail)
            self.assertTrue(stale['stale']);self.assertEqual(stale['as_of'],first['as_of'])
            clock[0]=400
            with self.assertRaises(market.MarketDataUnavailable): market._cached('test',5,fail)

    def test_simultaneous_reads_share_one_upstream_request(self):
        barrier=Barrier(8);calls=[]
        def fetch(): calls.append(1);time.sleep(.02);return ['snapshot']
        def run(_): barrier.wait();return market._cached('shared',5,fetch)
        with ThreadPoolExecutor(max_workers=8) as executor: results=list(executor.map(run,range(8)))
        self.assertEqual(len(calls),1)
        results[0]['data'].append('mutation')
        self.assertEqual(results[1]['data'],['snapshot'])

    def test_cache_is_bounded_and_failure_backoff_prevents_retry_storm(self):
        for i in range(market.MAX_CACHE_ENTRIES+10): market._cached(str(i),5,lambda:[])
        self.assertEqual(len(market._cache),market.MAX_CACHE_ENTRIES)
        with patch.object(market,'_get',side_effect=httpx.ConnectError('offline')) as source:
            for _ in range(5):
                with self.assertRaises(market.MarketDataUnavailable): market.depth('BTCUSDT')
            self.assertEqual(source.call_count,1)

    def test_tickers_and_orderbook_are_normalized(self):
        row={'symbol':'BTCUSDT','lastPrice':'110','openPrice':'100','highPrice':'115','lowPrice':'99','volume':'3','quoteVolume':'320','closeTime':1000}
        with patch.object(market,'_get',return_value=[row]):
            result=market.tickers()['data'][0]
            self.assertAlmostEqual(result['change_pct'],10)
        with patch.object(market,'_get',return_value={'bids':[['99','1'],['100','2']],'asks':[['102','1'],['101','3']]}):
            book=market.depth('BTCUSDT')['data']
            self.assertEqual(book['bids'][0]['price'],100)
            self.assertEqual(book['asks'][0]['price'],101)

    def test_old_simulation_endpoints_are_no_longer_registered(self):
        from main import app
        paths={route.path for route in app.routes if hasattr(route,'path')}
        self.assertFalse(any(path.startswith('/api/sim/') for path in paths))
        self.assertIn('/api/market/candles',paths)
