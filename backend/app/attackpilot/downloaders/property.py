import json
import os
from typing import Dict, Optional, Any

import aiohttp
from web3 import Web3

from app.attackpilot.downloaders.defs import JSONRPCDownloader
from app.attackpilot.settings import CACHE_DIR
from app.attackpilot.utils.web3 import parse_bytes_data


class TokenPropertyDownloader(JSONRPCDownloader):
    def __init__(self, rpc_url: str):
        super().__init__(rpc_url)
        self.rpc_url = rpc_url
        self.cache_dir = os.path.join(CACHE_DIR, 'property')

    def get_request_params(self, contract_address: str) -> dict[
        str, list[dict[str, str | list[str] | int | list[dict[str, str | Any] | str]]] | str]:
        requests = []
        property_queries = [
            {'id': 1, 'property_key': 'name', 'func': 'name()', 'return_type': ['string']},
            {'id': 2, 'property_key': 'token_symbol', 'func': 'symbol()', 'return_type': ['string']},
            {'id': 4, 'property_key': 'token_symbol', 'func': 'SYMBOL()', 'return_type': ['string']},
            {'id': 5, 'property_key': 'decimals', 'func': 'decimals()', 'return_type': ['uint8']},
            {'id': 6, 'property_key': 'total_supply', 'func': 'totalSupply()', 'return_type': ['uint256']},
        ]
        for query in property_queries:
            requests.append({
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{
                    'to': contract_address,
                    "data": '0x' + Web3.keccak(text=query['func'])[:4].hex()
                }, 'latest'],
                "id": query['id']
            })

        return {
            "url": self.rpc_url,
            "json": requests,
        }

    async def _preprocess(self, contract_address: str) -> Optional[Dict]:
        if not self.cache_dir:
            return None

        path = os.path.join(self.cache_dir, f'{contract_address}.json')
        if not os.path.exists(path):
            return None

        try:
            with open(path, 'r') as f:
                cached = json.load(f)
            # All-default entries were formerly cached after failed RPC calls.
            # They must not permanently suppress another metadata request.
            if isinstance(cached, dict) and (cached.get('name') or cached.get('token_symbol')
                    or type(cached.get('decimals')) is int and 0 <= cached['decimals'] <= 255):
                return cached
        except:
            return None

    async def _fetch(self, contract_address: str) -> str:
        params = self.get_request_params(contract_address)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30), trust_env=True) as client:
            async with client.post(**params) as response:
                response.raise_for_status()
                return await response.text()

    async def _process(self, result: str, **kwargs) -> Dict:
        try:
            responses = json.loads(result)
            if not isinstance(responses, list):
                raise ValueError('Token metadata RPC returned an invalid batch')
            property_data = {
                'name': '',
                'token_symbol': '',
                'decimals': -1,
                'total_supply': -1
            }

            expected_ids = (1, 2, 4, 5, 6)
            by_id, ambiguous_ids = {}, set()
            for response in responses:
                if not isinstance(response, dict):
                    continue
                request_id = response.get('id')
                if type(request_id) is not int or request_id not in expected_ids:
                    continue
                if request_id in by_id:
                    ambiguous_ids.add(request_id)
                by_id[request_id] = response

            # Batch responses may arrive in any order. Never interpret a missing,
            # failed, or duplicated response as another property's return value.
            for request_id in expected_ids:
                response = by_id.get(request_id)
                if (request_id in ambiguous_ids or not isinstance(response, dict)
                        or response.get('jsonrpc') != '2.0' or response.get('error') is not None
                        or 'result' not in response):
                    continue
                data = response['result']

                if request_id == 1:  # name (string)
                    parsed = parse_bytes_data(data, ['string'])
                    if parsed and parsed[0]:
                        property_data['name'] = parsed[0].replace('\0', '')

                elif request_id == 2:  # One symbol() response, two ABI encodings.
                    parsed = parse_bytes_data(data, ['string'])
                    if parsed is not None:
                        property_data['token_symbol'] = parsed[0].replace('\0', '')
                    else:
                        parsed = parse_bytes_data(data, ['bytes32'])
                        if parsed is not None:
                            property_data['token_symbol'] = parsed[0].decode(errors='replace').replace('\0', '')

                elif request_id == 4:  # SYMBOL (string)
                    if not property_data['token_symbol']:
                        parsed = parse_bytes_data(data, ['string'])
                        if parsed and parsed[0]:
                            property_data['token_symbol'] = parsed[0].replace('\0', '')

                elif request_id == 5:  # decimals
                    parsed = parse_bytes_data(data, ['uint8'])
                    if parsed and parsed[0] is not None:
                        property_data['decimals'] = parsed[0]

                elif request_id == 6:  # totalSupply
                    parsed = parse_bytes_data(data, ['uint256'])
                    if parsed and parsed[0] is not None:
                        property_data['total_supply'] = parsed[0]

            if self.cache_dir and (property_data['name'] or property_data['token_symbol']
                                   or property_data['decimals'] >= 0):
                os.makedirs(self.cache_dir, exist_ok=True)
                path = os.path.join(self.cache_dir, f'{kwargs["contract_address"]}.json')
                with open(path, 'w') as f:
                    json.dump(property_data, f)

            return property_data

        except Exception as e:
            return {
                'name': '',
                'token_symbol': '',
                'decimals': -1,
                'total_supply': -1
            }
