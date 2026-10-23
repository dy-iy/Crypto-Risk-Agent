import asyncio
import copy
import json
import logging
import re
import sys
import time
from typing import List, Optional, Dict, Set

import aiohttp
import httpx

from app.attackpilot.daos.contract import ContractDao
from app.attackpilot.downloaders.defs import Downloader
from app.attackpilot.downloaders.trans import TxReceiptDownloader
from app.attackpilot.downloaders.trace import TenderlyFullSimulationDownloader, TenderlySimulateDownloader, \
    TenderlyBundleSimulateDownloader, valid_tenderly_result
from app.attackpilot.errors import HistoricalReplayContextError, HistoricalReplayValidationError, TenderlyAPIError
from app.attackpilot.entities.contract import ContractEntity
from app.attackpilot.entities.trace import MixTraceItem, Log, StorageOp
from app.attackpilot.settings import PLATFORM_TO_CHAIN_ID
from app.attackpilot.utils.balance_utils import BalanceAnalyzer, fetch_token_prices
from app.attackpilot.utils.price import platform_to_chain
from app.attackpilot.utils.replay_validation import validate_original_transaction, validate_simulated_transaction
from app.attackpilot.utils.signature import hex_to_int


def _historical_transaction_position(transaction: Dict) -> tuple[int, int]:
    if not isinstance(transaction, dict):
        raise HistoricalReplayContextError('Historical transaction data is unavailable')

    def position(field: str) -> int:
        value = transaction.get(field)
        if type(value) is int:
            number = value
        elif isinstance(value, str) and value:
            try:
                number = int(value, 16 if value.lower().startswith('0x') else 10)
            except ValueError:
                raise HistoricalReplayContextError(f'Invalid historical {field}') from None
        else:
            raise HistoricalReplayContextError(f'Missing historical {field}')
        if number < 0:
            raise HistoricalReplayContextError(f'Invalid historical {field}')
        return number

    return position('blockNumber'), position('transactionIndex')


class MixTraceTree:

    def __init__(self, root: Dict, contracts: List[Dict], addr2name: Dict):
        enricher = TraceSourceEnricher(contracts, addr2name)
        self.contracts: Dict[str, ContractEntity] = enricher.entity_map
        self.root = enricher.enrich_tree(root)
        self.node_map: Dict[int, MixTraceItem] = {}  # absolute_position -> MixTraceItem
        self._build_map(self.root)

    def _build_map(self, node: MixTraceItem):
        if node.absolute_position != -1:
            self.node_map[node.absolute_position] = node

        for child in node.calls:
            self._build_map(child)

    def get_node(self, pos: int) -> Optional[MixTraceItem]:
        return self.node_map.get(pos)

    def get_all_positions(self) -> List[int]:
        return sorted(list(self.node_map.keys()))


