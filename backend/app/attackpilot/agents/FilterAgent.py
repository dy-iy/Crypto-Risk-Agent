import ast
import json
import re
from typing import Dict, Any, Union, List

from app.attackpilot.prompt.filter_prompt import FILTER_SP, FILTER_UP

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.errors import AgentContractError
from app.attackpilot.utils.agent_contracts import hash_list, trace_tree as validate_trace_tree


class FilterAgent(AgentBase):
    def __init__(self, dapp_name, name="Transaction Filter", log_callback=None):
        super(FilterAgent, self).__init__(name, FILTER_SP, max_turns=1, unique_id=dapp_name,log_callback=log_callback)

    async def handle(self, processed_data: Dict[str, Any]) -> List[str]:
        self.filter_degraded = False
        trace_tree_raw = processed_data.get("trace_tree", {})
        candidate_txs = processed_data.get("attack_transactions", [])
        candidate_txs = hash_list(candidate_txs, processed_data.get('transaction_hash_list', candidate_txs),
                                 stage='filter', reason_code='agent_filter_invalid')

        if not candidate_txs:
            print(f"[{self.name}] No attack transactions to filter.")
            return []

        trace_tree = {}
        if isinstance(trace_tree_raw, str):
            try:
                trace_tree = json.loads(trace_tree_raw)
            except json.JSONDecodeError:
                print(f"[{self.name}] Failed to parse trace_tree string.")
        elif isinstance(trace_tree_raw, dict):
            trace_tree = trace_tree_raw

        attack_traces_map = {}
        trace_str_parts = []

        for attack_tx in candidate_txs:
            if attack_tx in trace_tree:
                trace_content = trace_tree[attack_tx]
                try:
                    validate_trace_tree(trace_content)
                except AgentContractError:
                    continue
                attack_traces_map[attack_tx] = trace_content
                trace_str_parts.append(f"\n{attack_tx}: {trace_content}")

        if len(attack_traces_map) != len(candidate_txs):
            self.filter_degraded = True
            self.logger.warning('候选交易轨迹不完整，跳过去重并保留全部候选交易。')
            return candidate_txs

        trace_str = "".join(trace_str_parts)

        prompt = FILTER_UP.format(traces=trace_str)
        for attempt in range(2):
            # Provider/transport errors and cancellation must reach the caller.
            result = await self.query(prompt, _format="str")
            parsed_txs = self._parse_llm_output(result)
            try:
                selected = hash_list(parsed_txs, candidate_txs, stage='filter',
                                     reason_code='agent_filter_invalid', nonempty=True)
                omitted = [tx for tx in candidate_txs if tx not in selected]
                if omitted:
                    # A model's similar-template judgement is not a proof of
                    # equivalent execution. Preserve every candidate for deeper
                    # investigation; the selection may only set its priority.
                    self.filter_degraded = True
                    self.logger.warning('模型建议合并部分候选，但缺少执行等价证据；保留全部候选继续分析。')
                return selected + omitted
            except AgentContractError:
                if attempt:
                    self.filter_degraded = True
                    self.logger.warning('去重结果仍不可用，保留全部候选交易；未据此认定没有攻击。')
                    return list(dict.fromkeys(tx.lower() for tx in candidate_txs))
                prompt += '\nCorrect the format once: return a nonempty list containing only full hashes from the candidates. Deduplication cannot remove every candidate.'

    def _parse_llm_output(self, llm_output: str) -> Union[List[str], None]:
        if not isinstance(llm_output, str):
            return None
        cleaned = re.sub(r"```[a-zA-Z]*", "", llm_output).replace("```", "").strip()

        result_list = None

        try:
            val = ast.literal_eval(cleaned)
            if isinstance(val, list):
                result_list = val
        except (ValueError, SyntaxError):
            pass

        if result_list is None:
            try:
                val = json.loads(cleaned)
                if isinstance(val, list):
                    result_list = val
            except json.JSONDecodeError:
                pass

        if result_list is not None:
            return result_list

        print(f"[{self.name}] Failed to parse output: {llm_output}")
        return None
