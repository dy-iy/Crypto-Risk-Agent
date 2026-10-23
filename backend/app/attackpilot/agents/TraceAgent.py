import ast
import json
import re
from typing import Dict

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.errors import HistoricalReplayValidationError, AgentContractError
from app.attackpilot.mcp_tools.mcp_client import MCPToolError
from app.attackpilot.utils.agent_contracts import hash_list, patch_hypothesis, trace_tree
from app.attackpilot.prompt.trace_debug_prompt import (
    TRACE_DEBUG_SP, TRACE_DEBUG_UP_INIT, TRACE_DEBUG_UP_LATER,
    TRACE_DEBUG_FORCE_PATCH_UP,
    TRACE_SWITCH_TX_UP, MULTI_ATTACK_PART, TRACE_DEBUG_FORCE_COLLAPSE_UP
)
from app.attackpilot.settings import (
    TX_DEBUG_TURN,
    TX_DEBUG_MAX_IDLE_TURNS,
)
from app.attackpilot.utils.llm import MODEL_MAX_OUTPUT_TOKENS


class TraceAgent(AgentBase):
    RECOVERABLE_EXPLORATION_TOOLS = frozenset({
        'expand_node', 'collapse_node', 'get_function_source_code',
        'get_contract_source_code', 'get_mixed_execution_flow', 'get_node_detailed_state',
    })

    def __init__(self, processed_data, mcp_client, dapp_name,
                 name="Transaction Debugger", log_callback=None):
        super(TraceAgent, self).__init__(name, "", need_tool=True, unique_id=dapp_name,log_callback=log_callback)
        self.dapp = processed_data["dapp"]
        self.processed_data = processed_data
        self.tx_list = [tx.lower() for tx in self.dapp["transaction_hash"]]
        # ———————————————————————————————————
        self.mcp_client = mcp_client
        # ————————————————————————————————————
        self.current_tx = ""
        self.is_init = True
        self.transaction_insights = {}
        self.session_id = None

        self._debug_turn_left = TX_DEBUG_TURN
        self._idle_turns = 0

    async def _get_openai_tools(self):
        tools = await super()._get_openai_tools() or []
        tools = [tool for tool in tools if tool['function']['name'] != 'finish_investigation']
        tools.append({
            'type': 'function',
            'function': {
                'name': 'finish_investigation',
                'description': (
                    'End this investigation without a patch hypothesis when the reviewed evidence '
                    'does not support one. Explain the observations and remaining gaps. '
                    'This does not establish transaction safety or attack absence.'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': {'reason': {'type': 'string', 'minLength': 1}},
                    'required': ['reason'],
                    'additionalProperties': False,
                },
            },
        })
        self._available_tool_names = {tool['function']['name'] for tool in tools}
        return tools

    def _finish_investigation(self, arguments, final_trace):
        reason = arguments.get('reason')
        if set(arguments) != {'reason'} or not isinstance(reason, str) or not reason.strip():
            raise AgentContractError('trace', 'agent_trace_arguments_invalid')
        return {
            'reason': 'INVESTIGATION_FINISHED_NO_READY_FOR_PATCH',
            'data': [],
            'final_trace': final_trace,
            'diagnostic_reason': reason.strip(),
        }

    def _inject_session(self, args: Dict) -> Dict:
        if not self.session_id:
            raise ValueError(f"[{self.name}] Session ID not initialized. Cannot call MCP tools.")
        return {**args, 'session_id': self.session_id}

    async def init(self):
        # init MCP sessions
        self._check_cancelled()
        result = await self.mcp_client.call_tool("init_debug_session", {
            "dapp": self.dapp,
        })
        self._check_cancelled()
        if isinstance(result, dict) and result.get("error_code") == "historical_replay_validation":
            details = result.get("details") if isinstance(result.get("details"), dict) else {}
            exc = HistoricalReplayValidationError(result.get("status"), result.get("reason_code"),
                                                   details=details)
            tx_hash = details.get("original_transaction_hash")
            if isinstance(tx_hash, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
                exc.details["original_transaction_hash"] = tx_hash.lower()
            network_id = details.get("network_id")
            if isinstance(network_id, str) and re.fullmatch(r"[0-9]{1,12}", network_id):
                exc.details["network_id"] = network_id
            for key in ("block_number", "transaction_index"):
                value = details.get(key)
                if type(value) is int and 0 <= value <= 2**64 - 1:
                    exc.details[key] = value
            self.logger.error(str(exc))
            raise exc
        if not isinstance(result, dict) or not result.get('session_id') or not isinstance(result.get('tx2init'), dict):
            self.logger.error('执行轨迹初始化失败，调试工具未返回有效会话与轨迹。')
            raise RuntimeError('执行轨迹初始化失败，请检查 RPC/Tenderly 与调试工具文件日志')
        self.session_id = result['session_id']
        tx2init = result['tx2init']
        if set(tx2init) != set(self.tx_list):
            raise AgentContractError('trace', 'agent_trace_evidence_invalid')
        for tree in tx2init.values():
            trace_tree(tree)
        print(f"[{self.name}] Session initialized with ID: {self.session_id}")

        return tx2init

    async def handle(self, global_fault_understanding: dict, task_tree: str, force_terminate: bool = False) -> Dict:
        insights = []
        switch_data = {}

        self._debug_turn_left = TX_DEBUG_TURN
        self._idle_turns = 0
        invalid_rounds = 0
        exploration_failure_recovered = False

        if force_terminate:
            self.logger.info(f"[{self.name}] Analysis limit reached; review whether the evidence supports a patch hypothesis.")
            return await self._force_ready_for_patch(
                global_fault_understanding=global_fault_understanding,
                task_tree=task_tree,
                fallback_reason="GUIDE_TURN_EXHAUSTED"
            )

        # analyze trace
        while self._debug_turn_left > 0:
            self._check_cancelled()
            current_tree = await self.get_current_trace()
            self._check_cancelled()
            user_prompt = self._judge_too_long_trace(global_fault_understanding, current_tree, task_tree)
            tool_calls = await self.query_with_tools(user_prompt)
            self._check_cancelled()
            self.is_init = False

            if not isinstance(tool_calls, (list, tuple)) or not tool_calls:
                raise AgentContractError('trace', 'agent_trace_arguments_invalid')

            pending_return_result = None
            invalid_contract = None
            exploration_failed_in_batch = False
            # parse tool calls
            for tool_call in tool_calls:
                self._check_cancelled()
                func_name = tool_call.function.name
                func_args_str = tool_call.function.arguments
                call_id = tool_call.id
                if (func_name in self.INTERNAL_TOOLS or
                        getattr(self, '_available_tool_names', None) is not None
                        and func_name not in self._available_tool_names):
                    invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': 'This tool is not available to the debugger; use only advertised investigation tools.'})
                    continue
                if pending_return_result is not None or switch_data:
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': 'Not executed after a transaction switch or terminal investigation decision in this batch; reconsider in the new context.'})
                    continue
                if exploration_failed_in_batch:
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': 'Not executed after an exploration tool failed in this batch; reconsider the missing evidence before requesting more tools or a patch.'})
                    continue

                func_args = self._safe_parse_tool_args(func_args_str)
                if func_args is None:
                    invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                    error_msg = f"Error: Arguments for tool '{func_name}' could not be parsed as JSON. Please verify the JSON format (escape newlines). Raw: {func_args_str[:200]}..."
                    self.logger.warning(f"[{self.name}] JSON parsing failed. An error has been returned to the LLM: {func_name}")

                    self.memory.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": func_name,
                        "content": error_msg
                    })
                    continue

                if func_name == 'finish_investigation':
                    try:
                        decision = self._finish_investigation(func_args, current_tree)
                    except AgentContractError as exc:
                        invalid_contract = exc
                        content = 'Provide only a nonempty reason string describing the reviewed observations and remaining evidence gaps.'
                    else:
                        # Earlier calls may have expanded the tree. A failed
                        # evidence read must propagate before accepting termination.
                        decision['final_trace'] = await self.get_current_trace()
                        pending_return_result = decision
                        content = 'Investigation ended without a patch hypothesis. Safety and attack absence remain unconfirmed.'
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': content})
                    continue

                if func_name == "ready_for_patch":
                    fault_report = func_args.get("fault_report", "")
                    fix_report = func_args.get("fix_report", "")
                    try:
                        fix_report = patch_hypothesis(fault_report, fix_report, self.tx_list)
                    except AgentContractError as exc:
                        invalid_contract = exc
                        self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                            'content': 'Invalid patch hypothesis: provide a nonempty fault_report and a fix_report object with nonempty faulty_functions, each containing an original transaction hash and nonnegative trace index in trigger_point.'})
                        continue
                    self.memory.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": "The patch verification is in progress. Please wait for the patch verification result to be returned."
                    })
                    if pending_return_result is None:
                        final_trace = await self.get_current_trace()
                        self.logger.log_patch_report(fault_report, final_trace, fix_report)
                        pending_return_result = {
                            "reason": "READY_FOR_PATCH",
                            "data": [fault_report, final_trace, fix_report]
                        }
                    continue

                if func_name == "switch_transaction":
                    target_tx_hash = func_args.get("target_tx_hash", "")
                    if isinstance(target_tx_hash, str) and target_tx_hash.lower() in self.tx_list:
                        insight = func_args.get("insight", "")
                        code_patch = func_args.get("code_patch", "")
                        if not isinstance(insight, str) or not isinstance(code_patch, str):
                            invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                            self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                                'content': 'Switch insight and code_patch must be strings.'})
                            continue
                        target_tx_hash = str(target_tx_hash).lower()
                        func_args['target_tx_hash'] = target_tx_hash
                        if func_name not in ["init_debug_session", "ready_for_patch", "update_understanding"]:
                            func_args = self._inject_session(func_args)

                        tool_result = await self.mcp_client.call_tool(func_name, func_args)
                        self._check_cancelled()
                        if (isinstance(tool_result, str) and tool_result.startswith('Switched from ')
                                and f'to {target_tx_hash}.' in tool_result):
                            switch_data = {'current_tx': self.current_tx, 'insight': insight,
                                           'code_patch': code_patch, 'switch_to': target_tx_hash}
                            self.current_tx = target_tx_hash
                        self.logger.log_tool_result(func_name, tool_result)
                        self.memory.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": func_name,
                            "content": str(tool_result)
                        })
                        continue
                    invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': 'Target transaction must be an original hash in this analysis session.'})
                    continue

                if func_name == "update_understanding":
                    insight = func_args.get('insight')
                    if not isinstance(insight, str) or not insight.strip():
                        invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                        self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                            'content': 'Provide a nonempty insight string; missing analysis is not progress.'})
                        continue
                    insights.append(insight)
                    self.memory.append({'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                                        'content': 'Added to the global DApp fault understanding update queue.'})
                    continue

                if func_name not in ["init_debug_session", "ready_for_patch", "update_understanding"]:
                    func_args = self._inject_session(func_args)

                try:
                    tool_result = await self.mcp_client.call_tool(func_name, func_args)
                except MCPToolError as exc:
                    if (func_name not in self.RECOVERABLE_EXPLORATION_TOOLS
                            or exc.reason_code != 'remote_error' or exploration_failure_recovered):
                        raise
                    self._check_cancelled()
                    # A failed optional node lookup may be corrected, but a lost
                    # session or unreadable current trace remains fatal.
                    await self.get_current_trace()
                    self._check_cancelled()
                    exploration_failure_recovered = True
                    exploration_failed_in_batch = True
                    self.logger.warning('探索工具未返回证据；当前轨迹仍可读取，允许一次工具选择纠正。')
                    self.memory.append({
                        'role': 'tool', 'tool_call_id': call_id, 'name': func_name,
                        'content': 'Tool request failed; no evidence was returned. The current trace remains available. Recheck the visible node indexes and tool arguments, then select a valid node or a different investigation tool. One correction is allowed; do not treat this failed request as a successful observation or support for a patch.',
                    })
                    continue
                self._check_cancelled()
                self.logger.log_tool_result(func_name, tool_result)

                self.memory.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": func_name,
                    "content": str(tool_result)
                })

            if pending_return_result:
                return pending_return_result
            if invalid_contract is not None:
                invalid_rounds += 1
                if invalid_rounds >= 2:
                    raise invalid_contract
            else:
                invalid_rounds = 0

            has_progress = (len(switch_data) > 0) or (len(insights) > 0)

            if has_progress:
                self._idle_turns = 0
            else:
                self._idle_turns += 1

            self._debug_turn_left -= 1

            if len(switch_data) > 0:
                previous_transactions_summary = self._extract_previous_transactions_summary(global_fault_understanding)
                self.switch_transaction_context(switch_data, previous_transactions_summary)
                return {"reason": "CONTINUE_DEBUGGING", "switch_data": switch_data}
            if len(insights) > 0:
                return {"reason": "CONTINUE_DEBUGGING", "data": insights}

            if self._idle_turns >= TX_DEBUG_MAX_IDLE_TURNS:
                return await self._force_ready_for_patch(
                    global_fault_understanding=global_fault_understanding,
                    task_tree=task_tree,
                    fallback_reason="TIMEOUT_IDLE_LOOP"
                )

        return await self._force_ready_for_patch(
            global_fault_understanding=global_fault_understanding,
            task_tree=task_tree,
            fallback_reason="MAX_TURNS_REACHED"
        )

    def _judge_too_long_trace(self, global_fault_understanding: dict,
                              trace_str: str, task_tree: str, safety_buffer: int = 1000) -> str:
        """
        Construct user prompt words and check if the Trace is too large. If it is too large, prioritize trimming the Trace and injecting a warning.
        Strategy:
        1. Calculate the current Context budget (total limit - reserved output - safety margin - current historical record).
        2. Calculate the token cost of the static part of the Prompt except for Trace.
        3. Allocate all the remaining space to Trace.
        4. If Trace exceeds the budget, perform truncation at the tiktoken level and add a Warning.
        """
        current_history_tokens = self.tm.calculate_total_tokens(self.memory)
        max_output = MODEL_MAX_OUTPUT_TOKENS.get(self.model, 8192)

        global_fault_json = json.dumps(global_fault_understanding, ensure_ascii=False, indent=4)
        dummy_prompt = TRACE_DEBUG_FORCE_COLLAPSE_UP.format(
            global_fault_understanding=global_fault_json,
            trace="",
            task_tree=task_tree
        )
        static_part_tokens = self.tm.count_tokens(dummy_prompt)
        total_limit = self.tm.context_limit
        available_for_trace = total_limit - max_output - safety_buffer - current_history_tokens - static_part_tokens

        if available_for_trace < 25000:
            available_for_trace = 25000

        trace_tokens = self.tm.count_tokens(trace_str)
        print(
            f"trace: {trace_tokens} | available: {available_for_trace} | ratio: {str(trace_tokens / available_for_trace)}")

        if trace_tokens <= available_for_trace:
            user_prompt = TRACE_DEBUG_UP_INIT if self.is_init else TRACE_DEBUG_UP_LATER
            return user_prompt.format(
                global_fault_understanding=global_fault_json,
                trace=trace_str,
                task_tree=task_tree
            )
        else:
            encoded_trace = self.tm.encoder.encode(trace_str)
            pruned_encoded = encoded_trace[:available_for_trace]
            pruned_trace_str = self.tm.encoder.decode(pruned_encoded)

            pruned_trace_str += "\n... [⛔ Trace Data Truncated due to Context Limit ⛔] ..."

            final_prompt = TRACE_DEBUG_FORCE_COLLAPSE_UP.format(
                global_fault_understanding=global_fault_json,
                trace=pruned_trace_str,
                task_tree=task_tree
            )
            return final_prompt

    async def init_transactions(self, txs_need_analyze):
        if not txs_need_analyze or len(txs_need_analyze) == 0:
            raise ValueError(f"[{self.name}] Error: txs_need_analyze is empty, cannot initialize transactions.")
        self._check_cancelled()
        selected = hash_list(txs_need_analyze, self.tx_list, stage='trace',
                             reason_code='agent_trace_arguments_invalid', nonempty=True)
        result = await self.mcp_client.call_tool("set_current_tx", self._inject_session({"tx_hash": selected[0]}))
        if result != f'Current transaction set to {selected[0]}':
            raise AgentContractError('trace', 'agent_trace_evidence_invalid')
        self.current_tx = selected[0]
        self._check_cancelled()

    def init_prompt(self, processed_data):
        txs_need_analyze = processed_data["transactions_need_analyze"]
        is_multi = True if len(txs_need_analyze) > 1 else False
        new_trace_sp = TRACE_DEBUG_SP.replace("{multi_attack_part}", MULTI_ATTACK_PART if is_multi else "")
        self.init_system_prompt(new_trace_sp)

    def switch_transaction_context(self, switch_data, previous_transactions_summary=None):
        """
        When switching transactions, retain the key analysis history and integrate the analysis results of previous transactions.
        Args:
        switch_data: A dictionary containing the information about the current transaction switch
        previous_transactions_summary: The summary information of all analyzed transactions previously
        """
        system_prompt = self.memory[0]

        switch_content = TRACE_SWITCH_TX_UP.format(
            raw_tx=switch_data["current_tx"],
            insight=switch_data["insight"],
            code_patch=switch_data["code_patch"],
            switch_to=switch_data["switch_to"],
            previous_transactions_summary=previous_transactions_summary or "无"
        )

        summary_msg = {
            "role": "user",
            "content": switch_content
        }

        preserved_memory = [system_prompt]

        recent_insights = []
        for msg in reversed(self.memory[-10:]):
            if isinstance(msg, dict) and msg.get("role") == "tool":
                if msg.get("name") in ["update_understanding", "get_function_source", "get_mixed_execution_flow"]:
                    content = str(msg.get("content", ""))
                    recent_insights.append({
                        "role": "assistant",
                        "content": f"In the previous trading analysis, it was discovered that：{content}"
                    })
                    if len(recent_insights) >= 5:
                        break

        self.memory = preserved_memory + recent_insights + [summary_msg]

    async def close(self):
        if self.session_id:
            await self.mcp_client.call_tool("close_session", {"session_id": self.session_id})
            self.session_id = None

    async def get_current_trace(self):
        return trace_tree(await self.mcp_client.call_tool("get_current_tree", self._inject_session({})))

    @staticmethod
    def _extract_previous_transactions_summary(global_fault_understanding: dict) -> str:
        if not isinstance(global_fault_understanding, dict):
            return "None"

        analyzed_transactions = global_fault_understanding.get("analyzed_transactions", {})
        if not analyzed_transactions:
            return "None"

        summary_parts = ["=" * 80, "【Summary of the key findings from the previous analysis of the transaction】", "=" * 80]

        for tx_hash, tx_data in analyzed_transactions.items():
            if not isinstance(tx_data, dict):
                continue

            summary_parts.append(f"\n### Transaction {tx_hash}...")
            insight = tx_data.get("insight", "")
            if insight:
                summary_parts.append(f"**Key Findings：**\n{insight}")

            code_patch = tx_data.get("code_patch", "")
            if code_patch:
                summary_parts.append(f"**Patch concept：**\n{code_patch}")

            status = tx_data.get("status", "")
            if status:
                summary_parts.append(f"**Analysis status：** {status}")

            summary_parts.append("-" * 80)

        summary_parts.append("\n**Important Note:** When analyzing new transactions, please take into account the key findings from the previously analyzed transactions.")
        summary_parts.append("Evaluate whether the current patching approach can fully protect against all types of attacks.")
        summary_parts.append("And when new vulnerability exploitation methods are discovered in new transactions, promptly update and complete the patching ideas.")
        summary_parts.append("=" * 80)

        return "\n".join(summary_parts)

    async def _force_ready_for_patch(
            self,
            global_fault_understanding: dict,
            task_tree: str,
            fallback_reason: str = "TIMEOUT_IDLE_LOOP"
    ) -> Dict:
        max_force_trials = 2
        invalid_contract = None

        for trial in range(max_force_trials):
            self._check_cancelled()
            current_tree = await self.get_current_trace()
            self._check_cancelled()
            if trial == 0:
                user_prompt = TRACE_DEBUG_FORCE_PATCH_UP
            else:
                user_prompt = TRACE_DEBUG_FORCE_PATCH_UP + """
[Format correction] Return exactly one terminal tool call: `ready_for_patch` only for a supported patch hypothesis, or `finish_investigation` with a nonempty reason when no such hypothesis is supported. Do not invent a vulnerability to satisfy the format.
"""

            tool_calls = await self.query_with_tools(user_prompt.format(
                global_fault_understanding=json.dumps(global_fault_understanding, ensure_ascii=False),
                trace=current_tree,
                task_tree=task_tree
            ))
            self._check_cancelled()
            if tool_calls is not None and not isinstance(tool_calls, (list, tuple)):
                raise AgentContractError('trace', 'agent_trace_arguments_invalid')

            pending = None
            for tool_call in tool_calls or []:
                self._check_cancelled()
                func_name = tool_call.function.name
                content = 'Forced review accepts only one terminal decision; this tool was not executed.'
                if pending is not None:
                    self.memory.append({'role': 'tool', 'tool_call_id': tool_call.id, 'name': func_name,
                                        'content': content})
                    continue
                if (func_name in self.INTERNAL_TOOLS or
                        getattr(self, '_available_tool_names', None) is not None
                        and func_name not in self._available_tool_names):
                    invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                    self.memory.append({'role': 'tool', 'tool_call_id': tool_call.id, 'name': func_name,
                                        'content': 'This tool is not available to the debugger; it was not executed.'})
                    continue
                func_args = self._safe_parse_tool_args(tool_call.function.arguments)
                if func_args is None:
                    invalid_contract = AgentContractError('trace', 'agent_trace_arguments_invalid')
                    content = 'Invalid tool arguments: provide a JSON object, not a list, null or malformed JSON.'
                elif func_name == 'finish_investigation':
                    try:
                        pending = self._finish_investigation(func_args, current_tree)
                        content = 'Investigation ended without a patch hypothesis. Safety and attack absence remain unconfirmed.'
                    except AgentContractError as exc:
                        invalid_contract = exc
                        content = 'Provide only a nonempty reason string describing the reviewed observations and remaining evidence gaps.'
                elif func_name == "ready_for_patch":
                    fault_report = func_args.get("fault_report", "")
                    fix_report = func_args.get("fix_report", "")
                    try:
                        fix_report = patch_hypothesis(fault_report, fix_report, self.tx_list)
                        final_trace = await self.get_current_trace()
                        self.logger.log_patch_report(fault_report, final_trace, fix_report)
                        pending = {'reason': 'READY_FOR_PATCH', 'data': [fault_report, final_trace, fix_report]}
                        content = 'Patch hypothesis accepted for generation and evidence review; its effectiveness is not yet verified.'
                    except AgentContractError as exc:
                        invalid_contract = exc
                        content = 'Invalid patch hypothesis: provide fault_report and fix_report.faulty_functions with valid original trigger hashes and trace indexes.'
                self.memory.append({'role': 'tool', 'tool_call_id': tool_call.id, 'name': func_name, 'content': content})
            if pending:
                return pending

        if invalid_contract is not None:
            raise invalid_contract

        final_trace = await self.get_current_trace()
        return {
            "reason": f"{fallback_reason}_NO_READY_FOR_PATCH",
            "data": [],
            "final_trace": final_trace
        }

    def _safe_parse_tool_args(self, args_str: str) -> dict | None:
        if not args_str:
            return {}

        if not isinstance(args_str, str):
            return None

        cleaned_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", args_str.strip(), flags=re.IGNORECASE | re.DOTALL)

        cleaned_str_escaped = cleaned_str.replace('\n', '\\n')

        py_style_str = cleaned_str.replace("true", "True").replace("false", "False").replace("null", "None")
        for parser, text in ((json.loads, args_str), (json.loads, cleaned_str),
                             (json.loads, cleaned_str_escaped), (ast.literal_eval, cleaned_str),
                             (ast.literal_eval, py_style_str)):
            try:
                value = parser(text)
            except (ValueError, SyntaxError, TypeError):
                continue
            return value if isinstance(value, dict) else None

        self.logger.error(f"[{self.name}] ❌ JSON parsing has failed seriously.. Raw content snippet: {args_str[:200]}...")
        return None
