"""Bounded, read-only Chainlink historical *reference* prices.

OCR rounds can be read from a recent storage snapshot. Legacy feeds require
historical block states because an in-progress Flux round can change later.
Neither path establishes which publication a protocol consumed in a transaction.
"""

import asyncio
import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import aiohttp
from eth_utils import keccak

from app.attackpilot.settings import CACHE_DIR, JSONRPCS
from app.attackpilot.utils.chainlink_config import (
    ChainlinkConfigurationError,
    get_chainlink_config,
    normalize_token_address,
)


SCHEMA_VERSION = 2
STRATEGY = "published_reference_ocr_or_historical_state_v3"
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX = re.compile(r"^0x[0-9a-fA-F]*$")
_OCR_VERSION = re.compile(r"(?:AccessControlled)?(?:OffchainAggregator|OCR2Aggregator) [0-9]+\.[0-9]+\.[0-9]+\Z")
_MASK64 = (1 << 64) - 1
_MAX_BODY_BYTES = 512 * 1024
_PLATFORMS = {"ethereum": "Ethereum", "bsc": "BNBChain", "bnbchain": "BNBChain", "bscchain": "BNBChain"}
_CHAIN_IDS = {"Ethereum": 1, "BNBChain": 56}
_CHAIN_SLUGS = {"Ethereum": "ethereum", "BNBChain": "bsc"}
# These verified historical implementations predate typeAndVersion(). A numeric
# version alone is not evidence that an arbitrary contract has Flux/OCR semantics.
# Official implementations: smartcontractkit/chainlink v1.0.0 FluxAggregator.sol
# and smartcontractkit/libocr contract/OffchainAggregator.sol (version 4).
_LEGACY_AGGREGATORS = {
    (1, "0x00c7a37b03690fb9f41b5c5af8131735c7275446"): (3, "FluxAggregator 3"),
    (1, "0xd3fcd40153e56110e6eeae13e12530e26c9cb4fd"): (4, "AccessControlledOffchainAggregator 4"),
}


class _ReadError(Exception):
    """Only fixed reason codes escape the transport boundary."""

    def __init__(self, reason: str, **diagnostics):
        self.reason = reason
        self.diagnostics = {}
        for key in ('method', 'signature'):
            value = diagnostics.get(key)
            if isinstance(value, str) and len(value) <= 80 and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\([A-Za-z0-9,]*\))?', value):
                self.diagnostics[key] = value
        for key in ('rpc_code', 'http_status', 'phase_id'):
            value = diagnostics.get(key)
            if type(value) is int and abs(value) <= 2 ** 31:
                self.diagnostics[key] = value
        super().__init__(reason)


async def _parallel_reads(*operations):
    tasks = [asyncio.create_task(operation) for operation in operations]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # A failed read must not leave a sibling consuming the RPC budget or
        # sharing a transport while the caller switches historical strategies.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _uint(value: Any) -> int:
    if isinstance(value, bool):
        raise _ReadError("invalid_response")
    try:
        number = int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)
    except (ValueError, TypeError, OverflowError):
        raise _ReadError("invalid_response") from None
    if number < 0 or (not isinstance(value, (str, int))):
        raise _ReadError("invalid_response")
    return number


