import asyncio
import json
from typing import Dict

import aiohttp
import httpx
from app.attackpilot.errors import ChainRPCError


class Downloader:
    async def download(self, *args, **kwargs):
        result = await self._preprocess(*args, **kwargs)
        if result is not None:
            return result
        result = await self._fetch(*args, **kwargs)
        return await self._process(result, **kwargs)

    async def _preprocess(self, *args, **kwargs):
        raise NotImplementedError()

    async def _fetch(self, *args, **kwargs):
        raise NotImplementedError()

    async def _process(self, result, *args, **kwargs):
        raise NotImplementedError()


class JSONRPCDownloader(Downloader):
    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url

    def get_request_param(self, *args, **kwargs) -> Dict:
        raise NotImplementedError()

    async def _fetch(self, *args, **kwargs):
        params = self.get_request_param(*args, **kwargs)
        request = params.get('json', {})
        method = request.get('method') if isinstance(request, dict) else None
        timeout = aiohttp.ClientTimeout(total=180 if isinstance(method, str) and method.startswith(('debug_', 'trace_')) else 30)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as client:
            for attempt in range(2):
                try:
                    async with client.post(**params, allow_redirects=False) as response:
                        if response.status != 200:
                            raise ChainRPCError('http_error', method=method, status_code=response.status)
                        chunks, size = [], 0
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > 32 * 1024 * 1024:
                                raise ChainRPCError('invalid_response', method=method)
                            chunks.append(chunk)
                        text = b''.join(chunks).decode('utf-8')
                        data = json.loads(text)
                        if (not isinstance(data, dict) or data.get('jsonrpc') != '2.0'
                                or data.get('id') != request.get('id')
                                or type(data.get('id')) is not type(request.get('id'))):
                            raise ChainRPCError('invalid_response', method=method)
                        if data.get('error') is not None:
                            error = data['error']
                            raise ChainRPCError('rpc_error', method=method,
                                                rpc_code=error.get('code') if isinstance(error, dict) else None)
                        if 'result' not in data:
                            raise ChainRPCError('invalid_response', method=method)
                        return text
                except (UnicodeDecodeError, ValueError):
                    failure = ChainRPCError('invalid_response', method=method)
                except asyncio.TimeoutError:
                    failure = ChainRPCError('timeout', method=method)
                except (aiohttp.ClientError, OSError):
                    failure = ChainRPCError('unavailable', method=method)
                except ChainRPCError as exc:
                    failure = exc
                if attempt or not failure.retryable:
                    raise failure from None
                await asyncio.sleep(1)


class EtherscanDownloader(Downloader):
    def __init__(self, apikey: str):
        self.apikey = apikey

    def get_request_param(self, *args, **kwargs) -> Dict:
        raise NotImplementedError()

    async def _fetch(self, *args, **kwargs):
        params = self.get_request_param(*args, **kwargs)
        # Each request owns its transport. Most source downloaders are short
        # lived, so leaving a cached AsyncClient open leaks connection pools.
        async with httpx.AsyncClient(timeout=30.0, verify=True,
                                     headers={'User-Agent': 'AttackPilot/1.0'}) as client:
            for attempt in range(2):
                try:
                    async with asyncio.timeout(30):
                        response = await client.get(params['url'])
                        response.raise_for_status()
                        return response.text
                except (httpx.TransportError, TimeoutError):
                    if attempt:
                        raise
                except httpx.HTTPStatusError as exc:
                    if attempt or exc.response.status_code not in {408, 429, 500, 502, 503, 504}:
                        raise
                await asyncio.sleep(0.5)
