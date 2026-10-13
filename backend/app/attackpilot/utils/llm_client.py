"""Bounded streaming transport; callers still receive a complete SDK response."""
import asyncio
import json
import logging
import os
import threading
from typing import Optional

import httpx
from openai import AsyncOpenAI, APIConnectionError, APIStatusError
from openai.types.chat import ChatCompletion
from app.attackpilot.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MAX_CONCURRENT
from app.attackpilot.errors import ModelDeadlineError
from app.attackpilot.language import chinese_messages


class IncompleteCompletionError(RuntimeError):
    """A partial response must never be treated as agent evidence."""
    def __init__(self, message, *, token_limit=False):
        super().__init__(message)
        self.token_limit = token_limit


def _seconds(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        if minimum <= value <= maximum:
            return value
    except ValueError:
        pass
    logging.getLogger(__name__).warning('%s invalid; using %s seconds', name, default)
    return default


class LLMClient:
    _instance: Optional['LLMClient'] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.deadline = _seconds('ATTACKPILOT_LLM_TIMEOUT', 600, 30, 1800)
            read_timeout = _seconds('ATTACKPILOT_LLM_READ_TIMEOUT', 120, 10, 300)
            # Separate connect/read/overall deadlines; no nested SDK retries.
            self.client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL,
                timeout=httpx.Timeout(read_timeout, connect=15, write=30, pool=15), max_retries=0)
            self.semaphore = asyncio.Semaphore(max(1, int(LLM_MAX_CONCURRENT)))
            self._initialized = True

    async def create_chat_completion(self, *args, on_progress=None, **kwargs):
        kwargs['model'] = 'deepseek-v4-pro'
        kwargs['messages'] = chinese_messages(kwargs.get('messages', []))
        kwargs.setdefault('max_tokens', 16384)
        kwargs['stream'] = True
        kwargs['stream_options'] = {'include_usage': True}
        # Includes semaphore wait, both attempts, and backoff. Cancellation closes
        # the stream, and retries never execute any returned tool calls.
        try:
            async with asyncio.timeout(self.deadline), self.semaphore:
                for attempt in range(2):
                    try:
                        return await self._complete(args, kwargs, on_progress)
                    except (APIConnectionError, APIStatusError, httpx.TransportError, IncompleteCompletionError) as exc:
                        transient = not isinstance(exc, APIStatusError) or exc.status_code in (408, 409, 429) or exc.status_code >= 500
                        if attempt or not transient:
                            raise
                        if isinstance(exc, IncompleteCompletionError) and exc.token_limit:
                            kwargs['max_tokens'] = min(int(kwargs['max_tokens']) * 2, 32768)
                        if on_progress:
                            on_progress(f'模型请求暂时中断（{type(exc).__name__}），正在重试一次。')
                        await asyncio.sleep(2)
        except TimeoutError as exc:
            raise ModelDeadlineError("DeepSeek model call exceeded its deadline") from exc

    async def _complete(self, args, kwargs, on_progress):
        stream = await self.client.chat.completions.create(*args, **kwargs)
        content, reasoning, calls = [], [], {}
        usage, finish, header = None, None, None
        loop = asyncio.get_running_loop()
        next_notice = loop.time()
        async with stream:
            async for chunk in stream:
                header = chunk
                if chunk.usage is not None:
                    usage = chunk.usage.model_dump(exclude_none=True)
                for choice in chunk.choices:
                    if choice.index != 0:
                        continue
                    delta = choice.delta
                    if delta.content:
                        content.append(delta.content)
                    if getattr(delta, 'reasoning_content', None):
                        reasoning.append(delta.reasoning_content)
                    for fragment in delta.tool_calls or []:
                        call = calls.setdefault(fragment.index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                        if fragment.id:
                            call['id'] = fragment.id
                        if fragment.function:
                            call['function']['name'] += fragment.function.name or ''
                            call['function']['arguments'] += fragment.function.arguments or ''
                    if choice.finish_reason:
                        finish = choice.finish_reason
                if on_progress and loop.time() >= next_notice:
                    on_progress('模型正在生成分析，已收到响应。')
                    next_notice = loop.time() + 20
        if header is None or finish not in ('stop', 'tool_calls'):
            raise IncompleteCompletionError(f'模型响应未完整结束（{finish or "stream interrupted"}）', token_limit=finish == 'length')
        message = {'role': 'assistant', 'content': ''.join(content) or None}
        if reasoning:
            message['reasoning_content'] = ''.join(reasoning)
        if calls:
            tool_calls = [calls[index] for index in sorted(calls)]
            for call in tool_calls:
                try:
                    arguments = json.loads(call['function']['arguments'])
                except (TypeError, ValueError) as exc:
                    raise IncompleteCompletionError('模型工具参数不是完整 JSON') from exc
                if not call['id'] or not call['function']['name'] or not isinstance(arguments, dict):
                    raise IncompleteCompletionError('模型工具调用缺少必要字段')
            message['tool_calls'] = tool_calls
        if not calls and not (message['content'] or '').strip():
            raise IncompleteCompletionError('模型仅返回思考过程，未返回分析内容')
        return ChatCompletion.model_validate({'id': header.id, 'created': header.created,
            'model': header.model, 'object': 'chat.completion', 'usage': usage,
            'choices': [{'index': 0, 'finish_reason': finish, 'message': message}]})
