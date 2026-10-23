import copy
from typing import Dict

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.prompt.task_prompt import INIT_TASK_TREE, TASK_SP, TASK_UP
from app.attackpilot.errors import AgentContractError
from app.attackpilot.utils.agent_contracts import task_plan, trace_tree


class TaskAgent(AgentBase):
    def __init__(self, mcp_client, dapp_name, session_id, name="Task Organizer", log_callback=None):
        super(TaskAgent, self).__init__(name, TASK_SP, max_turns=2, unique_id=dapp_name,log_callback=log_callback)
        self.status = "CONTINUE_DEBUGGING"
        self.thought_process = ""
        self.task_tree = INIT_TASK_TREE
        self.suspicious_functions = []
        self.mcp_client = mcp_client
        self.last_end_result = ""
        self.session_id = session_id

    async def handle(self, global_fault_understanding, patch_feedback):
        trace = trace_tree(await self.mcp_client.call_tool("get_current_tree", self._inject_session({})))
        prompt = TASK_UP.format(
            global_fault_understanding=global_fault_understanding,
            trace=trace,
            patch_feedback=patch_feedback,
            task_tree=self.task_tree
        )
        for attempt in range(2):
            result = await self.query(prompt, _format="json")
            try:
                task_plan(result)
                break
            except AgentContractError:
                if attempt:
                    raise
                prompt += '\nCorrect the task schema once: task_tree must be a nonempty string; status CONTINUE_DEBUGGING or READY_FOR_PATCH; suspicious_functions a list of objects with nonnegative function_index, function_name, score 0..100, and reason.'
        self.task_tree = result.get("task_tree", INIT_TASK_TREE)
        self.suspicious_functions = result.get("suspicious_functions", [])
        self.status = result.get("status", "CONTINUE_DEBUGGING")
        self.thought_process = result.get("thought_process", "")
        return result

    async def end_analyze(self, end_result):
        # The coordinator already owns this hypothesis. No caller consumed the
        # previous extra model response, so retain the local record directly.
        self.last_end_result = copy.deepcopy(end_result)

    def _inject_session(self, args: Dict) -> Dict:
        if not self.session_id:
            raise ValueError(f"[{self.name}] Session ID not initialized. Cannot call MCP tools.")
        return {**args, 'session_id': self.session_id}
