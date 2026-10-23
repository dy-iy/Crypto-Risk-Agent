import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch
from openai import APITimeoutError, AuthenticationError
from openai.types.chat import ChatCompletionChunk
import httpx

from app.attackpilot.utils.llm_client import LLMClient, IncompleteCompletionError
from app.attackpilot.errors import failure_message


def chunk(delta=None, finish=None, usage=None):
    return ChatCompletionChunk.model_validate({'id':'test','created':1,'model':'deepseek-flash','object':'chat.completion.chunk','usage':usage,'choices':[{'index':0,'delta':delta or {},'finish_reason':finish}]})


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
        client=self.client(stream);response=await client.create_chat_completion(model="caller-override",messages=[])
        self.assertEqual(response.choices[0].message.reasoning_content,'think')
        self.assertEqual(response.choices[0].message.tool_calls[0].function.arguments,'{"a":1}')
        self.assertEqual(response.usage.total_tokens,30);self.assertTrue(stream.closed)
        self.assertTrue(client.client.chat.completions.create.call_args.kwargs['stream'])
        self.assertEqual(client.client.chat.completions.create.call_args.kwargs['model'],'deepseek-flash')
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
        from app.attackpilot.utils.agent_helpers import ResponseParser
        from app.attackpilot.errors import AgentContractError
        agent=object.__new__(AgentBase);agent.cancellation_checker=lambda:False;agent.logger=Mock();agent.parser=ResponseParser()
        agent._send_message=AsyncMock(side_effect=['not JSON','{"status":"ok"}'])
        self.assertEqual(await agent.query('return a status'),{'status':'ok'})
        self.assertEqual(agent._send_message.await_count,2)
        agent._send_message=AsyncMock(return_value='[]')
        with self.assertRaises(AgentContractError) as error:await agent.query('return a status')
        self.assertEqual(error.exception.reason_code,'agent_output_invalid')
        self.assertEqual(agent._send_message.await_count,2)

    async def test_tool_query_uses_auto_and_recovers_from_prose_once(self):
        from app.attackpilot.agents.AgentBase import AgentBase
        from app.attackpilot.errors import AgentContractError
        from openai.types.chat import ChatCompletion
        def response(message,finish='stop'):
            return ChatCompletion.model_validate({'id':'t','created':1,'object':'chat.completion','model':'deepseek-flash','choices':[{'index':0,'message':{'role':'assistant',**message},'finish_reason':finish}]})
        agent=object.__new__(AgentBase);agent.name='Test';agent.model='deepseek-flash';agent.memory=[{'role':'system','content':'test'}];agent.token=0;agent.times=[]
        agent.cancellation_checker=lambda:False;agent.logger=Mock();agent.mcp_client=Mock();agent.tm=Mock(context_limit=128000)
        agent.tm.truncate_prompt=lambda text:text;agent.tm.count_tokens=lambda text:1
        agent._get_memory_snapshot_str=Mock(return_value='snapshot');agent._get_openai_tools=AsyncMock(return_value=[{'type':'function','function':{'name':'trace'}}])
        agent.llm_client=Mock();agent.llm_client.create_chat_completion=AsyncMock(side_effect=[response({'content':'I will inspect'}),response({'content':None,'reasoning_content':'preserved','tool_calls':[{'id':'c1','type':'function','function':{'name':'trace','arguments':'{}'}}]},'tool_calls')])
        calls=await agent.query_with_tools('inspect')
        self.assertEqual(calls[0].function.name,'trace');self.assertEqual(agent.memory[-1]['reasoning_content'],'preserved')
        self.assertTrue(all(call.kwargs['tool_choice']=='auto' for call in agent.llm_client.create_chat_completion.call_args_list))
        agent.llm_client.create_chat_completion=AsyncMock(return_value=response({'content':'no tool'}))
        with self.assertRaisesRegex(AgentContractError,'两次未选择') as error:await agent.query_with_tools('inspect')
        self.assertEqual(error.exception.reason_code,'agent_trace_tool_selection_missing')
        self.assertEqual(agent.llm_client.create_chat_completion.await_count,2)

    async def test_invalid_trace_session_fails_before_downstream_use(self):
        from app.attackpilot.agents.TraceAgent import TraceAgent
        agent=object.__new__(TraceAgent);agent.cancellation_checker=lambda:False;agent.dapp={};agent.logger=Mock();agent.mcp_client=Mock();agent.mcp_client.call_tool=AsyncMock(return_value='Tool execution failed')
        with self.assertRaisesRegex(RuntimeError,'初始化失败'):await agent.init()


