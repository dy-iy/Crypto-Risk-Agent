import asyncio
import hashlib
import json
import os.path
from typing import List, Dict

from tqdm import tqdm

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.daos.property import TokenPropertyDao, TokenPropertyItem
from app.attackpilot.daos.tenderly import TenderlyDao
from app.attackpilot.daos.tx import TxDetailDao
from app.attackpilot.downloaders.contract import ContractSourceDownloader, ContractBytecodeDownloader, ContractCreationDownloader
from app.attackpilot.downloaders.property import TokenPropertyDownloader
from app.attackpilot.downloaders.trans import EventLogDownloader, TxDownloader
from app.attackpilot.prompt.tx_summary_prompt import TX_SUMMARY_SP, TX_SUMMARY_UP
from app.attackpilot.settings import CACHE_DIR
from app.attackpilot.utils.bucket import AsyncItemBucket
from app.attackpilot.utils.price import pricing_policy_fingerprint
from app.attackpilot.errors import AgentContractError


async def _gather_with_cleanup(*coroutines):
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # gather propagates one failure without stopping sibling transactions.
        # Drain every child before leaving the stage so no replay or cache write
        # can continue after the task has already failed or been cancelled.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class TxDetailAgent(AgentBase):
    def __init__(self, apikey_bucket: AsyncItemBucket, rpc_bucket: AsyncItemBucket, _platform, dapp_name,
                 name="TxDetailAgent", log_callback=None):
        super(TxDetailAgent, self).__init__(name, TX_SUMMARY_SP, unique_id=dapp_name,log_callback=log_callback)
        self.apikey_bucket = apikey_bucket
        self.rpc_bucket = rpc_bucket
        self._platform = _platform

    async def handle(self, tx_list: List[str]) -> tuple[str, Dict[str, Dict], dict[str, list[TokenPropertyItem]]]:
        tx_detail_str = ''
        self.logger.info(f'正在读取 {len(tx_list)} 笔交易的链上数据与执行轨迹。')

        # get token info
        txhash2property = await self._load_token_properties(tx_list)
        addr2property, addr2proname, property_str = self.process_properties(txhash2property)

        txhash2detail = await self._load_tx_detail_data(tx_list, addr2property, addr2proname)

        # transaction summary
        for tx in tqdm(tx_list, total=len(tx_list), desc="Detail Summary"):
            self._check_cancelled()
            tx_detail = txhash2detail.get(tx, {})
            detail_copy = tx_detail.copy()
            detail_copy.pop('state_diff', None)
            detail_copy.pop('balance_diff', None)
            detail_copy.pop('balance_changes', None)
            detail_copy.pop('asset_changes', None)
            tx_json_str = json.dumps(detail_copy, ensure_ascii=False, sort_keys=True)
            prompt = TX_SUMMARY_UP.format(tx_detail=tx_json_str, properties=property_str)
            # Replays and token metadata can change even when the hash does not.
            # Bind the exact facts supplied to the model, chain and prompt policy.
            summary_cache = 'summary/tx_detail_summary_validated_v3'
            cache_name = hashlib.sha256(json.dumps({
                'platform': self._platform, 'system': TX_SUMMARY_SP, 'prompt': prompt,
                'pricing_policy': pricing_policy_fingerprint(),
            }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            detail_path = os.path.join(CACHE_DIR, summary_cache, '%s.json' % cache_name)
            tx_summary = None
            if os.path.exists(detail_path):
                try:
                    cached = self.load_summary_from_cache(str(detail_path))
                    if not isinstance(cached, str) or not cached.strip():
                        raise ValueError('Invalid cached summary')
                    tx_summary = cached
                except (ValueError, TypeError, AttributeError, OSError):
                    self.logger.warning('交易摘要缓存无效，依据当前链上证据重新生成。')
            if tx_summary is None:
                tx_summary = await self.query(prompt, _format="str", thinking=False)
                if not isinstance(tx_summary, str) or not tx_summary.strip():
                    raise AgentContractError('agent', 'agent_output_invalid')
                # write cache
                self.write_summary_to_cache(cache_path=summary_cache, file_name=cache_name,
                                            summary=tx_summary)
            tx_detail_str = tx_detail_str + tx + ': ' + tx_summary + '\n'
        return tx_detail_str, txhash2detail, txhash2property

    async def _load_tx_detail_data(self, transaction_hashs: List[str], addr2property: Dict, addr2proname: Dict) -> Dict[str, Dict]:
        async def _create_task(_transaction_hash: str):
            return await TxDetailDao(tenderly_dao=TenderlyDao(
                _platform=self._platform,
                tx_downloader=TxDownloader(rpc_url=await self.rpc_bucket.get()),
                source_downloader=ContractSourceDownloader(apikey=await self.apikey_bucket.get()),
                bytecode_downloader=ContractBytecodeDownloader(rpc_url=await self.rpc_bucket.get()),
                creation_downloader=ContractCreationDownloader(apikey=await self.apikey_bucket.get()),
                addr2property=addr2proname
            ), properties=addr2property).get_tx_detail(transaction_hash=_transaction_hash)

        tasks = [_create_task(txhash) for txhash in transaction_hashs]
        result = await _gather_with_cleanup(*tasks)
        txhash2detail = dict()
        for i, txhash in enumerate(transaction_hashs):
            txhash2detail[txhash] = result[i]
        return txhash2detail

    async def _load_token_properties(self, transaction_hashs: List[str]) -> Dict[str, List[TokenPropertyItem]]:
        async def _create_task(_transaction_hash: str):
            return await TokenPropertyDao(property_downloader=TokenPropertyDownloader(
                rpc_url=await self.rpc_bucket.get()
            ), event_log_downloader=EventLogDownloader(
                rpc_url=await self.rpc_bucket.get())
            ).get_token_property_from_transaction(transaction_hash=_transaction_hash)

        tasks = [_create_task(txhash) for txhash in transaction_hashs]
        results = await _gather_with_cleanup(*tasks)
        txhash2property = dict()
        for i, txhash in enumerate(transaction_hashs):
            txhash2property[txhash] = results[i]
        return txhash2property

    def process_properties(self, txhash2property):
        addr2property = {}
        addr2proname = {}
        for tx, properties in txhash2property.items():
            for _property in properties:
                single = _property.to_dict()
                address = single.get("contract_address")
                _dict = _property.to_dict()
                addr2property[address] = _dict
                addr2proname[address] = _dict.get("name")

        property_str = " ".join(
            str(_tx) + ":" + " ".join(str(item) for item in _property) for _tx, _property in txhash2property.items())
        return addr2property, addr2proname, property_str
