import ast
import json
import logging
import os
import re
from datetime import datetime
from typing import Any,Optional, Callable
import uuid

from app.attackpilot.settings import PROJECT_PATH, WORK_ROOT
from app.attackpilot.utils.llm import MODEL_MAX_OUTPUT_TOKENS, MODEL_CONTEXT_WINDOWS
from app.attackpilot.utils.tokenization import get_token_encoder
from app.attackpilot.web.models import LogLevel, MsgType, LogMessage


class JSONParsingError(Exception):
    pass


class AgentLogger:
    _session_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
    _session_log_dir = None

    def __init__(self, agent_name: str, unique_id: str = "default", 
                 log_callback: Optional[Callable[[LogMessage], None]] = None):
        self.agent_name = agent_name
        self.unique_id = unique_id
        self.run_id = getattr(log_callback, "task_id", unique_id)
        self.log_callback = log_callback
        
        if AgentLogger._session_time is None:
            AgentLogger._session_time = datetime.now().strftime("%Y-%m-%d_%H-%M")
        if AgentLogger._session_log_dir is None:
            AgentLogger._session_log_dir = os.path.join(
                str(WORK_ROOT), "agent-logs"
            )
        if not os.path.exists(AgentLogger._session_log_dir):
            os.makedirs(AgentLogger._session_log_dir, exist_ok=True)

        self.file_logger = self._setup_file_logger()

    def _setup_file_logger(self):
        logger_key = f"Agent.{self.run_id}.{self.agent_name}"
        logger = logging.getLogger(logger_key)
        logger.setLevel(logging.INFO)

        if logger.handlers:
            logger.handlers.clear()

        dapp_log_dir = os.path.join(AgentLogger._session_log_dir, self.run_id)
        if not os.path.exists(dapp_log_dir):
            os.makedirs(dapp_log_dir, exist_ok=True)

        log_file = os.path.join(dapp_log_dir, f"{self.agent_name}.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - [%(agent_name)s] - %(message)s'))
        logger.addHandler(file_handler)

        logger.propagate = False
        return logging.LoggerAdapter(logger, {'agent_name': self.agent_name})

    @staticmethod
    def _snippet(text: str, max_len: int = 200) -> str:
        if not text: return ""
        text = str(text).replace('\n', ' ')
        if len(text) <= max_len: return text
        return f"{text[:max_len // 2]} ... [omit{len(text) - max_len}chars] ... {text[-max_len // 2:]}"

    def _send_to_callback(self, level: LogLevel, message_type: MsgType, message: str, is_truncated: bool = False):
        log_msg = LogMessage(agent=self.agent_name, level=level, message_type=message_type,
                             message=str(message), is_truncated=is_truncated,
                             timestamp=datetime.now().isoformat())
        if self.log_callback:
            self.log_callback(log_msg)


    def display_start(self, mode: str, user_prompt: str):
        print(f"\n{'=' * 80}\n🤖 [{self.unique_id}] [Agent: {self.agent_name}] -> ({mode})\n{'-' * 80}")
        
        is_trunc = len(user_prompt) > 1000
        safe_content = user_prompt
        md_message = f"### 🚀 执行阶段: {mode}\n\n"
        md_message += f"> {safe_content}"

        self._send_to_callback(LogLevel.INFO, MsgType.MARKDOWN, md_message)

    def display_tool_decision(self, tool_calls: list):
        if not tool_calls: return
        print(f"🛠️  [{self.unique_id}] Model calls tools: {', '.join([t.function.name for t in tool_calls])}")
        
        msg = f"Model determines invocation of tools ({len(tool_calls)}):\n"
        for idx, tool in enumerate(tool_calls):
            msg += f"- `{tool.function.name}(...)`\n"

        self._send_to_callback(LogLevel.INFO, MsgType.TOOL_CALL, msg)

    def display_result(self, content: Any, stats: dict):
        elapsed = stats.get('time', 0)
        tokens = stats.get('token', 0)
        
        if isinstance(content, (dict, list)):
            json_res = json.dumps(content, indent=2, ensure_ascii=False)
            result_str = f"```json\n{json_res}\n```"
        else:
            result_str = f"```\n{str(content)}\n```"

        md_message = f"#### ✅ 任务输出\n\n{result_str}\n\n> 📊 **统计**: 耗时 `{elapsed:.2f}s` | Token `{tokens}`"

        self._send_to_callback(LogLevel.INFO, MsgType.RESULT, md_message)

    def log_full_interaction(self, mode: str, memory_snapshot: str, input_text: str, output_text: str, tool_calls: list = None):
        # 1. 写入本地文件
        log_content = [f"\n{'=' * 30} {mode} START {'=' * 30}", f"📥 [INPUT]:\n{input_text}", f"📤 [OUTPUT]:\n{output_text}", "=" * 70]
        self.file_logger.info("\n".join(log_content))

        # 2. 发送到 Dashboard (Debug 级别)
        self._send_to_callback(LogLevel.DEBUG, MsgType.TEXT, "\n".join(log_content))
        self._send_to_callback(LogLevel.DEBUG, MsgType.MARKDOWN, f"**Snapshot Snippet:** {self._snippet(input_text, 150)}")

    def log_tool_result(self, tool_name: str, tool_result: Any):
        self.file_logger.info(f"\n🛠️ [TOOL RESULT] ({tool_name}):\n{tool_result}")
        msg = f"🔧 **Tool Result** ({tool_name}):\n```\n{tool_result}\n```"
        self._send_to_callback(LogLevel.INFO, MsgType.RESULT, msg)

    def log_patch_report(self, fault_report: str, final_trace: str, fix_report: str):
        log_content = [
            "",
            "=" * 40,
            "[PATCH GENERATED]",
            f"Fault Report:\n{fault_report}",
            f"Fix Report:\n{fix_report}",
            f"Trace Snapshot:\n{final_trace}",
            "=" * 40,
        ]
        self.file_logger.info("\n".join(log_content))
        print(
            f"\n{'=' * 80}\nPATCH GENERATED\n"
            f"Report Summary: {self._snippet(str(fault_report), 200)}\n"
            f"{'=' * 80}\n"
        )

        md_message = (
            "### Patch Candidate Generated\n\n"
            f"**Fault report:** {self._snippet(str(fault_report), 800)}\n\n"
            f"**Fix report:** {self._snippet(str(fix_report), 800)}\n\n"
            f"**Trace snapshot:**\n```\n{self._snippet(str(final_trace), 1200)}\n```"
        )
        self._send_to_callback(LogLevel.INFO, MsgType.MARKDOWN, md_message)

    def info(self, msg, *args, **kwargs):
        self.file_logger.info(msg, *args, **kwargs)
        self._send_to_callback(LogLevel.INFO, MsgType.TEXT, str(msg))

    def error(self, msg, *args, **kwargs):
        self.file_logger.error(msg, *args, **kwargs)
        self._send_to_callback(LogLevel.ERROR, MsgType.TEXT, str(msg))

    def warning(self, msg, *args, **kwargs):
        self.file_logger.warning(msg, *args, **kwargs)
        self._send_to_callback(LogLevel.WARNING, MsgType.TEXT, str(msg))

    def debug(self, msg, *args, **kwargs):
        self.file_logger.debug(msg, *args, **kwargs)
        self._send_to_callback(LogLevel.DEBUG, MsgType.TEXT, str(msg))

class TokenManager:
    def __init__(self, model: str):
        self.model = model
        self.context_limit = MODEL_CONTEXT_WINDOWS.get(model, 128000)
        self.encoder = get_token_encoder(model)

    def count_tokens(self, text: str) -> int:
        try:
            return len(self.encoder.encode(str(text)))
        except Exception:
            return int(len(str(text)) * 0.7)

    def calculate_total_tokens(self, memory: list) -> int:
        return sum(self.count_tokens(self.get_content(msg)) for msg in memory)

    def truncate_prompt(self, prompt: str, safety_buffer: int = 1000) -> str:
        limit = self.context_limit
        max_output = MODEL_MAX_OUTPUT_TOKENS.get(self.model, 8192)
        allowed = limit - max_output - safety_buffer
        if allowed <= 0: raise ValueError("Budget calculation failed.")

        token_ids = self.encoder.encode(prompt)
        if len(token_ids) <= allowed: return prompt
        print(f"⚠️ Triggered Truncation! Reduced to {allowed}")
        return self.encoder.decode(token_ids[:allowed])

    def truncate_history(self, history: list, max_turns: int) -> list:
        system_prompt = history[0]
        truncated = history[1:][-(max_turns * 2):]
        if not truncated: truncated = [history[-1]]
        return [system_prompt] + truncated

    def filter_redundant_messages(self, messages: list, ignore_tools: list) -> list:
        filtered = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = self.get_role(msg)
            if role == 'assistant' and hasattr(msg, 'tool_calls') and msg.tool_calls:
                all_ignorable = all(tc.function.name in ignore_tools for tc in msg.tool_calls)
                if all_ignorable and i + 1 < len(messages):
                    i += 1
                    while i < len(messages) and self.get_role(messages[i]) == 'tool':
                        i += 1
                    continue
            filtered.append(msg)
            i += 1
        return filtered

    def compress_messages(self, messages: list, threshold: int = 2000) -> list:
        compressed = []
        msg_count = len(messages)

        for idx, msg in enumerate(messages):
            role = self.get_role(msg)
            content = self.get_content(msg)
            tokens = self.count_tokens(content)

            if tokens > threshold and role in ['tool', 'assistant'] and idx < msg_count - 2:
                text = str(content)
                encoded = self.encoder.encode(text)
                truncated_text = (
                        self.encoder.decode(encoded[:800]) +
                        f"\n\n[... 内容过长，此处省略 {tokens - 1000} tokens ...]\n\n" +
                        self.encoder.decode(encoded[-200:])
                )

                new_msg = self._clone_msg(msg)
                self._set_content(new_msg, truncated_text)
                compressed.append(new_msg)
            else:
                compressed.append(msg)
        return compressed

    def truncate_history_by_token(self, history: list, keep_last_n_user: int = 3, ratio: float = 0.8) -> list:
        budget = int(self.context_limit * ratio)

        if not history: return []

        system_msg = history[0]
        user_indices = [i for i, msg in enumerate(history) if self.get_role(msg) == 'user']

        if keep_last_n_user > 0:
            protected_user_indices = set(user_indices[-keep_last_n_user:])
        else:
            protected_user_indices = set()

        processed_history = []
        for i, msg in enumerate(history):
            role = self.get_role(msg)
            if role == 'user' and i not in protected_user_indices:
                new_msg = msg.copy() if isinstance(msg, dict) else self._clone_msg(msg)
                self._set_content(new_msg, "[User message omitted to preserve tool context]")
                processed_history.append(new_msg)
            else:
                processed_history.append(msg)

        current_tokens = self.count_tokens(self.get_content(system_msg))
        kept_body = []

        for msg in reversed(processed_history[1:]):
            msg_tokens = self.count_tokens(self.get_content(msg))
            if current_tokens + msg_tokens > budget:
                break
            kept_body.insert(0, msg)
            current_tokens += msg_tokens

        while kept_body and self.get_role(kept_body[0]) == 'tool':
            kept_body.pop(0)

        return [system_msg] + kept_body

    def _clone_msg(self, msg):
        import copy
        return copy.copy(msg)

    def _set_content(self, msg, text):
        if isinstance(msg, dict):
            msg['content'] = text
        else:
            msg.content = text

    def get_role(self, msg):
        return msg.get('role') if isinstance(msg, dict) else getattr(msg, 'role', '')

    def get_content(self, msg):
        return msg.get('content') if isinstance(msg, dict) else getattr(msg, 'content', '')


class ResponseParser:
    @classmethod
    def process_response(cls, response: str, _format: str, *, strict: bool = False) -> Any:
        if _format == 'str': return response
        if _format == 'solidity': return cls._extract_solidity_code(response)

        clean_text = response.strip()
        try:
            parsed = cls._robust_parse(clean_text)
            if strict and _format in ('json', 'dict') and not isinstance(parsed, dict):
                raise JSONParsingError('Expected a JSON object')
            return parsed if isinstance(parsed, (dict, list)) else {"result": parsed}
        except Exception as exc:
            if strict:
                raise JSONParsingError('模型未返回有效的结构化结果') from exc
            return {} if _format in ['json', 'dict'] else []

    @classmethod
    def _robust_parse(cls, text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            pass

        code_block = re.compile(r'```(?:json|python)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
        match = code_block.search(text)
        if match:
            try:
                return cls._parse_structure(match.group(1).strip())
            except Exception:
                pass
        return cls._extract_and_parse_structure(text)

    @classmethod
    def _extract_and_parse_structure(cls, text: str) -> Any:
        json_start = re.search(r'[\{\[]', text)
        if not json_start: raise Exception("No JSON opening symbol was found")

        start_index = json_start.start()
        stack = []
        in_string = False
        escape_next = False

        for i in range(start_index, len(text)):
            char = text[i]
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if not in_string:
                if char in '{[':
                    stack.append(char)
                elif char in '}]':
                    if not stack: continue
                    last = stack.pop()
                    if (last == '{' and char == '}') or (last == '[' and char == ']'):
                        if not stack:
                            return cls._parse_structure(text[start_index: i + 1])

        raise Exception("No closed JSON structure was found.")

    @classmethod
    def _parse_structure(cls, content: str) -> Any:
        try:
            return json.loads(content, strict=False)
        except Exception:
            pass
        try:
            return ast.literal_eval(content)
        except Exception:
            pass

        try:
            fixed = content.replace("true", "True").replace("false", "False").replace("null", "None")
            return ast.literal_eval(fixed)
        except Exception:
            pass

        try:
            fixed = content.replace("True", "true").replace("False", "false").replace("None", "null")
            fixed = re.sub(r',\s*([\]}])', r'\1', fixed)
            return json.loads(fixed)
        except Exception:
            pass
        raise JSONParsingError(f"parse error: {content[:50]}")

    @classmethod
    def _extract_solidity_code(cls, text: str) -> str:
        code_content = ""
        pattern = re.compile(r'```\s*(?:solidity|typescript|javascript)?\s*([\s\S]*?)\s*```', re.IGNORECASE)
        match = pattern.search(text)
        if match: code_content = match.group(1)

        if not code_content:
            start_markers = ["// SPDX-License-Identifier", "pragma solidity", "contract "]
            start_index = -1
            for marker in start_markers:
                idx = text.find(marker)
                if idx != -1 and (start_index == -1 or idx < start_index): start_index = idx
            end_index = text.rfind("}")
            if start_index != -1 and end_index > start_index: code_content = text[start_index: end_index + 1]

        if not code_content and "pragma solidity" in text:
            code_content = text[text.find("pragma solidity"):]

        if not code_content: raise JSONParsingError("Solidity code not found")
        return cls._purify_solidity_code(code_content)

    @classmethod
    def _purify_solidity_code(cls, text: str) -> str:
        text = text.strip()
        lines = text.split('\n')
        if lines and lines[0].strip().startswith("```"): lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"): lines = lines[:-1]
        text = "\n".join(lines).strip()

        keywords = ["// SPDX-License-Identifier", "pragma solidity"]
        start_idx = -1
        for kw in keywords:
            idx = text.find(kw)
            if idx != -1 and (start_idx == -1 or idx < start_idx): start_idx = idx
        if start_idx != -1: text = text[start_idx:]

        last_brace = text.rfind("}")
        if last_brace != -1: text = text[:last_brace + 1]
        return text
