import hashlib
import json
import os
from typing import List, Dict

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.prompt.tx_role_analyze_prompt import TX_ROLE_ANALYZE_SP, TX_ROLE_ANALYZE_UP
from app.attackpilot.settings import CACHE_DIR
from app.attackpilot.utils.balance_utils import NATIVE_TOKEN_ADDRESS, BalanceAnalyzer, fetch_token_prices
from app.attackpilot.utils.bucket import AsyncItemBucket
from app.attackpilot.utils.price import platform_to_chain, pricing_policy_fingerprint
from app.attackpilot.errors import AgentContractError, HistoricalReplayValidationError
from app.attackpilot.utils.agent_contracts import classification, observed_addresses
from app.attackpilot.utils.prompt_evidence import compact_price_evidence


class TxRoleAgent(AgentBase):
    def __init__(self, apikey_bucket: AsyncItemBucket, rpc_bucket: AsyncItemBucket, _platform, dapp_name,
                 name="TxRoleAgent", log_callback=None):
        super(TxRoleAgent, self).__init__(name, TX_ROLE_ANALYZE_SP, unique_id=dapp_name,log_callback=log_callback)
        self.apikey_bucket = apikey_bucket
        self.rpc_bucket = rpc_bucket
        self._platform = _platform
        self.NATIVE_TOKEN_ADDRESS = NATIVE_TOKEN_ADDRESS

    async def handle(self, dapp_data: Dict, transactions: List[Dict]) -> tuple[Dict, List[str], List[str], Dict]:
        roles = {}
        attack_transactions = []
        auxiliary_transactions = []

        balance_change = await self.get_balance_change(dapp_data, transactions)
        addresses = observed_addresses(
            dapp_data.get('transaction_to_detail'), dapp_data.get('transaction_to_property'),
            dapp_data.get('trace_tree'), dapp_data.get('transfer_graph'), balance_change,
        )

        # transaction role analyze
        transfer_graph, prompt_balances, price_evidence = self._prompt_evidence(
            dapp_data.get("transfer_graph", ""), balance_change,
        )
        initial_trace = dapp_data.get("trace_tree", {})
        if isinstance(initial_trace, dict):
            initial_trace = "\n\n".join(f"{tx_hash}:\n{tree}" for tx_hash, tree in initial_trace.items())
        role_prompt = TX_ROLE_ANALYZE_UP.format(
            tx_hash=dapp_data.get("transaction_hash_list", ""),
            tx_detail=dapp_data.get("transaction_detail", ""),
            trace_tree=initial_trace,
            transfer_graph=transfer_graph,
            tx_token_property=self.process_property(dapp_data), balance_change=prompt_balances,
            price_evidence=price_evidence,
        )
        role_cache_name = hashlib.sha256(
            (pricing_policy_fingerprint() + TX_ROLE_ANALYZE_SP + role_prompt).encode()
        ).hexdigest()
        role_path = os.path.join(CACHE_DIR, 'summary/role_summary', f'{role_cache_name}.json')
        known = dapp_data.get('transaction_hash_list', [])
        if os.path.exists(role_path):
            try:
                roles, attack_transactions, auxiliary_transactions = classification(
                    self.load_summary_from_cache(str(role_path)), known, addresses=addresses)
                return roles, attack_transactions, auxiliary_transactions, balance_change
            except (AgentContractError, ValueError, TypeError, AttributeError, OSError):
                self.logger.warning('角色分类缓存不符合当前数据契约，重新分类。')
        prompt = role_prompt
        for attempt in range(2):
            role_summary = await self.query(prompt, _format="json")
            try:
                roles, attack_transactions, auxiliary_transactions = classification(
                    role_summary, known, addresses=addresses)
            except AgentContractError:
                if attempt:
                    raise
                self.logger.warning('角色分类范围或格式无效，进行一次纠正。')
                prompt = role_prompt + (
                    '\nReturn a JSON object with transaction.attack_transactions and auxiliary_transactions '
                    'as disjoint lists covering only and all supplied transaction hashes; address_role must '
                    'map full addresses to role/description strings. An empty attack list is allowed when '
                    'no concrete suspicious fault-trigger candidate is supported; unresolved candidates '
                    'do not require a proven vulnerability and unknown evidence does not prove safety. Address roles may '
                    'only reference addresses present in the supplied chain evidence. Allowed addresses: '
                    + ', '.join(sorted(addresses))
                )
                continue
            self.write_summary_to_cache(cache_path='summary/role_summary', file_name=role_cache_name,
                                        summary=role_summary)
            return roles, attack_transactions, auxiliary_transactions, balance_change

    _prompt_evidence = staticmethod(compact_price_evidence)

    def process_property(self, dapp_data):
        tx2property = dapp_data.get("transaction_to_property")
        return " ".join(
            str(_tx) + ":" + " ".join(str(item) for item in _property) for _tx, _property in tx2property.items())

    async def get_balance_change(self, dapp_data: Dict, transactions: List[Dict]):
        tx_hashes = dapp_data.get("transaction_hash_list", [])
        tx2property = dapp_data.get("transaction_to_property", {})
        tenderly_macro_map = dapp_data.get("transaction_to_detail", {}) or {} if dapp_data else {}

        platform = dapp_data.get("dapp", {}).get("platform") or self._platform

        hash_to_ts = {tx.get("tx_hash"): tx.get("timestamp") for tx in transactions}

        if (not isinstance(tenderly_macro_map, dict) or any(
                not isinstance(tenderly_macro_map.get(tx), dict) or not tenderly_macro_map[tx]
                for tx in tx_hashes)):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'transaction_to_detail'})

        price_map = await self._fetch_prices_for_all_txs(tx_hashes, hash_to_ts, tenderly_macro_map, tx2property,
                                                         platform)

        results = {}
        for tx_hash in tx_hashes:
            macro_for_tx = tenderly_macro_map.get(tx_hash)

            raw_balance_changes, extracted_meta = BalanceAnalyzer.parse_tenderly_data(macro_for_tx)
            # Metadata from a different transaction must not change this one's
            # units; partial provider labels also must not erase known decimals.
            metadata = self._build_initial_metadata({tx_hash: tx2property.get(tx_hash, [])})
            for address, info in extracted_meta.items():
                target = metadata.setdefault(address, {})
                for key, value in info.items():
                    if value is None or value in ('', 'UNKNOWN', 'Unknown Token'):
                        continue
                    if key == 'decimals' and (type(value) is not int or not 0 <= value <= 255):
                        continue
                    target[key] = value

            tx_price_info = price_map.get(tx_hash, {})
            results[tx_hash] = BalanceAnalyzer.calculate_usd_values(raw_balance_changes, metadata, tx_price_info, platform)

        return results

    async def _fetch_prices_for_all_txs(self, tx_hashes, hash_to_ts, tenderly_map, tx2prop, platform) -> Dict:
        chain = platform_to_chain.get(platform)
        price_results = {}
        if not chain:
            return price_results

        for tx_hash in tx_hashes:
            ts = hash_to_ts.get(tx_hash)
            if not ts: continue

            query_addrs = {self.NATIVE_TOKEN_ADDRESS.lower()}

            props = tx2prop.get(tx_hash, [])
            for p in props:
                a = p.get('contract_address')
                if a: query_addrs.add(a.lower())

            macro = tenderly_map.get(tx_hash)
            if macro:
                for asset in macro.get('asset_changes', []):
                    a = asset.get('token_info', {}).get('contract_address')
                    if a: query_addrs.add(a.lower())

            try:
                price_results[tx_hash] = await fetch_token_prices(
                    chain, ts, query_addrs, include_metadata=True, block_context=macro
                )
            except Exception as e:
                print(f"Price fetch error for {tx_hash}: {e}")

        return price_results

    def _build_initial_metadata(self, tx2property: Dict) -> Dict[str, Dict]:
        meta = {}
        for _tx, props in tx2property.items():
            for p in props:
                addr = p.get('contract_address', '').lower()
                if addr:
                    meta[addr] = {
                        "symbol": p.get('token_symbol') or p.get('symbol', 'UNKNOWN'),
                        "name": p.get('name', 'Unknown Token'),
                        "decimals": p.get('decimals'),
                        "contract": addr
                    }
        return meta
