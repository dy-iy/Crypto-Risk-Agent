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


class TraceVerificationPlanReadinessTests(unittest.IsolatedAsyncioTestCase):
    """Synthetic task artifacts exercise both terminal investigation paths offline."""

    def setUp(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from app.attackpilot import settings
        self.temporary = tempfile.TemporaryDirectory(prefix='attackpilot-trace-plan-')
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / 'cache'
        self.cache.mkdir()
        evidence = self.cache / 'observed.json'
        evidence.write_text('{"observed": "synthetic invariant"}', encoding='utf-8')
        self.evidence_digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
        cache_patch = patch.object(settings, 'CACHE_DIR', str(self.cache))
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.tx_a, self.tx_b = '0x' + 'a' * 64, '0x' + 'b' * 64

    @staticmethod
    def tool_call(arguments, call_id='ready'):
        import json
        from types import SimpleNamespace
        return SimpleNamespace(id=call_id, function=SimpleNamespace(
            name='ready_for_patch', arguments=json.dumps(arguments)))

    def agent(self):
        from app.attackpilot.agents.TraceAgent import TraceAgent
        agent = object.__new__(TraceAgent)
        agent.name = 'synthetic trace'; agent.logger = Mock()
        agent.cancellation_checker = lambda: False
        agent.memory = []; agent.tx_list = [self.tx_a, self.tx_b]
        agent.dapp = {'platform': 'Ethereum', 'transaction_hash': agent.tx_list}
        # The verified historical order may differ from submission order.
        agent.processed_data = {'dapp': agent.dapp,
                                'transaction_hash_list': [self.tx_b, self.tx_a]}
        agent.current_tx = self.tx_a; agent.is_init = True
        agent.session_id = 'synthetic'; agent._available_tool_names = None
        agent.get_current_trace = AsyncMock(return_value='[0] CALL synthetic()')
        agent._judge_too_long_trace = Mock(return_value='inspect synthetic evidence')
        agent.query_with_tools = AsyncMock()
        agent.mcp_client = Mock(); agent.mcp_client.call_tool = AsyncMock()
        return agent

    def plan(self):
        return {
            'schema_version': 1, 'network_id': 1,
            'attack_transaction_hashes': [self.tx_a, self.tx_b],
            'authority': {'kind': 'investigation_derived', 'reference': 'Synthetic invariant',
                          'evidence_refs': [{'reference': 'cache/observed.json',
                                             'sha256': self.evidence_digest}]},
            'security_properties': [{
                'id': 'synthetic_balance_bound', 'kind': 'native_balance',
                'account': '0x' + '1' * 40, 'operator': 'delta_lte', 'expected': 0,
                'transaction_hashes': [self.tx_a, self.tx_b],
                'rationale': 'Synthetic task measurement bound'}],
            'normal_regression_cases': [],
        }

    def arguments(self, plan):
        result = {'fault_report': 'Synthetic source misses the observed business check.',
                  'fix_report': {'faulty_functions': [{'trigger_point': {
                      'transaction_hash': self.tx_a, 'index': 0}}]}}
        if plan is not None:
            result['fix_report']['verification_plan'] = plan
        return result

    async def test_invalid_plan_can_be_corrected_in_regular_and_forced_readiness(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                bad = self.plan(); bad['schema_version'] = 2
                good = self.plan()
                agent = self.agent()
                agent.query_with_tools.side_effect = [
                    [self.tool_call(self.arguments(bad), 'bad-plan')],
                    [self.tool_call(self.arguments(good), 'corrected-plan')],
                ]
                result = await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                self.assertEqual(result['reason'], 'READY_FOR_PATCH')
                plan = result['data'][2]['verification_plan']
                self.assertEqual(plan['network_id'], '1')
                self.assertEqual(plan['attack_transaction_hashes'], [self.tx_b, self.tx_a])
                self.assertEqual(plan['normal_regression_cases'], [])
                self.assertEqual(agent.query_with_tools.await_count, 2)
                self.assertIn('schema_version', agent.memory[0]['content'])
                self.assertIn('Invalid verification_plan', agent.memory[0]['content'])
                agent.logger.log_patch_report.assert_called_once()
                agent.mcp_client.call_tool.assert_not_awaited()
                self.assertEqual(good['attack_transaction_hashes'], [self.tx_a, self.tx_b])

    async def test_invalid_authority_digest_and_scope_never_reach_patch_readiness(self):
        from app.attackpilot.errors import AgentContractError
        for forced in (False, True):
            for change in ('authority', 'digest', 'scope', 'chain', 'reference'):
                with self.subTest(forced=forced, change=change):
                    plan = self.plan()
                    if change == 'authority':
                        plan['authority']['kind'] = 'user_declared'
                    elif change == 'digest':
                        plan['authority']['evidence_refs'][0]['sha256'] = '0' * 64
                    elif change == 'scope':
                        plan['attack_transaction_hashes'] = [self.tx_a]
                        plan['security_properties'][0]['transaction_hashes'] = [self.tx_a]
                    elif change == 'chain':
                        plan['network_id'] = 56
                    else:
                        plan['authority']['evidence_refs'][0]['reference'] = 'cache/../observed.json'
                    agent = self.agent()
                    agent.query_with_tools.return_value = [self.tool_call(self.arguments(plan))]
                    with self.assertRaises(AgentContractError):
                        await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                    self.assertEqual(agent.query_with_tools.await_count, 2)
                    self.assertTrue(all('Invalid verification_plan' in item['content']
                                        for item in agent.memory))
                    self.assertNotIn(self.temporary.name, str(agent.memory))
                    agent.logger.log_patch_report.assert_not_called()
                    agent.mcp_client.call_tool.assert_not_awaited()

    async def test_explicit_plan_has_priority_over_conflicting_model_plan(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.agent()
                explicit = self.plan()
                explicit['authority'] = {'kind': 'user_declared', 'reference': 'Synthetic user input',
                                         'evidence_refs': []}
                agent.dapp['verification_plan'] = explicit
                proposal = self.plan(); proposal['network_id'] = 56
                proposal['security_properties'] = []
                agent.query_with_tools.return_value = [self.tool_call(self.arguments(proposal))]
                result = await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                plan = result['data'][2]['verification_plan']
                self.assertEqual(plan['authority']['kind'], 'user_declared')
                self.assertEqual(plan['network_id'], '1')
                self.assertEqual(len(plan['security_properties']), 1)
                self.assertEqual(agent.query_with_tools.await_count, 1)
                self.assertEqual(explicit['attack_transaction_hashes'], [self.tx_a, self.tx_b])

    async def test_missing_plan_is_allowed_without_fabricating_normal_cases(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.agent()
                bad = self.plan(); bad['schema_version'] = 2
                agent.query_with_tools.side_effect = [
                    [self.tool_call(self.arguments(bad))],
                    [self.tool_call(self.arguments(None))],
                ]
                result = await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                self.assertNotIn('verification_plan', result['data'][2])
                self.assertNotIn('normal_regression_cases', result['data'][2])
                self.assertEqual(agent.query_with_tools.await_count, 2)

    async def test_plan_feedback_does_not_increase_existing_round_limits(self):
        from app.attackpilot.errors import AgentContractError
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.agent()
                bad = self.plan(); bad['schema_version'] = 2
                agent.query_with_tools.side_effect = [
                    [self.tool_call(self.arguments(bad))],
                    [self.tool_call(self.arguments(bad))],
                    [self.tool_call(self.arguments(self.plan()))],
                ]
                with self.assertRaises(AgentContractError):
                    await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                self.assertEqual(agent.query_with_tools.await_count, 2)
                agent.logger.log_patch_report.assert_not_called()

    async def test_cancellation_during_plan_correction_propagates(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.agent()
                bad = self.plan(); bad['schema_version'] = 2
                agent.query_with_tools.side_effect = [
                    [self.tool_call(self.arguments(bad))], asyncio.CancelledError(),
                ]
                with self.assertRaises(asyncio.CancelledError):
                    await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                self.assertEqual(agent.query_with_tools.await_count, 2)
                self.assertEqual(len(agent.memory), 1)
                agent.logger.log_patch_report.assert_not_called()
                agent.mcp_client.call_tool.assert_not_awaited()

    async def test_accepted_plan_does_not_swallow_final_evidence_failure(self):
        from app.attackpilot.errors import AgentContractError
        for forced in (False, True):
            with self.subTest(forced=forced):
                agent = self.agent()
                agent.query_with_tools.return_value = [self.tool_call(self.arguments(self.plan()))]
                agent.get_current_trace.side_effect = [
                    '[0] CALL synthetic()', AgentContractError('trace', 'agent_trace_evidence_invalid'),
                ]
                with self.assertRaises(AgentContractError) as raised:
                    await agent.handle({}, 'synthetic tasks', force_terminate=forced)
                self.assertEqual(raised.exception.reason_code, 'agent_trace_evidence_invalid')
                self.assertEqual(agent.query_with_tools.await_count, 1)
                agent.logger.log_patch_report.assert_not_called()
                agent.mcp_client.call_tool.assert_not_awaited()

    def test_prompt_plan_example_is_complete_json_in_both_rendering_paths(self):
        import json
        import re
        from app.attackpilot.prompt.trace_debug_prompt import TRACE_DEBUG_SP, TRACE_DEBUG_FORCE_PATCH_UP
        from app.attackpilot.utils.security_checks import validate_verification_plan
        forced = TRACE_DEBUG_FORCE_PATCH_UP.format(
            global_fault_understanding='{}', trace='[0] CALL synthetic()', task_tree='synthetic tasks')
        for prompt in (TRACE_DEBUG_SP, forced):
            with self.subTest(prompt='forced' if prompt is forced else 'system'):
                example = re.search(r'```json\n(.*?)\n```', prompt, re.S).group(1)
                plan = validate_verification_plan(json.loads(example), network_id=1)
                self.assertEqual(plan['network_id'], '1')
                self.assertEqual(plan['normal_regression_cases'], [])
                self.assertIn('never copy', prompt)
                self.assertNotIn('normal_regression_cases', json.loads(example))
                self.assertIn('This plan verifies only the supplied attack transactions and their security conditions.', prompt)
                self.assertIn('Do not request or add normal-business regression transactions.', prompt)


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


class JudgeScopeReviewTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def agent(verdict):
        from app.attackpilot.agents.JudgeAgent import JudgeAgent
        agent = object.__new__(JudgeAgent)
        agent.cancellation_checker = lambda: False
        agent.init_system_prompt = Mock()
        agent.metrics_collector = Mock()
        agent.unique_id = 'synthetic attack'
        agent.query = AsyncMock(return_value={'verdict': verdict, 'reason': 'model interpretation'})
        return agent

    @staticmethod
    def inputs():
        return {'current_hypothesis': {}, 'replay_logs': {'artifact': 'same recorded execution'},
                'patches': 'actual applied patch', 'real_balance_change': {}}

    @staticmethod
    def state(scope, normal_status, *, verified=True, evidence_version=2):
        return {
            'status': 'verified' if verified else 'unverified', 'scope': scope,
            'evidence_version': evidence_version, 'evidence_validated': verified,
            'next_action': 'complete' if verified else 'collect_missing_evidence',
            'reason': 'machine execution checks',
            'dimensions': {**{key: {'status': 'passed'} for key in
                              ('sequence_replay', 'attack_interception', 'security_properties')},
                           'normal_regression': {'status': normal_status},
                           'profit': {'status': 'unavailable', 'usd': None}},
        }

    async def test_declared_checks_need_one_interpretation_without_changing_model_verdict(self):
        for scope, normal_status in (('declared_attack_chain', 'not_run'),
                                     ('declared_attack_chain_and_normal_cases', 'passed')):
            for verdict in ('UNVERIFIED', 'INEFFECTIVE_PATCH', 'WRONG_ROOT_CAUSE',
                            'BROKEN_LOGIC', 'VERIFIED', None):
                with self.subTest(scope=scope, verdict=verdict):
                    agent = self.agent(verdict)
                    state = self.state(scope, normal_status)
                    inputs = self.inputs()
                    with patch('app.attackpilot.agents.JudgeAgent.adjudicate_patch_verification',
                               return_value=state) as adjudicate:
                        result = await agent.handle(inputs)
                    self.assertEqual(result['verdict'], verdict)
                    self.assertIs(result['verification'], state)
                    self.assertEqual(result['verification']['scope'], scope)
                    self.assertEqual(result['verification']['dimensions']['normal_regression']['status'], normal_status)
                    self.assertEqual(result['evidence_review_attempts'], 1)
                    self.assertEqual(result['analysis_details']['attacker_profit_usd'], None)
                    agent.query.assert_awaited_once()
                    agent.init_system_prompt.assert_not_called()
                    adjudicate.assert_called_once_with(result, inputs['replay_logs'], inputs['patches'])
                    agent.metrics_collector.record_judge_result.assert_called_once_with(
                        case_name='synthetic attack', verdict='VERIFIED', reason='machine execution checks')

    async def test_declared_missing_evidence_is_not_passed_or_repeated_by_model(self):
        for action in ('collect_missing_evidence', 'review_same_evidence'):
            with self.subTest(action=action):
                agent = self.agent('VERIFIED')
                state = self.state('declared_attack_chain', 'not_run', verified=False)
                state['next_action'] = action
                state['dimensions']['security_properties']['status'] = 'unavailable'
                with patch('app.attackpilot.agents.JudgeAgent.adjudicate_patch_verification',
                           return_value=state):
                    result = await agent.handle(self.inputs())
                self.assertEqual(result['verdict'], 'VERIFIED')
                self.assertEqual(result['verification']['status'], 'unverified')
                self.assertEqual(result['evidence_review_attempts'], 1)
                agent.query.assert_awaited_once()
                agent.metrics_collector.record_judge_result.assert_called_once_with(
                    case_name='synthetic attack', verdict='UNVERIFIED', reason='machine execution checks')

    async def test_legacy_review_keeps_its_existing_evidence_protocol(self):
        agent = self.agent('UNVERIFIED')
        agent.query = AsyncMock(side_effect=[{'verdict': 'UNVERIFIED'}, {'verdict': 'VERIFIED'}])
        pending = self.state('recorded_attack_inputs', 'not_run', verified=False, evidence_version=1)
        pending['next_action'] = 'review_same_evidence'
        verified = self.state('recorded_attack_inputs', 'not_run', evidence_version=1)
        inputs = self.inputs()
        with patch('app.attackpilot.agents.JudgeAgent.adjudicate_patch_verification',
                   side_effect=[pending, verified]) as adjudicate:
            result = await agent.handle(inputs)
        self.assertEqual(result['verdict'], 'VERIFIED')
        self.assertEqual(result['evidence_review_attempts'], 2)
        self.assertEqual(adjudicate.call_count, 2)
        agent.init_system_prompt.assert_called_once()
        for call in adjudicate.call_args_list:
            self.assertIs(call.args[1], inputs['replay_logs'])
            self.assertEqual(call.args[2], inputs['patches'])
        agent.metrics_collector.record_judge_result.assert_called_once_with(
            case_name='synthetic attack', verdict='VERIFIED', reason=' ')


class JudgeInterpretationFailurePipelineTests(unittest.IsolatedAsyncioTestCase):
    """Transport failures cannot replace the durable execution decision."""

    async def run_pipeline(self, replay, patches, failure):
        from app.attackpilot.process import analyze
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        from app.attackpilot.utils.verification import verification_state
        hashes = [pair['original_transaction_hash'] for pair in replay['transactions']]
        trace = Mock(token=0)
        trace.get_total_time.return_value = 0
        trace.init_transactions = AsyncMock()
        trace.handle = AsyncMock(return_value={
            'reason': 'READY_FOR_PATCH',
            'data': ['recorded hypothesis', '[0] CALL Vault', {'faulty_functions': []}],
        })
        metrics = Mock()
        data = {'dapp': {'name': 'judge-unavailable-pipeline', 'platform': 'Ethereum'},
                'transactions_need_analyze': hashes, 'transaction_hash_list': hashes, 'balance_change': {}}

        async def deliver(judgement, hypothesis, evidence, applied):
            return render_verification_summary(report_evidence(judgement, evidence))

        with patch.object(analyze, 'GlobalMemoryAgent') as memory_factory, patch.object(
            analyze, 'TaskAgent'
        ) as task_factory, patch.object(analyze, 'FixAgent') as fix_factory, patch.object(
            analyze, 'JudgeAgent'
        ) as judge_factory, patch.object(analyze, 'TOTAL_TURN', 1), patch.object(
            analyze, 'GUIDE_TURN', 1
        ), patch.object(analyze, 'PATCH_TURN', 1):
            memory, tasks = memory_factory.return_value, task_factory.return_value
            fix, judge = fix_factory.return_value, judge_factory.return_value
            for boundary in (memory, tasks, fix, judge):
                boundary.token = 0
                boundary.get_total_time.return_value = 0
            memory.global_memory = {}
            memory.update = AsyncMock()
            memory.get_final_result = AsyncMock(side_effect=deliver)
            tasks.handle = AsyncMock()
            tasks.end_analyze = AsyncMock()
            fix._verification_plan = replay.get('verification_plan')
            fix.verification = verification_state('unverified', stage='replay',
                replay_attempted=True, replay_completed=True)
            fix.handle = AsyncMock(return_value=(True, replay, patches, 1))
            judge.handle = AsyncMock(side_effect=failure)
            runner = analyze.DAppAnalyze(data, trace, {'Ethereum': None}, {'Ethereum': None}, None,
                metrics_collector=metrics,
                enabled_modules=['fault_localization', 'patch_generation', 'patch_verification'])
            report, items = await runner.analyze()
        fix.handle.assert_awaited_once()
        judge.handle.assert_awaited_once()
        memory.get_final_result.assert_awaited_once()
        self.assertIs(items['replay_evidence'], replay)
        self.assertEqual(items['applied_patches'], patches)
        return report, items, memory.get_final_result.call_args.args[0], metrics

    async def declared_replay(self, root, *, secure):
        import hashlib
        from evals.test_attackpilot_failures import StatefulSequenceRegressionTests
        fixture = StatefulSequenceRegressionTests()
        dao, transactions = fixture.make_dao(root, count=2)
        if not secure:
            simulate = dao.bundle_downloader.download.side_effect
            async def unchanged_attack_effect(*, payload):
                results = await simulate(payload=payload)
                if 'state_objects' in payload['simulations'][0]:
                    for raw in results:
                        if raw['transaction']['input'] == '0x8da5cb5b':
                            raw['transaction']['transaction_info']['call_trace']['output'] = f'0x{9:064x}'
                return results
            dao.bundle_downloader.download.side_effect = unchanged_attack_effect
        plan = fixture.plan(transactions, normal=False, probe=True)
        _, replay = await dao.bundle_simulate_txs_in_tenderly(
            transactions, {fixture.address: fixture.runtime}, verification_plan=plan)
        patches = (f'# File: {fixture.address}::Vault.sol\n<<<<<<< SEARCH\n'
                   'uint amount = requested;\n=======\nuint amount = allowed;\n>>>>>>> REPLACE')
        digest = hashlib.sha256(patches.encode()).hexdigest()
        replay.update(applied_patch_sha256=digest,
            required_trigger_transaction_hashes=[item['hash'] for item in transactions],
            patch_attribution={'status': 'unavailable', 'reason_code': 'modified_guard_missing'},
            runtime_integrity={'schema_version': 1, 'status': 'validated',
                'applied_patch_sha256': digest, 'contracts': {fixture.address: {
                    'original_runtime_sha256': hashlib.sha256(bytes.fromhex(fixture.original_runtime[2:])).hexdigest(),
                    'original_compiled_runtime_sha256': hashlib.sha256(bytes.fromhex(fixture.original_runtime[2:])).hexdigest(),
                    'patched_runtime_sha256': hashlib.sha256(bytes.fromhex(fixture.runtime[2:])).hexdigest(),
                    'storage_layout_checked': True, 'immutable_checked': True}}})
        return replay, patches, dao

    async def test_declared_pass_survives_model_transport_and_parse_failure(self):
        import tempfile
        from pathlib import Path
        from app.attackpilot import settings
        from app.attackpilot.errors import AgentContractError
        from app.attackpilot.utils.report_evidence import report_evidence
        for failure in (TimeoutError('synthetic model timeout'),
                        AgentContractError('synthetic invalid JSON', reason_code='agent_output_invalid')):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory(
                prefix='attackpilot-judge-advisory-'
            ) as temp:
                root = Path(temp)
                replay, patches, dao = await self.declared_replay(root, secure=True)
                requests_before = dao.bundle_downloader.download.await_count
                with patch.object(settings, 'CACHE_DIR', root / 'cache'):
                    report, items, judgement, metrics = await self.run_pipeline(replay, patches, failure)
                    presented = report_evidence(judgement, replay)
                self.assertEqual(items['verification']['status'], 'verified')
                self.assertEqual(items['verification']['decision_authority'], 'validated_execution_evidence')
                self.assertIsNone(items['verification']['judge_verdict'])
                self.assertEqual(judgement['interpretation_status'], 'unavailable')
                self.assertNotIn('verdict', judgement)
                self.assertTrue(presented['evidence_trusted'])
                self.assertEqual(presented['verification']['status'], 'verified')
                self.assertIn('补丁验证状态：攻击交易验证通过', report)
                self.assertEqual(dao.bundle_downloader.download.await_count, requests_before)
                metrics.finalize_case.assert_called_once_with('judge-unavailable-pipeline', 'VERIFIED')
                metrics.record_judge_result.assert_called_once_with(
                    case_name='judge-unavailable-pipeline', verdict='VERIFIED',
                    reason=items['verification']['reason'])

    async def test_declared_failed_security_does_not_pass_when_model_is_unavailable(self):
        import tempfile
        from pathlib import Path
        from app.attackpilot import settings
        with tempfile.TemporaryDirectory(prefix='attackpilot-judge-advisory-') as temp:
            root = Path(temp)
            replay, patches, dao = await self.declared_replay(root, secure=False)
            requests_before = dao.bundle_downloader.download.await_count
            with patch.object(settings, 'CACHE_DIR', root / 'cache'):
                _, items, judgement, metrics = await self.run_pipeline(replay, patches, TimeoutError('synthetic timeout'))
            self.assertEqual(items['verification']['status'], 'unverified')
            self.assertEqual(items['verification']['dimensions']['security_properties']['status'], 'failed')
            self.assertFalse(items['verification']['evidence_validated'])
            self.assertIsNone(items['verification']['judge_verdict'])
            self.assertNotEqual(items['verification']['reason_code'], 'judge_error')
            self.assertEqual(judgement['verification']['status'], 'unverified')
            self.assertEqual(dao.bundle_downloader.download.await_count, requests_before)
            metrics.record_judge_result.assert_called_once_with(
                case_name='judge-unavailable-pipeline', verdict='UNVERIFIED',
                reason='声明的安全条件未形成原版违反、补丁版消除的执行对照。')

    async def test_legacy_transport_failure_retains_judge_error(self):
        from evals.test_attackpilot_failures import ReplayEvidenceRegressionTests
        fixture = ReplayEvidenceRegressionTests()
        fixture.setUp()
        _, items, judgement, metrics = await self.run_pipeline(
            fixture.report(), fixture.patches, TimeoutError('synthetic timeout'))
        self.assertEqual(items['verification']['status'], 'error')
        self.assertEqual(items['verification']['reason_code'], 'judge_error')
        self.assertEqual(judgement['verdict'], 'UNVERIFIED')
        metrics.record_judge_result.assert_not_called()


class DeclaredVerificationReportTests(unittest.TestCase):
    """Presentation consumes coordinator envelopes; execution is tested separately."""

    def envelope(self, *, with_normal=True):
        import hashlib
        from app.attackpilot.utils.security_checks import validate_verification_plan, plan_digest
        from app.attackpilot.utils.verification import VERIFICATION_POLICY_VERSION, replay_evidence_digest
        attack, normal, account = '0x' + 'a' * 64, '0x' + 'b' * 64, '0x' + 'c' * 40
        plan = validate_verification_plan({
            'schema_version': 1, 'network_id': '1', 'attack_transaction_hashes': [attack],
            'authority': {'kind': 'user_declared', 'reference': 'synthetic business contract', 'evidence_refs': []},
            'security_properties': [{'id': 'funds', 'kind': 'native_balance', 'account': account,
                'operator': 'delta_lte', 'expected': '10', 'rationale': 'bounded withdrawal',
                'transaction_hashes': [attack]}],
            'normal_regression_cases': [{'id': 'normal', 'transaction_hashes': [normal], 'assertions': [
                {'id': 'balance', 'kind': 'native_balance', 'account': account,
                 'operator': 'matches_control', 'rationale': 'normal withdrawal preserved'}]}],
        })
        if not with_normal:
            plan['normal_regression_cases'] = []
        patches = 'synthetic actual patch record'
        replay = {'schema_version': 2, 'scope': 'sequential_attack_and_regression', 'status': 'completed',
                  'applied_patch_sha256': hashlib.sha256(patches.encode()).hexdigest(),
                  'verification_plan': plan, 'verification_plan_sha256': plan_digest(plan)}
        state = {'schema_version': 2, 'evidence_version': 2,
                 'verification_policy_version': VERIFICATION_POLICY_VERSION,
                 'scope': 'declared_attack_chain_and_normal_cases' if with_normal else 'declared_attack_chain',
                 'stage': 'judge', 'status': 'verified',
                 'judge_verdict': 'VERIFIED', 'evidence_validated': True, 'execution_evidence_validated': True,
                 'replay_attempted': True, 'replay_completed': True,
                 'applied_patch_sha256': replay['applied_patch_sha256'],
                 'replay_evidence_sha256': replay_evidence_digest(replay),
                 'verification_plan_sha256': plan_digest(plan),
                 'coverage': {'mode': 'sequential_attack_and_regression', 'modified_addresses': [account],
                              'sequence_replay_verified': True},
                 'dimensions': {key: {'status': 'passed'} for key in
                                ('sequence_replay', 'attack_interception', 'security_properties', 'normal_regression')}}
        if not with_normal:
            state['dimensions']['normal_regression'] = {'status': 'not_run',
                'reason_code': 'normal_regression_cases_missing', 'checks': []}
        return state, replay, patches

    def test_attack_scope_preserves_verified_status_without_claiming_normal_coverage(self):
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        from app.attackpilot.store import public_task
        state, replay, patches = self.envelope(with_normal=False)
        evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
        self.assertTrue(evidence['evidence_trusted'])
        self.assertEqual(evidence['verification']['scope'], 'declared_attack_chain')
        self.assertEqual(evidence['verification']['dimensions']['normal_regression']['status'], 'not_run')
        text = render_verification_summary(evidence)
        self.assertIn('| 验证范围 | 本次攻击交易及声明的安全条件 |', text)
        self.assertNotRegex(text, '正常功能|正常业务')
        task = {'is_demo': False, 'result': {'verification': state, 'replay_evidence': replay,
                                          'applied_patches': patches}}
        self.assertEqual(public_task(task)['result']['verification']['status'], 'verified')

    def test_attack_scope_still_requires_all_attack_dimensions(self):
        from app.attackpilot.utils.report_evidence import report_evidence
        for dimension in ('sequence_replay', 'attack_interception', 'security_properties'):
            state, replay, _ = self.envelope(with_normal=False)
            state['dimensions'][dimension]['status'] = 'unavailable'
            with self.subTest(dimension=dimension):
                evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
                self.assertFalse(evidence['evidence_trusted'])
                self.assertEqual(evidence['verification']['status'], 'unverified')

    def test_declared_normal_cases_cannot_be_skipped_by_changing_scope(self):
        from app.attackpilot.utils.report_evidence import report_evidence
        for with_normal in (False, True):
            state, replay, _ = self.envelope(with_normal=with_normal)
            state['scope'] = 'declared_attack_chain' if with_normal else 'declared_attack_chain_and_normal_cases'
            with self.subTest(with_normal=with_normal):
                evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
                self.assertFalse(evidence['evidence_trusted'])
                self.assertEqual(evidence['verification']['status'], 'unverified')

    def test_complete_envelope_renders_attack_dimensions_and_no_invented_profit(self):
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        state, replay, _ = self.envelope()
        evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
        self.assertTrue(evidence['evidence_trusted'])
        self.assertEqual(evidence['verification']['dimensions']['profit'], {'status': 'unavailable', 'usd': None})
        text = render_verification_summary(evidence)
        self.assertIn('| 整条攻击链顺序回放 | 通过 |', text)
        self.assertIn('| 资金、权限与状态条件 | 通过 |', text)
        self.assertIn('| 验证范围 | 本次攻击交易及声明的安全条件 |', text)
        self.assertNotRegex(text, '正常功能|正常业务')
        self.assertNotIn('各笔回放不传递状态', text)

    def test_plan_and_replay_mutations_revoke_complete_report(self):
        from copy import deepcopy
        from app.attackpilot.utils.report_evidence import report_evidence
        for change in ('plan', 'digest', 'policy', 'scope', 'execution', 'normal', 'sequence'):
            state, replay, _ = self.envelope()
            state, replay = deepcopy(state), deepcopy(replay)
            if change == 'plan': replay['verification_plan']['security_properties'][0]['expected'] = '100000'
            elif change == 'digest': state['verification_plan_sha256'] = '0' * 64
            elif change == 'policy': state['verification_policy_version'] = 2
            elif change == 'scope': state['scope'] = 'attack_path_only'
            elif change == 'execution': state['execution_evidence_validated'] = False
            elif change == 'normal': state['dimensions']['normal_regression']['status'] = 'not_run'
            elif change == 'sequence': state['coverage']['sequence_replay_verified'] = False
            with self.subTest(change=change):
                evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
                self.assertFalse(evidence['evidence_trusted'])
                self.assertEqual(evidence['verification']['status'], 'unverified')

    def test_recorded_normal_failure_preserves_status_without_an_extra_report_item(self):
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        state, replay, _ = self.envelope()
        state.update(status='unverified', evidence_validated=False, reason_code='normal_regression_failed')
        state['dimensions']['normal_regression'] = {'status': 'failed', 'checks': [{'case_id': 'normal'}]}
        evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
        self.assertFalse(evidence['evidence_trusted'])
        self.assertEqual(evidence['verification']['dimensions']['normal_regression']['status'], 'failed')
        text = render_verification_summary(evidence)
        self.assertEqual(evidence['verification']['status'], 'unverified')
        self.assertIn('| 原因代码 | normal_regression_failed |', text)
        self.assertNotRegex(text, '正常功能|正常业务')
        evidence['verification']['dimensions']['normal_regression']['checks'].append({'case_id': 'other'})
        self.assertEqual(len(state['dimensions']['normal_regression']['checks']), 1)

    def test_public_task_binds_the_actual_patch_record_for_declared_scope(self):
        from app.attackpilot.store import public_task
        state, replay, patches = self.envelope()
        task = {'is_demo': False, 'result': {'verification': state, 'replay_evidence': replay,
                                          'applied_patches': patches}}
        self.assertEqual(public_task(task)['result']['verification']['status'], 'verified')
        task['result']['applied_patches'] = 'different applied patch'
        normalized = public_task(task)['result']['verification']
        self.assertEqual(normalized['status'], 'unverified')
        self.assertFalse(normalized['execution_evidence_validated'])
        self.assertEqual(normalized['dimensions']['normal_regression']['status'], 'unavailable')


class NativeProfitReportTests(unittest.TestCase):
    """Display boundaries consume amounts bound to the actual replay envelope."""

    def native_report(self, *, network='1', original=(3471046840896039542, 14600505729854944540),
                      patched=(3471046840896039542, 3465240771829121624)):
        from app.attackpilot.utils.native_profit import extract_native_balance_change
        from app.attackpilot.utils.security_checks import plan_digest
        from app.attackpilot.utils.verification import replay_evidence_digest
        state, replay, patches = DeclaredVerificationReportTests().envelope(with_normal=False)
        account, tx_hash = '0x' + '1' * 40, replay['verification_plan']['attack_transaction_hashes'][0]
        replay['verification_plan']['network_id'] = network
        replay['verification_plan_sha256'] = plan_digest(replay['verification_plan'])
        state['verification_plan_sha256'] = replay['verification_plan_sha256']
        pair = {'original_transaction_hash': tx_hash, 'context': {'from': account, 'network_id': network}}
        for role, balances, digest in (('control', original, 'c' * 64), ('patched', patched, 'd' * 64)):
            shared = {'from': account, 'network_id': network, 'status': True, 'gas_used': 21000}
            raw = {'simulation': dict(shared), 'transaction': {**shared, 'transaction_info': {
                'balance_diff': [{'address': account, 'original': str(balances[0]), 'dirty': str(balances[1])}]}}}
            pair[role] = {'completed': True, 'status': 'success', 'artifact': {'sha256': digest},
                          'native_balance_change': extract_native_balance_change(raw)}
        replay['transactions'] = [pair]
        state['replay_evidence_sha256'] = replay_evidence_digest(replay)
        return state, replay, patches

    def test_report_and_public_api_render_exact_native_comparison_without_usd_or_normal_test(self):
        from app.attackpilot.store import public_task
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        state, replay, patches = self.native_report()
        # Model-supplied profit values do not override recorded native balances.
        state['dimensions']['profit'] = {'status': 'available', 'usd': 9999999}
        evidence = report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay)
        profit = evidence['verification']['dimensions']['profit']
        self.assertEqual(profit['status'], 'available')
        self.assertIsNone(profit['usd'])
        self.assertEqual(profit['transactions'][0]['control']['delta_wei'], '11129458888958904998')
        text = render_verification_summary(evidence)
        self.assertIn('原版 +11.129458888958904998 ETH → 补丁 -0.005806069066917918 ETH', text)
        self.assertIn('余额净变化已含 gas，逐笔列示', text)
        self.assertIn(replay['transactions'][0]['context']['from'], text)
        self.assertIn(replay['transactions'][0]['original_transaction_hash'], text)
        self.assertNotRegex(text, r'正常功能|正常业务|9999999|USD')
        api = public_task({'is_demo': False, 'result': {'verification': state, 'replay_evidence': replay,
                                                     'applied_patches': patches}})
        self.assertEqual(api['result']['verification']['dimensions']['profit'], profit)

    def test_bnb_zero_and_one_wei_remain_exact(self):
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        state, replay, _ = self.native_report(network='56', original=(0, 1), patched=(0, 0))
        text = render_verification_summary(report_evidence({'verdict': 'VERIFIED', 'verification': state}, replay))
        self.assertIn('原版 +0.000000000000000001 BNB → 补丁 0 BNB', text)
        self.assertNotIn('ETH', text)

    def test_partial_and_unresolved_attack_verdict_preserve_only_measured_values(self):
        from app.attackpilot.utils.verification import replay_evidence_digest
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        state, replay, _ = self.native_report()
        state.update(status='unverified', evidence_validated=False, judge_verdict='UNVERIFIED', reason_code='judge_unresolved')
        evidence = report_evidence({'verdict': 'UNVERIFIED', 'verification': state}, replay)
        self.assertEqual(evidence['verification']['status'], 'unverified')
        self.assertEqual(evidence['verification']['dimensions']['profit']['status'], 'available')
        replay['transactions'][0]['patched'] = {'completed': False, 'status': 'not_executed',
                                              'reason_code': 'sequence_stopped_after_revert'}
        state['replay_evidence_sha256'] = replay_evidence_digest(replay)
        evidence = report_evidence({'verdict': 'UNVERIFIED', 'verification': state}, replay)
        self.assertEqual(evidence['verification']['dimensions']['profit']['status'], 'partial')
        text = render_verification_summary(evidence)
        self.assertIn('+11.129458888958904998 ETH | 未执行 |', text)
        self.assertNotIn('补丁 0 ETH', text)

    def test_profit_binding_and_actual_patch_record_are_required(self):
        from copy import deepcopy
        from app.attackpilot.store import public_task
        from app.attackpilot.utils.report_evidence import report_evidence
        for mutation in ('digest', 'execution', 'changed_replay', 'patch'):
            state, replay, patches = self.native_report()
            if mutation == 'digest':
                state['replay_evidence_sha256'] = '0' * 64
            elif mutation == 'execution':
                state['execution_evidence_validated'] = False
            elif mutation == 'changed_replay':
                replay['transactions'][0]['control']['native_balance_change']['delta_wei'] = '9999999'
            else:
                patches = 'different applied patch'
            with self.subTest(mutation=mutation):
                normalized = public_task({'is_demo': False, 'result': {
                    'verification': deepcopy(state), 'replay_evidence': replay, 'applied_patches': patches}})
                self.assertEqual(normalized['result']['verification']['dimensions']['profit'],
                                 {'status': 'unavailable', 'usd': None})


class DeclaredTraceReachabilityTests(unittest.TestCase):
    """An unknown parsed path cannot prove that modified code was absent."""

    account = '0x' + 'c' * 40
    other = '0x' + 'd' * 40

    def setUp(self):
        import tempfile
        from pathlib import Path
        from app.attackpilot import settings
        from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore
        temporary = tempfile.TemporaryDirectory(prefix='attackpilot-trace-gate-')
        self.addCleanup(temporary.cleanup)
        cache = Path(temporary.name) / 'cache'
        cache_patch = patch.object(settings, 'CACHE_DIR', str(cache))
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.store = PatchReplayEvidenceStore(cache)

    def fixture(self, traces):
        import hashlib
        from app.attackpilot.utils.patch_replay import execution_summary
        from app.attackpilot.utils.security_checks import (
            extract_security_observations, plan_digest, validate_verification_plan,
        )
        hashes = [f'0x{index + 1:064x}' for index in range(len(traces))]
        plan = validate_verification_plan({
            'schema_version': 1, 'network_id': '1', 'attack_transaction_hashes': hashes,
            'authority': {'kind': 'user_declared', 'reference': 'offline trace regression',
                          'evidence_refs': []},
            'security_properties': [{'id': 'vault-loss', 'kind': 'native_balance',
                'account': self.account, 'operator': 'delta_gte', 'expected': '-1',
                'rationale': 'At most one raw unit leaves the vault.',
                'transaction_hashes': [hashes[0]]}], 'normal_regression_cases': [],
        })
        patches = (f'# File: {self.account}::Vault.sol\n<<<<<<< SEARCH\n'
                   'uint amount = requested;\n=======\nuint amount = allowed;\n>>>>>>> REPLACE')
        patch_hash = hashlib.sha256(patches.encode()).hexdigest()
        pairs = []
        for index, (tx_hash, trace) in enumerate(zip(hashes, traces)):
            pair = {'original_transaction_hash': tx_hash, 'sequence_index': index,
                    'context': {'network_id': '1'}}
            for role, after in (('control', 0), ('patched', 9)):
                status = {'status': True, 'gas_used': 21000}
                raw = {'simulation': dict(status), 'transaction': {**status, 'transaction_info': {
                    'logs': [], 'asset_changes': [], 'state_diff': [],
                    'balance_diff': [{'address': self.account, 'original': '10', 'dirty': str(after)}],
                    'call_trace': {'type': 'CALL', 'to': self.account, 'input': '0x12345678',
                                   'output': '0x', 'status': True, 'calls': []}}}}
                artifact = self.store.persist({'role': role, 'transaction_hash': tx_hash}, raw,
                                              role=role, original_hash=tx_hash)
                execution = execution_summary(raw, artifact, [self.account])
                execution['security_observations'] = extract_security_observations(
                    raw, artifact, plan, transaction_hash=tx_hash)
                if role == 'patched':
                    execution['trace'] = trace
                pair[role] = execution
            pairs.append(pair)
        return patches, {'schema_version': 2, 'scope': 'sequential_attack_and_regression',
            'status': 'completed', 'transactions': pairs,
            'verification_plan': plan, 'verification_plan_sha256': plan_digest(plan),
            'required_trigger_transaction_hashes': hashes, 'patched_addresses': [self.account],
            'applied_patch_sha256': patch_hash,
            'runtime_integrity': {'status': 'validated', 'applied_patch_sha256': patch_hash,
                'contracts': {self.account: {'storage_layout_checked': True, 'immutable_checked': True,
                    'patched_runtime_sha256': '1' * 64, 'original_runtime_sha256': '2' * 64,
                    'original_compiled_runtime_sha256': '3' * 64}}}}

    def adjudicate(self, traces):
        from app.attackpilot.utils.verification import adjudicate_patch_verification
        patches, report = self.fixture(traces)
        # Real artifact-backed security measurements remain active. Only the
        # separately tested sequence request validator is outside this gate test.
        with patch('app.attackpilot.utils.patch_replay.validate_sequential_evidence',
                   return_value={'status': 'validated'}):
            return adjudicate_patch_verification({'verdict': 'VERIFIED'}, report, patches)

    def complete(self, target):
        return {'available': True, 'complete': True, 'call_targets_complete': True,
                'call_targets': [target], 'issues': [], 'issue_codes': []}

    def assert_unknown_path(self, trace, code):
        result = self.adjudicate([trace])
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['reason_code'], code)
        self.assertEqual(result['next_action'], 'collect_missing_evidence')
        self.assertTrue(result['terminal'])
        self.assertTrue(result['execution_evidence_validated'])
        self.assertNotEqual(result['next_action'], 'select_trigger_transactions')
        return result

    def test_missing_or_incomplete_call_targets_are_unknown_instead_of_absent(self):
        for trace in (None, {}, {'available': False},
                      {**self.complete(self.other), 'complete': False},
                      {**self.complete(self.other), 'call_targets_complete': False},
                      {**self.complete(self.other), 'call_targets': []}):
            with self.subTest(trace=trace):
                self.assert_unknown_path(trace, 'patched_trace_unavailable')

    def test_invalid_structure_or_status_keeps_a_precise_reason(self):
        for code in ('invalid_root', 'invalid_node', 'invalid_call_target',
                     'invalid_status', 'status_conflict', 'invalid_children'):
            for field in ('issues', 'issue_codes'):
                with self.subTest(code=code, field=field):
                    diagnostics = [{'code': code}] if field == 'issues' else [code]
                    self.assert_unknown_path({'available': True, 'complete': False,
                        'call_targets_complete': False, 'call_targets': [self.other],
                        field: diagnostics}, 'patched_trace_invalid')

    def test_unknown_provider_nodes_request_parser_review_instead_of_new_attack_hashes(self):
        for code in ('unsupported_node_type', 'unrecognized_untyped_node'):
            with self.subTest(code=code):
                result = self.assert_unknown_path({'available': True, 'complete': False,
                    'call_targets_complete': False, 'call_targets': [self.account],
                    'issues': [{'code': code}]}, 'patched_trace_format_unsupported')
                self.assertIn('已有记录', result['reason'])

    def test_only_complete_disjoint_paths_select_different_trigger_transactions(self):
        result = self.adjudicate([self.complete(self.other), self.complete(self.other)])
        self.assertEqual(result['reason_code'], 'modified_code_not_reached')
        self.assertEqual(result['next_action'], 'select_trigger_transactions')
        self.assertFalse(result['terminal'])

    def test_any_unknown_path_prevents_a_disjoint_path_from_proving_absence(self):
        unknowns = [None, {'issues': [{'code': 'unsupported_node_type'}]},
                    {'issue_codes': ['invalid_status']}]
        for unknown, expected in zip(unknowns, ('patched_trace_unavailable',
                'patched_trace_format_unsupported', 'patched_trace_invalid')):
            with self.subTest(expected=expected):
                result = self.adjudicate([self.complete(self.other), unknown])
                self.assertEqual(result['reason_code'], expected)
                self.assertEqual(result['next_action'], 'collect_missing_evidence')

    def test_mixed_unknown_reasons_preserve_invalid_then_unsupported_priority(self):
        unsupported = {'issues': [{'code': 'unsupported_node_type'}]}
        invalid = {'issue_codes': ['status_conflict']}
        for traces in ([None, unsupported, invalid], [invalid, unsupported, None]):
            self.assertEqual(self.adjudicate(traces)['reason_code'], 'patched_trace_invalid')
        self.assertEqual(self.adjudicate([None, unsupported])['reason_code'],
                         'patched_trace_format_unsupported')

    def test_complete_modified_target_keeps_existing_success_even_with_another_unknown_path(self):
        for traces in ([self.complete(self.account)], [self.complete(self.account), None]):
            with self.subTest(count=len(traces)):
                result = self.adjudicate(traces)
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['reason_code'], 'declared_attack_chain_verified')
                self.assertEqual(result['dimensions']['security_properties']['status'], 'passed')


class DeclaredPatchTargetFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_functions_at_one_call_site_reach_generation_for_the_resolved_owner(self):
        from app.attackpilot.daos.contract import ContractCompileItem
        from evals.test_attackpilot_failures import PatchCompilerRegressionTests
        fixture = PatchCompilerRegressionTests()
        agent = fixture.agent()
        source = 'pragma solidity ^0.8.0; contract Vault { function alpha() external {} function beta() external {} }'
        observed = {'Vault.alpha()': 4, 'Vault.beta()': 5}
        calls = []

        async def resolved_source(name, arguments):
            self.assertEqual(name, 'get_patch_items')
            calls.append(dict(arguments))
            expected = arguments['expected_function']
            return {'address': fixture.address, 'file_index': 0, 'contract_name': 'Vault',
                    'compiler_version': fixture.version, 'optimizations_used': False,
                    'optimization_runs': 200, 'contract_info': [{'id': 0, 'path': 'Vault.sol', 'source': source}],
                    'resolved_trigger_index': observed[expected],
                    'source_target': {'status': 'resolved', 'expected_function': expected},
                    'source_mapping': {'method': 'compiler_ast_observed_function', 'file_index': 0}}

        agent.mcp_client.call_tool.side_effect = resolved_source
        original = ContractCompileItem(fixture.address, '0x6000', {}, [],
                                       storage_layout={'storage': [], 'types': {}})
        agent._load_compile_result = AsyncMock(return_value={fixture.address: original})
        agent._load_runtime_bytecode = AsyncMock(return_value={fixture.address: '0x6000'})
        agent.query = AsyncMock(side_effect=asyncio.CancelledError('Stop after the preflight passes'))
        report = {'fix_report': {'faulty_functions': [
            {'function_name': name, 'trigger_point': {'transaction_hash': fixture.transaction_hash, 'index': 0}}
            for name in observed]}}
        with self.assertRaises(asyncio.CancelledError):
            await agent.handle(report)
        self.assertEqual([call['expected_function'] for call in calls], list(observed))
        self.assertTrue(all(call['faulty_index'] == fixture.transaction_hash + '::0' for call in calls))
        self.assertEqual(set(agent._load_compile_result.await_args.args[0]), {fixture.address})
        agent._load_runtime_bytecode.assert_awaited_once_with([fixture.address])
        agent.query.assert_awaited_once()
        self.assertEqual(agent._patch_trigger_transactions, {fixture.address: {fixture.transaction_hash}})
        prompt = agent.query.await_args.args[0]
        for index in observed.values():
            self.assertIn(fixture.transaction_hash + f'::{index}', prompt)
        self.assertEqual([item['resolved_trigger'] for item in agent.verification['source_target_resolutions']],
                         [fixture.transaction_hash + f'::{index}' for index in observed.values()])
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 1)
        agent.run_patch_verification_from_tenderly.assert_not_awaited()

    async def test_unresolved_declared_function_stops_before_compilation_or_generation(self):
        from evals.test_attackpilot_failures import PatchCompilerRegressionTests
        fixture = PatchCompilerRegressionTests()
        agent = fixture.agent()
        diagnostic = {'status': 'unresolved', 'reason_code': 'source_target_unresolved',
                      'expected_function': 'Vault.unobserved()'}
        agent.mcp_client.call_tool.return_value = {'source_target': diagnostic}
        agent._load_compile_result = AsyncMock(side_effect=AssertionError('Wrong contract must not be compiled'))
        result = await agent.handle({'fix_report': {'faulty_functions': [{
            'function_name': 'Vault.unobserved()',
            'trigger_point': {'transaction_hash': fixture.transaction_hash, 'index': 0}}]}})
        self.assertFalse(result[0])
        self.assertEqual(agent.verification['reason_code'], 'unmappable_patch_target')
        self.assertEqual(agent.verification['source_target_diagnostic'], diagnostic)
        self.assertEqual(agent.verification['patch_generation_budget']['requests_used'], 0)
        agent._load_compile_result.assert_not_awaited()
        agent._load_runtime_bytecode.assert_not_awaited()
        agent.query.assert_not_awaited()


class SequenceFailureDeliveryTests(unittest.TestCase):
    def test_original_sequence_failure_keeps_location_and_both_receipt_differences(self):
        from copy import deepcopy
        from app.attackpilot.agents.FixAgent import FixAgent
        from app.attackpilot.errors import HistoricalReplayValidationError
        from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary
        tx_hash = '0x' + '9' * 64
        diagnostic = {
            'schema_version': 1, 'role': 'control', 'sequence_index': 1,
            'transaction_hash': tx_hash, 'field': 'sequence.transaction.receipt',
            'error_code': 'execution_mismatch',
            'state_base': {'block_number': 300, 'transaction_index': 5},
            'execution_position': {'block_number': 303, 'transaction_index': 8},
            'receipt_comparison': {
                'expected': {'status': 1, 'gas_used': 40000, 'log_count': 2,
                             'ordered_logs_sha256': 'a' * 64},
                'simulation': {'status': 1, 'gas_used': 52000},
                'transaction': {'status': 1, 'gas_used': 52000, 'log_count': 2,
                                'ordered_logs_sha256': 'b' * 64},
                'status_match': True, 'gas_match': False, 'events_match': False,
            },
        }
        exc = HistoricalReplayValidationError('inconsistent', 'execution_mismatch',
                                              details={'field': diagnostic['field']})
        exc.sequence_validation_diagnostic = diagnostic
        exc.replay_attempted = True
        exc.replay_evidence = {'schema_version': 2, 'scope': 'sequential_attack_and_regression',
                               'status': 'incomplete', 'transactions': [],
                               'validation_failure': deepcopy(diagnostic)}
        agent = object.__new__(FixAgent)
        result = agent._stop_error(exc, 'replay', 'replay_service_error', patches='saved patch')
        self.assertFalse(result[0])
        self.assertIs(result[1], exc.replay_evidence)
        self.assertEqual(result[2], 'saved patch')
        self.assertEqual(agent.verification['status'], 'blocked')
        self.assertEqual(agent.verification['reason_code'], 'historical_sequence_result_mismatch')
        self.assertTrue(agent.verification['replay_attempted'])
        self.assertFalse(agent.verification['replay_completed'])
        self.assertFalse(agent.verification['retryable'])
        self.assertEqual(agent.verification['next_action'], 'restore_historical_sequence_context')
        self.assertEqual(agent.verification['sequence_validation_diagnostic'], diagnostic)
        summary = render_verification_summary(report_evidence(
            {'verification': agent.verification}, exc.replay_evidence))
        for value in (tx_hash, '第 2 笔', '历史回执 40000；连续回放 52000',
                      '原版历史事件对照 | 不一致', '尚不能判断补丁效果'):
            self.assertIn(value, summary)
        diagnostic['receipt_comparison']['events_match'] = True
        self.assertFalse(agent.verification['sequence_validation_diagnostic']['receipt_comparison']['events_match'])

    def test_identity_and_patched_failures_do_not_become_original_sequence_result_mismatches(self):
        from app.attackpilot.agents.FixAgent import FixAgent
        from app.attackpilot.errors import HistoricalReplayValidationError
        for role, code, diagnostic in (
            ('control', 'context_mismatch', True),
            ('patched', 'execution_mismatch', True),
            ('control', 'execution_mismatch', False),
        ):
            with self.subTest(role=role, code=code, diagnostic=diagnostic):
                exc = HistoricalReplayValidationError('inconsistent', code,
                                                      details={'field': 'sequence.transaction.receipt'})
                if diagnostic:
                    exc.sequence_validation_diagnostic = {'schema_version': 1, 'role': role}
                agent = object.__new__(FixAgent)
                agent._stop_error(exc, 'replay', 'replay_service_error')
                self.assertEqual(agent.verification['reason_code'], 'baseline_inconsistent')
                self.assertNotIn('next_action', agent.verification)
