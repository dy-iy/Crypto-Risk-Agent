import asyncio
import copy
import json
from typing import Dict, Any, List

import httpx
from openai import APIError

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.prompt.global_memory_prompt import GLOBAL_MEMORY_SP, GLOBAL_MEMORY_UP, GLOBAL_MEMORY_FINAL_UP, MULTI_ATTACK_PART
from app.attackpilot.utils.price import collect_price_evidence
from app.attackpilot.errors import (
    AgentContractError, EvidencePersistenceError, HistoricalReplayContextError,
    HistoricalReplayValidationError, TenderlyAPIError, exception_chain,
)
from app.attackpilot.utils.llm_client import IncompleteCompletionError
from app.attackpilot.utils.agent_contracts import hash_list, memory_update
from app.attackpilot.utils.report_evidence import (
    report_evidence, render_verification_summary, render_applied_patches, sanitize_report_body,
    render_recorded_analysis,
)


class GlobalMemoryAgent(AgentBase):
    def __init__(self, is_multi: bool, dapp_name: str, name: str = "GlobalMemory Administrator",log_callback=None):
        """
        init global memory
        :param is_multi: if multi transaction
        :param dapp_name: DApp name
        :param name: Agent name
        """
        global_memory_sp = GLOBAL_MEMORY_SP.replace("{multi_attack_part}", MULTI_ATTACK_PART if is_multi else "")

        super(GlobalMemoryAgent, self).__init__(name, global_memory_sp, max_turns=2, unique_id=dapp_name,log_callback=log_callback)

        self.global_memory: Dict[str, Any] = {}
        self.report_generation = {"status": "not_run"}

        self._memory_history: List[Dict[str, Any]] = []
        self._max_history_len = 10

        self._protected_keys = {
            "transaction_abnormal_analysis",
            "transaction_roles",
            "transactions_need_analyze",
            "auxiliary_transactions",
            "analyzed_transactions",
            "current_transaction", "market_evidence", "retrieved_knowledge", "investigation_scope"
        }

    def init(self, processed_data: Dict[str, Any]):
        known = processed_data.get('transaction_hash_list') or (
            list(processed_data.get('transactions_need_analyze', [])) + list(processed_data.get('auxiliary_transactions', [])))
        self._transaction_hashes = hash_list(known, known, stage='memory', reason_code='agent_memory_invalid')
        self.global_memory = {
            "transaction_abnormal_analysis": processed_data.get("bug_summary", ""),
            "transaction_roles": processed_data.get("transaction_roles", ""),
            "transactions_need_analyze": processed_data.get("transactions_need_analyze", []),
            "auxiliary_transactions": processed_data.get("auxiliary_transactions", []),
            "investigation_scope": copy.deepcopy(processed_data.get("investigation_scope", {})),
            "retrieved_knowledge": processed_data.get("rag_context", {}),
            "market_evidence": copy.deepcopy(collect_price_evidence(processed_data)),
            "analyzed_transactions": {},
            "current_transaction": None
        }
        self._create_snapshot("Initial State")
        print(f"[{self.name}] Memory initialized.")

    def init_transactions(self, txs_need_analyze: List[str]):
        if not txs_need_analyze:
            print(f"[{self.name}] Warning: No transactions to analyze.")
            return

        txs_need_analyze = hash_list(txs_need_analyze, self._transaction_hashes,
                                    stage='memory', reason_code='agent_memory_invalid', nonempty=True)

        self._create_snapshot("Init Transactions")
        self.global_memory["current_transaction"] = txs_need_analyze[0]
        self.global_memory["transactions_need_analyze"] = txs_need_analyze
        print(f"[{self.name}] Transaction list initialized. Current: {txs_need_analyze[0]}")

    async def update(self, agent_name: str, new_data: Any):
        if isinstance(new_data, dict) and {'fault_report', 'final_trace', 'fix_report'}.issubset(new_data):
            current = self.global_memory.get('current_transaction')
            if current not in self._transaction_hashes:
                raise AgentContractError('memory', 'agent_memory_invalid')
            # This record comes from coordinator-accepted readiness, never the
            # memory model's proposed rewrite. Analyzed does not mean verified.
            self.global_memory['analyzed_transactions'][current] = {
                'insight': copy.deepcopy(new_data['fault_report']),
                'code_patch': copy.deepcopy(new_data['fix_report']), 'status': 'Analyzed',
            }
        prompt = GLOBAL_MEMORY_UP.format(agent=agent_name, new_data=new_data,
                                         current_understanding=self._serialize_memory_for_prompt())
        for attempt in range(2):
            # Infrastructure errors/cancellation are not model shape mistakes.
            llm_response = await self.query(prompt, _format='json')
            try:
                updates = memory_update(llm_response)
                break
            except AgentContractError:
                if attempt:
                    raise
                prompt += ('\nCorrect the memory schema once: global_fault_understanding must be an object; '
                           'thought_process/action_directive strings. Do not change original evidence, '
                           'transaction lists, current_transaction, or analyzed_transactions.')

        self._create_snapshot(f"Update by {agent_name}")

        print(f"[{self.name}] Merging updates from {agent_name}...")
        try:
            self._deep_update(self.global_memory, updates)
        except Exception as e:
            print(f"[{self.name}] Error during deep merge: {e}. Rolling back...")
            self._rollback()
            raise AgentContractError('memory', 'agent_memory_invalid') from e

        if not self._validate_integrity():
            print(f"[{self.name}] Validation failed after update. Rolling back...")
            self._rollback()
            raise AgentContractError('memory', 'agent_memory_invalid')
        else:
            print(f"[{self.name}] Memory updated successfully.")

    async def switch_transaction(self, agent_name: str, switch_data: Dict):
        if not isinstance(switch_data, dict):
            raise AgentContractError('memory', 'agent_memory_invalid')
        current = hash_list([switch_data.get('current_tx')], self._transaction_hashes,
                            stage='memory', reason_code='agent_memory_invalid', nonempty=True)[0]
        target = hash_list([switch_data.get('switch_to')], self._transaction_hashes,
                           stage='memory', reason_code='agent_memory_invalid', nonempty=True)[0]
        if any(not isinstance(switch_data.get(key), str) for key in ('insight', 'code_patch')):
            raise AgentContractError('memory', 'agent_memory_invalid')
        switch_data = {**switch_data, 'current_tx': current, 'switch_to': target}
        await self.update(agent_name, switch_data)

        self._create_snapshot(f"Switch Transaction to {switch_data.get('switch_to')}")

        current_tx = switch_data.get("current_tx")
        insight = switch_data.get("insight")
        code_patch = switch_data.get("code_patch")
        next_tx = switch_data.get("switch_to")

        if "analyzed_transactions" not in self.global_memory:
            self.global_memory["analyzed_transactions"] = {}

        if current_tx:
            if current_tx not in self.global_memory["analyzed_transactions"]:
                self.global_memory["analyzed_transactions"][current_tx] = {}

            tx_record = self.global_memory["analyzed_transactions"][current_tx]
            tx_record["insight"] = insight
            tx_record["code_patch"] = code_patch
            tx_record["status"] = "Analyzed"

        if next_tx:
            self.global_memory["current_transaction"] = next_tx
            print(f"[{self.name}] Switched focus to transaction: {next_tx}")
        else:
            print(f"[{self.name}] Warning: No 'switch_to' transaction provided.")

    async def get_final_result(self, judge_result, current_hypothesis, replay_logs, patches):
        self._check_cancelled()
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError("Task was cancelled")
        evidence = report_evidence(judge_result, replay_logs)
        fault_report = current_hypothesis.get("fault_report", "N/A")
        final_trace = current_hypothesis.get("final_trace", "N/A")
        fix_report = current_hypothesis.get("fix_report", "N/A")

        prompt = GLOBAL_MEMORY_FINAL_UP.format(
            verification_result=json.dumps(evidence, ensure_ascii=False, indent=2),
            applied_patches=patches if isinstance(patches, str) else "No applied patch record.",
            current_understanding=self._serialize_memory_for_prompt(),
            fault_report=fault_report,
            final_trace=final_trace,
            fix_report=fix_report
        )
        try:
            final_report = await self.query(prompt, _format="str")
            self._check_cancelled()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError("Task was cancelled")
            if (not isinstance(final_report, str) or not final_report.strip()
                    or final_report.strip().lower() in {'null', 'none', 'n/a', '{}', '[]'}
                    or final_report.lstrip().startswith(('ERROR', 'RUNTIME_ERROR:', 'FAILED:'))):
                raise AgentContractError('report', 'analysis_report_invalid')
            narrative = sanitize_report_body(final_report)
            if not narrative:
                raise AgentContractError('report', 'analysis_report_invalid')
        except Exception as exc:
            # Cancellation always wins, including a caller cancellation flag
            # set just before an unrelated transport failure is delivered.
            self._check_cancelled()
            causes = exception_chain(exc)
            cancelled = next((cause for cause in causes if isinstance(cause, asyncio.CancelledError)), None)
            if task is not None and task.cancelling():
                raise cancelled or asyncio.CancelledError("Task was cancelled")
            if any(isinstance(cause, (
                EvidencePersistenceError, HistoricalReplayContextError,
                HistoricalReplayValidationError, TenderlyAPIError,
            )) for cause in causes):
                raise
            primary = exc
            unwrapped = set()
            while (type(primary) is RuntimeError and primary.__cause__ is not None
                   and id(primary) not in unwrapped and str(primary) == (
                    f"Agent '{getattr(self, 'name', '')}' API Error: "
                    f"{type(primary.__cause__).__name__} - {primary.__cause__}"
                   )):
                unwrapped.add(id(primary))
                primary = primary.__cause__
            if not (
                isinstance(primary, (APIError, httpx.HTTPError, IncompleteCompletionError, TimeoutError))
                or isinstance(primary, AgentContractError) and primary.reason_code in {
                    "analysis_report_invalid", "agent_output_invalid", "agent_context_budget_exceeded",
                }
            ):
                # Unknown outer failures cannot borrow an earlier timeout to
                # become recoverable. A wrapped user cancellation stays one.
                if cancelled is not None:
                    raise cancelled
                raise
            # Trusted model/transport exceptions may wrap httpcore internals or
            # the CancelledError already converted by asyncio.timeout. They do
            # not imply user cancellation when the task has no pending cancel.
            narrative = render_recorded_analysis(current_hypothesis, self.global_memory)
            if narrative is None:
                raise
            self.report_generation = {
                "status": "evidence_fallback",
                "reason_code": "report_model_output_invalid" if isinstance(exc, AgentContractError)
                and exc.reason_code == "analysis_report_invalid" else "report_model_error",
                "error_type": type(exc).__name__,
            }
            self.logger.warning("最终报告文字整理未完成，已保留本次记录的分析、回放状态和实际补丁。")
        else:
            narrative = "## 根因与路径分析\n\n以下为基于已收集资料的模型分析；文字陈述不替代执行证据，" \
                "补丁效果、验证范围和未完成项目以上方结构化状态为准。\n\n" + narrative
            self.report_generation = {"status": "model", "reason_code": "generated"}

        return "\n\n".join((
            render_verification_summary(evidence),
            narrative,
            render_applied_patches(patches),
        ))

    def _deep_update(self, target: Dict, source: Dict):
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def _create_snapshot(self, reason: str = ""):
        snapshot = copy.deepcopy(self.global_memory)
        self._memory_history.append({
            "data": snapshot,
            "reason": reason
        })
        if len(self._memory_history) > self._max_history_len:
            self._memory_history.pop(0)

    def _rollback(self):
        if not self._memory_history:
            print(f"[{self.name}] Error: No history to rollback.")
            return

        last_snapshot = self._memory_history.pop()
        self.global_memory = copy.deepcopy(last_snapshot['data'])
        print(f"[{self.name}] Rolled back memory to state: {last_snapshot['reason']}")

    def _validate_integrity(self) -> bool:
        missing_keys = [k for k in self._protected_keys if k not in self.global_memory]
        if missing_keys:
            print(f"[{self.name}] Integrity Violation: Missing protected keys: {missing_keys}")
            return False
        return (isinstance(self.global_memory['analyzed_transactions'], dict)
                and isinstance(self.global_memory['transactions_need_analyze'], list)
                and isinstance(self.global_memory['auxiliary_transactions'], list)
                and self.global_memory['current_transaction'] in (None, *self._transaction_hashes)
                and all(tx in self._transaction_hashes and isinstance(record, dict)
                        for tx, record in self.global_memory['analyzed_transactions'].items()))

    def _serialize_memory_for_prompt(self) -> str:
        try:
            return json.dumps(self.global_memory, indent=2, ensure_ascii=False)
        except Exception:
            return str(self.global_memory)
