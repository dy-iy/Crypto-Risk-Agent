import os
import hashlib
import json
from typing import Dict

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.prompt.bug_summary_prompt import BUG_SUMMARY_SP, BUG_SUMMARY_UP
from app.attackpilot.settings import CACHE_DIR
from app.attackpilot.utils.rag_context import format_rag_context
from app.attackpilot.utils.price import pricing_policy_fingerprint
from app.attackpilot.utils.prompt_evidence import compact_price_evidence


class TxFaultAgent(AgentBase):
    def __init__(self, dapp_name, name="TxFaultAgent", log_callback=None):
        super(TxFaultAgent, self).__init__(name, BUG_SUMMARY_SP, unique_id=dapp_name,log_callback=log_callback)

    async def handle(self, dapp_data: Dict) -> str:
        transfer_graph, _, price_evidence = compact_price_evidence(
            dapp_data.get("transfer_graph", ""), {},
        )
        initial_trace = dapp_data.get("trace_tree", "")
        if isinstance(initial_trace, dict):
            initial_trace = "\n\n".join(f"{tx_hash}:\n{tree}" for tx_hash, tree in initial_trace.items())
        prompt = BUG_SUMMARY_UP.format(
            tx_hash=dapp_data.get("transaction_hash_list", ""),
            tx_detail=dapp_data.get("transaction_detail", ""),
            transfer_graph=transfer_graph,
            price_evidence=price_evidence,
            trace_tree=initial_trace,
            tx_token_property=dapp_data.get("transaction_to_property", ""),
            attack_list=dapp_data.get("attack_transactions", ""),
            auxiliary_list=dapp_data.get("auxiliary_transactions", ""),
            investigation_targets=dapp_data.get("transactions_need_analyze", []),
            investigation_scope=dapp_data.get("investigation_scope", {}),
            tx_roles=dapp_data.get("transaction_roles", ""),
            rag_context=format_rag_context(dapp_data.get("rag_context", {}), max_chars=3500),
        )
        cache_name = hashlib.sha256(json.dumps({
            'schema_version': 2, 'system': BUG_SUMMARY_SP, 'prompt': prompt,
            'pricing_policy': pricing_policy_fingerprint(), 'balances': dapp_data.get('balance_change'),
        }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        bug_path = os.path.join(CACHE_DIR, 'summary/bug_summary', f'{cache_name}.json')
        if os.path.exists(bug_path):
            try:
                cached = self.load_summary_from_cache(str(bug_path))
                if isinstance(cached, str) and cached.strip():
                    return cached
            except (ValueError, TypeError, AttributeError, OSError):
                self.logger.warning('宏观分析缓存无效，重新生成。')
        bug_summary = await self.query(prompt, _format='str')
        if not isinstance(bug_summary, str) or not bug_summary.strip():
            from app.attackpilot.errors import AgentContractError
            raise AgentContractError('agent', 'agent_output_invalid')
        self.write_summary_to_cache(cache_path='summary/bug_summary', file_name=cache_name, summary=bug_summary)
        return bug_summary