class OrdinaryContextBudgetTests(unittest.IsolatedAsyncioTestCase):
    """Ordinary queries must preserve current evidence before any model call."""

    @staticmethod
    def payload_size(messages):
        import json
        from app.attackpilot.language import chinese_messages
        return len(json.dumps(chinese_messages(messages), ensure_ascii=False, separators=(',', ':')))

    @staticmethod
    def token_manager(budget):
        from app.attackpilot.utils.agent_helpers import TokenManager
        # A deterministic encoder avoids downloading tokenizer assets and makes
        # message envelopes, Unicode rules, and reasoning costs observable.
        manager = object.__new__(TokenManager)
        manager.model = 'offline-context-budget-test'
        manager.context_limit = 8192 + 1000 + budget
        manager.count_tokens = len
        return manager

    def agent(self, memory, budget, *, max_turns=1):
        from copy import deepcopy
        from app.attackpilot.agents.AgentBase import AgentBase
        from app.attackpilot.utils.agent_helpers import ResponseParser
        agent = object.__new__(AgentBase)
        agent.name = 'OfflineBudgetAgent'; agent.model = 'offline-context-budget-test'
        agent.max_turns = max_turns; agent.memory = deepcopy(memory)
        agent.tm = self.token_manager(budget); agent.parser = ResponseParser()
        agent.logger = Mock(); agent.cancellation_checker = lambda: False
        agent.token = 0; agent.times = []
        agent.llm_client = Mock(); agent.llm_client.create_chat_completion = AsyncMock()
        return agent

    def test_preserves_complete_system_and_latest_user_without_mutation(self):
        from copy import deepcopy
        system = {'role': 'system', 'content': '完整系统指令\n' * 700}
        latest = {'role': 'user', 'content': '合成证据首部\n' + '多行证据\n' * 1600 + '证据尾部'}
        history = [system, {'role': 'user', 'content': 'old question'},
                   {'role': 'assistant', 'content': 'old answer'}, latest]
        original = deepcopy(history)
        manager = self.token_manager(self.payload_size([system, latest]))
        self.assertEqual(manager.truncate_history(history, max_turns=1), [system, latest])
        self.assertEqual(history, original)

    def test_budget_counts_reasoning_and_injected_language_rules(self):
        from app.attackpilot.language import chinese_messages
        import json
        system = {'role': 'system', 'content': 'system'}
        user = {'role': 'user', 'content': 'old question'}
        latest = {'role': 'user', 'content': 'latest evidence'}
        for field in ('reasoning_content', 'language_rules'):
            with self.subTest(field=field):
                answer = {'role': 'assistant', 'content': 'old answer'}
                if field == 'reasoning_content':
                    answer['reasoning_content'] = '完整合成推理\n' * 900
                history = [system, user, answer, latest]
                budget = self.payload_size(history) - 1
                manager = self.token_manager(budget)
                if field == 'reasoning_content':
                    omitted = [system, user, {'role': 'assistant', 'content': 'old answer'}, latest]
                    self.assertLessEqual(self.payload_size(omitted), budget)
                else:
                    self.assertLessEqual(len(json.dumps(history, ensure_ascii=False, separators=(',', ':'))), budget)
                self.assertEqual(manager.truncate_history(history, max_turns=3), [system, latest])
                self.assertLessEqual(self.payload_size([system, latest]), budget)
                self.assertEqual(chinese_messages([system])[0]['content'].count('【输出语言】'), 1)

    def test_budget_removes_whole_old_turns_and_retains_recent_turn_in_order(self):
        system = {'role': 'system', 'content': 'system'}
        old = [{'role': 'user', 'content': 'large old question ' * 500},
               {'role': 'assistant', 'content': 'large old answer ' * 500}]
        recent = [{'role': 'user', 'content': 'recent question'},
                  {'role': 'assistant', 'content': 'recent answer', 'reasoning_content': 'retained reasoning'}]
        latest = {'role': 'user', 'content': 'complete latest evidence'}
        expected = [system, *recent, latest]
        manager = self.token_manager(self.payload_size(expected))
        self.assertEqual(manager.truncate_history([system, *old, *recent, latest], max_turns=9), expected)

    def test_turn_limit_does_not_leave_orphan_assistants_or_unanswered_users(self):
        system = {'role': 'system', 'content': 'system'}
        recent = [{'role': 'user', 'content': 'paired question'},
                  {'role': 'assistant', 'content': 'paired answer'}]
        latest = {'role': 'user', 'content': 'latest evidence'}
        history = [system, {'role': 'assistant', 'content': 'leading orphan'},
                   {'role': 'user', 'content': 'unanswered historical question'},
                   *recent, {'role': 'assistant', 'content': 'trailing orphan'}, latest]
        manager = self.token_manager(100000)
        self.assertEqual(manager.truncate_history(history, max_turns=2), [system, *recent, latest])
        self.assertEqual(manager.truncate_history(history, max_turns=1), [system, latest])

    async def test_required_system_or_latest_evidence_over_budget_never_calls_model(self):
        from copy import deepcopy
        from app.attackpilot.errors import AgentContractError
        for system_text, evidence in (('synthetic system ' * 1000, 'latest evidence'),
                                      ('system', 'synthetic evidence ' * 1000)):
            with self.subTest(oversized='system' if len(system_text) > len(evidence) else 'user'):
                memory = [{'role': 'system', 'content': system_text}]
                budget = self.payload_size([*memory, {'role': 'user', 'content': evidence}]) - 1
                agent = self.agent(memory, budget)
                original = deepcopy(agent.memory)
                with self.assertRaises(AgentContractError) as raised:
                    await agent.query(evidence)
                self.assertEqual(raised.exception.reason_code, 'agent_context_budget_exceeded')
                agent.llm_client.create_chat_completion.assert_not_awaited()
                self.assertEqual(agent.memory, original)

    async def test_long_json_correction_with_one_turn_drops_old_assistant_and_reasoning(self):
        from openai.types.chat import ChatCompletion
        system = {'role': 'system', 'content': 'Full synthetic role instruction'}
        evidence = 'Synthetic evidence begins\n' + '原始证据行\n' * 1100 + 'Evidence ends'
        correction = ('\n\nReturn only a valid JSON object matching the requested schema. '
                      'Preserve the evidence; do not invent missing facts.')
        budget = self.payload_size([system, {'role': 'user', 'content': evidence + correction}])
        agent = self.agent([system], budget, max_turns=1)

        def completion(content, reasoning):
            return ChatCompletion.model_validate({'id': 'offline-budget', 'created': 1,
                'object': 'chat.completion', 'model': agent.model,
                'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': content, 'reasoning_content': reasoning}}]})

        agent.llm_client.create_chat_completion.side_effect = [
            completion('Synthetic invalid response ' * 900, 'discard old reasoning ' * 900),
            completion('{"status":"ok"}', 'synthetic corrected reasoning')]
        self.assertEqual(await agent.query(evidence), {'status': 'ok'})
        requests = agent.llm_client.create_chat_completion.call_args_list
        self.assertEqual(len(requests), 2)
        for index, call in enumerate(requests):
            messages = call.kwargs['messages']
            self.assertEqual([item['role'] for item in messages], ['system', 'user'])
            self.assertEqual(messages[0], system)
            self.assertEqual(messages[1]['content'], evidence + (correction if index else ''))
            self.assertLessEqual(self.payload_size(messages), budget)


class TraceInvestigationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def simulator():
        from types import SimpleNamespace
        from app.attackpilot.process.trace.debug_simulator import DebugSimulator
        def node(index, depth, *, address='0x' + 'a' * 40, kind='CALL', gas=5000):
            return SimpleNamespace(index=index, depth=depth, children=[], address_to=address,
                                   trace_type=kind, gas_used=gas, comment='',
                                   format_node=lambda: f'[{index}] {kind}')
        root, precompile, low_gas, target, vulnerable = (
            node(0, 0), node(1, 1, address='0x' + '0' * 39 + '1'),
            node(2, 1, kind='STATICCALL', gas=100), node(3, 1), node(4, 2))
        root.children = [precompile, low_gas, target]
        target.children = [vulnerable]
        simulator = DebugSimulator(root, {item.index: item for item in (root, precompile, low_gas, target, vulnerable)})
        simulator.expand_trace_by_depth(0)
        return simulator

    def test_expand_keeps_later_siblings_after_filtered_calls(self):
        simulator = self.simulator()
        simulator.expand_node(0, 2)
        self.assertIn('[4]', simulator.render())
        self.assertFalse(simulator.node_map[1].view_expanded)
        self.assertFalse(simulator.node_map[2].view_expanded)
        self.assertTrue(simulator.node_map[3].view_expanded)

    def test_invalid_trace_mutations_do_not_report_success_or_partial_update(self):
        simulator = self.simulator()
        for operation in (lambda: simulator.expand_node(999), lambda: simulator.collapse_node(999),
                          lambda: simulator.expand_node(0, -1),
                          lambda: simulator.update_comments({'0': 'would mutate', '999': 'invalid'})):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(simulator.node_map[0].comment, '')
        self.assertFalse(simulator.node_map[0].view_expanded)

    async def test_mcp_server_failure_reaches_client_as_tool_error(self):
        import os
        import tempfile
        from app.attackpilot import settings
        from app.attackpilot.mcp_tools.mcp_client import MCPClient, MCPToolError
        with tempfile.TemporaryDirectory(prefix='attackpilot-mcp-error-') as directory, patch.dict(
                os.environ, {'ATTACKPILOT_WORK_DIR': directory}):
            client = MCPClient(settings.MCP_SERVER_PATH)
            async with asyncio.timeout(30):
                try:
                    await client.connect()
                    with self.assertRaises(MCPToolError) as raised:
                        await client.call_tool('expand_node', {'session_id': 'missing-session', 'index': 0})
                    self.assertEqual(raised.exception.reason_code, 'remote_error')
                finally:
                    await client.close()

    async def test_all_debugger_failures_use_mcp_error_channel(self):
        from fastmcp.exceptions import ToolError
        from app.attackpilot.mcp_tools import mcp_server as server
        cases = {
            'expand_node': {'index': 0}, 'collapse_node': {'index': 0},
            'get_function_source_code': {'index': 0}, 'get_contract_source_code': {'index': 0},
            'get_mixed_execution_flow': {'index': 0}, 'get_node_detailed_state': {'index': 0},
            'update_comments': {'comments_json': {'0': 'comment'}}, 'get_current_tree': {},
            'set_current_tx': {'tx_hash': '0x' + 'a' * 64},
            'get_patch_items': {'faulty_index': '0x' + 'a' * 64 + '::0'},
            'switch_transaction': {'target_tx_hash': '0x' + 'a' * 64, 'insight': '', 'code_patch': ''},
            'analyze_unverified_contract': {'index': 0},
        }
        for name, arguments in cases.items():
            with self.subTest(tool=name), self.assertRaises(ToolError):
                await getattr(server, name).fn(session_id='missing-session', **arguments)

    def trace_agent(self, calls):
        from app.attackpilot.agents.TraceAgent import TraceAgent
        agent = object.__new__(TraceAgent)
        agent.name = 'trace'; agent.logger = Mock(); agent.cancellation_checker = lambda: False
        agent.memory = []; agent.tx_list = ['0x' + 'a' * 64]; agent.current_tx = agent.tx_list[0]
        agent.is_init = True; agent.session_id = 'session'; agent._available_tool_names = None
        agent.get_current_trace = AsyncMock(return_value='[0] CALL')
        agent._judge_too_long_trace = Mock(return_value='inspect')
        agent.query_with_tools = AsyncMock(return_value=calls)
        agent.mcp_client = Mock(); agent.mcp_client.call_tool = AsyncMock()
        return agent

    @staticmethod
    def tool_call(name, arguments, call_id='tool-1'):
        import json
        from types import SimpleNamespace
        return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))

    async def test_exploration_error_allows_one_corrected_tool_and_analysis_continues(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        for terminal in ('update_understanding', 'ready_for_patch'):
            with self.subTest(terminal=terminal):
                agent = self.trace_agent([])
                arguments = ({'insight': 'Checked the valid source node.'} if terminal == 'update_understanding'
                             else {'fault_report': 'The source node lacks the required check.',
                                   'fix_report': {'faulty_functions': [{'trigger_point': {
                                       'transaction_hash': agent.tx_list[0], 'index': 0}}]}})
                agent.query_with_tools.side_effect = [
                    [self.tool_call('get_function_source_code', {'index': 999}, 'failed')],
                    [self.tool_call('get_function_source_code', {'index': 0}, 'corrected'),
                     self.tool_call(terminal, arguments, 'terminal')],
                ]
                error = MCPToolError('get_function_source_code', 'remote_error')
                error.args = ('untrusted_remote_error_detail',)
                agent.mcp_client.call_tool.side_effect = [error, 'File: Contract.sol\nfunction checked() {}']
                result = await agent.handle({}, 'task tree')
                self.assertEqual(result['reason'], 'READY_FOR_PATCH' if terminal == 'ready_for_patch' else 'CONTINUE_DEBUGGING')
                self.assertEqual(agent.query_with_tools.await_count, 2)
                self.assertEqual(agent.mcp_client.call_tool.await_count, 2)
                self.assertEqual(agent.mcp_client.call_tool.await_args_list[1].args,
                                 ('get_function_source_code', {'index': 0, 'session_id': 'session'}))
                failed = next(message for message in agent.memory if message['tool_call_id'] == 'failed')
                self.assertIn('no evidence was returned', failed['content'])
                self.assertNotIn('untrusted_remote_error_detail', str(agent.memory))
                agent.logger.log_tool_result.assert_called_once_with(
                    'get_function_source_code', 'File: Contract.sol\nfunction checked() {}')
                if terminal == 'ready_for_patch':
                    agent.logger.log_patch_report.assert_called_once()
                else:
                    self.assertEqual(result['data'], ['Checked the valid source node.'])

    async def test_repeated_exploration_failure_stops_after_one_correction(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        agent = self.trace_agent([self.tool_call('expand_node', {'index': 999})])
        agent.mcp_client.call_tool.side_effect = MCPToolError('expand_node', 'remote_error')
        with self.assertRaises(MCPToolError):
            await agent.handle({}, 'task tree')
        self.assertEqual(agent.query_with_tools.await_count, 2)
        self.assertEqual(agent.mcp_client.call_tool.await_count, 2)
        self.assertEqual(len(agent.memory), 1)
        self.assertIn('no evidence was returned', agent.memory[0]['content'])
        agent.logger.log_tool_result.assert_not_called()
        agent.logger.log_patch_report.assert_not_called()

    async def test_exploration_transport_errors_and_cancellation_are_not_retried(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        for error in (MCPToolError('expand_node', 'transport_error'),
                      MCPToolError('expand_node', 'not_connected'),
                      MCPToolError('expand_node', 'empty_content'), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__, reason=getattr(error, 'reason_code', 'cancelled')):
                agent = self.trace_agent([self.tool_call('expand_node', {'index': 0})])
                agent.mcp_client.call_tool.side_effect = error
                with self.assertRaises(type(error)):
                    await agent.handle({}, 'task tree')
                self.assertEqual(agent.query_with_tools.await_count, 1)
                self.assertEqual(agent.get_current_trace.await_count, 1)
                self.assertEqual(agent.memory, [])
                agent.logger.log_tool_result.assert_not_called()

    async def test_failed_exploration_does_not_recover_a_lost_session_or_cancelled_trace_read(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        for error in (MCPToolError('get_current_tree', 'remote_error'), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                agent = self.trace_agent([self.tool_call('expand_node', {'index': 999})])
                agent.mcp_client.call_tool.side_effect = MCPToolError('expand_node', 'remote_error')
                agent.get_current_trace.side_effect = ['[0] CALL', error]
                with self.assertRaises(type(error)):
                    await agent.handle({}, 'task tree')
                self.assertEqual(agent.query_with_tools.await_count, 1)
                self.assertEqual(agent.memory, [])
                agent.logger.log_tool_result.assert_not_called()

    async def test_failed_exploration_skips_same_batch_patch_and_insight(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        agent = self.trace_agent([])
        agent.query_with_tools.side_effect = [
            [self.tool_call('get_node_detailed_state', {'index': 999}, 'failed'),
             self.tool_call('ready_for_patch', {'fault_report': 'unsupported'}, 'patch'),
             self.tool_call('update_understanding', {'insight': 'unsupported'}, 'insight')],
            [self.tool_call('update_understanding', {'insight': 'Will inspect a valid node.'}, 'continued')],
        ]
        agent.mcp_client.call_tool.side_effect = MCPToolError('get_node_detailed_state', 'remote_error')
        result = await agent.handle({}, 'task tree')
        self.assertEqual(result['data'], ['Will inspect a valid node.'])
        self.assertEqual(agent.mcp_client.call_tool.await_count, 1)
        self.assertTrue(all('Not executed' in message['content'] for message in agent.memory[1:3]))
        agent.logger.log_tool_result.assert_not_called()
        agent.logger.log_patch_report.assert_not_called()

    async def test_remote_transaction_switch_and_comment_errors_remain_fatal(self):
        from app.attackpilot.mcp_tools.mcp_client import MCPToolError
        for name, arguments in (
            ('switch_transaction', {'target_tx_hash': '0x' + 'a' * 64, 'insight': '', 'code_patch': ''}),
            ('update_comments', {'comments_json': {'999': 'comment'}}),
        ):
            with self.subTest(tool=name):
                agent = self.trace_agent([self.tool_call(name, arguments)])
                agent.mcp_client.call_tool.side_effect = MCPToolError(name, 'remote_error')
                with self.assertRaises(MCPToolError):
                    await agent.handle({}, 'task tree')
                self.assertEqual(agent.query_with_tools.await_count, 1)
                self.assertEqual(agent.get_current_trace.await_count, 1)
                self.assertEqual(agent.current_tx, agent.tx_list[0])
                self.assertEqual(agent.memory, [])
                agent.logger.log_tool_result.assert_not_called()

    async def test_memory_insight_is_recorded_without_noop_remote_call(self):
        agent = self.trace_agent([self.tool_call('update_understanding', {'insight': 'source checked'})])
        result = await agent.handle({}, 'task tree')
        self.assertEqual(result['data'], ['source checked'])
        agent.mcp_client.call_tool.assert_not_awaited()
        self.assertEqual(agent.memory[-1]['tool_call_id'], 'tool-1')

    async def test_invalid_transaction_switch_never_reaches_remote_session(self):
        from app.attackpilot.errors import AgentContractError
        agent = self.trace_agent([self.tool_call('switch_transaction', {'target_tx_hash': '0x' + 'b' * 64})])
        with self.assertRaises(AgentContractError):
            await agent.handle({}, 'task tree')
        agent.mcp_client.call_tool.assert_not_awaited()
        self.assertEqual(agent.current_tx, '0x' + 'a' * 64)
        self.assertEqual(agent.query_with_tools.await_count, 2)

    async def test_inconclusive_investigation_can_end_without_patch_in_regular_and_forced_review(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.trace_agent([
                    self.tool_call('finish_investigation', {'reason': 'Reviewed calls; source is insufficient.'}),
                    self.tool_call('expand_node', {'index': 0}),
                ])
                result = await agent.handle({}, 'task tree', force_terminate=forced)
                self.assertEqual(result['reason'], 'INVESTIGATION_FINISHED_NO_READY_FOR_PATCH')
                self.assertEqual(result['data'], [])
                self.assertEqual(result['final_trace'], '[0] CALL')
                self.assertIn('source is insufficient', result['diagnostic_reason'])
                self.assertNotIn('verification', result)
                agent.mcp_client.call_tool.assert_not_awaited()
                agent.logger.log_patch_report.assert_not_called()
                self.assertIn('not executed', agent.memory[-1]['content'].lower())

    async def test_inconclusive_tool_rejects_missing_reason_and_invented_verdict(self):
        from app.attackpilot.errors import AgentContractError
        for forced in (False, True):
            for arguments in ({}, {'reason': ' '}, {'reason': 1}, {'reason': 'reviewed', 'safety_confirmed': True}):
                with self.subTest(forced=forced, arguments=arguments):
                    agent = self.trace_agent([self.tool_call('finish_investigation', arguments)])
                    with self.assertRaises(AgentContractError):
                        await agent.handle({}, 'task tree', force_terminate=forced)
                    agent.mcp_client.call_tool.assert_not_awaited()
                    self.assertEqual(agent.query_with_tools.await_count, 2)

    async def test_inconclusive_decision_cannot_swallow_a_failed_final_trace_read(self):
        from app.attackpilot.errors import AgentContractError
        agent = self.trace_agent([self.tool_call('finish_investigation', {'reason': 'No supported hypothesis.'})])
        agent.get_current_trace = AsyncMock(side_effect=[
            '[0] CALL', AgentContractError('trace', 'agent_trace_evidence_invalid'),
        ])
        with self.assertRaises(AgentContractError):
            await agent.handle({}, 'task tree')
        agent.mcp_client.call_tool.assert_not_awaited()

    async def test_inconclusive_tool_is_advertised_without_exposing_internal_tools(self):
        from app.attackpilot.agents.AgentBase import AgentBase
        agent = self.trace_agent([])
        with patch.object(AgentBase, '_get_openai_tools', AsyncMock(return_value=[])):
            tools = await agent._get_openai_tools()
        self.assertEqual(agent._available_tool_names, {'finish_investigation'})
        schema = tools[0]['function']['parameters']
        self.assertEqual(schema['required'], ['reason'])
        self.assertFalse(schema['additionalProperties'])


class GenericWorkflowInputsTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def inputs(count=3):
        import secrets
        return [{'name': '未知输入_' + secrets.token_hex(8), 'platform': 'Ethereum',
                 'transaction_hash': ['0x' + secrets.token_hex(32)]} for _ in range(count)]

    @staticmethod
    def workflow():
        from app.attackpilot.workflow import WorkFlow
        workflow = object.__new__(WorkFlow)
        workflow.dapp2report = {}
        workflow.cancellation_checker = lambda: False
        workflow.process_single_dapp = AsyncMock()
        return workflow

    @staticmethod
    def explicit_json_inputs(inputs):
        from contextlib import ExitStack
        from io import StringIO
        import json
        stack = ExitStack()
        paths = [f'/synthetic-inputs/input_{i}.json' for i in range(len(inputs))]
        documents = {path: json.dumps(data) for path, data in zip(paths, inputs)}
        stack.enter_context(patch('app.attackpilot.workflow.open', create=True,
                                 side_effect=lambda path, *args, **kwargs: StringIO(documents[path])))
        return stack, paths

    async def test_unknown_names_and_new_hashes_all_reach_analysis_unchanged(self):
        from copy import deepcopy
        inputs = self.inputs()
        original = deepcopy(inputs)
        workflow = self.workflow()
        workflow.process_single_dapp.side_effect = lambda dapp: (
            dapp['name'], f'Synthetic report: {dapp["transaction_hash"][0]}')
        reports = await workflow.main_workflow(inputs)
        self.assertEqual(len(reports), len(inputs))
        self.assertEqual(workflow.process_single_dapp.await_count, len(inputs))
        for index, call in enumerate(workflow.process_single_dapp.await_args_list):
            self.assertEqual(call.args, (original[index],))
            self.assertEqual(call.kwargs, {})
            self.assertIn(original[index]['transaction_hash'][0], reports[original[index]['name']])
        self.assertEqual(inputs, original)

    async def test_batch_failure_cancels_and_awaits_other_analyses(self):
        inputs = self.inputs(2)
        workflow = self.workflow()
        sibling_started, sibling_closed = asyncio.Event(), asyncio.Event()
        children = []

        async def process(dapp):
            children.append(asyncio.current_task())
            if dapp is inputs[0]:
                await sibling_started.wait()
                raise RuntimeError('synthetic analysis failure')
            try:
                sibling_started.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                sibling_closed.set()

        workflow.process_single_dapp.side_effect = process
        with self.assertRaisesRegex(RuntimeError, 'synthetic analysis failure'):
            await workflow.main_workflow(inputs)
        self.assertTrue(sibling_closed.is_set())
        self.assertTrue(all(task.done() for task in children))
        self.assertTrue(children[1].cancelled())
        self.assertEqual(workflow.dapp2report, {})

    async def test_batch_cancellation_awaits_every_child_cleanup(self):
        inputs = self.inputs(3)
        workflow = self.workflow()
        all_started = asyncio.Event()
        children, closed = [], set()

        async def process(dapp):
            children.append(asyncio.current_task())
            if len(children) == len(inputs):
                all_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                closed.add(dapp['name'])

        workflow.process_single_dapp.side_effect = process
        batch = asyncio.create_task(workflow.main_workflow(inputs))
        await asyncio.wait_for(all_started.wait(), timeout=2)
        batch.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await batch
        self.assertEqual(closed, {dapp['name'] for dapp in inputs})
        self.assertTrue(all(task.done() and task.cancelled() for task in children))
        self.assertEqual(workflow.dapp2report, {})

    async def test_cancelled_before_explicit_inputs_does_not_open_or_start_analysis(self):
        workflow = self.workflow()
        workflow.cancellation_checker = lambda: True
        with patch('app.attackpilot.workflow.open', create=True) as opened:
            with self.assertRaises(asyncio.CancelledError):
                await workflow.main_workflow(input_paths=['/synthetic-inputs/cancelled.json'])
        opened.assert_not_called()
        workflow.process_single_dapp.assert_not_awaited()

    async def test_only_explicit_json_paths_are_read_and_submitted_without_dataset_indexes(self):
        from app.attackpilot.workflow import WorkFlow
        from unittest.mock import PropertyMock
        inputs = self.inputs(2)
        workflow = self.workflow()
        workflow.process_single_dapp.side_effect = lambda dapp: (dapp['name'], 'Synthetic report')
        stack, paths = self.explicit_json_inputs(inputs)
        with stack, patch.object(WorkFlow, 'raw_file_names', new_callable=PropertyMock,
                                 side_effect=AssertionError('Dataset discovery is forbidden')) as discovered:
            reports = await workflow.main_workflow(input_paths=paths)
        discovered.assert_not_called()
        self.assertEqual(set(reports), {dapp['name'] for dapp in inputs})
        self.assertEqual([call.args for call in workflow.process_single_dapp.await_args_list],
                         [(dapp,) for dapp in inputs])

    async def test_same_names_keep_all_new_reports_without_colliding_or_reusing_previous_batch(self):
        from copy import deepcopy
        inputs = self.inputs(3)
        name = inputs[0]['name']
        inputs[1]['name'] = name
        inputs[2]['name'] = f'{name} [2]'
        original = deepcopy(inputs)
        workflow = self.workflow()
        workflow.dapp2report = {'previous batch': 'stale report'}
        workflow.process_single_dapp.side_effect = lambda dapp: (dapp['name'], dapp['transaction_hash'][0])
        reports = await workflow.main_workflow(inputs)
        self.assertEqual(reports, {
            name: inputs[0]['transaction_hash'][0],
            f'{name} [3]': inputs[1]['transaction_hash'][0],
            f'{name} [2]': inputs[2]['transaction_hash'][0],
        })
        self.assertEqual(workflow.dapp2report, reports)
        self.assertNotIn('previous batch', reports)
        self.assertEqual(inputs, original)

    async def test_missing_or_empty_inputs_do_not_discover_read_or_submit(self):
        from app.attackpilot.workflow import WorkFlow
        from unittest.mock import PropertyMock
        workflow = self.workflow()
        with patch.object(WorkFlow, 'raw_file_names', new_callable=PropertyMock) as discovered, \
                patch('app.attackpilot.workflow.open', create=True) as opened:
            with self.assertRaisesRegex(ValueError, 'explicit'):
                await workflow.main_workflow()
            self.assertEqual(await workflow.main_workflow([]), {})
            self.assertEqual(await workflow.main_workflow(input_paths=[]), {})
        discovered.assert_not_called()
        opened.assert_not_called()
        workflow.process_single_dapp.assert_not_awaited()

    async def test_cli_without_inputs_only_prints_usage_and_never_constructs_workflow(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from app.attackpilot.workflow import main
        output = StringIO()
        with patch('app.attackpilot.workflow.WorkFlow') as workflow_class, \
                patch('app.attackpilot.workflow.open', create=True) as opened, redirect_stdout(output):
            self.assertEqual(await main([]), {})
        self.assertIn('usage:', output.getvalue())
        workflow_class.assert_not_called()
        opened.assert_not_called()

    async def test_cli_passes_only_explicit_json_paths_to_batch(self):
        from app.attackpilot.workflow import main
        paths = ['/synthetic-inputs/first.json', '/synthetic-inputs/second.json']
        with patch('app.attackpilot.workflow.WorkFlow') as workflow_class:
            workflow_class.return_value.main_workflow = AsyncMock(return_value={'synthetic': 'report'})
            self.assertEqual(await main(paths), {'synthetic': 'report'})
        workflow_class.assert_called_once_with(semaphore_num=1)
        workflow_class.return_value.main_workflow.assert_awaited_once_with(input_paths=paths)


class WorkflowCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_report_cache_needs_no_mcp_process(self):
        from app.attackpilot.workflow import WorkFlow, REPORT_POLICY_VERSION, request_fingerprint
        from app.attackpilot.workflow import normalize_enabled_modules
        tx = '0x' + 'a' * 64
        dapp = {'name': 'cache-test', 'platform': 'Ethereum', 'transaction_hash': [tx]}
        report = {'report': 'cached result', 'report_policy_version': REPORT_POLICY_VERSION,
                  'verification': {'status': 'skipped'},
                  'enabled_modules': sorted(normalize_enabled_modules(dapp)),
                  'request_fingerprint': request_fingerprint(dapp),
                  'baseline_validation': {'transactions': {tx: {'schema_version': 1, 'status': 'validated',
                      'original_transaction_hash': tx, 'network_id': '1',
                      'method': 'rpc_receipt_vs_tenderly_original_replay',
                      'block_number': 1, 'transaction_index': 0, 'gas_used': 21000,
                      'log_count': 0, 'receipt_status': 1, 'block_hash': '0x' + 'b' * 64,
                      'ordered_logs_sha256': 'c' * 64, 'receipt_digest': 'd' * 64}}}}
        with patch('app.attackpilot.workflow.PatchQualityMetrics'), patch('app.attackpilot.workflow.MCPClient') as mcp:
            workflow = WorkFlow()
            workflow.check_cache = Mock(side_effect=[{}, report])
            result = await workflow.process_single_dapp(dapp, processed_path='unused', report_path='unused')
        self.assertEqual(result, ('cache-test', 'cached result'))
        mcp.assert_not_called()

    async def test_macro_cache_needs_no_trace_reload(self):
        from app.attackpilot.workflow import WorkFlow, request_fingerprint
        tx = '0x' + 'a' * 64
        dapp = {'name': 'cache-test', 'platform': 'Ethereum', 'transaction_hash': [tx],
                'enabled_modules': ['attack_detection']}
        processed = {'request_fingerprint': request_fingerprint(dapp), 'transaction_hash_list': [tx],
                     'transaction_to_detail': {tx: {'baseline_validation': {'schema_version': 1,
                         'status': 'validated', 'original_transaction_hash': tx, 'network_id': '1',
                         'method': 'rpc_receipt_vs_tenderly_original_replay',
                         'block_number': 1, 'transaction_index': 0, 'gas_used': 21000,
                         'log_count': 0, 'receipt_status': 1, 'block_hash': '0x' + 'b' * 64,
                         'ordered_logs_sha256': 'c' * 64, 'receipt_digest': 'd' * 64}}}}
        with patch('app.attackpilot.workflow.PatchQualityMetrics'), patch('app.attackpilot.workflow.MCPClient') as mcp:
            workflow = WorkFlow(use_report_cache=False, write_report_cache=False)
            workflow.check_cache = Mock(return_value=processed)
            workflow.reload_debugger = AsyncMock()
            result = await workflow.process_single_dapp(dapp, processed_path='unused', report_path='unused')
        self.assertIn('宏观交易复盘', result[1])
        mcp.assert_not_called()
        workflow.reload_debugger.assert_not_awaited()


class AnalysisDataIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def process_classified_inputs(self, modules, hashes, attack):
        from app.attackpilot.process import pyg
        import networkx as nx
        from contextlib import ExitStack

        auxiliary = [tx for tx in hashes if tx not in attack]
        with ExitStack() as stack:
            factories = {name: stack.enter_context(patch.object(pyg, name)) for name in (
                'TxDetailAgent', 'TraceAgent', 'TxRoleAgent', 'TxFaultAgent',
                'FilterAgent', 'FundFlowGraphBuilder',
            )}
            for factory in factories.values():
                factory.return_value.token = 0
                factory.return_value.get_total_time.return_value = 0
            detail = factories['TxDetailAgent'].return_value
            detail.handle = AsyncMock(return_value=('receipt summary', {tx: {} for tx in hashes}, {}))
            trace = factories['TraceAgent'].return_value
            trace.init = AsyncMock(return_value={tx: '[0] CALL Game.makeBid' for tx in hashes})
            roles = factories['TxRoleAgent'].return_value
            roles.handle = AsyncMock(return_value=({}, list(attack), auxiliary, {}))
            fault = factories['TxFaultAgent'].return_value
            fault.handle = AsyncMock(return_value='A hypothesis is not yet established.')
            factories['FundFlowGraphBuilder'].return_value.add_transactions = AsyncMock(return_value=nx.MultiDiGraph())
            processor = pyg.DAppProcess({'Ethereum': None}, {'Ethereum': None}, None,
                                       enabled_modules=modules)
            processor.format_transactions = AsyncMock(return_value=([], hashes))
            processed, _ = await processor.process({
                'name': 'classification-regression', 'platform': 'Ethereum',
                'transaction_hash': hashes,
            })
            return processed, fault.handle.await_count, factories['FilterAgent'].call_count

    async def test_deep_investigation_continues_after_empty_attack_classification(self):
        tx = '0x' + 'a' * 64
        data, fault_calls, filter_calls = await self.process_classified_inputs(
            ['attack_detection', 'fault_localization'], [tx], [])
        self.assertEqual(data['transactions_need_analyze'], [tx])
        self.assertEqual(data['attack_transactions'], [])
        self.assertEqual(data['auxiliary_transactions'], [tx])
        self.assertFalse(data['attack_classification']['safety_confirmed'])
        self.assertFalse(data['investigation_scope']['attack_confirmed'])
        self.assertEqual(data['investigation_scope']['source'], 'requested_fault_localization')
        self.assertEqual(fault_calls, 1)
        self.assertEqual(filter_calls, 0)

    async def test_inconclusive_deep_investigation_finishes_unverified_without_patch(self):
        from app.attackpilot.process import analyze
        tx = '0x' + 'a' * 64
        trace = Mock()
        trace.init_transactions = AsyncMock()
        trace.handle = AsyncMock(return_value={
            'reason': 'INVESTIGATION_FINISHED_NO_READY_FOR_PATCH', 'data': [],
            'final_trace': '[0] CALL', 'diagnostic_reason': 'No supported hypothesis after source review.',
        })
        data = {'dapp': {'name': 'inconclusive', 'platform': 'Ethereum'},
                'transactions_need_analyze': [tx], 'transaction_hash_list': [tx],
                'attack_transactions': [], 'auxiliary_transactions': [tx]}
        with patch.object(analyze, 'GlobalMemoryAgent') as memory, patch.object(analyze, 'TaskAgent') as tasks:
            for agent in (trace, memory.return_value, tasks.return_value):
                agent.token = 0
                agent.get_total_time.return_value = 0
            tasks.return_value.handle = AsyncMock()
            runner = analyze.DAppAnalyze(data, trace, {}, {}, None,
                                         enabled_modules=['attack_detection', 'fault_localization'])
            report, items = await runner.analyze()
        trace.init_transactions.assert_awaited_once_with([tx])
        trace.handle.assert_awaited_once()
        self.assertEqual(items['verification']['status'], 'unverified')
        self.assertEqual(items['verification']['reason_code'], 'no_attack_hypothesis')
        self.assertFalse(items['verification']['replay_attempted'])
        self.assertIsNone(items['replay_evidence'])
        self.assertEqual(items['applied_patches'], '')
        self.assertIn('不代表交易安全', report)

    async def test_deep_investigation_keeps_unselected_inputs_in_historical_order(self):
        hashes = ['0x' + digit * 64 for digit in 'abc']
        data, fault_calls, filter_calls = await self.process_classified_inputs(
            ['attack_detection', 'fault_localization'], hashes, [hashes[1]])
        self.assertEqual(data['transactions_need_analyze'], hashes)
        self.assertEqual(data['attack_transactions'], [hashes[1]])
        self.assertEqual(data['auxiliary_transactions'], [hashes[0], hashes[2]])
        self.assertEqual(fault_calls, 1)
        self.assertEqual(filter_calls, 0)

    async def test_macro_only_empty_classification_does_not_force_attack_hypothesis(self):
        tx = '0x' + 'a' * 64
        data, fault_calls, _ = await self.process_classified_inputs(['attack_detection'], [tx], [])
        self.assertEqual(data['transactions_need_analyze'], [])
        self.assertEqual(data['attack_transactions'], [])
        self.assertEqual(fault_calls, 0)

    TX = '0x' + 'a' * 64
    TOKEN = '0x' + 'b' * 40
    SENDER = '0x' + 'c' * 40
    RECIPIENT = '0x' + 'd' * 40

    def transfer(self, amount, *, nft=False):
        from app.attackpilot.utils.token_utils import ERC20_TRANSFER_TOPIC
        topics = [ERC20_TRANSFER_TOPIC, '0x' + '0' * 24 + self.SENDER[2:],
                  '0x' + '0' * 24 + self.RECIPIENT[2:]]
        if nft:
            topics.append(hex(amount))
        return {'name': 'Transfer', 'raw': {'address': self.TOKEN, 'topics': topics,
                'data': '0x' if nft else '0x' + format(amount, '064x')},
                'inputs': [{'soltype': {'name': name}, 'value': value} for name, value in
                           [('from', self.SENDER), ('to', self.RECIPIENT),
                            ('tokenId' if nft else 'value', str(amount))]]}

    def asset(self, amount=10, **metadata):
        return {'from': self.SENDER, 'to': self.RECIPIENT, 'raw_amount': str(amount),
                'amount': 999999, 'token_info': {'contract_address': self.TOKEN, **metadata}}

    def test_trace_decimal_hex_and_integer_quantities_agree(self):
        from app.attackpilot.entities.trace import MixTraceItem, TraceNode
        amount = 294000000000000000
        for value in (str(amount), hex(amount), amount):
            with self.subTest(value=value):
                node = TraceNode(MixTraceItem({'call_type': 'CALL', 'value': value,
                    'to': self.RECIPIENT, 'gas_used': 1}), 0, 'EXTERNAL')
                self.assertEqual(node.value, amount)
                self.assertIn('0.2940 native', node.format_node())
                self.assertIn(f'Raw: {amount}', node.format_node())
        for value in (True, -1, 1.2, '1.2', 'garbage'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TraceNode(MixTraceItem({'call_type': 'CALL', 'value': value,
                                      'to': self.RECIPIENT}), 0, 'EXTERNAL')

    def test_unknown_token_decimals_and_zero_log_amount_are_not_invented(self):
        from app.attackpilot.utils.log import LogAnalyzer
        for info in ({}, {self.TOKEN: {'name': 'Token', 'decimals': -1}},
                     {self.TOKEN: {'name': 'Token', 'decimals': None}}):
            text = LogAnalyzer(info).process_log(self.transfer(0))
            self.assertIn('Raw: 0', text)
            self.assertIn('Decimals: unknown', text)
            self.assertNotIn('None', text)
        text = LogAnalyzer({self.TOKEN: {'name': 'Token', 'decimals': 6}}).process_log(self.transfer(1234567))
        self.assertIn('1.234567 Token', text)
        self.assertIn('Raw: 1234567', text)

    def test_raw_logs_survive_entity_and_override_partial_or_decoded_asset_data(self):
        from app.attackpilot.entities.tx import TxDetailItem
        from app.attackpilot.utils.balance_utils import BalanceAnalyzer
        logs = [self.transfer(10), self.transfer(20)]
        logs[0]['inputs'][2]['value'] = '9999999999'
        detail = TxDetailItem({'transaction': {'hash': self.TX, 'status': True,
            'transaction_info': {'logs': logs, 'asset_changes': [self.asset(10)]}}}).to_dict()
        self.assertEqual(detail['logs'], logs)
        self.assertEqual(detail['log_analysis']['transfer_events'], 2)
        from app.attackpilot.utils.log import LogAnalyzer
        self.assertIn('Raw: 10', LogAnalyzer({}).process_log(logs[0]))
        balances, _ = BalanceAnalyzer.parse_tenderly_data(detail)
        self.assertEqual(balances[self.SENDER][self.TOKEN], -30)
        self.assertEqual(balances[self.RECIPIENT][self.TOKEN], 30)

    def test_nft_token_id_never_becomes_fungible_balance(self):
        from app.attackpilot.utils.balance_utils import BalanceAnalyzer
        from app.attackpilot.utils.log import LogAnalyzer
        log = self.transfer(123456789, nft=True)
        balances, _ = BalanceAnalyzer.parse_tenderly_data({
            'logs': [log], 'asset_changes': [self.asset(123456789)]})
        self.assertEqual(dict(balances), {})
        text = LogAnalyzer({}).process_log(log)
        self.assertIn('NFT TRANSFER', text)
        self.assertIn('Token ID: 123456789', text)

    async def test_graph_uses_raw_events_and_never_prices_nft_ids(self):
        from app.attackpilot.process.fund_graph import FundFlowGraphBuilder
        tx = {'tx_hash': self.TX, 'timestamp': 10, 'block_number': 1,
              'asset_changes': [self.asset(10, decimals=1)],
              'logs': [self.transfer(10), self.transfer(20)], 'balance_diff': []}
        graph = FundFlowGraphBuilder('Ethereum')
        graph._fetch_all_historical_prices = AsyncMock(return_value={(10, self.TOKEN): {'price': 2}})
        result = await graph.add_transactions([tx])
        self.assertEqual(sorted(edge['amount'] for *_, edge in result.edges(data=True)), [1, 2])
        self.assertEqual(sorted(edge['dollar_value'] for *_, edge in result.edges(data=True)), [2, 4])
        graph = FundFlowGraphBuilder('Ethereum')
        graph._fetch_all_historical_prices = AsyncMock(return_value={(10, self.TOKEN): {'price': 2}})
        tx['logs'] = [self.transfer(987654321, nft=True)]
        result = await graph.add_transactions([tx])
        edge = next(iter(result.edges(data=True)))[2]
        self.assertEqual(edge['amount'], 1)
        self.assertEqual(edge['token_id'], 987654321)
        self.assertIsNone(edge['dollar_value'])

    async def test_graph_preserves_unknown_precision_and_parses_hex_native_balance(self):
        from app.attackpilot.process.fund_graph import FundFlowGraphBuilder
        graph = FundFlowGraphBuilder('Ethereum')
        self.assertIsNone(graph._normalize_amount(self.asset(100)))
        self.assertIsNone(graph._normalize_amount({'amount': 123, 'token_info': {'decimals': 18}}))
        graph._fetch_all_historical_prices = AsyncMock(return_value={})
        result = await graph.add_transactions([{'tx_hash': self.TX,
            'balance_diff': [{'address': self.SENDER, 'original': '0x10', 'dirty': '0x0'}]}])
        self.assertEqual(next(iter(result.edges(data=True)))[2]['amount'], 16 / 10 ** 18)

    async def test_role_metadata_stays_with_its_transaction_and_keeps_known_decimals(self):
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        tx2 = '0x' + 'e' * 64
        agent = object.__new__(TxRoleAgent)
        agent._platform = 'Ethereum'
        agent._fetch_prices_for_all_txs = AsyncMock(return_value={})
        data = {'transaction_hash_list': [self.TX, tx2], 'transaction_to_detail': {
            self.TX: {'asset_changes': [self.asset(1000000)]},
            tx2: {'asset_changes': [self.asset(1000000)]}},
            'transaction_to_property': {
                self.TX: [{'contract_address': self.TOKEN, 'decimals': 6}],
                tx2: [{'contract_address': self.TOKEN, 'decimals': 18}]}}
        result = await agent.get_balance_change(data, [])
        self.assertEqual(result[self.TX][self.RECIPIENT][self.TOKEN]['fmt_amount'], 1)
        self.assertEqual(result[tx2][self.RECIPIENT][self.TOKEN]['fmt_amount'], 1e-12)

    async def test_role_rejects_a_fabricated_participant_then_accepts_observed_one(self):
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        from app.attackpilot.errors import AgentContractError
        agent = object.__new__(TxRoleAgent)
        agent.logger = Mock(); agent.get_balance_change = AsyncMock(return_value={})
        agent.write_summary_to_cache = Mock()
        def response(address):
            return {'transaction': {'attack_transactions': [self.TX], 'auxiliary_transactions': []},
                    'address_role': {address: {'role': 'attacker', 'description': 'observed sender'}}}
        data = {'transaction_hash_list': [self.TX], 'transaction_to_property': {},
                'transaction_to_detail': {self.TX: {'from': self.SENDER}}}
        agent.query = AsyncMock(side_effect=[response(self.RECIPIENT), response(self.SENDER)])
        with patch('app.attackpilot.agents.TxRoleAgent.os.path.exists', return_value=False):
            result = await agent.handle(data, [])
        self.assertEqual(list(result[0]), [self.SENDER])
        self.assertEqual(agent.query.await_count, 2)
        agent.query = AsyncMock(return_value=response(self.RECIPIENT))
        with patch('app.attackpilot.agents.TxRoleAgent.os.path.exists', return_value=False):
            with self.assertRaises(AgentContractError):
                await agent.handle(data, [])

    async def test_role_accepts_ordinary_transaction_without_forcing_attack(self):
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        agent = object.__new__(TxRoleAgent)
        agent.logger = Mock(); agent.get_balance_change = AsyncMock(return_value={})
        agent.write_summary_to_cache = Mock()
        agent.query = AsyncMock(return_value={
            'transaction': {'attack_transactions': [], 'auxiliary_transactions': [self.TX]},
            'address_role': {self.SENDER: {'role': 'sender', 'description': 'ordinary transfer'}}})
        with patch('app.attackpilot.agents.TxRoleAgent.os.path.exists', return_value=False):
            _, attack, auxiliary, _ = await agent.handle({
                'transaction_hash_list': [self.TX], 'transaction_to_property': {},
                'transaction_to_detail': {self.TX: {'from': self.SENDER}}}, [])
        self.assertEqual(attack, [])
        self.assertEqual(auxiliary, [self.TX])
        agent.query.assert_awaited_once()

    async def test_role_prompt_includes_multiline_trace_and_cache_changes_with_calls(self):
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        agent = object.__new__(TxRoleAgent)
        agent.logger = Mock(); agent.get_balance_change = AsyncMock(return_value={})
        agent.write_summary_to_cache = Mock()
        agent.query = AsyncMock(return_value={
            'transaction': {'attack_transactions': [], 'auxiliary_transactions': [self.TX]},
            'address_role': {},
        })
        tree = '[0] CALL Game.makeBid\n└── [1] CALL receiver.callback'
        data = {'transaction_hash_list': [self.TX], 'transaction_to_property': {},
                'transaction_to_detail': {}, 'trace_tree': {self.TX: tree}}
        with patch('app.attackpilot.agents.TxRoleAgent.os.path.exists', return_value=False):
            await agent.handle(data, [])
            self.assertIn(tree, agent.query.call_args.args[0])
            data['trace_tree'][self.TX] += '\n    └── [2] CALL Game.makeBid'
            await agent.handle(data, [])
        keys = [call.kwargs['file_name'] for call in agent.write_summary_to_cache.call_args_list]
        self.assertNotEqual(keys[0], keys[1])

    def test_role_prompt_deduplicates_quotes_without_changing_assets_or_unknowns(self):
        from copy import deepcopy
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        quote = {'price': None, 'status': 'unavailable', 'decimals': None, 'chain_id': 1}
        other_chain = {**quote, 'chain_id': 56}
        graph = f'edge: price_evidence={quote}, timestamp=10\nedge2: price_evidence={quote}, timestamp=10'
        balances = {'token1': {'raw_amount': 123, 'decimals': None, 'price_evidence': quote},
                    'token2': {'raw_amount': 456, 'decimals': None, 'price_evidence': other_chain}}
        original = deepcopy(balances)
        compact_graph, compact_balances, registry = TxRoleAgent._prompt_evidence(graph, balances)
        self.assertEqual(balances, original)
        self.assertEqual(len(registry), 2)
        for token in balances:
            compact = compact_balances[token]
            self.assertEqual(compact['raw_amount'], balances[token]['raw_amount'])
            self.assertIsNone(compact['decimals'])
            self.assertEqual(registry[compact['price_evidence']['$ref']], balances[token]['price_evidence'])
        graph_ref = compact_balances['token1']['price_evidence']
        self.assertEqual(compact_graph.replace(str(graph_ref), str(quote)), graph)
        opaque_graph = 'price_evidence={unrecognized provider format}'
        self.assertEqual(TxRoleAgent._prompt_evidence(opaque_graph, {})[0], opaque_graph)

    def detail_agent(self):
        from app.attackpilot.agents.TxDetailAgent import TxDetailAgent
        agent = object.__new__(TxDetailAgent)
        agent.logger = Mock(); agent._platform = 'Ethereum'; agent.cancellation_checker = lambda: False
        agent._load_token_properties = AsyncMock(return_value={self.TX: []})
        agent._load_tx_detail_data = AsyncMock(return_value={self.TX: {'hash': self.TX, 'nonce': 1}})
        agent.query = AsyncMock(return_value='Valid transaction summary')
        agent.write_summary_to_cache = Mock()
        return agent

    async def test_generated_inputs_keep_full_price_evidence_through_role_and_fault_prompts(self):
        from copy import deepcopy
        import hashlib
        from app.attackpilot.agents.TxRoleAgent import TxRoleAgent
        from app.attackpilot.agents.TxFaultAgent import TxFaultAgent

        hashes = ['0x' + hashlib.sha256(f'generated-input-{i}'.encode()).hexdigest() for i in range(3)]
        quote = {'price': None, 'decimals': None, 'chain_id': 1, 'status': 'unavailable',
                 'provenance': {'history': 'synthetic provenance ' * 450}}
        quotes = [quote, {**quote, 'chain_id': 56}]
        graph = '\n'.join(
            f'edge_{i}: raw_amount={10**24 + i}, decimals=None, '
            f'price_evidence={quotes[i % 2]}, timestamp=10' for i in range(80)
        )
        traces = {tx: f'[0] CALL synthetic.entry\n  [1] CALL synthetic.trigger_{i}'
                  for i, tx in enumerate(hashes)}
        balances = {tx: {'raw_amount': str(10**24 + i), 'decimals': None,
                         'price_evidence': quotes[i % 2]} for i, tx in enumerate(hashes)}
        data = {'transaction_hash_list': hashes, 'transaction_detail': 'Synthetic receipt observations',
                'transaction_to_property': {tx: [] for tx in hashes}, 'trace_tree': traces,
                'transfer_graph': graph, 'balance_change': balances,
                'transactions_need_analyze': hashes,
                'investigation_scope': {'attack_confirmed': False, 'targets': hashes}}
        original = deepcopy(data)
        role = object.__new__(TxRoleAgent)
        role.logger = Mock(); role.get_balance_change = AsyncMock(return_value=balances)
        role.write_summary_to_cache = Mock()
        role.query = AsyncMock(return_value={'transaction': {
            'attack_transactions': hashes[-1:], 'auxiliary_transactions': hashes[:-1]}, 'address_role': {}})
        fault = object.__new__(TxFaultAgent)
        fault.logger = Mock(); fault.write_summary_to_cache = Mock()
        fault.query = AsyncMock(return_value='Inspect synthetic.trigger_2 before forming a patch hypothesis.')
        with patch('os.path.exists', return_value=False):
            roles, attack, auxiliary, _ = await role.handle(data, [])
            classified = {**data, 'transaction_roles': roles, 'attack_transactions': attack,
                          'auxiliary_transactions': auxiliary}
            await fault.handle(classified)

        self.assertEqual(data, original)
        self.assertGreater(len(graph), 700000)
        for agent in (role, fault):
            prompt = agent.query.call_args.args[0]
            self.assertLess(len(prompt), len(graph) // 10)
            for tx, tree in traces.items():
                self.assertIn(tx, prompt)
                self.assertTrue(tree in prompt, f'{type(agent).__name__} must retain the full multiline trace')
            for i in range(80):
                self.assertIn(f'edge_{i}: raw_amount={10**24 + i}, decimals=None', prompt)
            self.assertIn("'chain_id': 1", prompt)
            self.assertIn("'chain_id': 56", prompt)
            self.assertEqual(prompt.count(quote['provenance']['history']), 2)
            self.assertIn("{'$ref': 'price_evidence_1'}", prompt)
            self.assertIn("{'$ref': 'price_evidence_2'}", prompt)

    def test_structured_prompt_compaction_round_trips_nested_evidence(self):
        from copy import deepcopy
        from app.attackpilot.utils.prompt_evidence import compact_price_evidence
        quote = {'price': None, 'decimals': None, 'status': 'unavailable', 'chain_id': 1}
        graph = {'edges': [{'raw_amount': '0', 'price_evidence': quote},
                           {'raw_amount': '9007199254740993', 'price_evidence': quote}]}
        balances = {'tokens': [{'decimals': None, 'price_evidence': {**quote, 'chain_id': 56}}]}
        original_graph, original_balances = deepcopy(graph), deepcopy(balances)
        compact_graph, compact_balances, registry = compact_price_evidence(graph, balances)

        def restore(value):
            if isinstance(value, dict):
                if set(value) == {'$ref'}:
                    return registry[value['$ref']]
                return {key: restore(item) for key, item in value.items()}
            return [restore(item) for item in value] if isinstance(value, list) else value

        self.assertEqual(restore(compact_graph), original_graph)
        self.assertEqual(restore(compact_balances), original_balances)
        self.assertEqual(graph, original_graph)
        self.assertEqual(balances, original_balances)
        self.assertEqual(len(registry), 2)

    async def test_detail_cache_is_bound_to_current_facts_and_chain(self):
        agent = self.detail_agent()
        with patch('app.attackpilot.agents.TxDetailAgent.os.path.exists', return_value=False):
            await agent.handle([self.TX])
            agent._load_tx_detail_data.return_value[self.TX]['nonce'] = 2
            await agent.handle([self.TX])
            agent._platform = 'BSC'
            await agent.handle([self.TX])
        keys = [call.kwargs['file_name'] for call in agent.write_summary_to_cache.call_args_list]
        self.assertEqual(len(set(keys)), 3)

    async def test_invalid_detail_cache_regenerates_and_empty_model_output_cannot_succeed(self):
        from app.attackpilot.errors import AgentContractError
        agent = self.detail_agent()
        agent.load_summary_from_cache = Mock(return_value={})
        with patch('app.attackpilot.agents.TxDetailAgent.os.path.exists', return_value=True):
            result = await agent.handle([self.TX])
        self.assertIn('Valid transaction summary', result[0])
        agent.query.assert_awaited_once()
        agent.query = AsyncMock(return_value='  ')
        with patch('app.attackpilot.agents.TxDetailAgent.os.path.exists', return_value=False):
            with self.assertRaises(AgentContractError):
                await agent.handle([self.TX])

    async def test_filter_cannot_drop_candidates_based_on_model_similarity(self):
        from app.attackpilot.agents.FilterAgent import FilterAgent
        tx2 = '0x' + 'e' * 64
        agent = object.__new__(FilterAgent)
        agent.logger = Mock(); agent.name = 'filter'
        agent.query = AsyncMock(return_value=repr([tx2]))
        result = await agent.handle({'transaction_hash_list': [self.TX, tx2],
            'attack_transactions': [self.TX, tx2],
            'trace_tree': {self.TX: '[0] CALL a()', tx2: '[0] CALL b()'}})
        self.assertEqual(result, [tx2, self.TX])
        self.assertTrue(agent.filter_degraded)

    async def test_filter_does_not_query_with_empty_or_failed_trace_evidence(self):
        from app.attackpilot.agents.FilterAgent import FilterAgent
        for trace in ('', 'Error: unavailable', {'unexpected': 'shape'}):
            agent = object.__new__(FilterAgent)
            agent.logger = Mock(); agent.name = 'filter'; agent.query = AsyncMock()
            result = await agent.handle({'transaction_hash_list': [self.TX],
                'attack_transactions': [self.TX], 'trace_tree': {self.TX: trace}})
            self.assertEqual(result, [self.TX])
            self.assertTrue(agent.filter_degraded)
            agent.query.assert_not_awaited()