def _selector(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


def _words(data: Any, expected: int) -> list[int]:
    if not isinstance(data, str) or not _HEX.fullmatch(data) or len(data) != 2 + expected * 64:
        raise _ReadError("invalid_contract_response")
    return [int(data[2 + offset * 64:2 + (offset + 1) * 64], 16) for offset in range(expected)]


def _string(data: Any) -> str:
    if not isinstance(data, str) or not _HEX.fullmatch(data) or len(data) < 130 or len(data) % 64 != 2:
        raise _ReadError("invalid_contract_response")
    raw = bytes.fromhex(data[2:])
    offset = int.from_bytes(raw[:32])
    if offset != 32 or len(raw) < offset + 32:
        raise _ReadError("invalid_contract_response")
    length = int.from_bytes(raw[offset:offset + 32])
    if length > 256 or offset + 32 + length > len(raw):
        raise _ReadError("invalid_contract_response")
    try:
        return raw[offset + 32:offset + 32 + length].decode("utf-8")
    except UnicodeDecodeError:
        raise _ReadError("invalid_contract_response") from None


@dataclass(frozen=True)
class _Round:
    round_id: int
    answer: int
    started_at: int
    updated_at: int
    answered_in_round: int

    @classmethod
    def decode(cls, data: Any, expected_id: int | None = None) -> "_Round":
        round_id, answer, started, updated, answered = _words(data, 5)
        if answer >= 1 << 255:
            answer -= 1 << 256
        return cls.validated(round_id, answer, started, updated, answered, expected_id)

    @classmethod
    def from_evidence(cls, data: Any) -> "_Round":
        if not isinstance(data, dict):
            raise _ReadError("invalid_round")
        return cls.validated(*(_uint(data.get(key)) for key in (
            "round_id", "answer", "started_at", "updated_at", "answered_in_round"
        )))

    @classmethod
    def validated(cls, round_id: int, answer: int, started: int, updated: int,
                  answered: int, expected_id: int | None = None) -> "_Round":
        if (
            not 0 < round_id < 1 << 80
            or round_id & _MASK64 == 0
            or (expected_id is not None and round_id != expected_id)
            or not 0 < answer < 1 << 255
            or not 0 < started <= updated < 1 << 256
            or not round_id <= answered < 1 << 80
        ):
            raise _ReadError("invalid_round")
        return cls(round_id, answer, started, updated, answered)

    def evidence(self) -> dict:
        # uint80 IDs exceed JavaScript's safe integer range; preserve strings.
        return {"round_id": str(self.round_id), "answer": str(self.answer),
                "started_at": self.started_at, "updated_at": self.updated_at,
                "answered_in_round": str(self.answered_in_round)}


class _Rpc:
    def __init__(self, client: aiohttp.ClientSession, config: dict):
        self.client = client
        self.max_calls = int(config["max_rpc_calls"])
        self.request_timeout = float(config.get("request_timeout_seconds", 8))
        self.calls = 0
        self.url = ""
        self.block_tag = ""

    async def request(self, method: str, params: list, url: str | None = None):
        if self.calls >= self.max_calls:
            raise _ReadError("rpc_budget_exceeded")
        self.calls += 1
        request_id = self.calls
        try:
            async with self.client.post(
                url or self.url,
                json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    reason = {401: "rpc_authentication", 403: "rpc_permission", 429: "rpc_rate_limited"}.get(response.status, "rpc_http_error")
                    raise _ReadError(reason, method=method, http_status=response.status)
                chunks, size = [], 0
                while chunk := await response.content.read(65536):
                    size += len(chunk)
                    if size > _MAX_BODY_BYTES:
                        raise _ReadError("invalid_response")
                    chunks.append(chunk)
                body = b"".join(chunks)
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    raise _ReadError("invalid_response") from None
        except asyncio.TimeoutError:
            raise _ReadError("rpc_timeout", method=method) from None
        except (aiohttp.ClientError, OSError, ValueError):
            # Never surface response bodies, endpoint URLs, API keys or repr(exc).
            raise _ReadError("rpc_unavailable", method=method) from None
        if not isinstance(payload, dict) or payload.get("id") != request_id or payload.get("jsonrpc") != "2.0":
            raise _ReadError("invalid_response")
        if payload.get("error") is not None:
            error = payload["error"]
            reason = "rpc_method_unsupported" if isinstance(error, dict) and error.get("code") == -32601 else "rpc_call_failed"
            if isinstance(error, dict) and (error.get('code') == 3 or
                    isinstance(error.get('message'), str) and error['message'].lower().startswith('execution reverted')):
                reason = 'contract_call_reverted'
            raise _ReadError(reason, method=method, rpc_code=error.get('code') if isinstance(error, dict) else None)
        if "result" not in payload or payload["result"] is None:
            raise _ReadError("invalid_response")
        return payload["result"]

    async def connect(self, urls: list[str], chain_id: int):
        reason = "rpc_not_configured"
        for url in urls:
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            try:
                actual_id = _uint(await self.request("eth_chainId", [], url=url))
            except _ReadError as exc:
                reason = exc.reason
                if reason == "rpc_budget_exceeded":
                    raise
                continue
            if actual_id == chain_id:
                self.url = url
                return
            reason = "chain_id_mismatch"
        raise _ReadError(reason)

    async def call(self, address: str, signature: str, argument: int | None = None):
        data = _selector(signature)
        if argument is not None:
            data += format(argument, "064x")
        try:
            return await self.request("eth_call", [{"to": address, "data": data}, self.block_tag])
        except _ReadError as exc:
            exc.diagnostics.update(_ReadError(exc.reason, signature=signature).diagnostics)
            raise


@dataclass
class _Phase:
    phase_id: int
    aggregator: str
    decimals: int
    first: _Round
    last: _Round
    type_and_version: str


class _History:
    def __init__(self, rpc: _Rpc, feed: dict, config: dict):
        self.rpc, self.feed, self.config = rpc, feed, config
        self.proxy = feed["proxy_address"].lower()
        self.rounds: dict[int, _Round] = {}

    async def round(self, phase_id: int, local_id: int) -> _Round:
        if not 0 < local_id <= _MASK64 or not 0 < phase_id < 1 << 16:
            raise _ReadError("invalid_round")
        round_id = (phase_id << 64) | local_id
        if round_id not in self.rounds:
            try:
                data = await self.rpc.call(self.proxy, "getRoundData(uint80)", round_id)
                self.rounds[round_id] = _Round.decode(data, round_id)
            except _ReadError as exc:
                if exc.reason in {"rpc_call_failed", "contract_call_reverted"}:
                    raise _ReadError("historical_round_unavailable", **exc.diagnostics) from None
                raise
        return self.rounds[round_id]

    async def phase(self, phase_id: int) -> _Phase:
        raw_address = _words(await self.rpc.call(self.proxy, "phaseAggregators(uint16)", phase_id), 1)[0]
        if not 0 < raw_address < 1 << 160:
            raise _ReadError("historical_phase_unavailable")
        aggregator = "0x" + format(raw_address, "040x")
        try:
            version = _string(await self.rpc.call(aggregator, "typeAndVersion()"))
        except _ReadError as exc:
            if exc.reason == 'contract_call_reverted':
                raise _ReadError('historical_aggregator_metadata_unavailable',
                                 **{**exc.diagnostics, 'phase_id': phase_id}) from None
            raise
        # OCR local round numbers are sequential. Legacy FluxAggregator round
        # history has different semantics and must not silently use this search.
        if not _OCR_VERSION.fullmatch(version):
            raise _ReadError("historical_aggregator_unsupported")
        description = _string(await self.rpc.call(aggregator, "description()"))
        if description.replace(" ", "").upper() != str(self.feed["pair"]).replace(" ", "").upper():
            raise _ReadError("feed_description_mismatch")
        decimals = _words(await self.rpc.call(aggregator, "decimals()"), 1)[0]
        if decimals > 255:
            raise _ReadError("invalid_feed_decimals")
        last_local = _Round.decode(await self.rpc.call(aggregator, "latestRoundData()"))
        if last_local.round_id > _MASK64:
            raise _ReadError("historical_aggregator_unsupported")
        first = await self.round(phase_id, 1)
        last = await self.round(phase_id, last_local.round_id)
        if last.updated_at < first.updated_at or last.answer != last_local.answer or last.updated_at != last_local.updated_at:
            raise _ReadError("inconsistent_history")
        return _Phase(phase_id, aggregator, decimals, first, last, version)

    async def bracket(self, requested: int) -> tuple[_Phase, _Round, _Round]:
        latest = _Round.decode(await self.rpc.call(self.proxy, "latestRoundData()"))
        phase_id = latest.round_id >> 64
        if phase_id <= 0:
            raise _ReadError("historical_aggregator_unsupported")
        self.rounds[latest.round_id] = latest
        next_first: _Round | None = None
        for offset in range(min(phase_id, int(self.config.get("max_phases", 8)))):
            phase = await self.phase(phase_id - offset)
            if offset == 0 and (phase.last.round_id != latest.round_id or phase.last != latest):
                raise _ReadError("inconsistent_history")
            if requested < phase.first.updated_at:
                next_first = phase.first
                continue
            if requested >= phase.last.updated_at:
                if requested == phase.last.updated_at:
                    raise _ReadError("timestamp_order_ambiguous")
                if next_first is not None:
                    # Without the proxy's activation event/block, a boundary
                    # between aggregators is not a verified historical bracket.
                    raise _ReadError("phase_boundary_ambiguous")
                raise _ReadError("successor_round_unavailable")
            if requested == phase.first.updated_at:
                raise _ReadError("timestamp_order_ambiguous")
            low, high = phase.first, phase.last
            for _ in range(int(self.config["max_history_rounds"])):
                low_id, high_id = low.round_id & _MASK64, high.round_id & _MASK64
                if high_id - low_id == 1:
                    if not low.updated_at < requested < high.updated_at:
                        raise _ReadError("inconsistent_history")
                    return phase, low, high
                if high_id <= low_id:
                    raise _ReadError("inconsistent_history")
                middle = await self.round(phase.phase_id, (low_id + high_id) // 2)
                if not low.updated_at <= middle.updated_at <= high.updated_at:
                    raise _ReadError("non_monotonic_history")
                if middle.updated_at == requested:
                    # A timestamp cannot establish the order of transactions
                    # within the second in which the oracle was updated.
                    raise _ReadError("timestamp_order_ambiguous")
                if middle.updated_at < requested:
                    low = middle
                else:
                    high = middle
            raise _ReadError("history_search_budget_exceeded")
        raise _ReadError("historical_phase_unavailable")


def _block_header(data, expected_number=None):
    if not isinstance(data, dict):
        raise _ReadError('invalid_block_context')
    number, timestamp = _uint(data.get('number')), _uint(data.get('timestamp'))
    block_hash, parent_hash = data.get('hash'), data.get('parentHash')
    if (expected_number is not None and number != expected_number
            or any(not isinstance(value, str) or not _HEX.fullmatch(value) or len(value) != 66
                   for value in (block_hash, parent_hash))):
        raise _ReadError('invalid_block_context')
    return {'number': number, 'timestamp': timestamp, 'hash': block_hash, 'parent_hash': parent_hash}


async def _historical_reference(rpc, feed, requested, recent_block, block_context=None):
    """Read the pre-second state and the next publication, including same-round updates.

    This searches block timestamps/publication timestamps, never Flux round IDs.
    Flux updateRoundAnswer records block.timestamp on every update, so publication
    timestamps remain monotonic within the pinned, verified aggregator phase.
    """
    recent_tag = rpc.block_tag
    latest = _block_header(recent_block)
    lower, upper = 0, latest['number']
    headers = {upper: latest}
    if block_context is not None:
        # Transaction metadata is only a search hint. Re-read its exact block
        # and parent before using it to skip the genesis-to-present search.
        if (not isinstance(block_context, dict) or type(block_context.get('number')) is not int
                or not 0 < block_context['number'] <= latest['number']
                or block_context.get('timestamp') != requested
                or not isinstance(block_context.get('hash'), str)
                or not re.fullmatch(r'0x[0-9a-fA-F]{64}', block_context['hash'])):
            raise _ReadError('invalid_block_context')
        hinted = block_context['number']
        raw_before, raw_after = await _parallel_reads(*(
            rpc.request('eth_getBlockByNumber', [hex(number), False])
            for number in (hinted - 1, hinted)
        ))
        before_hint, after_hint = _block_header(raw_before, hinted - 1), _block_header(raw_after, hinted)
        if (after_hint['hash'].lower() != block_context['hash'].lower()
                or after_hint['timestamp'] != requested
                or after_hint['parent_hash'] != before_hint['hash']):
            raise _ReadError('historical_block_context_mismatch')
        headers.update({hinted - 1: before_hint, hinted: after_hint})
        upper = hinted
        # Some networks permit equal timestamps in consecutive blocks. Keep
        # searching for a state strictly before the requested second there.
        if before_hint['timestamp'] < requested:
            lower = hinted - 1
    if lower == 0:
        headers[0] = _block_header(await rpc.request('eth_getBlockByNumber', ['0x0', False]), 0)
    # Ethereum's genesis timestamp is zero rather than the start of its normal
    # block cadence. A real early header gives time interpolation a useful bound.
    if lower == 0 and headers[0]['timestamp'] == 0 and upper > 1:
        headers[1] = _block_header(await rpc.request('eth_getBlockByNumber', ['0x1', False]), 1)
        if headers[1]['timestamp'] < requested:
            lower = 1
        else:
            upper = 1
    steps = 0
    while upper - lower > 1:
        low_time, high_time = headers[lower]['timestamp'], headers[upper]['timestamp']
        if not low_time < requested <= high_time:
            raise _ReadError('invalid_historical_block_bracket')
        steps += 1
        # Interpolate block time, never aggregator rounds. Periodic bisection
        # guarantees progress even across large changes in block production rate.
        middle = ((lower + upper) // 2 if steps % 4 == 0 else
                  lower + (requested - low_time) * (upper - lower) // (high_time - low_time))
        middle = min(upper - 1, max(lower + 1, middle))
        header = _block_header(await rpc.request('eth_getBlockByNumber', [hex(middle), False]), middle)
        headers[middle] = header
        if header['timestamp'] < requested:
            lower = middle
        else:
            upper = middle
    for number in (lower, upper):
        if number not in headers:
            headers[number] = _block_header(await rpc.request('eth_getBlockByNumber', [hex(number), False]), number)
    before, after = headers[lower], headers[upper]
    if (not before['timestamp'] < requested <= after['timestamp']
            or after['parent_hash'] != before['hash']):
        raise _ReadError('invalid_historical_block_bracket')
    proxy = feed['proxy_address'].lower()
    rpc.block_tag = hex(lower)
    selected = _Round.decode(await rpc.call(proxy, 'latestRoundData()'))
    phase_id = selected.round_id >> 64
    if not phase_id or selected.updated_at > before['timestamp']:
        raise _ReadError('invalid_round_timestamp')
    aggregator_data, active_data = await _parallel_reads(
        rpc.call(proxy, 'phaseAggregators(uint16)', phase_id), rpc.call(proxy, 'aggregator()'))
    aggregator_word = _words(aggregator_data, 1)[0]
    active_word = _words(active_data, 1)[0]
    if not 0 < aggregator_word < 1 << 160 or aggregator_word != active_word:
        raise _ReadError('historical_proxy_mapping_mismatch')
    aggregator = '0x' + format(aggregator_word, '040x')
    version_number = None
    metadata_source = 'typeAndVersion'
    try:
        version = _string(await rpc.call(aggregator, 'typeAndVersion()'))
        if not _OCR_VERSION.fullmatch(version):
            raise _ReadError('historical_aggregator_unsupported')
    except _ReadError as exc:
        if exc.reason != 'contract_call_reverted':
            raise
        known = _LEGACY_AGGREGATORS.get((feed['chain_id'], aggregator))
        if known is None:
            raise _ReadError('historical_aggregator_unsupported') from None
        version_number = _words(await rpc.call(aggregator, 'version()'), 1)[0]
        if version_number != known[0]:
            raise _ReadError('historical_aggregator_unsupported')
        version, metadata_source = known[1], 'verified_legacy_catalog'
    description_data, decimals_data = await _parallel_reads(
        rpc.call(aggregator, 'description()'), rpc.call(aggregator, 'decimals()'))
    description = _string(description_data)
    if description.replace(' ', '').upper() != str(feed['pair']).replace(' ', '').upper():
        raise _ReadError('feed_description_mismatch')
    decimals = _words(decimals_data, 1)[0]
    if decimals > 255:
        raise _ReadError('invalid_feed_decimals')

    observations = {lower: selected}
    async def publication(number):
        if number not in observations:
            rpc.block_tag = hex(number)
            observed = _Round.decode(await rpc.call(proxy, 'latestRoundData()'))
            if observed.round_id >> 64 != phase_id:
                raise _ReadError('phase_boundary_ambiguous')
            if observed.updated_at == requested:
                raise _ReadError('timestamp_order_ambiguous')
            if observed.updated_at < requested and observed != selected:
                raise _ReadError('inconsistent_history')
            observations[number] = observed
        return observations[number]

    # Find an upper bound locally before bisecting publication timestamps. The
    # next report can update the same Flux round; getRoundData(round+1) misses it.
    left, right, distance = lower, lower + 1, 1
    while (await publication(right)).updated_at < requested:
        left = right
        if right == latest['number']:
            raise _ReadError('successor_round_unavailable')
        distance *= 2
        right = min(lower + distance, latest['number'])
    while right - left > 1:
        middle = (left + right) // 2
        if (await publication(middle)).updated_at > requested:
            right = middle
        else:
            left = middle
    successor = await publication(right)
    predecessor = await publication(left)
    if predecessor != selected or not selected.updated_at < requested < successor.updated_at:
        raise _ReadError('inconsistent_history')
    boundary_headers = {}
    for number in (left, right):
        boundary_headers[number] = _block_header(await rpc.request('eth_getBlockByNumber', [hex(number), False]), number)
    previous_block, successor_block = boundary_headers[left], boundary_headers[right]
    if (successor_block['parent_hash'] != previous_block['hash']
            or successor.updated_at != successor_block['timestamp']
            or not requested <= previous_block['timestamp'] < successor_block['timestamp']):
        # The immediate next block may itself publish the successor.
        if not (left == lower and previous_block == before
                and before['timestamp'] < requested < successor_block['timestamp']
                and successor_block['parent_hash'] == before['hash']
                and successor.updated_at == successor_block['timestamp']):
            raise _ReadError('invalid_successor_block')
    for original in (before, successor_block):
        checked = _block_header(await rpc.request('eth_getBlockByNumber', [hex(original['number']), False]), original['number'])
        if checked != original:
            raise _ReadError('snapshot_changed')
    rpc.block_tag = recent_tag
    return _Phase(phase_id, aggregator, decimals, selected, successor, version), selected, successor, {
        'reference_method': 'historical_block_snapshot',
        'aggregator_version': version_number, 'type_metadata_source': metadata_source,
        'historical_snapshot': {
            'scope': 'block_before_requested_second', 'before': before, 'after': after,
            'successor_previous_block': previous_block, 'successor_block': successor_block,
            'previous_publication': predecessor.evidence(),
            'proxy_mapping_verified': True, 'same_phase_verified': True,
            'successor_relation': 'next_publication_block', 'block_hashes_rechecked': True,
        },
    }


def _snapshot_cache_valid(cached, selected, successor, requested, feed):
    snapshot = cached.get('historical_snapshot')
    if not isinstance(snapshot, dict):
        return False
    def header(key):
        item = snapshot.get(key)
        if not isinstance(item, dict):
            raise _ReadError('invalid_block_context')
        return _block_header({**item, 'parentHash': item.get('parent_hash')})
    before, after = header('before'), header('after')
    previous, following = header('successor_previous_block'), header('successor_block')
    version = cached.get('aggregator_type_and_version')
    known = _LEGACY_AGGREGATORS.get((feed['chain_id'], cached.get('aggregator_address')))
    valid_type = (isinstance(version, str) and _OCR_VERSION.fullmatch(version) is not None
                  and cached.get('type_metadata_source') == 'typeAndVersion') or (
        known is not None and version == known[1] and cached.get('aggregator_version') == known[0]
        and cached.get('type_metadata_source') == 'verified_legacy_catalog')
    return bool(valid_type and snapshot.get('scope') == 'block_before_requested_second'
                and snapshot.get('proxy_mapping_verified') is True and snapshot.get('same_phase_verified') is True
                and snapshot.get('block_hashes_rechecked') is True
                and snapshot.get('successor_relation') == 'next_publication_block'
                and after['number'] == before['number'] + 1 and after['parent_hash'] == before['hash']
                and selected.updated_at <= before['timestamp'] < requested <= after['timestamp']
                and following['number'] == previous['number'] + 1 and following['parent_hash'] == previous['hash']
                and previous['number'] >= before['number'] and previous['timestamp'] < following['timestamp']
                and (previous['timestamp'] >= requested or previous == before)
                and requested < following['timestamp'] == successor.updated_at
                and snapshot.get('previous_publication') == selected.evidence()
                and successor.round_id >> 64 == selected.round_id >> 64)


def _fingerprint(platform: str, address: str, feed: dict) -> str:
    context = {"schema_version": SCHEMA_VERSION, "strategy": STRATEGY,
               "platform": platform, "token_address": address, "feed": feed}
    return hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cache_path(fingerprint: str, timestamp: int) -> Path:
    return Path(CACHE_DIR) / "price" / "chainlink" / f"{fingerprint}_{timestamp}.json"


def _read_cache(path: Path, fingerprint: str, requested: int, feed: dict) -> dict | None:
    try:
        if path.stat().st_size > 32 * 1024:
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict):
            return None
        selected = _Round.from_evidence(cached)
        successor_round = _Round.from_evidence(cached.get("successor"))
        updated = selected.updated_at
        phase = _uint(cached.get("phase_id"))
        round_id = selected.round_id
        successor_id = successor_round.round_id
        decimals = _uint(cached.get("feed_decimals"))
        answer = selected.answer
        if decimals > 255 or not 0 < answer < 1 << 255 or not 0 < phase < 1 << 16:
            return None
        platform = next((name for name, chain_id in _CHAIN_IDS.items() if chain_id == feed["chain_id"]), None)
        if platform is None:
            return None
        block = cached.get("block_context", {})
        method = cached.get('reference_method')
        snapshot = method == 'historical_block_snapshot'
        if method not in {'historical_block_snapshot', 'ocr_adjacent_round_storage'}:
            return None
        if snapshot and not _snapshot_cache_valid(cached, selected, successor_round, requested, feed):
            return None
        if (
            not isinstance(block, dict)
            or not _ADDRESS.fullmatch(str(cached.get("aggregator_address", "")))
            or (not snapshot and not _OCR_VERSION.fullmatch(str(cached.get("aggregator_type_and_version", ""))))
            or not _HEX.fullmatch(str(block.get("hash", "")))
            or len(str(block.get("hash", ""))) != 66
            or _uint(block.get("number")) <= 0
            or _uint(block.get("timestamp")) < successor_round.updated_at
            or block.get("purpose") != "round_storage_snapshot"
            or block.get("finality_verified") is not False
        ):
            return None
        with localcontext() as ctx:
            ctx.prec = 400
            exact = Decimal(answer).scaleb(-decimals)
        if (
            type(cached.get("schema_version")) is not int
            or cached.get("schema_version") != SCHEMA_VERSION
            or cached.get("config_fingerprint") != fingerprint
            or cached.get("strategy") != STRATEGY
            or cached.get("status") != "available"
            or cached.get("reason") is not None
            or cached.get("source") != "chainlink"
            or type(cached.get("chain_id")) is not int
            or cached.get("chain_id") != feed["chain_id"]
            or cached.get("chain") != _CHAIN_SLUGS[platform]
            or cached.get("contract_address") != feed["token_address"]
            or cached.get("pair") != feed["pair"]
            or cached.get("quote_asset") != feed["quote_asset"]
            or cached.get("symbol") != feed.get("token_symbol", feed["base_asset"])
            or type(cached.get("token_decimals")) is not int
            or type(cached.get("decimals")) is not int
            or cached.get("token_decimals") != feed["token_decimals"]
            or cached.get("decimals") != feed["token_decimals"]
            or cached.get("configuration_origin") != feed["configuration_origin"]
            or cached.get("mapping_type") != feed["mapping_type"]
            or cached.get("temporal_scope") != "published_round_reference"
            or cached.get("timestamp_granularity") != "seconds"
            or cached.get("max_age_policy_scope") != "application_reference_valuation"
            or cached.get("max_age_seconds") != feed["max_age_seconds"]
            or cached.get("requested_timestamp") != requested
            or cached.get("timestamp") != updated
            or not 0 < updated < requested < successor_round.updated_at
            or requested - updated > int(feed["max_age_seconds"])
            or cached.get("quote_age_seconds") != requested - updated
            or round_id >> 64 != phase
            or (not snapshot and successor_id != round_id + 1)
            or successor_id >> 64 != phase
            or cached.get("feed_address") != feed["proxy_address"].lower()
            or cached.get("proxy_address") != feed["proxy_address"].lower()
            or cached.get("source_url") != feed["source_url"]
            or cached.get("price_exact") != format(exact, "f")
            or cached.get("price") != float(exact)
            or not math.isfinite(float(exact)) or float(exact) <= 0
            or decimals > 255 or answer <= 0
            or cached.get("transaction_state_verified") is not False
            or cached.get("proxy_activation_verified") is not False
        ):
            return None
        return {**cached, "cache_hit": True, "rpc_calls": 0}
    except (OSError, ValueError, TypeError, AttributeError, _ReadError):
        return None


def _write_cache(path: Path, result: dict):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".quote-", suffix=".tmp", delete=False) as output:
            temporary = output.name
            json.dump(result, output, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    except (OSError, TypeError, ValueError):
        pass
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                pass


async def get_chainlink_price(chain: str, address: str, timestamp: int, *, block_context=None) -> dict:
    """Return an auditable historical round or a structured unavailable reason.

    No current-price fallback, paid APIs, wallet, transactions, or RPC debugging
    are involved. Transport failures are deliberately represented without URLs.
    Caller cancellation propagates, while each quote has a total deadline and
    one RPC request budget shared by endpoint selection and all phase searches.
    """
    platform = _PLATFORMS.get(str(chain).lower())
    token_address = normalize_token_address(address) or str(address).lower()
    result = {"schema_version": SCHEMA_VERSION, "source": "chainlink", "status": "unavailable",
              "reason": None, "price": None, "price_exact": None, "timestamp": None,
              "updated_at": None, "requested_timestamp": timestamp,
              "chain": _CHAIN_SLUGS.get(platform, str(chain)), "contract_address": token_address,
              "strategy": STRATEGY, "temporal_scope": "published_round_reference",
              "timestamp_granularity": "seconds", "transaction_state_verified": False,
              "proxy_activation_verified": False, "rpc_calls": 0, "cache_hit": False}
    if platform is None or not _ADDRESS.fullmatch(token_address):
        return {**result, "status": "unsupported", "reason": "feed_not_configured"}
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        return {**result, "reason": "invalid_timestamp"}
    try:
        config = get_chainlink_config()
    except ChainlinkConfigurationError:
        return {**result, "reason": "invalid_feed_configuration"}
    if not config["enabled"]:
        return {**result, "status": "disabled", "reason": "chainlink_disabled"}
    feed = config["feeds"].get(platform, {}).get(token_address)
    if feed is None:
        return {**result, "status": "unsupported", "reason": "feed_not_configured"}
    if int(feed["chain_id"]) != _CHAIN_IDS[platform] or not _ADDRESS.fullmatch(feed["proxy_address"]):
        return {**result, "reason": "invalid_feed_configuration"}
    result.update({"feed_address": feed["proxy_address"].lower(), "proxy_address": feed["proxy_address"].lower(),
                   "pair": feed["pair"], "symbol": feed.get("token_symbol", feed["base_asset"]), "quote_asset": feed["quote_asset"],
                   "chain_id": feed["chain_id"], "decimals": feed["token_decimals"],
                   "token_decimals": feed["token_decimals"], "max_age_seconds": feed["max_age_seconds"],
                   "max_age_policy_scope": "application_reference_valuation",
                   "configuration_origin": feed.get("configuration_origin"),
                   "mapping_type": feed.get("mapping_type"),
                   "source_url": feed["source_url"]})
    fingerprint = _fingerprint(platform, token_address, feed)
    result["config_fingerprint"] = fingerprint
    path = _cache_path(fingerprint, timestamp)
    cached = _read_cache(path, fingerprint, timestamp, feed)
    if cached is not None:
        return cached
    rpc = None
    try:
        async with asyncio.timeout(float(config["timeout_seconds"])):
            async with aiohttp.ClientSession(trust_env=False) as client:
                rpc = _Rpc(client, config)
                await rpc.connect(JSONRPCS.get(platform, []), _CHAIN_IDS[platform])
                block = await rpc.request("eth_getBlockByNumber", ["latest", False])
                if not isinstance(block, dict):
                    raise _ReadError("invalid_block_context")
                number, block_timestamp = _uint(block.get("number")), _uint(block.get("timestamp"))
                block_hash = block.get("hash")
                if not isinstance(block_hash, str) or not _HEX.fullmatch(block_hash) or len(block_hash) != 66 or block_timestamp <= 0:
                    raise _ReadError("invalid_block_context")
                rpc.block_tag = hex(number)
                result["block_context"] = {"number": number, "hash": block_hash, "timestamp": block_timestamp,
                                           "purpose": "round_storage_snapshot", "finality_verified": False}
                if timestamp > block_timestamp:
                    raise _ReadError("future_timestamp")
                recent_tag = rpc.block_tag
                extra = {'reference_method': 'ocr_adjacent_round_storage'}
                if block_timestamp - timestamp > 7 * 86400:
                    try:
                        phase, selected, successor, extra = await _historical_reference(rpc, feed, timestamp, block, block_context)
                    except _ReadError as exc:
                        if exc.reason not in {'rpc_call_failed', 'contract_call_reverted', 'rpc_method_unsupported',
                                              'rpc_permission', 'rpc_unavailable', 'rpc_http_error', 'invalid_response'}:
                            raise
                        result['historical_state_failure'] = {'reason': exc.reason, 'diagnostics': exc.diagnostics}
                        rpc.block_tag = recent_tag
                        phase, selected, successor = await _History(rpc, feed, config).bracket(timestamp)
                else:
                    try:
                        phase, selected, successor = await _History(rpc, feed, config).bracket(timestamp)
                    except _ReadError as exc:
                        if exc.reason not in {'historical_aggregator_metadata_unavailable', 'historical_aggregator_unsupported'}:
                            raise
                        rpc.block_tag = recent_tag
                        phase, selected, successor, extra = await _historical_reference(rpc, feed, timestamp, block, block_context)
                rpc.block_tag = recent_tag
                result.update(extra)
                if successor.updated_at > block_timestamp:
                    raise _ReadError("invalid_round_timestamp")
                # The provider must still identify this number with the same
                # canonical block when the bounded search completes.
                final_block = await rpc.request("eth_getBlockByNumber", [rpc.block_tag, False])
                if not isinstance(final_block, dict) or final_block.get("hash") != block_hash:
                    raise _ReadError("snapshot_changed")
                with localcontext() as ctx:
                    ctx.prec = 400
                    exact = Decimal(selected.answer).scaleb(-phase.decimals)
                price = float(exact)
                if not math.isfinite(price) or price <= 0:
                    raise _ReadError("invalid_price")
                result.update(selected.evidence())
                result.update({"timestamp": selected.updated_at, "feed_decimals": phase.decimals,
                               "phase_id": phase.phase_id, "aggregator_address": phase.aggregator,
                               "aggregator_type_and_version": phase.type_and_version,
                               "successor": successor.evidence(), "quote_age_seconds": timestamp - selected.updated_at,
                               "rpc_calls": rpc.calls, "price_exact": format(exact, "f")})
                if timestamp - selected.updated_at > int(feed["max_age_seconds"]):
                    return {**result, "status": "stale", "reason": "stale_reference_round", "price": None}
                result.update({"status": "available", "reason": None, "price": price})
    except _ReadError as exc:
        return {**result, "reason": exc.reason, "diagnostics": exc.diagnostics,
                "rpc_calls": rpc.calls if rpc else 0}
    except asyncio.TimeoutError:
        return {**result, "reason": "quote_deadline_exceeded", "rpc_calls": rpc.calls if rpc else 0}
    _write_cache(path, result)
    return result
