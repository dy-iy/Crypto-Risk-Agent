import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from openai import APITimeoutError, AuthenticationError
from openai.types.chat import ChatCompletionChunk
import httpx

from app.attackpilot.utils.llm_client import LLMClient, IncompleteCompletionError
from app.attackpilot.errors import failure_message


def chunk(delta=None, finish=None, usage=None):
    return ChatCompletionChunk.model_validate({'id':'test','created':1,'model':'deepseek-v4-pro','object':'chat.completion.chunk','usage':usage,'choices':[{'index':0,'delta':delta or {},'finish_reason':finish}]})


class Stream:
    def __init__(self, chunks): self.chunks=chunks; self.closed=False
    async def __aenter__(self): return self
    async def __aexit__(self,*args): self.closed=True
    async def __aiter__(self):
        for item in self.chunks:
            if isinstance(item, BaseException): raise item
            yield item


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def client(self,*streams):
        client=object.__new__(LLMClient)
        client.deadline=2; client.semaphore=asyncio.Semaphore(1)
        client.client=Mock();client.client.chat.completions.create=AsyncMock(side_effect=streams)
        return client

    async def test_accumulates_reasoning_tools_and_usage(self):
        stream=Stream([chunk({'reasoning_content':'think'}),chunk({'tool_calls':[{'index':0,'id':'c1','type':'function','function':{'name':'trace','arguments':'{"a":'}}]}),chunk({'tool_calls':[{'index':0,'function':{'arguments':'1}'}}]},'tool_calls',{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30})])
        client=self.client(stream);response=await client.create_chat_completion(messages=[])
        self.assertEqual(response.choices[0].message.reasoning_content,'think')
        self.assertEqual(response.choices[0].message.tool_calls[0].function.arguments,'{"a":1}')
        self.assertEqual(response.usage.total_tokens,30);self.assertTrue(stream.closed)
        self.assertTrue(client.client.chat.completions.create.call_args.kwargs['stream'])
        self.assertEqual(response.choices[0].message.model_dump()['reasoning_content'],'think')

    async def test_timeout_retries_once_without_merging_partial_text(self):
        first=Stream([chunk({'content':'discard'}),APITimeoutError(request=httpx.Request('POST','https://example.test'))]);second=Stream([chunk({'content':'complete'},'stop')])
        client=self.client(first,second);progress=[]
        with patch('app.attackpilot.utils.llm_client.asyncio.sleep',AsyncMock()):
            response=await client.create_chat_completion(messages=[],on_progress=progress.append)
        self.assertEqual(response.choices[0].message.content,'complete');self.assertTrue(first.closed and second.closed)
        self.assertEqual(client.client.chat.completions.create.await_count,2);self.assertTrue(any('重试' in x for x in progress))

    async def test_incomplete_or_reasoning_only_stream_is_never_accepted(self):
        for parts in ([chunk({'content':'partial'})],[chunk({'reasoning_content':'thinking'},'stop')],[chunk({'content':'partial'},'length')]):
            client=self.client(Stream(parts),Stream(parts))
            with patch('app.attackpilot.utils.llm_client.asyncio.sleep',AsyncMock()):
                with self.assertRaises(IncompleteCompletionError): await client.create_chat_completion(messages=[])
            self.assertEqual(client.client.chat.completions.create.await_count,2)

    async def test_auth_error_does_not_retry(self):
        error=AuthenticationError('secret',response=httpx.Response(401,request=httpx.Request('POST','https://example.test')),body=None)
        client=self.client(error)
        with self.assertRaises(AuthenticationError):await client.create_chat_completion(messages=[])
        self.assertEqual(client.client.chat.completions.create.await_count,1)

    async def test_cancellation_closes_stream_and_does_not_retry(self):
        stream=Stream([asyncio.CancelledError()]);client=self.client(stream)
        with self.assertRaises(asyncio.CancelledError):await client.create_chat_completion(messages=[])
        self.assertTrue(stream.closed);self.assertEqual(client.client.chat.completions.create.await_count,1)

    async def test_total_deadline_also_limits_semaphore_wait(self):
        client=self.client();client.deadline=.01;await client.semaphore.acquire()
        with self.assertRaises(TimeoutError):await client.create_chat_completion(messages=[])
        client.client.chat.completions.create.assert_not_awaited()

    def test_wrapped_timeout_identifies_model_not_block_explorer(self):
        source=APITimeoutError(request=httpx.Request('POST','https://example.test'))
        wrapper=RuntimeError('agent failed');wrapper.__cause__=source
        message=failure_message(wrapper,'宏观分析')
        self.assertIn('APITimeoutError',message);self.assertIn('DeepSeek',message);self.assertNotIn('example.test',message)

    async def test_unparseable_filter_keeps_candidates(self):
        from app.attackpilot.agents.FilterAgent import FilterAgent
        agent=object.__new__(FilterAgent);agent.name='filter';agent.logger=Mock();agent.query=AsyncMock(return_value='not a list')
        tx='0x'+'a'*64
        result=await agent.handle({'attack_transactions':[tx],'trace_tree':{tx:'trace'}})
        self.assertEqual(result,[tx]);agent.logger.warning.assert_called_once()

    async def test_json_format_correction_is_bounded_and_not_an_empty_success(self):
        from app.attackpilot.agents.AgentBase import AgentBase
        from app.attackpilot.utils.agent_helpers import ResponseParser, JSONParsingError
        agent=object.__new__(AgentBase);agent.cancellation_checker=lambda:False;agent.logger=Mock();agent.parser=ResponseParser()
        agent._send_message=AsyncMock(side_effect=['not JSON','{"status":"ok"}'])
        self.assertEqual(await agent.query('return a status'),{'status':'ok'})
        self.assertEqual(agent._send_message.await_count,2)
        agent._send_message=AsyncMock(return_value='[]')
        with self.assertRaises(JSONParsingError):await agent.query('return a status')
        self.assertEqual(agent._send_message.await_count,2)

    async def test_tool_query_uses_auto_and_recovers_from_prose_once(self):
        from app.attackpilot.agents.AgentBase import AgentBase
        from openai.types.chat import ChatCompletion
        def response(message,finish='stop'):
            return ChatCompletion.model_validate({'id':'t','created':1,'object':'chat.completion','model':'deepseek-v4-pro','choices':[{'index':0,'message':{'role':'assistant',**message},'finish_reason':finish}]})
        agent=object.__new__(AgentBase);agent.name='Test';agent.model='deepseek-v4-pro';agent.memory=[{'role':'system','content':'test'}];agent.token=0;agent.times=[]
        agent.cancellation_checker=lambda:False;agent.logger=Mock();agent.mcp_client=Mock();agent.tm=Mock(context_limit=128000)
        agent.tm.truncate_prompt=lambda text:text;agent.tm.count_tokens=lambda text:1
        agent._get_memory_snapshot_str=Mock(return_value='snapshot');agent._get_openai_tools=AsyncMock(return_value=[{'type':'function','function':{'name':'trace'}}])
        agent.llm_client=Mock();agent.llm_client.create_chat_completion=AsyncMock(side_effect=[response({'content':'I will inspect'}),response({'content':None,'reasoning_content':'preserved','tool_calls':[{'id':'c1','type':'function','function':{'name':'trace','arguments':'{}'}}]},'tool_calls')])
        calls=await agent.query_with_tools('inspect')
        self.assertEqual(calls[0].function.name,'trace');self.assertEqual(agent.memory[-1]['reasoning_content'],'preserved')
        self.assertTrue(all(call.kwargs['tool_choice']=='auto' for call in agent.llm_client.create_chat_completion.call_args_list))
        agent.llm_client.create_chat_completion=AsyncMock(return_value=response({'content':'no tool'}))
        with self.assertRaisesRegex(RuntimeError,'两次未选择'):await agent.query_with_tools('inspect')
        self.assertEqual(agent.llm_client.create_chat_completion.await_count,2)

    async def test_invalid_trace_session_fails_before_downstream_use(self):
        from app.attackpilot.agents.TraceAgent import TraceAgent
        agent=object.__new__(TraceAgent);agent.cancellation_checker=lambda:False;agent.dapp={};agent.logger=Mock();agent.mcp_client=Mock();agent.mcp_client.call_tool=AsyncMock(return_value='Tool execution failed')
        with self.assertRaisesRegex(RuntimeError,'初始化失败'):await agent.init()
