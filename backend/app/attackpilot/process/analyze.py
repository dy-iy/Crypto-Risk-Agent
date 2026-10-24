import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional

from app.attackpilot.agents.FixAgent import FixAgent
from app.attackpilot.agents.GlobalMemoryAgent import GlobalMemoryAgent
from app.attackpilot.agents.JudgeAgent import JudgeAgent
from app.attackpilot.agents.TaskAgent import TaskAgent
from app.attackpilot.agents.TraceAgent import TraceAgent
from app.attackpilot.settings import TOTAL_TURN, GUIDE_TURN, PATCH_TURN
from app.attackpilot.utils.bucket import AsyncItemBucket
from app.attackpilot.utils.patch_quality_metrics import PatchQualityMetrics
from app.attackpilot.utils.rag_context import build_rag_query_from_dapp, retrieve_rag_context
from app.attackpilot.errors import failure_message
from app.attackpilot.utils.verification import adjudicate_patch_verification, patch_execution_state, verification_state
from app.attackpilot.utils.report_evidence import report_evidence, render_verification_summary


def investigation_verification_context(processed_data):
    """Expose only this task's revalidated original artifacts as citable evidence."""
    from app.attackpilot import settings
    from app.attackpilot.errors import HistoricalReplayValidationError
    from app.attackpilot.utils.patch_replay import PatchReplayEvidenceStore
    from app.attackpilot.utils.replay_validation import validate_simulated_transaction
    from app.attackpilot.utils.security_checks import MAX_EVIDENCE_BYTES

    dapp = processed_data.get('dapp') or {}
    known = processed_data.get('transaction_hash_list') or dapp.get('transaction_hash') or []
    details = processed_data.get('transaction_to_detail') or {}
    chain_id = settings.PLATFORM_TO_CHAIN_ID.get(dapp.get('platform'))
    root = Path(settings.CACHE_DIR)
    result = {'explicit_verification_plan': deepcopy(dapp.get('verification_plan',
                                                processed_data.get('verification_plan'))),
              'investigation_evidence_index': [], 'unavailable_transaction_hashes': [],
              'authority': 'Evidence references only; no business or security assertion is established by this index.'}
    if not isinstance(known, list) or not isinstance(details, dict) or chain_id is None:
        return result

    def safe_bytes(relative, limit=MAX_EVIDENCE_BYTES):
        candidate = root / relative
        cursor = candidate
        while cursor != root.parent:
            if cursor.is_symlink():
                raise ValueError('Task evidence path contains a symbolic link')
            cursor = cursor.parent
        if not candidate.is_file() or candidate.stat().st_size > limit:
            raise ValueError('Task evidence file is unavailable')
        with candidate.open('rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Task evidence file exceeds the size limit')
        return data

    for transaction_hash in known[:50]:
        if not isinstance(transaction_hash, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', transaction_hash):
            continue
        transaction_hash = transaction_hash.lower()
        detail = details.get(transaction_hash)
        baseline = detail.get('baseline_validation') if isinstance(detail, dict) else None
        simulation_id = baseline.get('simulation_id') if isinstance(baseline, dict) else None
        try:
            if (not isinstance(baseline, dict) or baseline.get('status') != 'validated'
                    or baseline.get('method') != 'rpc_receipt_vs_tenderly_original_replay'
                    or baseline.get('original_transaction_hash') != transaction_hash
                    or baseline.get('network_id') != str(chain_id)
                    or not isinstance(simulation_id, str)
                    or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', simulation_id)):
                raise ValueError('Original replay provenance is unavailable')
            raw_transaction = json.loads(safe_bytes(Path('tx_detail/tx') / f'{transaction_hash}.json'))
            safe_bytes(Path('tx_detail/tx_receipt') / f'{transaction_hash}.json')
            block = raw_transaction.get('blockNumber')
            if type(block) is not int:
                block = int(block, 16 if isinstance(block, str) and block.startswith('0x') else 10)
            if block < 0:
                raise ValueError('Invalid block number')
            safe_bytes(Path('timestamp') / f'{block}.json', 65536)
            relative = Path('trace/simulation_result') / f'{simulation_id}.json'
            data = safe_bytes(relative)
            raw = json.loads(data)
            context, _ = PatchReplayEvidenceStore(root).original_context(transaction_hash, chain_id)
            validated = validate_simulated_transaction(context, raw)
            if (any(baseline.get(key) != value for key, value in validated.items())
                    or raw.get('simulation', {}).get('state_objects')):
                raise ValueError('Original evidence does not match its saved baseline')
            result['investigation_evidence_index'].append({
                'transaction_hash': transaction_hash, 'simulation_id': simulation_id,
                'reference': (Path('cache') / relative).as_posix(),
                'sha256': hashlib.sha256(data).hexdigest()})
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError,
                HistoricalReplayValidationError):
            result['unavailable_transaction_hashes'].append(transaction_hash)
    return result


class DAppAnalyze:
    def __init__(self, processed_data: Dict, transaction_debugger: TraceAgent,
                 net2apikey_bucket: Dict[str, AsyncItemBucket],
                 net2rpc_bucket: Dict[str, AsyncItemBucket],
                 mcp_client,
                 metrics_collector: Optional[PatchQualityMetrics] = None,
                 log_callback=None,
                 cancellation_checker: Optional[Callable[[], bool]] = None,
                 enabled_modules: Optional[List[str]] = None):
        self._net2apikey_bucket = net2apikey_bucket
        self._net2rpc_bucket = net2rpc_bucket
        self.processed_data = processed_data
        self.dapp_name = processed_data["dapp"]["name"]
        self.enabled_modules = set(enabled_modules or [
            "attack_detection",
            "fault_localization",
            "rag_retrieval",
            "patch_generation",
            "patch_verification",
        ])
        if self._module_enabled("rag_retrieval") and not self.processed_data.get("rag_context"):
            self.processed_data["rag_context"] = retrieve_rag_context(
                build_rag_query_from_dapp(self.processed_data.get("dapp", {})),
                top_k=5,
            )
        elif not self._module_enabled("rag_retrieval") and not self.processed_data.get("rag_context"):
            self.processed_data["rag_context"] = {"items": [], "skipped": True, "reason": "rag_retrieval module disabled"}
        self.txs_need_analyze = processed_data["transactions_need_analyze"]
        self.is_multi = True if len(self.txs_need_analyze) > 1 else False
        self.mcp_client = mcp_client
        self.transaction_debugger = transaction_debugger
        self.transaction_debugger.init_prompt(self.processed_data)
        memory = getattr(self.transaction_debugger, 'memory', None)
        if (self._module_enabled('patch_verification') and isinstance(memory, list) and memory
                and isinstance(memory[0], dict) and isinstance(memory[0].get('content'), str)):
            memory[0]['content'] += (
                '\n\n<Verification_Plan_Context authority="coordinator_provenance">\n'
                + json.dumps(investigation_verification_context(processed_data), ensure_ascii=False)
                + '\n</Verification_Plan_Context>\n'
                  'Use an explicit input plan as declared. Investigation-derived plans may cite only '
                  'the indexed original evidence and must explain the observed basis of each rule. '
                  'Missing evidence, normal transactions, calldata, storage locations, or business '
                  'requirements remain unavailable; never fabricate them or relabel attack inputs as normal cases.'
            )
        self.global_memory_administrator = GlobalMemoryAgent(self.is_multi, dapp_name=self.dapp_name, log_callback=log_callback)
        self.task_organizer = TaskAgent(self.mcp_client, dapp_name=self.dapp_name, session_id=self.transaction_debugger.session_id, log_callback=log_callback)
        self.code_patcher = None
        self.transaction_judge = None
        if self._module_enabled("patch_generation") or self._module_enabled("patch_verification"):
            self.code_patcher = FixAgent(processed_data=processed_data,
                                         apikey_bucket=self._net2apikey_bucket[processed_data["dapp"]["platform"]],
                                         rpc_bucket=self._net2rpc_bucket[processed_data["dapp"]["platform"]],
                                         mcp_client=self.mcp_client,
                                         dapp_name=self.dapp_name,
                                         session_id=self.transaction_debugger.session_id,
                                         metrics_collector=metrics_collector,
                                         log_callback=log_callback)
        if self._module_enabled("patch_verification"):
            self.transaction_judge = JudgeAgent(dapp_name=self.dapp_name, metrics_collector=metrics_collector, log_callback=log_callback)
        self.metrics_collector = metrics_collector
        self.log_callback = log_callback
        self.cancellation_checker = cancellation_checker or (lambda: False)
        self.verification = verification_state() if self._module_enabled("patch_verification") else verification_state(
            "skipped", stage="module_selection", reason_code="module_disabled",
            reason="本次任务未启用补丁回放验证。", terminal=True,
        )
        self.replay_evidence = None
        self.applied_patches = ""

    def _check_cancelled(self):
        if self.cancellation_checker():
            raise asyncio.CancelledError("Task was cancelled")

    def _module_enabled(self, module_id: str) -> bool:
        return module_id in self.enabled_modules

    def _attach_cancel(self, agent):
        if hasattr(agent, "set_cancellation_checker"):
            agent.set_cancellation_checker(self.cancellation_checker)
        return agent

    async def _finish_unverified(self, hypothesis, replay_logs="", patches=""):
        if self.metrics_collector:
            self.metrics_collector.finalize_case(self.dapp_name, "UNVERIFIED")
        report = await self.global_memory_administrator.get_final_result(
            {"verdict": "UNVERIFIED", "reason": self.verification.get("reason", ""),
             "verification": self.verification},
            hypothesis, replay_logs or "No completed patch replay evidence is available.",
            patches or "No finalized patch available.",
        )
        return report, self.get_analyze_items()

    def _finish_without_hypothesis(self, reason_code, reason):
        """An unsupported attack hypothesis is an inconclusive investigation."""
        self.verification = verification_state(
            "skipped" if reason_code == "no_attack_evidence" else "unverified",
            stage="fault_localization", reason_code=reason_code, reason=reason, terminal=True,
            retryable=False, next_action="review_attack_evidence",
        )
        self.replay_evidence, self.applied_patches = None, ""
        if self.metrics_collector:
            self.metrics_collector.finalize_case(self.dapp_name, "NO_ATTACK_EVIDENCE")
        evidence = report_evidence({"verdict": "UNVERIFIED", "verification": self.verification}, None)
        report = render_verification_summary(evidence) + (
            "\n\n## 复盘结果\n\n" + reason
            + "\n\n本次未建立可验证的攻击假设，未生成或执行补丁。"
              "这不代表交易安全，也不代表已证明不存在攻击；需要补充交易、调用轨迹或安全条件等证据。"
        )
        return report, self.get_analyze_items()

    async def analyze(self) -> [str, Dict]:
        self._check_cancelled()
        if self.metrics_collector:
            self.metrics_collector.start_case(self.dapp_name)

        for agent in [
            self.transaction_debugger,
            self.global_memory_administrator,
            self.task_organizer,
            self.code_patcher,
            self.transaction_judge,
        ]:
            if agent:
                self._attach_cancel(agent)
        
        self.global_memory_administrator.init(self.processed_data)
        verify_feedback = "Initial state: Start analysis."

        if len(self.txs_need_analyze) <= 0:
            return self._finish_without_hypothesis(
                "no_attack_evidence", "当前证据未筛出需要继续复盘的攻击交易，补丁验证未执行。",
            )

        self._check_cancelled()
        await self.transaction_debugger.init_transactions(self.txs_need_analyze)
        self.global_memory_administrator.init_transactions(self.txs_need_analyze)

        last_valid_hypothesis = {}
        last_replay_logs = ""
        last_patches = ""

        total_turn = TOTAL_TURN
        while total_turn > 0:
            self._check_cancelled()
            guide_turn = GUIDE_TURN
            current_hypothesis = {}
            while guide_turn > 0:
                self._check_cancelled()
                # generate task tree (assume)
                await self.task_organizer.handle(
                    self.global_memory_administrator.global_memory,
                    verify_feedback
                )
                self._check_cancelled()
                is_force_turn = (guide_turn == 1)
                # transaction debug (analyze)
                debug_result = await self.transaction_debugger.handle(
                    self.global_memory_administrator.global_memory,
                    self.task_organizer.task_tree,
                    force_terminate=is_force_turn
                )
                self._check_cancelled()
                if not isinstance(debug_result, dict):
                    verify_feedback = "Debugger returned no structured analysis result; retry within the analysis limit."
                    guide_turn -= 1
                    continue
                reason = debug_result.get("reason", "")
                if isinstance(reason, str) and reason == "ERROR":
                    if self.metrics_collector:
                        self.metrics_collector.finalize_case(self.dapp_name, "TRACE_AGENT_ERROR")
                    return f"ERROR_{debug_result.get('data', '')}", self.get_analyze_items() if last_valid_hypothesis else {}

                if isinstance(reason, str) and reason.endswith("_NO_READY_FOR_PATCH"):
                    if last_valid_hypothesis:
                        verify_feedback = f"Debugger terminated ({reason}), falling back to last valid hypothesis."
                        current_hypothesis = dict(last_valid_hypothesis)
                        break
                    else:
                        return self._finish_without_hypothesis(
                            "no_attack_hypothesis", "在本次分析轮次内尚未形成可验证的攻击假设，现有证据不足以继续生成补丁。",
                        )

                if reason == "READY_FOR_PATCH" or guide_turn == 1:
                    debug_data = debug_result.get("data")
                    if (not isinstance(debug_data, (list, tuple)) or len(debug_data) < 3
                            or not isinstance(debug_data[2], (str, dict)) or not debug_data[2]):
                        verify_feedback = "Debugger returned an incomplete hypothesis; source targets and a fix report are required."
                        if guide_turn > 1:
                            guide_turn -= 1
                            continue
                        if last_valid_hypothesis:
                            current_hypothesis = dict(last_valid_hypothesis)
                            break
                        return self._finish_without_hypothesis(
                            "no_attack_hypothesis", "攻击分析未提供完整的修复目标与方案，尚无法建立可验证的攻击假设。",
                        )

                    current_hypothesis = {
                        "fault_report": debug_data[0] if len(debug_data) > 0 else "",
                        "final_trace": debug_data[1] if len(debug_data) > 1 else "",
                        "fix_report": debug_data[2] if len(debug_data) > 2 else ""
                    }
                    last_valid_hypothesis = current_hypothesis
                    if self.metrics_collector:
                        self.metrics_collector.record_analysis_hypothesis(self.dapp_name, current_hypothesis)
                    await self.task_organizer.end_analyze(current_hypothesis)
                    await self.global_memory_administrator.update(self.transaction_debugger.name, current_hypothesis)
                    break

                if "data" in debug_result:
                    await self.global_memory_administrator.update(self.transaction_debugger.name, debug_result["data"])
                if "switch_data" in debug_result:
                    await self.global_memory_administrator.switch_transaction(self.transaction_debugger.name,
                                                                              debug_result["switch_data"])
                    self.transaction_debugger.is_init = False
                guide_turn -= 1

            if not current_hypothesis:
                if last_valid_hypothesis:
                    current_hypothesis = dict(last_valid_hypothesis)
                else:
                    return self._finish_without_hypothesis(
                        "no_attack_hypothesis", "攻击分析未形成可用于验证的结构化假设，现有交易证据仍需复核。",
                    )

            # Patch loop (verify)
            if not self._module_enabled("patch_generation"):
                self.verification = verification_state(
                    "skipped", stage="module_selection", reason_code="module_disabled",
                    reason="本次任务未启用补丁生成与回放验证。", terminal=True,
                )
                skipped_verification = {
                    "verdict": "SKIPPED",
                    "reason": "Patch generation and verification modules were disabled by the user.",
                    "verification": self.verification,
                }
                if self.metrics_collector:
                    self.metrics_collector.finalize_case(self.dapp_name, "UNVERIFIED_MODULE_DISABLED")
                return await self.global_memory_administrator.get_final_result(
                    skipped_verification,
                    current_hypothesis,
                    "Patch generation and replay were skipped by module selection.",
                    "No patch generated because patch_generation was disabled."
                ), self.get_analyze_items()

            patch_turn = PATCH_TURN
            verification_result = None
            is_finalized = False
            replay_logs, patches = "", ""
            patch_fix_total_count = 0

            while patch_turn > 0:
                self._check_cancelled()
                patch_execution_success, replay_logs, patches, fix_count = await self.code_patcher.handle(current_hypothesis, verify=self._module_enabled("patch_verification"))
                self._check_cancelled()
                self.verification = patch_execution_state(self.code_patcher)
                patch_fix_total_count += fix_count

                if self.metrics_collector:
                    self.metrics_collector.record_fix_turns(self.dapp_name, patch_fix_total_count)

                last_replay_logs = replay_logs
                self.replay_evidence = replay_logs if isinstance(replay_logs, dict) else None
                last_patches = patches
                self.applied_patches = patches if isinstance(patches, str) else ""

                if self.verification.get("terminal") and not patch_execution_success:
                    # Missing source or unavailable infrastructure cannot be fixed
                    # by asking the models to generate the same patch again.
                    return await self._finish_unverified(current_hypothesis, replay_logs, patches)

                if patch_execution_success:
                    if not self._module_enabled("patch_verification"):
                        self.verification = verification_state(
                            "skipped", stage="module_selection", reason_code="module_disabled",
                            reason="补丁已生成并编译，本次任务未启用回放验证。", terminal=True,
                        )
                        unverified_patch_result = {
                            "verdict": "PATCH_GENERATED",
                            "reason": "Patch was generated, but replay verification was disabled by the user.",
                            "verification": self.verification,
                        }
                        if self.metrics_collector:
                            self.metrics_collector.finalize_case(self.dapp_name, "PATCH_GENERATED_UNVERIFIED")
                        return await self.global_memory_administrator.get_final_result(
                            unverified_patch_result,
                            current_hypothesis,
                            replay_logs or "Patch replay skipped because patch_verification was disabled.",
                            patches,
                        ), self.get_analyze_items()

                    if not self.verification.get("replay_completed") or not replay_logs:
                        self.verification = verification_state(
                            "unverified", stage="replay", reason_code="replay_evidence_missing",
                            reason="缺少完整的补丁回放结果，无法判定补丁有效性。", terminal=True,
                            replay_attempted=self.verification.get("replay_attempted", False),
                        )
                        return await self._finish_unverified(current_hypothesis, replay_logs, patches)

                    # The model interprets completed replay. Declared execution
                    # checks decide the outcome even if interpretation fails.
                    judge_data = {
                        "real_balance_change": self.processed_data["balance_change"],
                        "replay_logs": replay_logs,
                        "current_hypothesis": current_hypothesis,
                        "patches": patches
                    }
                    try:
                        judge_result = await self.transaction_judge.handle(judge_data)
                    except Exception as exc:
                        if (isinstance(replay_logs, dict) and type(replay_logs.get('schema_version')) is int
                                and replay_logs['schema_version'] == 2
                                and replay_logs.get('scope') == 'sequential_attack_and_regression'):
                            judge_result = {
                                'interpretation_status': 'unavailable',
                                'reason': failure_message(exc, "解读补丁回放结果"),
                            }
                        else:
                            self.verification.update(
                                status="error", stage="judge", reason_code="judge_error", terminal=True,
                                reason=failure_message(exc, "解读补丁回放结果"),
                            )
                            return await self._finish_unverified(current_hypothesis, replay_logs, patches)
                    self._check_cancelled()
                    judge_result = judge_result if isinstance(judge_result, dict) else {"verdict": "UNVERIFIED"}
                    execution_state = self.verification
                    self.verification = adjudicate_patch_verification(judge_result, replay_logs, patches)
                    if (self.metrics_collector and self.verification.get('evidence_version') == 2
                            and judge_result.get('interpretation_status') == 'unavailable'):
                        self.metrics_collector.record_judge_result(
                            case_name=self.dapp_name,
                            verdict='VERIFIED' if self.verification.get('status') == 'verified'
                            and self.verification.get('evidence_validated') is True else 'UNVERIFIED',
                            reason=self.verification.get('reason', ''),
                        )
                    for budget_key in ("request_budget", "patch_generation_budget", "runtime_generation_budget", "runtime_source_evidence"):
                        if isinstance(execution_state.get(budget_key), dict):
                            self.verification[budget_key] = dict(execution_state[budget_key])
                    if isinstance(execution_state.get('source_target_resolutions'), list):
                        self.verification['source_target_resolutions'] = deepcopy(execution_state['source_target_resolutions'])
                    # Candidate repair history is diagnostic context, copied
                    # only after the replay evidence gate has made its verdict.
                    rejected_candidates = execution_state.get('rejected_patch_candidates')
                    if isinstance(rejected_candidates, list) and all(isinstance(item, dict) for item in rejected_candidates):
                        self.verification['rejected_patch_candidates'] = deepcopy(rejected_candidates)
                    if self.verification.get("status") == "verified":
                        verification_result = {**judge_result, "verification": dict(self.verification)}
                        is_finalized = True
                        break
                    if (self.verification.get("retryable") is True
                            and self.verification.get("next_action") == "select_trigger_transactions"):
                        verify_feedback = (
                            "The replay scope did not establish a test of the modified code. "
                            "Revisit the original transaction traces and correct the fix report's "
                            "source-mapped trigger_point transaction hashes and indexes. Preserve "
                            "attack candidates and include any required intermediate trigger even "
                            "if it was initially labelled auxiliary. Do not revise the same patch "
                            "or repeat unchanged replay inputs merely because no interception was observed. "
                            f"Coordinator reason: {self.verification.get('reason_code')}. "
                            f"Coverage: {self.verification.get('coverage')}"
                        )
                        # Return to the bounded localization loop, rather than
                        # spending a patch revision on an untested trigger.
                        break
                    if (self.verification.get("retryable") is True
                            and self.verification.get("next_action") == "revise_patch"):
                        patch_turn -= 1
                        current_hypothesis["fix_feedback"] = (
                            f"Patch effectiveness remains unverified. Coordinator reason: {self.verification.get('reason_code')}: "
                            f"{self.verification.get('reason')}\n"
                            f"Model interpretation only: {judge_result.get('feedback_to_agent') or judge_result.get('reason')}\n"
                            "Revise the implementation using the observed execution; keep the root cause as a hypothesis.\n"
                            f"Replay Evidence: {replay_logs}"
                        )
                        print(f"[-] Patch outcome remains unverified. Revising implementation... ({patch_turn} turns left)")
                        continue
                    self.verification.update(terminal=True, retryable=False)
                    if self.verification.get("next_action") == "review_same_evidence":
                        self.verification["next_action"] = "inspect_judge_evidence"
                    return await self._finish_unverified(current_hypothesis, replay_logs, patches)
                else:
                    patch_turn -= 1
                    current_hypothesis["fix_feedback"] = f"Patch execution failed: {replay_logs}"

            if is_finalized:
                if self.metrics_collector:
                    self.metrics_collector.finalize_case(self.dapp_name, "VERIFIED")
                return await self.global_memory_administrator.get_final_result(
                    verification_result, current_hypothesis, replay_logs, patches
                ), self.get_analyze_items()

            if patch_turn <= 0:
                verify_feedback = (
                    "Patch revision attempts exhausted without confirmed interception. "
                    "Re-evaluate the trace using the recorded feedback; the existing root cause has not been disproved. "
                    + str(current_hypothesis.get("fix_feedback", ""))
                )

            total_turn -= 1

        if last_valid_hypothesis:
            if self.verification.get("status") in {"not_run", "unverified"}:
                self.verification.update(status="unverified", terminal=True, retryable=False)
                if self.verification.get("next_action") != "select_trigger_transactions":
                    self.verification.update(
                        next_action="inspect_analysis_feedback", reason_code="turn_limit_reached",
                        reason="已达到修复尝试上限，尚未完成有效补丁的验证。",
                    )
            if self.metrics_collector:
                self.metrics_collector.finalize_case(self.dapp_name, "UNVERIFIED")
            unverified_result = {
                "verdict": "UNVERIFIED",
                "reason": f"Analysis process terminated after {TOTAL_TURN} turns. "
                          f"This report is based on the latest hypothesis but lacks verification.",
                "verification": self.verification,
            }
            raw_report = await self.global_memory_administrator.get_final_result(
                unverified_result,
                last_valid_hypothesis,
                last_replay_logs or "No completed patch replay evidence is available.",
                last_patches or "No finalized patch available."
            )

            warning_header = (
                    "\n" + "!" * 80 + "\n"
                                      "⚠️  WARNING: ANALYSIS INCOMPLETE / UNVERIFIED REPORT  ⚠️\n"
                                      "The system failed to verify the fix within the allowed turns.\n"
                                      "The following report is generated based on the LAST HYPOTHESIS.\n"
                                      "It may contain inaccurate root causes or ineffective patches.\n"
                                      f"Final Status: {verify_feedback}\n"
                    + "!" * 80 + "\n\n"
            )

            return warning_header + raw_report, self.get_analyze_items()

        if self.metrics_collector:
            self.metrics_collector.finalize_case(self.dapp_name, "MAX_TURNS_EXCEEDED")

        return (f"FAILED: Unable to generate any valid hypothesis within {TOTAL_TURN} turns. \n"
                f"Last Feedback: {verify_feedback}"), self.get_analyze_items()

    def get_analyze_items(self):
        patch_time = self.code_patcher.get_total_time() if self.code_patcher else 0
        judge_time = self.transaction_judge.get_total_time() if self.transaction_judge else 0
        patch_token = self.code_patcher.token if self.code_patcher else 0
        judge_token = self.transaction_judge.token if self.transaction_judge else 0
        return {
            "verification": self.verification,
            "verification_plan": deepcopy(getattr(self.code_patcher, '_verification_plan', None)),
            "replay_evidence": self.replay_evidence,
            "applied_patches": self.applied_patches,
            "report_generation": getattr(self.global_memory_administrator, "report_generation", {"status": "not_run"}),
            "time": {
                "debugger": self.transaction_debugger.get_total_time(),
                "task": self.task_organizer.get_total_time(),
                "memory": self.global_memory_administrator.get_total_time(),
                "patch": patch_time,
                "judge": judge_time
            },
            "token": {
                "total_token": self.transaction_debugger.token + self.task_organizer.token + self.global_memory_administrator.token + patch_token + judge_token,
                "debugger": self.transaction_debugger.token,
                "task": self.task_organizer.token,
                "memory": self.global_memory_administrator.token,
                "patch": patch_token,
                "judge": judge_token
            }
        }
