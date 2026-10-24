import asyncio
from copy import deepcopy
import time
from typing import Callable, List, Dict, Optional, Union

from app.attackpilot.agents.FilterAgent import FilterAgent
from app.attackpilot.agents.TraceAgent import TraceAgent
from app.attackpilot.agents.TxDetailAgent import TxDetailAgent
from app.attackpilot.agents.TxFaultAgent import TxFaultAgent
from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
from app.attackpilot.downloaders.trans import BlockTimestampDownloader
from app.attackpilot.process.fund_graph import FundFlowGraphBuilder
from app.attackpilot.settings import TRANSACTION_FILTER_SMALL_SET_THRESHOLD
from app.attackpilot.utils.bucket import AsyncItemBucket
from app.attackpilot.utils.graph2text import convert_to_graph
from app.attackpilot.utils.rag_context import build_rag_query_from_dapp, retrieve_rag_context


class DAppProcess:
    def __init__(
            self,
            net2rpc_bucket: Dict[str, AsyncItemBucket],
            net2apikey_bucket: Dict[str, AsyncItemBucket],
            mcp_client,
            log_callback=None,
            cancellation_checker: Optional[Callable[[], bool]] = None,
            enabled_modules: Optional[List[str]] = None
    ):
        self._net2rpc_bucket = net2rpc_bucket
        self._net2apikey_bucket = net2apikey_bucket
        self.mcp_client = mcp_client
        self.log_callback = log_callback
        self.cancellation_checker = cancellation_checker or (lambda: False)
        self.enabled_modules = set(enabled_modules or [
            "attack_detection",
            "fault_localization",
            "rag_retrieval",
            "patch_generation",
            "patch_verification",
        ])

    def _module_enabled(self, module_id: str) -> bool:
        return module_id in self.enabled_modules

    def _check_cancelled(self):
        if self.cancellation_checker():
            raise asyncio.CancelledError("Task was cancelled")

    def _attach_cancel(self, agent):
        if hasattr(agent, "set_cancellation_checker"):
            agent.set_cancellation_checker(self.cancellation_checker)
        return agent

    async def process(self, dapp):
        self._check_cancelled()
        processed_data = {'dapp': dapp}
        if dapp.get('verification_plan') is not None:
            processed_data['verification_plan'] = deepcopy(dapp['verification_plan'])
        dapp_name = dapp["name"]

        raw_tx_list = dapp['transaction_hash']

        start_time = time.time()
        if self._module_enabled("rag_retrieval"):
            rag_context = retrieve_rag_context(build_rag_query_from_dapp(dapp), top_k=5)
        else:
            rag_context = {"items": [], "skipped": True, "reason": "rag_retrieval module disabled"}
        processed_data["rag_context"] = rag_context
        if rag_context.get("items"):
            print(f"[RAG] Retrieved {len(rag_context['items'])} related knowledge chunks for {dapp_name}")
        elif rag_context.get("error"):
            print(f"[RAG] Retrieval skipped for {dapp_name}: {rag_context.get('error')}")

        # analyze transaction detail
        print("downloading transaction details ~ ")
        self._check_cancelled()
        tx_detail_agent = TxDetailAgent(apikey_bucket=self._net2apikey_bucket[dapp['platform']],
                                        rpc_bucket=self._net2rpc_bucket[dapp['platform']],
                                        _platform=dapp["platform"],
                                        dapp_name=dapp_name,
                                        log_callback=self.log_callback)
        self._attach_cancel(tx_detail_agent)
        tx_detail_str, tx2detail, tx2property = await tx_detail_agent.handle(raw_tx_list)
        self._check_cancelled()
        _tx2property, property_dict = self.process_property(tx2property=tx2property)

        processed_data["transaction_detail"] = tx_detail_str
        processed_data["transaction_to_detail"] = tx2detail
        processed_data["transaction_to_property"] = _tx2property

        # load state diff
        tx2balance_diff, tx2asset_changes = self.load_fund_data(tx2detail)

        # load transfer graph
        print("loading transfer graph ~")
        self._check_cancelled()
        transactions, sorted_tx_list = await self.format_transactions(dapp["platform"], tx2detail, tx2balance_diff,
                                                                      tx2asset_changes)
        processed_data["transaction_hash_list"] = sorted_tx_list
        print(f"transaction_hash_list: {sorted_tx_list}")

        builder = FundFlowGraphBuilder(platform=dapp["platform"])
        self._check_cancelled()
        transfer_graph = await builder.add_transactions(transactions)
        flow_graph_str = str(convert_to_graph(transfer_graph, graph_name="DApp_Transfer_Graph"))
        processed_data["transfer_graph"] = flow_graph_str

        # init trace simulator
        print("loading init trace ~")
        self._check_cancelled()
        trace_agent = TraceAgent(processed_data, mcp_client=self.mcp_client, dapp_name=dapp_name, log_callback=self.log_callback)
        self._attach_cancel(trace_agent)
        tx2init_trace = await trace_agent.init()
        self._check_cancelled()
        processed_data["trace_tree"] = tx2init_trace

        # identify transaction roles
        print("analyzing transaction roles ~ ")
        self._check_cancelled()
        tx_role_agent = TxRoleAgent(apikey_bucket=self._net2apikey_bucket[dapp['platform']],
                                    rpc_bucket=self._net2rpc_bucket[dapp['platform']],
                                    _platform=dapp["platform"],
                                    dapp_name=dapp_name,
                                    log_callback=self.log_callback)
        self._attach_cancel(tx_role_agent)
        roles, attack_transactions, auxiliary_transactions, balance_change = await tx_role_agent.handle(processed_data,
                                                                                                        transactions)
        self._check_cancelled()
        processed_data["transaction_roles"] = roles
        processed_data["balance_change"] = balance_change
        processed_data["attack_transactions"] = attack_transactions
        processed_data["auxiliary_transactions"] = auxiliary_transactions

        # Select investigation targets independently of confirmed attack roles.
        print("selecting investigation targets ~ ")
        self._check_cancelled()
        attack_filter = None

        num_attack_txs = len(attack_transactions)
        num_total_txs = len(sorted_tx_list)
        if self._module_enabled("fault_localization") or not self._module_enabled("attack_detection"):
            # Explicit investigation must not depend on a preliminary model
            # already proving the fault it is meant to investigate. Preserve
            # classification separately; an investigation target is not an attack.
            txs_need_analyze = list(sorted_tx_list)
            if self._module_enabled("fault_localization"):
                trace_agent.logger.info(
                    f"已启用根因深度调查，保留全部 {len(txs_need_analyze)} 笔输入交易；"
                    "初步角色分类不作为跳过调查或确认攻击的依据。"
                )
        elif num_attack_txs == 0:
            txs_need_analyze = []
        elif num_total_txs <= TRANSACTION_FILTER_SMALL_SET_THRESHOLD:
            txs_need_analyze = list(attack_transactions)
        else:
            attack_filter = FilterAgent(dapp_name=dapp_name, log_callback=self.log_callback)
            self._attach_cancel(attack_filter)
            if num_attack_txs > 1:
                txs_need_analyze = await attack_filter.handle(processed_data)
                self._check_cancelled()
            else:
                txs_need_analyze = attack_transactions

        processed_data["transactions_need_analyze"] = txs_need_analyze
        processed_data['attack_classification'] = {
            'source': 'model_classification',
            'status': 'candidates_identified' if attack_transactions else 'no_attack_candidates',
            'safety_confirmed': False,
            'filter_degraded': getattr(attack_filter, 'filter_degraded', False),
        }
        processed_data['investigation_scope'] = {
            'source': 'requested_fault_localization' if self._module_enabled("fault_localization")
            else 'classification_candidates' if self._module_enabled("attack_detection") else 'submitted_transactions',
            'transaction_hashes': list(txs_need_analyze),
            'attack_confirmed': False,
        }

        # macro transaction fault
        print("analyzing transaction bug ~ ")
        self._check_cancelled()
        tx_fault_agent = TxFaultAgent(dapp_name=dapp_name,  log_callback=self.log_callback)
        self._attach_cancel(tx_fault_agent)
        bug_summary = (await tx_fault_agent.handle(processed_data) if txs_need_analyze else
                       '本次角色分类未筛出攻击候选，尚未确认攻击；未开展故障假设或补丁验证，不代表交易安全。')
        self._check_cancelled()
        processed_data["bug_summary"] = bug_summary

        # single = SingleAgent(dapp_name=dapp_name)
        # fault_report = await single.handle(processed_data)

        elapsed_time = time.time() - start_time

        processed_data["token_used"] = {
            "total_token": tx_detail_agent.token + tx_fault_agent.token + tx_role_agent.token + (attack_filter.token if attack_filter else 0),
            "detail": tx_detail_agent.token,
            "role": tx_role_agent.token,
            "filter": attack_filter.token if attack_filter else 0,
            "fault": tx_fault_agent.token
        }

        processed_data["time_used"] = {
            "total_time": elapsed_time,
            "detail": tx_detail_agent.get_total_time(),
            "role": tx_role_agent.get_total_time(),
            "filter": attack_filter.get_total_time() if attack_filter else 0,
            "fault": tx_fault_agent.get_total_time()
        }
        return processed_data, trace_agent

    def process_property(self, tx2property):
        _tx2property = {}
        for tx, property_list in tx2property.items():
            _tx2property[tx] = [property_item.to_dict() for property_item in property_list]

        property_dict = {}
        for _tx, _property_list in _tx2property.items():
            for _property in _property_list:
                address = _property.get("contract_address", "")
                if address == "":
                    continue
                property_dict[address] = _property
        return _tx2property, property_dict

    def load_fund_data(self, tx2detail: Dict[str, Dict]):
        tx2balance_diff = self.fully_load(tx2detail, "balance_diff")
        tx2asset_changes = self.fully_load(tx2detail, "asset_changes")
        return tx2balance_diff, tx2asset_changes

    def fully_load(self, tx2detail: Dict[str, Dict], name: str):
        return {tx: detail.get(name, []) for tx, detail in tx2detail.items()}

    async def format_transactions(self, platform, tx2detail, tx2balance_diff, tx2asset_changes):
        transactions = []
        block_numbers = [detail["block_number"] for tx, detail in tx2detail.items()]
        block2time = await self._load_transaction_time(block_numbers, platform)

        for tx, detail in tx2detail.items():
            index = detail["transaction_index"]
            block_number = detail["block_number"]
            timestamp = block2time.get(block_number)
            if not timestamp:
                raise ValueError(f"CRITICAL: Failed to fetch timestamp for block {block_number}. Cannot proceed.")
            balance_diff = tx2balance_diff.get(tx, [])
            asset_changes = tx2asset_changes.get(tx, [])
            transactions.append({
                "tx_hash": tx,
                "timestamp": timestamp,
                "block_number": block_number,
                "block_hash": detail.get("block_hash"),
                "index": index,
                "transaction_index": index,
                "balance_diff": balance_diff,
                "asset_changes": asset_changes,
                "logs": detail.get('logs', []),
            })
        transactions.sort(key=lambda x: (x['block_number'], x['index']))
        sorted_tx_hashes = [tx['tx_hash'] for tx in transactions]
        return transactions, sorted_tx_hashes

    async def _load_transaction_time(self, block_numbers: List[Union[int, str]], platform: str) -> Dict[Union[int, str], int]:
        unique_blocks = list(set(block_numbers))

        async def _create_task(block_number):
            ts = await BlockTimestampDownloader(
                rpc_url=await self._net2rpc_bucket[platform].get(),
            ).download(block_number=block_number)
            return block_number, ts

        tasks = [_create_task(bn) for bn in unique_blocks]
        results = await asyncio.gather(*tasks)
        return {bn: ts for bn, ts in results}