class TraceSourceEnricher:
    def __init__(self, contracts: List[Dict], addr2name: Dict):
        safe_contracts = contracts or []
        # address -> ContractEntity
        self.entity_map: Dict[str, ContractEntity] = {
            c.get("address", "").lower(): ContractEntity.from_dict(c)
            for c in safe_contracts
        }
        # address -> name
        self.addr2name = addr2name

    def enrich_tree(self, root_data: Dict) -> MixTraceItem:

        def _is_call_type(call_type: str) -> bool:
            call_types = {"CALL", "STATICCALL", "DELEGATECALL", "CREATE", "CREATE2", "CALLCODE", "JUMPDEST", "JUMP"}
            return call_type in call_types

        def _recursive_build(data: Dict, parent: Optional[MixTraceItem] = None, depth: int = 0) -> MixTraceItem | None:
            if not data:
                return None

            call_type = data.get('call_type', '')

            node = MixTraceItem(data, parent, depth)
            to_addr = node.to_addr.lower()
            from_addr = node.from_addr.lower()
            context_addr = node.address.lower()
            node.from_name = self.addr2name.get(from_addr, "")
            node.to_name = self.addr2name.get(context_addr) or self.addr2name.get(to_addr, "")

            # SLOAD/SSTORE/LOG
            if not _is_call_type(call_type) and parent is not None:
                if call_type in ["SLOAD", "SSTORE"]:
                    item = StorageOp(data)
                    item.source_snippet = self._get_snippet(
                        parent.to_addr.lower(), item.loc.file_index, item.loc.code_start, item.loc.code_length
                    )
                    item.source_line = self._get_line(parent.to_addr.lower(), item.loc.file_index, item.loc.line_number)
                    parent.storage_ops.append(item)
                elif call_type.startswith("LOG"):
                    item = Log(data)
                    item.source_snippet = self._get_snippet(
                        parent.to_addr.lower(), item.loc.file_index, item.loc.code_start, item.loc.code_length
                    )
                    parent.events.append(item)
                return None

            for _input in node.decoded_input:
                _input.decoded_value = self.addr2name.get(str(_input.value), "")

            for _output in node.decoded_output:
                _output.decoded_value = self.addr2name.get(str(_output.value), "")

            contracts = self.entity_map.get(to_addr)
            if contracts:
                contract_type, description = contracts.get_contract_status()

                if contract_type == "FULLY_OPEN_SOURCE":
                    file_idx = node.function_loc.file_index
                    if contracts and file_idx in contracts.file_map:
                        node.contract_source = contracts.file_map[file_idx]
                    if node.function_loc.code_start != -1:
                        node.function_source = self._get_snippet(
                            to_addr, node.function_loc.file_index, node.function_loc.code_start,
                            node.function_loc.code_length
                        )
                elif contract_type == "BYTECODE_ONLY":
                    node.contract_source = (f"Unverified Contract (Bytecode Only).\n"
                                            f"Tip: Use `analyze_unverified_contract(session_id, {node.absolute_position})` "
                                            f"to decompile and inspect logic.")
                    node.function_source = "Source not available. Only Bytecode."
                else:
                    node.contract_source = description
                    node.function_source = description

            if parent and parent is not None and node.caller_loc.code_start != -1:
                node.caller_source = self._get_snippet(
                    parent.to_addr, node.caller_loc.file_index, node.caller_loc.code_start, node.caller_loc.code_length
                )

            raw_calls = data.get('calls') or []
            if isinstance(raw_calls, list):
                for sub_data in raw_calls:
                    child_node = _recursive_build(sub_data, node, depth + 1)
                    if child_node:
                        node.calls.append(child_node)
            return node

        return _recursive_build(root_data)

    def _get_snippet(self, addr: str, file_idx: int, start: int, length: int) -> str:
        entity = self.entity_map.get(addr.lower())
        if not entity or file_idx not in entity.file_map:
            return ""
        source_code = entity.file_map[file_idx]
        if not source_code or start == -1:
            return ""
        encoded_source = source_code.encode('utf-8')
        byte_end = start + length
        snippet_bytes = encoded_source[start:byte_end]
        try:
            return snippet_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return snippet_bytes.decode('utf-8', errors='replace')

    def _get_line(self, addr: str, file_idx: int, line: int) -> str:
        entity = self.entity_map.get(addr.lower())
        if not entity or file_idx not in entity.file_map:
            return ""

        source_code = entity.file_map[file_idx]
        if not source_code or line < 1:
            return ""

        try:
            lines = source_code.splitlines()
            if 1 <= line <= len(lines):
                return lines[line - 1]
        except Exception:
            return ""

        return ""


