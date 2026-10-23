from typing import Union

from app.attackpilot.downloaders.defs import JSONRPCDownloader, Downloader
from app.attackpilot.downloaders.trace import FlatTraceDownloader
import asyncio
import json
import os
import re
from typing import Dict
from app.attackpilot.settings import CACHE_DIR
from app.attackpilot.errors import ChainRPCError


class TransactionDownloader(Downloader):
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url

    async def _preprocess(self, transaction_hash: str, **kwargs):
        return None

    async def _fetch(self, transaction_hash: str, **kwargs):
        return await asyncio.gather(*[
            asyncio.create_task(FlatTraceDownloader(self.rpc_url).download(transaction_hash=transaction_hash)),
            asyncio.create_task(TxReceiptDownloader(self.rpc_url).download(transaction_hash=transaction_hash)),
        ])

    async def _process(self, result, *args, **kwargs):
        trace, receipt = result
        return {
            'trace': trace,
            'logs': receipt["logs"],
            'block_number': receipt["blockNumber"]
        }


class TxReceiptDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [transaction_hash.lower()],
            "method": "eth_getTransactionReceipt"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'tx_detail/tx_receipt', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        result = json.loads(result)
        result = result["result"]

        # cache data
        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'tx_detail/tx_receipt')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(result, f)
        return result


class EventLogDownloader(JSONRPCDownloader):
    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'tx_detail/tx_receipt', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            receipt = json.load(f)
            if not receipt:
                return None
            return receipt["logs"]

    async def _fetch(self, transaction_hash: str):
        receipt = await TxReceiptDownloader(rpc_url=self.rpc_url).download(transaction_hash=transaction_hash)
        return receipt

    async def _process(self, result: dict, **kwargs):
        return result.get("logs", [])


class TxDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [transaction_hash.lower()],
            "method": "eth_getTransactionByHash"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str, **kwargs):
        path = os.path.join(CACHE_DIR, 'tx_detail/tx', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        result_dict = json.loads(result)
        if result_dict is None or result_dict.get("result", None) is None:
            return None

        tx_data = result_dict['result']
        # cache data
        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'tx_detail/tx')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(tx_data, f)
        return tx_data


class TxDetailDownloader(JSONRPCDownloader):
    async def _preprocess(self, transaction_hash: str, **kwargs):
        return None

    async def _fetch(self, transaction_hash: str, **kwargs):
        return await asyncio.gather(*[
            asyncio.create_task(TxReceiptDownloader(self.rpc_url).download(transaction_hash=transaction_hash)),
            asyncio.create_task(TxDownloader(self.rpc_url).download(transaction_hash=transaction_hash)),
        ])

    async def _process(self, result, *args, **kwargs):
        tx_receipt, tx = result
        return {
            'tx_receipt': tx_receipt,
            'tx': tx
        }


class BlockTimestampDownloader(JSONRPCDownloader):
    @staticmethod
    def _block_number(value):
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+', value):
            return int(value, 16 if value.startswith('0x') else 10)
        raise ValueError('Invalid block number')

    def get_request_param(self, block_number: Union[int, str]) -> Dict:
        block_number = hex(self._block_number(block_number))
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [block_number, False],
            "method": "eth_getBlockByNumber"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, block_number: Union[int, str]):
        bn_int = self._block_number(block_number)

        path = os.path.join(CACHE_DIR, 'timestamp', f'{bn_int}.json')
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    cached = json.load(f)
                if (isinstance(cached, dict) and type(cached.get('schema_version')) is int
                        and cached['schema_version'] == 1
                        and type(cached.get('block_number')) is int and cached['block_number'] == bn_int
                        and isinstance(cached.get('block_hash'), str)
                        and re.fullmatch(r'0x[0-9a-fA-F]{64}', cached['block_hash'])
                        and type(cached.get('timestamp')) is int and cached['timestamp'] >= 0):
                    return cached['timestamp']
            except (OSError, ValueError, UnicodeError):
                pass
        return None

    async def _process(self, result: str, **kwargs):
        block_number = self._block_number(kwargs['block_number'])
        try:
            header = json.loads(result)['result']
            if not isinstance(header, dict) or self._block_number(header.get('number')) != block_number:
                raise ValueError('Block identity mismatch')
            if not isinstance(header.get('hash'), str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', header['hash']):
                raise ValueError('Invalid block hash')
            timestamp_hex = header.get('timestamp')
            if not isinstance(timestamp_hex, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', timestamp_hex):
                raise ValueError('Invalid block timestamp')
            timestamp = int(timestamp_hex, 16)
        except (ValueError, TypeError, KeyError):
            raise ChainRPCError('invalid_response', method='eth_getBlockByNumber') from None

        path = os.path.join(CACHE_DIR, 'timestamp')
        if not os.path.exists(path):
            os.makedirs(path)

        save_path = os.path.join(path, f'{block_number}.json')
        with open(save_path, 'w') as f:
            json.dump({'schema_version': 1, 'block_number': block_number,
                       'block_hash': header['hash'].lower(), 'timestamp': timestamp}, f)

        return timestamp
