import asyncio
import hashlib
import json
import os
import re
from typing import Dict

import aiohttp

from app.attackpilot.downloaders.defs import JSONRPCDownloader, Downloader
from app.attackpilot.errors import TenderlyAPIError
from app.attackpilot.settings import PC_TRACER, CACHE_DIR, PHALCON_TRACER, ACCOUNT_SLUG, PROJECT_SLUG, TENDERLY_API_KEY


class PCTraceDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [
                transaction_hash.lower(),
                {"tracer": PC_TRACER},
            ],
            "method": "debug_traceTransaction"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'pc', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        result = json.loads(result)
        result = [item for item in result["result"]]

        # cache data
        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'pc')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(result, f)
        return result


class FlatTraceDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [
                transaction_hash.lower(),
                {"tracer": "callTracer"},
            ],
            "method": "debug_traceTransaction"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'trace/flat_trace', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        result = json.loads(result)
        result = [item for item in self._parse(result['result'])]

        # cache data
        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'trace/flat_trace')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(result, f)
        return result

    def _parse(self, data: dict):
        if not data.get('calls'):
            yield data
            return

        calls = data.pop('calls')
        yield data
        for _call in calls:
            yield from self._parse(_call)


class RawTraceDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [
                transaction_hash.lower(),
                {"tracer": "callTracer"},
            ],
            "method": "debug_traceTransaction"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'trace/raw_trace', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        result = json.loads(result)

        # cache data
        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'trace/raw_trace')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(result, f)
        return result


class PhalconTraceDownloader(JSONRPCDownloader):
    def get_request_param(self, transaction_hash: str) -> Dict:
        data = {
            "id": 1,
            "jsonrpc": "2.0",
            "params": [
                transaction_hash.lower(),
                {
                    "tracer": PHALCON_TRACER
                },
            ],
            "method": "debug_traceTransaction"
        }
        return {
            "url": self.rpc_url,
            "json": data,
        }

    async def _preprocess(self, transaction_hash: str):
        path = os.path.join(CACHE_DIR, 'trace/phalcon_trace', '%s.json' % transaction_hash)
        if not os.path.exists(path):
            return None
        with open(path, 'r') as f:
            return json.load(f)

    async def _process(self, result: str, **kwargs):
        parsed = json.loads(result)

        if 'error' in parsed:
            print(f"RPC Error for {kwargs.get('transaction_hash')}: {parsed['error']}")
            return {}

        result_data = parsed.get('result', {})

        transaction_hash = kwargs['transaction_hash']
        path = os.path.join(CACHE_DIR, 'trace/phalcon_trace')
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % transaction_hash)
        with open(path, 'w') as f:
            json.dump(result_data, f)

        return result_data


def _has_tenderly_error(result):
    return isinstance(result, dict) and any(result.get(key) for key in ('error', 'errors', 'error_code'))