class TenderlyDao:
    def __init__(self, _platform, tx_downloader, source_downloader: Downloader, bytecode_downloader, creation_downloader: Downloader, addr2property: Dict, *, receipt_downloader: Downloader | None = None):
        self.chain_id = PLATFORM_TO_CHAIN_ID.get(_platform, 1)
        self.tx_downloader = tx_downloader if tx_downloader else None
        rpc_url = getattr(tx_downloader, 'rpc_url', None)
        self.receipt_downloader = receipt_downloader
        if self.receipt_downloader is None and isinstance(rpc_url, str) and rpc_url:
            self.receipt_downloader = TxReceiptDownloader(rpc_url=rpc_url)
        self.source_downloader = source_downloader
        self.id_downloader = TenderlySimulateDownloader()
        self.result_downloader = TenderlyFullSimulationDownloader()
        self.bytecode_downloader = bytecode_downloader
        self.creation_downloader = creation_downloader
        self.addr2property = addr2property

    async def send_request(self, payload) -> Dict:
        max_attempts = 3
        simulation_id = None
        for attempt in range(1, max_attempts + 1):
            try:
                if simulation_id is None:
                    candidate_id = await self.id_downloader.download(payload=payload)
                    if not isinstance(candidate_id, str) or not candidate_id.strip():
                        raise TenderlyAPIError('simulate', error_code='invalid_response', retryable=True)
                    simulation_id = candidate_id
                full_result = await self.result_downloader.download(simulation_id=simulation_id)
                if not valid_tenderly_result(full_result):
                    raise TenderlyAPIError('simulation_result', error_code='invalid_response', retryable=True)
                return full_result
            except TenderlyAPIError as exc:
                # A failed creation response can still represent a paid server
                # simulation. Without its ID there is no safe idempotent retry;
                # keep runtime request budgets tied to actual creation attempts.
                if simulation_id is None:
                    raise
                if exc.operation == 'simulation_result' and exc.status_code == 404:
                    # Drop only the matching stale ID. Do not automatically create
                    # several new simulations for a permanent lookup failure.
                    try:
                        self.id_downloader.invalidate_cache(payload)
                    except OSError as cache_error:
                        logging.getLogger(__name__).warning(
                            'Tenderly stale ID cache could not be removed: %s', type(cache_error).__name__
                        )
                if not exc.retryable or attempt == max_attempts:
                    raise
                logging.getLogger(__name__).warning('Tenderly retry %s/%s: %s', attempt, max_attempts, exc)
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                if simulation_id is None or attempt == max_attempts:
                    raise
                logging.getLogger(__name__).warning(
                    'Tenderly retry %s/%s: %s', attempt, max_attempts, type(exc).__name__
                )
            await asyncio.sleep(min(2 ** attempt, 8))

    async def simulate_tx_in_tenderly(self, transaction_hash: str, *, enrich_contracts: bool = True):
        tx_info = await self.tx_downloader.download(transaction_hash=transaction_hash)
        block_number, transaction_index = _historical_transaction_position(tx_info)
        if self.receipt_downloader is None:
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence', details={'field': 'rpc_receipt'})
        receipt = await self.receipt_downloader.download(transaction_hash=transaction_hash)
        original_context = validate_original_transaction(transaction_hash, self.chain_id, tx_info, receipt)

        payload = {
            "transaction_hash": transaction_hash,
            "network_id": str(self.chain_id),
            "from": tx_info.get("from", ""),
            "to": tx_info.get("to", ""),
            "input": tx_info.get("input", ""),
            "gas": hex_to_int(tx_info.get("gas", "")),
            "gas_price": str(hex_to_int(tx_info.get("gasPrice", ""))),
            "value": str(hex_to_int(tx_info.get("value", ""))),
            "block_number": block_number,
            "transaction_index": transaction_index,
            "save": True,
            "save_if_fails": True,
            "simulation_type": "full",
            "generate_state_diff": True,
            "generate_visual_trace": True,
            "cache": True
        }
        if isinstance(tx_info.get('accessList'), list):
            payload['access_list'] = tx_info['accessList']
        full_result = await self.send_request(payload)
        try:
            validation = validate_simulated_transaction(original_context, full_result)
        except HistoricalReplayValidationError as exc:
            exc.details.update({
                'original_transaction_hash': original_context['transaction_hash'],
                'network_id': str(original_context['chain_id']),
                'block_number': original_context['block_number'],
                'transaction_index': original_context['transaction_index'],
            })
            # Preserve the raw result for diagnostics, but do not pin future
            # explicit attempts to a simulation that failed evidence checks.
            try:
                self.id_downloader.invalidate_cache(payload)
            except OSError as cache_error:
                logging.getLogger(__name__).warning(
                    'Invalid original replay ID cache could not be removed: %s', type(cache_error).__name__
                )
            raise

        transaction = dict(full_result['transaction'])
        transaction['original_transaction_hash'] = original_context['transaction_hash']
        transaction['original_block_hash'] = original_context['block_hash']
        transaction['original_transaction_index'] = original_context['transaction_index']
        transaction['baseline_validation'] = validation
        from app.attackpilot.utils.oracle_evidence import extract_chainlink_observations
        transaction['oracle_evidence'] = extract_chainlink_observations(transaction, self.chain_id_to_platform())
        contracts = full_result.get('contracts', [])

        # Transaction summaries consume only transaction data. Source enrichment is
        # needed by the debugger, not by this earlier collection stage.
        if not enrich_contracts:
            return transaction, contracts, dict(self.addr2property)

        addresses = transaction.get('addresses', [])
        contracts = await self._supplement_missing_contracts(
            addresses, contracts, block_number=transaction.get('block_number'))
        known_names = {
            c['address'].lower(): c['contract_name'] for c in contracts
            if c.get('address') and c.get('contract_name') and c.get('public') is not False
        }
        # Source lookup already supplied the name or an explicit failure. Do not
        # repeat the same failed explorer requests just for optional labels.
        known_names.update({c['address'].lower(): known_names.get(c['address'].lower(), '')
                            for c in contracts if c.get('address') and c.get('source_lookup')})
        addr2name = await self._load_contract_name(set(addresses), known_names)
        addr2name.update(self.addr2property)

        return transaction, contracts, addr2name

    def chain_id_to_platform(self):
        return {1: 'Ethereum', 56: 'BNBChain'}.get(self.chain_id)


    async def get_micro_data(self, transaction_hash: str) -> MixTraceTree | None:
        res = await self.simulate_tx_in_tenderly(transaction_hash)
        if not res:
            return None
        transaction, contracts, addr2name = res

        transaction_info = transaction.get('transaction_info', {})
        call_trace = transaction_info.get('call_trace')
        if not call_trace:
            print(f"Error: call_trace is empty for hash {transaction_hash}")
            return None

        mix_trace_tree = MixTraceTree(call_trace, contracts, addr2name)
        return mix_trace_tree


    @staticmethod
    def _source_contract(raw_data, addr, existing):
        raw_source = raw_data['SourceCode'].strip()
        compiler_settings = {}
        if raw_source.startswith('{'):
            parsed = json.loads(raw_source[1:-1] if raw_source.startswith('{{') else raw_source)
            compiler_settings = copy.deepcopy(parsed.get('settings') or {})
            source_data = parsed.get('sources', parsed)
            sources = {path: item['content'] for path, item in source_data.items()
                       if isinstance(item, dict) and isinstance(item.get('content'), str)}
        else:
            sources = {f"{raw_data.get('ContractName') or 'Contract'}.sol": raw_source.replace('\r\n', '\n')}
        if not sources or not any(source.strip() for source in sources.values()):
            raise ValueError('Verified source response has no usable source files')
        optimizer = compiler_settings.setdefault('optimizer', {
            'enabled': str(raw_data.get('OptimizationUsed')) == '1',
            'runs': int(raw_data.get('Runs') or 200),
        })
        evm_version = raw_data.get('EVMVersion')
        if evm_version and evm_version != 'Default' and evm_version != 'default':
            compiler_settings.setdefault('evmVersion', evm_version)
        libraries = compiler_settings.setdefault('libraries', {})
        for entry in (raw_data.get('Library') or '').split(','):
            if not entry.strip():
                continue
            name, address = entry.rsplit(':', 1)
            address = address if address.startswith('0x') else '0x' + address
            if not re.fullmatch(r'0x[0-9a-fA-F]{40}', address):
                raise ValueError('Invalid source library address')
            path, name = name.rsplit(':', 1) if ':' in name else (next(iter(sources)), name)
            libraries.setdefault(path, {})[name] = address
        data = copy.deepcopy(existing.get('data') or {})
        old_ids, used_ids = {}, set()
        id_paths = {}
        for item in data.get('contract_info', []) or []:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] < 0:
                continue
            file_id, path = item['id'], item.get('path')
            used_ids.add(file_id)
            if not isinstance(path, str) or not path:
                continue
            if ((path in old_ids and old_ids[path] != file_id)
                    or (file_id in id_paths and id_paths[file_id] != path)):
                raise ValueError('Existing source file identifiers are ambiguous')
            old_ids[path], id_paths[file_id] = file_id, path
        data['contract_info'] = []
        next_id = 0
        for path, content in sorted(sources.items()):
            file_id = old_ids.get(path)
            if file_id is None:
                while next_id in used_ids:
                    next_id += 1
                file_id = next_id
                used_ids.add(file_id)
            data['contract_info'].append({'id': file_id, 'path': path, 'source': content})
        if not data.get('abi') and raw_data.get('ABI'):
            try:
                abi = json.loads(raw_data['ABI'])
                if isinstance(abi, list):
                    data['abi'] = abi
            except (ValueError, TypeError):
                pass
        return {**existing, 'id': existing.get('id') or f'ext-{addr}', 'address': addr,
                'contract_name': raw_data.get('ContractName') or existing.get('contract_name') or 'Unknown',
                'public': True, 'compiler_version': raw_data.get('CompilerVersion'),
                'compiler_settings': compiler_settings, 'evm_version': compiler_settings.get('evmVersion'),
                'optimizations_used': optimizer.get('enabled'), 'optimization_runs': optimizer.get('runs'),
                'libraries': libraries, 'data': data,
                'source_lookup': {'status': 'available', 'reason_code': 'source_available', 'retryable': False}}

    async def _supplement_missing_contracts(
            self,
            involved_addresses: List[str],
            existing_contracts: List[Dict],
            *, block_number=None,
    ) -> List[Dict]:
        existing_by_address = {c.get('address', '').lower(): c for c in existing_contracts}
        candidates = dict.fromkeys(addr.lower() for addr in involved_addresses
                                   if isinstance(addr, str) and re.fullmatch(r'0x[0-9a-fA-F]{40}', addr)
                                   and int(addr, 16) > 255)
        missing_addrs = [addr for addr in candidates if not ContractEntity(
            existing_by_address.get(addr, {})).has_source_code]

        if not missing_addrs:
            return existing_contracts

        async def fetch_and_format(addr: str) -> Dict:
            existing = existing_by_address.get(addr, {})
            lookup = {'status': 'unverified', 'reason_code': 'source_not_verified', 'retryable': False}
            try:
                raw_data = await self.source_downloader.download(contract_address=addr)
                if not isinstance(raw_data, dict) or not isinstance(raw_data.get('SourceCode'), str):
                    raise ValueError('Invalid source response')
                if raw_data['SourceCode'].strip():
                    return self._source_contract(raw_data, addr, existing)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                retryable = isinstance(e, (httpx.TransportError, TimeoutError)) or (
                    isinstance(e, httpx.HTTPStatusError) and e.response.status_code in {408, 429, 500, 502, 503, 504})
                lookup = {'status': 'failed', 'reason_code': 'source_fetch_failed', 'retryable': retryable}
                logging.getLogger(__name__).warning(
                    "Source fetch failed for %s (%s); attempting bytecode lookup.",
                    addr, type(e).__name__,
                )

            bytecode = existing.get('deployed_bytecode')
            if not bytecode:
                try:
                    kwargs = {'contract_address': addr}
                    if block_number is not None:
                        kwargs['quantity'] = block_number
                    bytecode = await self.bytecode_downloader.download(**kwargs)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logging.getLogger(__name__).warning('Bytecode lookup failed for %s (%s).', addr, type(exc).__name__)
            return {**existing, 'id': existing.get('id') or f'bytecode-{addr}', 'address': addr,
                    'contract_name': existing.get('contract_name') or f'Unknown_{addr[:8]}',
                    'public': False, 'deployed_bytecode': bytecode or '',
                    'data': copy.deepcopy(existing.get('data') or {'contract_info': [], 'abi': []}),
                    'source_lookup': lookup}

        semaphore = asyncio.Semaphore(3)
        async def limited(addr):
            async with semaphore:
                return await fetch_and_format(addr)
        tasks = [asyncio.create_task(limited(addr)) for addr in missing_addrs]
        try:
            supplemental_data = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        replacements = {item['address']: item for item in supplemental_data}
        return [replacements.get(item.get('address', '').lower(), item) for item in existing_contracts] + [
            item for item in supplemental_data if item['address'] not in existing_by_address]

    async def _load_contract_name(self, contract_addresses: Set[str], known_names=None) -> Dict[str, str]:
        names = dict(known_names or {})
        addr_list = sorted({addr.lower() for addr in contract_addresses} - names.keys())
        semaphore = asyncio.Semaphore(5)

        async def _create_task(_address: str):
            async with semaphore:
                try:
                    async with asyncio.timeout(10):
                        return await ContractDao(downloader=self.source_downloader).get_contract_name(_address)
                except (httpx.HTTPError, aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                    # Names are optional labels. Keep the address and real trace;
                    # never let an explorer outage discard a successful replay.
                    logging.getLogger(__name__).warning(
                        'Contract name unavailable for %s (%s); retaining address.',
                        _address, type(exc).__name__,
                    )
                    return ''

        tasks = [_create_task(addr) for addr in addr_list]
        result = await asyncio.gather(*tasks)
        names.update(zip(addr_list, result))
        return names


class BundleTenderlyDao:
    def __init__(self, _platform):
        from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore

        self.platform = _platform
        self.bundle_downloader = TenderlyBundleSimulateDownloader()
        self.chain_id = PLATFORM_TO_CHAIN_ID.get(_platform)
        self.chain_slug = platform_to_chain.get(_platform)
        self.evidence_store = PatchReplayEvidenceStore()

    async def bundle_simulate_txs_in_tenderly(self, transactions, addr2bytecode):
        from app.attackpilot.utils.patch_replay import (
            MAX_REPLAY_REQUESTS, MAX_REPLAY_TRANSACTIONS, execution_summary,
            historical_payload, public_context, runtime_overrides, validate_patch_context,
            validate_historical_header, PatchReplayBudgetError,
        )

        if self.chain_id is None or not isinstance(transactions, list) or not transactions:
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
        if len(transactions) > MAX_REPLAY_TRANSACTIONS:
            raise PatchReplayBudgetError(transaction_limit=True)
        overrides = runtime_overrides(addr2bytecode)
        patched_addresses = sorted(overrides)
        originals, seen = [], set()
        # Resolve every original receipt before any paid simulation is requested.
        for detail in transactions:
            if not isinstance(detail, dict):
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
            original_hash = detail.get('original_transaction_hash') or detail.get('hash')
            context, raw_transaction = self.evidence_store.original_context(original_hash, self.chain_id)
            if context['transaction_hash'] in seen:
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
            seen.add(context['transaction_hash'])
            originals.append((context, raw_transaction))

        report = {
            'schema_version': 1, 'scope': 'independent_historical_transaction_pairs',
            'status': 'incomplete', 'control_validation': 'pending',
            'transaction_count': len(originals), 'patched_addresses': patched_addresses,
            'transactions': [], 'profit_usd': None,
            'normal_regression': {'status': 'not_run', 'reason_code': 'not_provided'},
            'request_budget': {'max_requests_per_task': MAX_REPLAY_REQUESTS,
                               'max_transactions': MAX_REPLAY_TRANSACTIONS},
        }
        for context, raw_transaction in originals:
            pair = {
                'original_transaction_hash': context['transaction_hash'],
                'context': public_context(context, raw_transaction),
                'patched_addresses': patched_addresses,
            }
            report['transactions'].append(pair)
            current_payload = None
            try:
                control_payload = historical_payload(context, raw_transaction)
                current_payload = control_payload
                control_result, control_artifact = await self._recorded_single_replay(
                    control_payload, role='control', original_hash=context['transaction_hash'])
                pair['control'] = {'artifact': control_artifact}
                validate_historical_header(context, control_result)
                baseline = validate_simulated_transaction(context, control_result)
                control = execution_summary(control_result, control_artifact, patched_addresses)
                control['baseline_validation'] = baseline
                control['control_validation'] = 'validated'
                pair['control'] = control

                # A distinct request starts from the same real historical state;
                # the control and patch never share a cumulative bundle state.
                patched_payload = historical_payload(context, raw_transaction, overrides)
                current_payload = patched_payload
                patched_result, patched_artifact = await self._recorded_single_replay(
                    patched_payload, role='patched', original_hash=context['transaction_hash'])
                pair['patched'] = {'artifact': patched_artifact}
                validate_historical_header(context, patched_result)
                validate_patch_context(context, patched_result)
                patched = execution_summary(patched_result, patched_artifact, patched_addresses,
                                            runtime_codes={address: item['code'] for address, item in overrides.items()})
                pair['patched'] = patched
                pair['comparison'] = {
                    'attack_transaction_reverted': control['status'] == 'success' and patched['status'] == 'revert',
                    'logs_changed': control['logs']['ordered_logs_sha256'] != patched['logs']['ordered_logs_sha256'],
                    'gas_changed': control['gas_used'] != patched['gas_used'],
                    'profit_usd': None,
                }
            except Exception as exc:
                if current_payload is not None:
                    self.evidence_store.invalidate_response(current_payload)
                # The caller can retain references to already completed evidence
                # even if a later control, patch, or budget check blocks progress.
                exc.replay_evidence = report
                raise
        report['status'] = 'completed'
        report['control_validation'] = 'validated'
        return True, report

    async def _recorded_single_replay(self, payload: Dict, *, role: str, original_hash: str):
        cached = self.evidence_store.cached_response(payload)
        if cached is not None:
            return cached
        # Reservations are task-local and atomic, including across repair retries.
        # Reusing an identical stored response does not consume another request.
        self.evidence_store.reserve_request(payload)
        results = await self.bundle_downloader.download(payload=payload)
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_response')
        result = results[0]
        artifact = self.evidence_store.persist(payload, result, role=role, original_hash=original_hash)
        return result, artifact
