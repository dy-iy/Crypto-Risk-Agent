import json
import os
import time
import traceback
import asyncio
from copy import deepcopy
from typing import Any, Dict, List, Optional, Callable

from app.attackpilot.settings import LLM_NAME, CACHE_DIR
from app.attackpilot.utils.agent_helpers import AgentLogger, TokenManager, ResponseParser, JSONParsingError
from app.attackpilot.utils.llm import MODEL_MAX_OUTPUT_TOKENS
from app.attackpilot.utils.llm_client import LLMClient
from app.attackpilot.web.models import LogMessage
from app.attackpilot.errors import AgentContractError

class AgentBase:
    INTERNAL_TOOLS = frozenset({'get_current_tree', 'init_debug_session', 'set_current_tx',
                                'set_attack_tx_list', 'get_patch_items', 'close_session'})
    def __init__(self, name: str, role_prompt: str, unique_id: str = "default", need_tool=False, max_turns=1,log_callback: Optional[Callable[[LogMessage], None]] = None):
        self.name = name
        self.model = LLM_NAME
        self.max_turns = max_turns
        self.need_tool = need_tool

        self.logger = AgentLogger(name, unique_id, log_callback=log_callback)
        self.tm = TokenManager(self.model)
        self.parser = ResponseParser()

        self.llm_client = LLMClient()

        self.token = 0
        self.times = []
        self.memory: List[Dict[str, Any]] = [{"role": "system", "content": role_prompt}]
        self.mcp_client = None
        self.safety_margin = 0.8
        self.target_margin = 0.6
        self.cancellation_checker: Callable[[], bool] = lambda: False

    def set_cancellation_checker(self, cancellation_checker: Optional[Callable[[], bool]]):
        self.cancellation_checker = cancellation_checker or (lambda: False)

    def _check_cancelled(self):
        if self.cancellation_checker():
            raise asyncio.CancelledError("Task was cancelled")

    def init_system_prompt(self, role_prompt):
        self.memory = [{"role": "system", "content": role_prompt}]

    def _get_memory_snapshot_str(self, history: list) -> str:
        lines = [f"{'Index':<7} | {'Role':<12} | {'Tokens':<8} | {'Content Snippet'}", "-" * 80]
        for i, msg in enumerate(history):
            role = self.tm.get_role(msg)
            content = self.tm.get_content(msg)
            content_str = str(content) if content else ""

            tool_calls = None
            if isinstance(msg, dict):
                tool_calls = msg.get('tool_calls')
            elif hasattr(msg, 'tool_calls'):
                tool_calls = msg.tool_calls
            if not content and tool_calls:
                content_str = f"[Tool Calls: {len(tool_calls)} items]"
            tokens = self.tm.count_tokens(content_str)
            snippet = (content_str.replace('\n', ' ')[:60] + "...") if len(content_str) > 60 else content_str
            lines.append(f"[{i:<5}] | {role.upper():<12} | {tokens:<8} | {snippet}")
        return "\n".join(lines)

    async def query(self, user_message: str, temperature=1.0, _format='json', *, thinking=True):
        self._check_cancelled()
        self.logger.display_start("Query", user_message)
        result = await self._send_message(user_message, temperature, thinking=thinking)
        self._check_cancelled()
        if _format == 'str':
            return result

        try:
            return self.parser.process_response(result, _format, strict=True)
        except JSONParsingError:
            self.logger.warning('模型输出格式不正确，正在进行一次格式纠正。')
            corrected = await self._send_message(
                user_message + '\n\nReturn only a valid JSON object matching the requested schema. Preserve the evidence; do not invent missing facts.',
                temperature, thinking=thinking,
            )
            try:
                return self.parser.process_response(corrected, _format, strict=True)
            except JSONParsingError as exc:
                stage = {'TxRoleAgent': 'classification', 'FilterAgent': 'filter',
                         'TaskAgent': 'task', 'TraceAgent': 'trace',
                         'GlobalMemoryAgent': 'memory'}.get(type(self).__name__, 'agent')
                raise AgentContractError(stage, 'agent_output_invalid') from exc

    async def _send_message(self, user_message: str, temperature=1.0, *, thinking=True) -> str:
        try:
            self._check_cancelled()
            user_input = {"role": "user", "content": user_message}
            final_messages = self.tm.truncate_history([*self.memory, user_input], self.max_turns)
            self.memory.append(user_input)

            start_time = time.time()
            chat_completion = await self.llm_client.create_chat_completion(
                messages=final_messages,
                model=self.model,
                temperature=temperature,
                extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}},
                on_progress=self.logger.info,
            )
            elapsed_time = time.time() - start_time
            self._check_cancelled()

            reply = chat_completion.choices[0].message.content
            usage_token = int(chat_completion.usage.total_tokens) if chat_completion.usage else 0
            if not chat_completion.usage:
                self.logger.warning('模型未返回用量统计，本轮 token 用量未知。')

            self.times.append(elapsed_time)
            self.token += usage_token
            self.memory.append(chat_completion.choices[0].message.model_dump(exclude_none=True))

            snapshot = self._get_memory_snapshot_str(final_messages)
            self.logger.log_full_interaction("Query", snapshot, user_message, reply)
            self.logger.display_result(reply, {"time": elapsed_time, "token": usage_token})

            return reply
        except Exception as e:
            self._handle_error(e)

    async def query_with_tools(self, user_message: str, temperature=1.0, *, _retry_without_tools=True):
        self._check_cancelled()
        self.logger.display_start("QueryWithTools", user_message)
        try:
            self._check_cancelled()
            truncated_user_msg = self.tm.truncate_prompt(user_message)
            self.memory.append({"role": "user", "content": truncated_user_msg})
            from app.attackpilot.model_history import tool_history
            final_messages = tool_history(self.memory, self.tm.context_limit - MODEL_MAX_OUTPUT_TOKENS.get(self.model, 32768) - 1000, self.tm.count_tokens)

            tools = await self._get_openai_tools() if self.mcp_client else None
            self._check_cancelled()
            start_time = time.time()
            response = await self.llm_client.create_chat_completion(
                model=self.model,
                messages=final_messages,
                tools=tools,
                # DeepSeek thinking mode accepts auto, not forced tool choice.
                tool_choice="auto",
                temperature=temperature,
                on_progress=self.logger.info,
            )
            elapsed_time = time.time() - start_time
            self._check_cancelled()

            message = response.choices[0].message
            self.memory.append(message.model_dump(exclude_none=True))
            usage_token = int(response.usage.total_tokens) if response.usage else 0
            if not response.usage:
                self.logger.warning('模型未返回用量统计，本轮 token 用量未知。')
            self.token += usage_token
            self.times.append(elapsed_time)

            snapshot = self._get_memory_snapshot_str(final_messages)
            self.logger.log_full_interaction("QueryWithTools", snapshot, truncated_user_msg, message.content,
                                             message.tool_calls)
            self.logger.display_tool_decision(message.tool_calls)

            if tools and not message.tool_calls:
                if not _retry_without_tools:
                    raise AgentContractError('trace', 'agent_trace_tool_selection_missing')
                self.logger.warning('模型尚未选择工具，正在补问一次以继续调试。')
                return await self.query_with_tools(
                    user_message + '\n\nSelect and call the next available debugging tool. A prose-only answer does not execute the requested investigation.',
                    temperature, _retry_without_tools=False,
                )

            return message.tool_calls
        except Exception as e:
            self._handle_error(e)

    def _handle_error(self, e):
        if isinstance(e, AgentContractError):
            self.logger.file_logger.error(traceback.format_exc())
            raise e
        error_str = str(e)
        error_type = type(e).__name__
        print(f"\n❌ API Error: {type(e).__name__}\ndetail: {error_str}")
        self.logger.file_logger.error(traceback.format_exc())
        # A failed call did not produce an assistant turn. Remove its user input
        # so a caller's bounded retry does not poison subsequent history.
        if self.memory and self.memory[-1].get('role') == 'user':
            self.memory.pop()
        raise RuntimeError(f"Agent '{self.name}' API Error: {error_type} - {error_str}") from e

    async def _get_openai_tools(self):
        if not self.mcp_client:
            return None

        mcp_tools_result = await self.mcp_client.list_tools()
        tools = []
        for tool in mcp_tools_result.tools:
            if tool.name in self.INTERNAL_TOOLS:
                continue
            schema = deepcopy(tool.inputSchema)
            if "properties" in schema and "session_id" in schema["properties"]:
                del schema["properties"]["session_id"]
            if "required" in schema and isinstance(schema["required"], list):
                if "session_id" in schema["required"]:
                    schema["required"] = [p for p in schema["required"] if p != "session_id"]

            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": schema
                }
            })

        self._available_tool_names = {tool['function']['name'] for tool in tools}
        return tools

    def load_summary_from_cache(self, cache_path: str):
        with open(cache_path, 'r', encoding="utf-8") as f:
            cache = json.load(f)
            summary = cache.get("summary", "")
            # Stored usage belongs to the original generation. Reading its
            # result does not consume tokens or model time in this run.
        return summary

    def write_summary_to_cache(self, cache_path: str, file_name: str, summary: str):
        path = os.path.join(CACHE_DIR, cache_path)
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(path, '%s.json' % file_name)
        with open(path, 'w', encoding="utf-8") as f:
            json.dump({'summary': summary, 'token': str(self.token), 'time': ','.join([str(t) for t in self.times])},
                      f, ensure_ascii=False, indent=4)

    def get_total_time(self):
        return sum(self.times)
