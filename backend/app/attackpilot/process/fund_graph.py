from typing import List, Dict
from math import isfinite

import networkx as nx
from decimal import Decimal
from app.attackpilot.utils.balance_utils import CHAIN_CONFIG, NATIVE_TOKEN_ALIASES, quote_price
from app.attackpilot.utils.price import get_token_price, platform_to_chain
from app.attackpilot.utils.signature import parse_quantity
from app.attackpilot.utils.token_utils import ERC20_TRANSFER_TOPIC, parse_address


class FundFlowGraphBuilder:
    def __init__(self, platform: str):
        self.graph = nx.MultiDiGraph()
        self.platform = platform
        self.chain = platform_to_chain.get(platform)
        chain_config = CHAIN_CONFIG.get(self.chain, {})
        self.native_symbol = chain_config.get("symbol", "native")
        self.NATIVE_TOKEN_ADDRESS = chain_config.get("wrapped")
        self.processed_txs = set()

    def _price_address(self, address):
        normalized = (address or "").lower()
        if not normalized or normalized in NATIVE_TOKEN_ALIASES:
            return self.NATIVE_TOKEN_ADDRESS
        return normalized

    @staticmethod
    def _usd_value(amount, quote):
        price = quote_price(quote)
        if price is None or amount is None:
            return None
        try:
            value = float(amount) * price
            return value if isfinite(value) else None
        except (TypeError, ValueError, OverflowError):
            return None

    def _normalize_amount(self, change):
        token_info = change.get("token_info") or {}
        decimals = token_info.get("decimals")
        if not token_info.get("contract_address") or token_info.get("contract_address", "").lower() in NATIVE_TOKEN_ALIASES:
            decimals = 18
        elif self.NATIVE_TOKEN_ADDRESS and token_info.get("contract_address", "").lower() == self.NATIVE_TOKEN_ADDRESS:
            decimals = 18
        raw_amount = change.get("raw_amount")
        if raw_amount is not None:
            if decimals is None or isinstance(decimals, bool):
                return None
            try:
                parsed_decimals = int(decimals)
                if not 0 <= parsed_decimals <= 255 or Decimal(str(decimals)) != parsed_decimals:
                    return None
            except (TypeError, ValueError, ArithmeticError):
                return None
            val = parse_quantity(raw_amount)
            return Decimal(val) / Decimal(10 ** parsed_decimals)

        return None

    @staticmethod
    def _asset_changes(tx):
        changes = tx.get('asset_changes', []) or []
        metadata = {((change.get('token_info') or {}).get('contract_address') or '').lower():
                    dict(change.get('token_info') or {}) for change in changes}
        logged_tokens, parsed = set(), []
        for log in tx.get('logs', []) or []:
            raw = log.get('raw') or log
            topics = raw.get('topics', [])
            if (len(topics) not in {3, 4} or not isinstance(topics[0], str)
                    or topics[0].lower() != ERC20_TRANSFER_TOPIC):
                continue
            token = raw['address'].lower()
            info = {**metadata.get(token, {}), 'contract_address': token}
            if len(topics) == 4:
                info.update(standard='ERC721', decimals=0)
            else:
                info['standard'] = 'ERC20'
            logged_tokens.add(token)
            parsed.append({'from': parse_address(topics[1]).lower(),
                           'to': parse_address(topics[2]).lower(), 'type': 'Transfer',
                           'raw_amount': 1 if len(topics) == 4 else parse_quantity(raw.get('data')),
                           'token_id': parse_quantity(topics[3]) if len(topics) == 4 else None,
                           'token_info': info})
        return parsed + [change for change in changes if
                         ((change.get('token_info') or {}).get('contract_address') or '').lower() not in logged_tokens]

    @staticmethod
    def _is_nft(change):
        standard = str((change.get('token_info') or {}).get('standard') or '').upper().replace('-', '')
        return standard in {'ERC721', 'ERC1155'}

    async def _fetch_all_historical_prices(self, transactions: List[Dict]):
        price_cache = {}  # (requested timestamp, pricing address) -> full quote
        if not self.chain or self.chain not in CHAIN_CONFIG:
            return price_cache

        for tx in transactions:
            ts = tx.get("timestamp")
            if ts is None:
                continue
            contracts = set()

            for change in self._asset_changes(tx):
                if self._is_nft(change):
                    continue
                addr = self._price_address(change.get("token_info", {}).get("contract_address"))
                if addr:
                    contracts.add(addr)

            if tx.get("balance_diff") and self.NATIVE_TOKEN_ADDRESS:
                contracts.add(self.NATIVE_TOKEN_ADDRESS.lower())

            if not contracts:
                continue

            coins_query = ",".join(f"{self.chain}:{addr}" for addr in sorted(contracts))

            try:
                prices = await get_token_price(coins_query, ts, block_context=tx)
                for _key, info in prices.items():
                    addr = _key.split(':')[-1].lower()
                    price_cache[(ts, addr)] = dict(info)
            except Exception as e:
                print(f"Error fetching price for ts {ts}: {e}")

        return price_cache

    async def add_transactions(self, transactions: List[Dict]):
        sorted_txs = sorted(
            transactions,
            key=lambda x: (x.get("block_number", 0), x.get("transaction_index", 0))
        )

        price_map = await self._fetch_all_historical_prices(sorted_txs)

        for tx in sorted_txs:
            tx_hash = tx.get("tx_hash", "unknown_tx")
            if tx_hash in self.processed_txs:
                continue

            ts = tx.get("timestamp")
            asset_changes = self._asset_changes(tx)
            balance_diff = tx.get("balance_diff", [])

            for idx, change in enumerate(asset_changes):
                token_info = change.get("token_info", {})
                change_type = change.get("type", "Transfer")
                from_addr = change.get("from")
                to_addr = change.get("to")

                if change_type.lower() == "mint" and not from_addr:
                    from_addr = "0x0000000000000000000000000000000000000000"
                if change_type.lower() == "burn" and not to_addr:
                    to_addr = "0x0000000000000000000000000000000000000000"

                if not from_addr or not to_addr:
                    continue

                contract_address = (token_info.get("contract_address") or "").lower()
                amount = self._normalize_amount(change)
                raw_amount = change.get("raw_amount", "")
                quote = None if self._is_nft(change) else price_map.get((ts, self._price_address(contract_address)))
                usd_value = self._usd_value(amount, quote)

                edge_key = f"{tx_hash}_{change_type}_{idx}"

                self.graph.add_edge(
                    from_addr, to_addr,
                    edge_key=edge_key,
                    amount=float(amount) if amount is not None else None,
                    raw_amount=raw_amount,
                    symbol=token_info.get("symbol") or token_info.get("name", "Unknown"),
                    token_address=contract_address,
                    asset_standard=token_info.get('standard'),
                    token_id=change.get('token_id'),
                    dollar_value=usd_value,
                    valuation_status='available' if usd_value is not None else 'unavailable',
                    price_evidence=quote,
                    timestamp=ts
                )

            native_quote = price_map.get((ts, self.NATIVE_TOKEN_ADDRESS))

            for idx, diff in enumerate(balance_diff):
                addr = diff.get("address")
                delta = parse_quantity(diff.get("dirty")) - parse_quantity(diff.get("original"))
                if delta == 0:
                    continue

                amount = abs(Decimal(delta) / Decimal(10 ** 18))
                usd_value = self._usd_value(amount, native_quote)

                if delta < 0:
                    to_addr = "0xMINER" if diff.get("is_miner") else "0xOUT_GAS_OR_OTHER"
                    u, v = addr, to_addr
                    edge_type = "Native_Out"
                else:
                    from_addr = "0xMINER" if diff.get("is_miner") else "0xSOURCE"
                    u, v = from_addr, addr
                    edge_type = "Native_In"

                edge_key = f"{tx_hash}_{edge_type}_{idx}"

                self.graph.add_edge(
                    u, v,
                    edge_key=edge_key,
                    amount=float(amount),
                    raw_amount=str(abs(delta)),
                    decimals=18,
                    symbol=self.native_symbol,
                    dollar_value=usd_value,
                    valuation_status='available' if usd_value is not None else 'unavailable',
                    price_evidence=native_quote,
                    timestamp=ts
                )

            self.processed_txs.add(tx_hash)

        return self.graph