def _tenderly_error_code(result):
    """Use upstream details only for classification, never in diagnostic output."""
    if not isinstance(result, dict):
        return None
    error = result.get('error')
    details = error if isinstance(error, dict) else {}
    code = details.get('slug') or details.get('code') or result.get('error_code')
    text = ' '.join(str(value) for value in (
        code, details.get('message'), error if isinstance(error, str) else None,
        result.get('message'), result.get('errors'),
    ) if value is not None).lower()
    if any(marker in text for marker in (
        'quota', 'monthly limit', 'monthly_limit', 'simulation limit', 'simulation_limit',
        'billing', 'payment required', 'insufficient credit', 'insufficient balance',
        'budget exceeded', 'budget_exceeded', 'credits exhausted',
    )):
        return 'quota_exceeded'
    if any(marker in text for marker in ('rate limit', 'rate_limit', 'too many requests', 'too_many_requests')):
        return 'rate_limit_exceeded'
    if any(marker in text for marker in ('invalid access key', 'invalid api key', 'authentication failed', 'unauthorized', 'unauthenticated')):
        return 'authentication_failed'
    if any(marker in text for marker in ('insufficient permission', 'permission denied', 'forbidden')):
        return 'forbidden'
    if isinstance(code, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', code):
        return code.lower()
    return None


def _tenderly_response_error(operation, *, status_code=None, result=None, invalid=False):
    code = _tenderly_error_code(result)
    if invalid and code is None:
        code = 'invalid_response'
    retryable = status_code in (408, 429) or (status_code is not None and status_code >= 500)
    if status_code is None:
        retryable = code in {
            'invalid_response', 'internal_server_error', 'service_unavailable', 'timeout',
            'gateway_timeout', 'rate_limit_exceeded', 'too_many_requests',
        }
    if code in {
        'unauthorized', 'unauthenticated', 'authentication_failed', 'invalid_access_key',
        'invalid_api_key', 'insufficient_permissions', 'forbidden', 'quota_exceeded',
        'insufficient_quota', 'monthly_limit_exceeded', 'limit_exceeded', 'payment_required',
        'simulation_limit_exceeded', 'invalid_request', 'bad_request',
    }:
        retryable = False
    return TenderlyAPIError(
        operation, status_code=status_code, error_code=code, retryable=retryable,
        message='Tenderly returned an invalid response' if invalid else 'Tenderly request failed',
    )


def _parse_tenderly_response(result_text, operation):
    try:
        result = json.loads(result_text)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        raise _tenderly_response_error(operation, invalid=True) from None
    if not isinstance(result, dict):
        raise _tenderly_response_error(operation, invalid=True)
    if _has_tenderly_error(result):
        raise _tenderly_response_error(operation, result=result)
    return result


def valid_tenderly_result(result):
    """A reverted EVM transaction is valid data; an API error is not."""
    return (
        isinstance(result, dict)
        and not _has_tenderly_error(result)
        and isinstance(result.get('transaction'), dict)
        and bool(result['transaction'])
        and isinstance(result.get('contracts'), list)
    )


def _simulation_request_fingerprint(payload):
    request = {key: value for key, value in payload.items() if key != 'cache'}
    encoded = json.dumps(request, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


async def _fetch_tenderly(params, operation, *, include_json=True, timeout=None):
    timeout = timeout or aiohttp.ClientTimeout(total=300, sock_connect=30, sock_read=300)
    request = {'headers': params['headers']}
    if include_json:
        request['json'] = params['json']
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.post(params['url'], **request) as response:
                result_text = await response.text()
                if response.status >= 400:
                    try:
                        result = json.loads(result_text)
                    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                        result = None
                    raise _tenderly_response_error(operation, status_code=response.status, result=result)
                return result_text
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        code = 'timeout' if isinstance(exc, asyncio.TimeoutError) else 'service_unavailable'
        raise TenderlyAPIError(
            operation, error_code=code, retryable=True, message='Tenderly connection or response failed',
        ) from None


class TenderlySimulateDownloader(Downloader):
    def get_request_param(self, payload: Dict) -> Dict:
        return {
            "url": f"https://api.tenderly.co/api/v1/account/{ACCOUNT_SLUG}/project/{PROJECT_SLUG}/simulate",
            "headers": {
                "X-Access-Key": TENDERLY_API_KEY,
                "Content-Type": "application/json",
            },
            "json": payload,
        }

    async def _preprocess(self, payload: Dict, **kwargs):
        if payload.get("cache", True):
            transaction_hash = payload["transaction_hash"]
            path = os.path.join(CACHE_DIR, 'trace/simulation_id', f'{transaction_hash.lower()}.json')
            if not os.path.exists(path):
                return None
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    wrapped_id = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return None
            if (
                isinstance(wrapped_id, dict)
                and wrapped_id.get('schema_version') == 2
                and wrapped_id.get('request_fingerprint') == _simulation_request_fingerprint(payload)
                and isinstance(wrapped_id.get('simulation_id'), str)
                and wrapped_id['simulation_id'].strip()
            ):
                return wrapped_id['simulation_id']

    def invalidate_cache(self, payload: Dict):
        if not payload.get('cache', True):
            return
        path = os.path.join(CACHE_DIR, 'trace/simulation_id', f"{payload['transaction_hash'].lower()}.json")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                wrapped_id = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if isinstance(wrapped_id, dict) and wrapped_id.get('request_fingerprint') == _simulation_request_fingerprint(payload):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    async def _fetch(self, payload: Dict, **kwargs):
        params = self.get_request_param(payload)
        return await _fetch_tenderly(params, 'simulate')

    async def _process(self, result_text: str, **kwargs):
        result = _parse_tenderly_response(result_text, 'simulate')
        simulation = result.get('simulation')
        simulation_id = simulation.get('id') if isinstance(simulation, dict) else None
        if not isinstance(simulation_id, str) or not simulation_id.strip():
            raise _tenderly_response_error('simulate', invalid=True)

        payload = kwargs.get('payload')
        if payload.get("cache", True):
            transaction_hash = payload["transaction_hash"]
            path = os.path.join(CACHE_DIR, 'trace/simulation_id')
            os.makedirs(path, exist_ok=True)
            cache_path = os.path.join(path, f'{transaction_hash.lower()}.json')
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'schema_version': 2,
                    'request_fingerprint': _simulation_request_fingerprint(payload),
                    'simulation_id': simulation_id,
                }, f, indent=4)
        return simulation_id


class TenderlyFullSimulationDownloader(Downloader):
    def get_request_param(self, simulation_id: str) -> Dict:
        return {
            "url": f"https://api.tenderly.co/api/v1/account/{ACCOUNT_SLUG}/project/{PROJECT_SLUG}/simulations/{simulation_id}",
            "headers": {
                "X-Access-Key": TENDERLY_API_KEY,
                "Content-Type": "application/json",
            }
        }

    async def _preprocess(self, simulation_id: str, **kwargs):
        path = os.path.join(CACHE_DIR, 'trace/simulation_result', f'{simulation_id.lower()}.json')
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                result = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return result if valid_tenderly_result(result) else None

    async def _fetch(self, simulation_id: str, **kwargs):
        params = self.get_request_param(simulation_id)
        return await _fetch_tenderly(params, 'simulation_result', include_json=False)

    async def _process(self, result_text: str, **kwargs):
        result = _parse_tenderly_response(result_text, 'simulation_result')
        if not valid_tenderly_result(result):
            raise _tenderly_response_error('simulation_result', invalid=True)

        simulation_id = kwargs.get('simulation_id')
        path = os.path.join(CACHE_DIR, 'trace/simulation_result')
        os.makedirs(path, exist_ok=True)

        cache_path = os.path.join(path, f'{simulation_id.lower()}.json')
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=4)

        return result


class TenderlyBundleSimulateDownloader(Downloader):
    def get_request_param(self, payload: Dict) -> Dict:
        return {
            "url": f"https://api.tenderly.co/api/v1/account/{ACCOUNT_SLUG}/project/{PROJECT_SLUG}/simulate-bundle",
            "headers": {
                "X-Access-Key": TENDERLY_API_KEY,
                "Content-Type": "application/json",
            },
            "json": payload,
        }

    async def _preprocess(self, payload: Dict, **kwargs):
        pass

    async def _fetch(self, payload: Dict, **kwargs):
        api_payload = {k: v for k, v in payload.items() if k != "bundle_id"}

        params = self.get_request_param(api_payload)
        return await _fetch_tenderly(params, 'simulate_bundle', timeout=aiohttp.ClientTimeout(total=300))

    async def _process(self, result_text: str, **kwargs):
        result = _parse_tenderly_response(result_text, 'simulate_bundle')
        simulations = result.get('simulation_results')
        payload = kwargs.get('payload') or {}
        requested = payload.get('simulations')
        if (
            not isinstance(simulations, list) or not simulations
            or any(
                not isinstance(item, dict) or _has_tenderly_error(item)
                or not isinstance(item.get('transaction'), dict) or not item['transaction']
                or not isinstance(item.get('simulation'), dict) or not item['simulation']
                for item in simulations
            )
        ):
            raise _tenderly_response_error('simulate_bundle', invalid=True)
        if isinstance(requested, list) and (
            len(simulations) > len(requested)
            or (
                len(simulations) < len(requested)
                and simulations[-1]['simulation'].get('status') is not False
            )
        ):
            raise _tenderly_response_error('simulate_bundle', invalid=True)

        return simulations
