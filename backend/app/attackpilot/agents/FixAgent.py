import ast
import asyncio
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple, Union

from app.attackpilot.agents.AgentBase import AgentBase
from app.attackpilot.daos.contract import ContractDao, ContractCompileItem
from app.attackpilot.daos.tenderly import BundleTenderlyDao
from app.attackpilot.downloaders.contract import ContractSourceDownloader, ContractBytecodeDownloader
from app.attackpilot.downloaders.trans import BlockTimestampDownloader, TxDownloader, TxReceiptDownloader
from app.attackpilot.entities.contract import ContractEntityForCompile
from app.attackpilot.errors import HistoricalReplayValidationError, TenderlyAPIError, failure_message
from app.attackpilot.privacy import redact_text
from app.attackpilot.mcp_tools.mcp_client import MCPClient
from app.attackpilot.prompt.fix_prompt import FIX_SP, FIX_UP, FIX_FIX_UP
from app.attackpilot.settings import PLATFORM_TO_CHAIN_ID, FIX_TURN
from app.attackpilot.utils.bytecode_transplanter import BytecodeTransplanter, RuntimeIntegrityError
from app.attackpilot.utils.patch import SolidityCodePatcher, build_applied_patch_record
from app.attackpilot.utils.patch_attribution import build_patch_attribution
from app.attackpilot.utils.patch_replay import (
    MAX_REPLAY_REQUESTS, MAX_REPLAY_TRANSACTIONS, PatchReplayBudgetError,
    PatchReplayEvidenceStore, historical_payload, runtime_overrides, trace_summary,
)
from app.attackpilot.utils.replay_validation import validate_simulated_transaction


MAX_PATCH_GENERATION_REQUESTS = FIX_TURN
REPAIRABLE_RUNTIME_REJECTIONS = {
    'constructor_or_immutable_changed', 'storage_layout_changed', 'patch_runtime_unchanged',
}


class HistoricalRuntimeError(RuntimeError):
    def __init__(self, reason_code):
        reasons = {
            'historical_runtime_unavailable': '缺少可用的历史合约运行时代码；未使用当前 latest 代码替代。',
            'historical_runtime_conflict': '同一合约在相关历史交易中的运行时代码不一致，已停止混用不同版本。',
            'historical_runtime_context_mismatch': '历史代码来源与交易、网络或已校验回执不一致，已停止补丁生成。',
        }
        self.reason_code = reason_code if reason_code in reasons else 'historical_runtime_unavailable'
        super().__init__(reasons[self.reason_code])


class FixAgent(AgentBase):
    def __init__(self, processed_data, apikey_bucket, rpc_bucket, mcp_client: MCPClient, dapp_name: str,
                 session_id: str, name="Code Patcher", metrics_collector=None, log_callback=None):
        super(FixAgent, self).__init__(name, FIX_SP, unique_id=dapp_name, max_turns=1,log_callback=log_callback)
        self.processed_data = processed_data
        self.apikey_bucket = apikey_bucket
        self.rpc_bucket = rpc_bucket
        self.mcp_client = mcp_client
        self.session_id = session_id
        self.unique_id = dapp_name
        self._platform = self.processed_data.get("dapp", {}).get("platform", "Ethereum")
        self.chain_id = PLATFORM_TO_CHAIN_ID.get(self._platform)
        self.metrics_collector = metrics_collector
        self._replayed_patch_digests = set()
        self._rejected_patch_candidates = {}
        self._source_refresh_attempted_addresses = set()
        self._patch_generation_requests = 0
        self._set_verification("not_run", "preconditions", "patch_not_started",
                               "Patch generation and replay have not started.")

    def _set_verification(self, status, stage, reason_code, reason, *,
                          replay_attempted=False, replay_completed=False, terminal=False):
        self.verification = {
            "schema_version": 2,
            "status": status,
            "stage": stage,
            "reason_code": reason_code,
            "reason": reason,
            "replay_attempted": replay_attempted,
            "replay_completed": replay_completed,
            "terminal": terminal,
            "patch_generation_budget": {
                "max_requests_per_task": MAX_PATCH_GENERATION_REQUESTS,
                "requests_used": getattr(self, '_patch_generation_requests', 0),
                "remaining_requests": max(0, MAX_PATCH_GENERATION_REQUESTS - getattr(self, '_patch_generation_requests', 0)),
                "counting_scope": "generation_calls_including_repairs_and_errors",
            },
            "runtime_generation_budget": {
                "max_requests_per_task": 0,
                "requests_used": 0,
                "method": "validated_historical_runtime_transplant",
            },
        }
        budget = getattr(self, "_last_replay_request_budget", None)
        if isinstance(budget, dict):
            self.verification["request_budget"] = dict(budget)
        integrity = getattr(self, "_runtime_integrity", None)
        if isinstance(integrity, dict):
            self.verification["runtime_integrity"] = integrity
        sources = getattr(self, "_runtime_source_evidence", None)
        if isinstance(sources, dict):
            self.verification["runtime_source_evidence"] = dict(sources)
        resolutions = getattr(self, '_patch_source_resolutions', None)
        if isinstance(resolutions, list) and resolutions:
            self.verification['source_target_resolutions'] = deepcopy(resolutions)
        rejected = getattr(self, '_rejected_patch_candidates', None)
        if isinstance(rejected, dict) and rejected:
            self.verification['rejected_patch_candidates'] = [
                {**item, 'generation_requests': list(item['generation_requests'])}
                for item in rejected.values()
            ]
        plan = getattr(self, '_verification_plan', None)
        if isinstance(plan, dict):
            self.verification['verification_plan'] = deepcopy(plan)

    def _stop(self, status, stage, reason_code, reason, *, patches="", retry_count=0,
              replay_attempted=False, replay_completed=False, terminal=True):
        self._set_verification(status, stage, reason_code, reason,
                               replay_attempted=replay_attempted,
                               replay_completed=replay_completed, terminal=terminal)
        return False, reason, patches, retry_count

    def _stop_error(self, exc, stage, reason_code, *, patches="", retry_count=0,
                    replay_attempted=False):
        replay_attempted = getattr(exc, "replay_attempted", replay_attempted) is True
        partial = getattr(exc, "replay_evidence", None)
        if isinstance(partial, dict):
            if getattr(self, '_required_replay_triggers', None):
                partial['required_trigger_transaction_hashes'] = list(self._required_replay_triggers)
            self.replay_evidence = partial
        status = "error"
        if isinstance(exc, TimeoutError):
            reason_code = f"{stage}_timeout"
        elif isinstance(exc, PatchReplayBudgetError):
            status, reason_code = "blocked", exc.reason_code
        elif isinstance(exc, (HistoricalRuntimeError, RuntimeIntegrityError)):
            status, reason_code = "blocked", exc.reason_code
        elif isinstance(exc, HistoricalReplayValidationError):
            status, reason_code = "blocked", f"baseline_{exc.status}"
        elif isinstance(exc, TenderlyAPIError) and exc.error_code:
            reason_code = f"tenderly_{exc.error_code}"
        sequence_diagnostic = getattr(exc, 'sequence_validation_diagnostic', None)
        historical_sequence_mismatch = (
            isinstance(exc, HistoricalReplayValidationError)
            and exc.reason_code in {'execution_mismatch', 'event_mismatch'}
            and isinstance(sequence_diagnostic, dict)
            and sequence_diagnostic.get('role') == 'control'
        )
        reason = (str(exc) if isinstance(exc, (PatchReplayBudgetError, HistoricalRuntimeError, RuntimeIntegrityError))
                  else failure_message(exc, "补丁处理"))
        if historical_sequence_mismatch:
            reason_code = 'historical_sequence_result_mismatch'
            reason = '原版连续回放未还原历史执行结果；需要核对攻击步骤之间的链上状态变化，当前尚不能判断补丁效果。'
        stopped = self._stop(status, stage, reason_code,
                             reason,
                             patches=patches, retry_count=retry_count, replay_attempted=replay_attempted)
        if isinstance(sequence_diagnostic, dict):
            self.verification['sequence_validation_diagnostic'] = deepcopy(sequence_diagnostic)
        if historical_sequence_mismatch:
            self.verification['retryable'] = False
            self.verification['next_action'] = 'restore_historical_sequence_context'
        if isinstance(exc, PatchReplayBudgetError):
            self.verification["request_budget"] = {
                "max_requests_per_task": MAX_REPLAY_REQUESTS,
                "required_requests": getattr(exc, "required_requests", None),
                "remaining_requests": getattr(exc, "remaining_requests", None),
            }
        if isinstance(partial, dict):
            return stopped[0], partial, stopped[2], stopped[3]
        return stopped

    @staticmethod
    def _valid_runtime_bytecode(bytecode):
        return (isinstance(bytecode, str)
                and re.fullmatch(r"(?:0x)?(?:[0-9a-fA-F]{2})+", bytecode) is not None)

    def _stop_generation_budget(self, *, patches='', retry_count=0):
        patches = patches or getattr(self, '_last_applied_patches', '')
        previous = getattr(self, 'verification', {})
        last_reason = previous.get('reason_code')
        budget_reason = '本任务已达到累计补丁生成调用上限；初稿、反馈修订和失败调用均计入，未再请求生成或回放，补丁效果仍未验证。'
        candidate_rejected = last_reason in REPAIRABLE_RUNTIME_REJECTIONS
        reason = previous.get('reason', '')
        if candidate_rejected and previous.get('generation_stop_reason_code') != 'patch_generation_request_limit':
            reason = f'{reason} {budget_reason}'
        result = self._stop('blocked', 'runtime_generation' if candidate_rejected else 'patch_generation',
                            last_reason if candidate_rejected else 'patch_generation_request_limit',
                            reason if candidate_rejected else budget_reason,
                            patches=patches, retry_count=retry_count)
        self.verification.update(terminal=True, retryable=False,
                                 generation_stop_reason_code='patch_generation_request_limit')
        if last_reason not in {'patch_not_started', 'patch_generation_pending'}:
            self.verification['last_attempt_reason_code'] = last_reason
        return result

    def _reject_runtime_candidate(self, patch_digest, reason_code, reason):
        rejected = self._rejected_patch_candidates
        if patch_digest not in rejected:
            rejected[patch_digest] = {
                'applied_patch_sha256': patch_digest, 'reason_code': reason_code,
                'reason': reason, 'generation_requests': [],
            }
        rejected[patch_digest]['generation_requests'].append(self._patch_generation_requests)
        self._set_verification('unverified', 'runtime_generation', reason_code, reason)
        self.verification.update(retryable=True, next_action='revise_patch')
        instructions = {
            'constructor_or_immutable_changed':
                'Preserve every original constructor, state initializer, base constructor argument, '
                'and immutable declaration. Fix runtime logic instead; initialize only new patch state lazily.',
            'storage_layout_changed':
                'Preserve all original state declarations, types, order, and inheritance. '
                'Store any new patch state in compiler-compatible unstructured storage.',
            'patch_runtime_unchanged':
                'The applied edits did not change executable runtime. Generate a source change '
                'that implements the evidenced fix in executed runtime logic.',
        }
        return (f"Runtime candidate rejected: {reason_code}: {reason}\n"
                f"{instructions[reason_code]} Do not repeat this rejected patch or deploy a replacement contract. "
                'No attack replay was executed for this candidate.')

    def _stop_original_compile(self, failures):
        missing = all(item['reason_code'] == 'compiler_unavailable' for item in failures)
        code = 'compiler_unavailable' if missing else 'original_compile_failed'
        first = failures[0]
        reason = (f"缺少合约 {first['address']} 所需的 Solidity 编译器 {first['compiler_version']}；补丁生成与回放均未开始。"
                  if missing else f"合约 {first['address']} 的原始源码未通过编译，无法建立验证基准；补丁生成与回放均未开始。")
        stopped = self._stop('blocked', 'compile', code, reason)
        self.verification['compile_diagnostics'] = failures[:8]
        logger = getattr(self, 'logger', None)
        if logger:
            # Diagnostic logging must not replace the actual failure outcome.
            try:
                logger.warning(reason + '\n' + json.dumps(failures[:8], ensure_ascii=False))
            except Exception:
                pass
        return stopped

    async def _get_patch_item(self, faulty_index, *, expected_function=None):
        arguments = {"session_id": self.session_id, "faulty_index": faulty_index}
        if expected_function is not None:
            arguments['expected_function'] = expected_function
        item = await self.mcp_client.call_tool("get_patch_items", arguments)
        self._check_cancelled()
        if not isinstance(item, dict):
            return item
        address, source = item.get('address'), item.get('source_lookup')
        files = item.get('contract_info')
        has_source = (isinstance(files, list) and any(
            isinstance(file, dict) and isinstance(file.get('source'), str) and file['source'].strip()
            for file in files))
        if (has_source or not isinstance(address, str) or not address.strip()
                or not isinstance(source, dict) or source.get('status') != 'failed'
                or source.get('retryable') is not True):
            return item
        if not hasattr(self, '_source_refresh_attempted_addresses'):
            self._source_refresh_attempted_addresses = set()
        address = address.lower()
        if address in self._source_refresh_attempted_addresses:
            return item
        self._source_refresh_attempted_addresses.add(address)
        refreshed = await self.mcp_client.call_tool("get_patch_items", {**arguments, "refresh_source": True})
        self._check_cancelled()
        if not isinstance(refreshed, dict) or str(refreshed.get('address', '')).lower() != address:
            return {}
        return refreshed

    async def handle(self, fault_data: Dict, verify: bool = True):
        self._check_cancelled()
        self.replay_evidence = None
        self._last_replay_request_budget = None
        self._required_replay_triggers = []
        self._replay_scope = ()
        self._runtime_source_evidence = {}
        self._patch_source_resolutions = []
        self._runtime_integrity = None
        self._verification_plan = None
        if not hasattr(self, "_replayed_patch_digests"):
            self._replayed_patch_digests = set()
        if not hasattr(self, '_rejected_patch_candidates'):
            self._rejected_patch_candidates = {}
        if getattr(self, '_patch_generation_requests', 0) >= MAX_PATCH_GENERATION_REQUESTS:
            return self._stop_generation_budget(patches=getattr(self, '_last_applied_patches', ''))
        self._set_verification("not_run", "preconditions", "patch_not_started",
                               "Patch generation and replay have not started.")
        if not isinstance(fault_data, dict):
            return self._stop("blocked", "preconditions", "invalid_fix_report",
                              "The patch report is missing or malformed; replay was not started.")
        try:
            json_parse_success, fix_report = self.process_fix_report(fault_data.get("fix_report"))
        except (TypeError, ValueError, AttributeError):
            json_parse_success, fix_report = False, None
        if not json_parse_success or not isinstance(fix_report, dict):
            return self._stop("blocked", "preconditions", "invalid_fix_report",
                              "The patch report is missing or malformed; replay was not started.")

        if verify:
            try:
                self._verification_plan = self._resolve_verification_plan(fix_report)
            except (ValueError, OSError, TypeError) as exc:
                from app.attackpilot.utils.security_checks import verification_plan_diagnostic
                dapp = self.processed_data.get('dapp') or {}
                explicit = dapp.get('verification_plan', self.processed_data.get('verification_plan'))
                stopped = self._stop('blocked', 'preconditions', 'invalid_verification_plan',
                                     f'验证计划未通过输入及证据校验：{exc}；尚未生成或回放补丁。')
                self.verification['plan_diagnostic'] = verification_plan_diagnostic(
                    exc, origin='user_declared' if explicit is not None else 'investigation_derived')
                return stopped

        faulty_functions = fix_report.get("faulty_functions")
        if not isinstance(faulty_functions, list) or not faulty_functions:
            return self._stop("blocked", "preconditions", "no_patch_targets",
                              "No source patch targets were identified; replay was not started.")
        faulty_targets = []
        for faulty_function in faulty_functions:
            trigger = faulty_function.get("trigger_point") if isinstance(faulty_function, dict) else None
            if not isinstance(trigger, dict):
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  "A patch target cannot be mapped to an original transaction trace.")
            index, transaction_hash = trigger.get("index"), trigger.get("transaction_hash")
            if type(index) is int and index >= 0:
                pass
            elif isinstance(index, str) and index.isdecimal():
                index = int(index)
            else:
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  "A patch target has no valid trace index; replay was not started.")
            if (not isinstance(transaction_hash, str)
                    or re.fullmatch(r'0x[0-9a-fA-F]{64}', transaction_hash) is None):
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  "A patch target has no original transaction hash; replay was not started.")
            transaction_hash = transaction_hash.lower()
            faulty_index = f"{transaction_hash}::{index}"
            expected_function = faulty_function.get('function_name')
            if expected_function is not None:
                if not isinstance(expected_function, str) or not expected_function.strip():
                    return self._stop('blocked', 'preconditions', 'invalid_fix_report',
                                      'A declared patch function must have a valid function name.')
                expected_function = expected_function.strip()
            target = (faulty_index, expected_function)
            if target not in faulty_targets:
                faulty_targets.append(target)

        address2contracts: Dict[str, ContractEntityForCompile] = {}
        uid2faults: Dict[str, list] = {}
        uid2source: Dict[str, str] = {}
        self._patch_trigger_transactions = {}
        # Validate every target before compilation, bytecode fetching, or model calls.
        # Patching a subset silently would leave the reported hypothesis untested.
        for faulty_index, expected_function in faulty_targets:
            self._check_cancelled()
            try:
                patch_item = (await self._get_patch_item(faulty_index) if expected_function is None else
                              await self._get_patch_item(faulty_index, expected_function=expected_function))
            except Exception as exc:
                return self._stop_error(exc, "source_lookup", "patch_source_lookup_error")
            self._check_cancelled()
            if not isinstance(patch_item, dict) or not patch_item:
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  f"Source mapping is unavailable for trace target {faulty_index}; replay was not started.")
            source_target = patch_item.get('source_target')
            if isinstance(source_target, dict) and source_target.get('status') == 'unresolved':
                stopped = self._stop('blocked', 'preconditions', 'unmappable_patch_target',
                    f'声明函数 {expected_function} 无法与这笔交易已执行的源码唯一对应；尚未生成或回放补丁。')
                self.verification['source_target_diagnostic'] = deepcopy(source_target)
                return stopped
            address = patch_item.get("address")
            if not isinstance(address, str) or not address.strip():
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  "A patch target has no contract address; replay was not started.")
            resolved_index = patch_item.get('resolved_trigger_index')
            if resolved_index is not None:
                if type(resolved_index) is not int or resolved_index < 0:
                    return self._stop('blocked', 'preconditions', 'unmappable_patch_target',
                                      'The source target has an invalid observed trace position.')
                original_index = faulty_index
                faulty_index = f"{faulty_index.rsplit('::', 1)[0]}::{resolved_index}"
                self._patch_source_resolutions.append({
                    'expected_function': expected_function, 'requested_trigger': original_index,
                    'resolved_trigger': faulty_index, 'address': address.lower(),
                    'source_mapping': deepcopy(patch_item.get('source_mapping')),
                })
            self._patch_trigger_transactions.setdefault(address.lower(), set()).add(faulty_index.rsplit('::', 1)[0].lower())
            contract_info = patch_item.get("contract_info")
            if not isinstance(contract_info, list) or not any(
                    isinstance(file, dict) and isinstance(file.get('source'), str) and file['source'].strip()
                    for file in contract_info):
                source_lookup = patch_item.get("source_lookup")
                if isinstance(source_lookup, dict) and source_lookup.get("status") in {"failed", "unverified"}:
                    failed = source_lookup["status"] == "failed"
                    code = "source_fetch_failed" if failed else "source_not_verified"
                    reason = (f"合约 {address} 的源码获取失败，尚不能确认源码是否公开；请检查区块浏览器连接或稍后重试。"
                              if failed else f"区块浏览器尚未提供合约 {address} 的已验证源码；补丁生成与回放已停止。")
                    stopped = self._stop("blocked", "source_lookup" if failed else "preconditions", code, reason)
                    self.verification["source_lookup"] = {
                        "address": address, "status": source_lookup["status"], "reason_code": code,
                    }
                    for field in ('refresh_attempted', 'refresh_reason_code'):
                        if field in source_lookup:
                            self.verification["source_lookup"][field] = source_lookup[field]
                    self.verification["retryable"] = failed and source_lookup.get("retryable") is True
                    self.verification["next_action"] = "retry_source_lookup" if failed else "provide_verified_source"
                    return stopped
                return self._stop("blocked", "preconditions", "missing_source",
                                  f"Source code is unavailable for contract {address}; automatic patching and replay were stopped.")

            full_file_map, sources = {}, {}
            for file_info in contract_info:
                if (not isinstance(file_info, dict)
                        or not isinstance(file_info.get("path"), str) or not file_info["path"].strip()
                        or not isinstance(file_info.get("source"), str) or not file_info["source"].strip()):
                    return self._stop("blocked", "preconditions", "missing_source",
                                      f"Source files are incomplete for contract {address}; automatic patching and replay were stopped.")
                file_id = file_info.get("id")
                if file_id is None or str(file_id) in full_file_map or file_info["path"] in sources:
                    return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                      f"Source file mapping is incomplete or ambiguous for contract {address}.")
                full_file_map[str(file_id)] = dict(file_info)
                sources[file_info["path"]] = file_info["source"]
            target_file_info = full_file_map.get(str(patch_item.get("file_index")))
            if target_file_info is None:
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  f"The trace target cannot be mapped to a source file for contract {address}.")
            if address in address2contracts and address2contracts[address].sources != sources:
                return self._stop("blocked", "preconditions", "unmappable_patch_target",
                                  f"Conflicting source mappings were returned for contract {address}.")
            if address not in address2contracts:
                address2contracts[address] = ContractEntityForCompile.from_dict({
                    **patch_item, "full_file_map": full_file_map, "sources": sources,
                })
            unique_id = f"{address}::{target_file_info['path']}"
            uid2source[unique_id] = target_file_info["source"]
            uid2faults.setdefault(unique_id, []).append(faulty_index)

        format_contracts = self.get_format_contracts(uid2faults, uid2source, address2contracts)
        original_compile_results, on_chain_bytecodes = {}, {}
        if verify:
            try:
                # Source mapping may locate the fault in a transaction that the
                # initial attack classifier labelled auxiliary. Validate the
                # complete selection before compilation or paid execution.
                self._replay_selection()
            except Exception as exc:
                return self._stop_error(exc, "replay_preparation", "replay_preparation_error")
            try:
                original_compile_results = await self._load_compile_result(address2contracts)
                self._check_cancelled()
                failures = []
                for address in address2contracts:
                    original_item = original_compile_results.get(address)
                    if not original_item or not original_item.bytecode or len(original_item.bytecode) <= 2:
                        raw_errors = getattr(original_item, 'errors', []) or []
                        missing = bool(raw_errors) and all(isinstance(error, dict)
                            and error.get('reason_code') == 'compiler_unavailable' for error in raw_errors)
                        failures.append({
                            'address': address, 'contract_name': address2contracts[address].contract_name,
                            'compiler_version': address2contracts[address].compiler_version,
                            'reason_code': 'compiler_unavailable' if missing else 'original_compile_failed',
                            'errors': [{'severity': error.get('severity', 'error') if isinstance(error, dict) else 'error',
                                        'message': redact_text(str(error.get('formattedMessage') or error.get('message') or 'Unknown compiler error')
                                                               if isinstance(error, dict) else str(error))[:1000]}
                                       for error in raw_errors[:8]],
                        })
                if failures:
                    return self._stop_original_compile(failures)
            except Exception as exc:
                return self._stop_error(exc, "compile", "patch_preparation_error")
            try:
                on_chain_bytecodes = await self._load_runtime_bytecode(list(address2contracts))
                self._check_cancelled()
            except Exception as exc:
                return self._stop_error(exc, "runtime_generation", "runtime_generation_error")
            if any(not self._valid_runtime_bytecode(on_chain_bytecodes.get(address))
                   for address in address2contracts):
                return self._stop("blocked", "runtime_generation", "missing_runtime_bytecode",
                                  "Original contract bytecode is unavailable; replay was not started.")
            try:
                for address, original_item in original_compile_results.items():
                    BytecodeTransplanter.validate_original(original_item, on_chain_bytecodes[address])
                    BytecodeTransplanter._storage_signature(original_item)
            except RuntimeIntegrityError as exc:
                return self._stop_error(exc, "runtime_generation", exc.reason_code)

        patches, last_error = "", fault_data.get("fix_feedback") or ""
        retry_count = 0
        while retry_count < FIX_TURN:
            self._check_cancelled()
            if getattr(self, '_patch_generation_requests', 0) >= MAX_PATCH_GENERATION_REQUESTS:
                return self._stop_generation_budget(patches=patches, retry_count=retry_count)
            self._set_verification("unverified", "patch_generation", "patch_generation_pending",
                                   "Patch generation is in progress; replay has not started.")
            try:
                prompt = FIX_UP if not last_error else FIX_FIX_UP
                patches = ""
                self._patch_generation_requests = getattr(self, '_patch_generation_requests', 0) + 1
                self.verification['patch_generation_budget'].update(
                    requests_used=self._patch_generation_requests,
                    remaining_requests=MAX_PATCH_GENERATION_REQUESTS - self._patch_generation_requests,
                )
                proposal = await self.query(prompt.format(
                    fault_report=fault_data.get("fault_report", ""),
                    final_trace=fault_data.get("final_trace", ""),
                    fix_report=json.dumps({**fix_report, 'verification_plan': self._verification_plan},
                                          ensure_ascii=False) if self._verification_plan is not None
                               else fault_data.get("fix_report", ""),
                    contract_code=format_contracts, last_error=last_error,
                ), _format="str", temperature=1.0)
                parse_success, parse_logs, patched_contracts = SolidityCodePatcher(uid2source).apply_patches(proposal)
            except Exception as exc:
                return self._stop_error(exc, "patch_generation", "patch_generation_error",
                                        patches=patches, retry_count=retry_count)
            self._check_cancelled()
            changed_sources = isinstance(patched_contracts, dict) and any(
                isinstance(code, str) and file_id in uid2source
                and code.splitlines() != uid2source[file_id].splitlines()
                for file_id, code in patched_contracts.items()
            )
            if not parse_success or not changed_sources:
                retry_count += 1
                last_error = f"Patch application failed or changed no source code: {parse_logs}"
                self._set_verification("unverified", "patch_generation", "patch_application_failed",
                                       "No applicable source change was generated; replay has not started.")
                continue
            patches = build_applied_patch_record(uid2source, patched_contracts)
            self._last_applied_patches = patches
            patch_digest = hashlib.sha256(patches.encode()).hexdigest()
            if verify and patch_digest in self._rejected_patch_candidates:
                rejection = self._rejected_patch_candidates[patch_digest]
                retry_count += 1
                last_error = self._reject_runtime_candidate(
                    patch_digest, rejection['reason_code'], rejection['reason'],
                )
                continue
            replay_key = (patch_digest, getattr(self, '_replay_scope', ()))
            if getattr(self, '_verification_plan', None) is not None:
                from app.attackpilot.utils.security_checks import plan_digest
                replay_key += (plan_digest(self._verification_plan),)
            previous_scopes = [set(key[1]) for key in self._replayed_patch_digests
                               if isinstance(key, tuple) and len(key) == len(replay_key)
                               and key[0] == patch_digest and key[2:] == replay_key[2:]]
            already_tested = (patch_digest in self._replayed_patch_digests or previous_scopes
                              and not set().union(*previous_scopes) < set(replay_key[1]))
            if verify and already_tested:
                retry_count += 1
                last_error = (
                    "This exact applied patch was already replayed for the same original transactions "
                    "and did not produce confirmed interception. Revise the implementation or add "
                    "an evidenced trigger while preserving all previous replay inputs; do not repeat, "
                    "shrink, or replace the same patch's replay scope."
                )
                self._set_verification("unverified", "patch_generation", "duplicate_patch", last_error)
                continue
            updated_contracts = self._update_contracts_with_patch(address2contracts, patched_contracts)
            try:
                compile_success, compile_result_or_error = await self.compile_patched_codes(updated_contracts)
            except Exception as exc:
                return self._stop_error(exc, "compile", "patch_compile_error",
                                        patches=patches, retry_count=retry_count)
            self._check_cancelled()
            if compile_success and (not isinstance(compile_result_or_error, dict)
                                    or set(compile_result_or_error) != set(updated_contracts)):
                compile_success, compile_result_or_error = False, "Compilation returned incomplete contract results."
            if self.metrics_collector:
                self.metrics_collector.record_compile_status(self.unique_id, compile_success)
            if not compile_success:
                retry_count += 1
                last_error = f"Compilation failed: {compile_result_or_error}"
                self._set_verification("unverified", "compile", "patch_compile_failed",
                                       "The generated patch did not compile; replay has not started.")
                continue
            if not verify:
                reason = "Patch compiled; replay verification was not requested."
                self._set_verification("skipped", "compile", "verification_disabled", reason, terminal=True)
                return True, reason, patches, retry_count

            addr2runtime_bytecode = {}
            runtime_integrity = {
                "schema_version": 1, "status": "validated", "applied_patch_sha256": patch_digest,
                "contracts": {},
            }
            runtime_rejection = None
            for address, patched_compile_item in compile_result_or_error.items():
                self._check_cancelled()
                is_ok, final_bytecode, diagnostic = BytecodeTransplanter.transplant(
                    original_compile_item=original_compile_results.get(address),
                    on_chain_runtime_bytecode_hex=on_chain_bytecodes.get(address),
                    patched_compile_item=patched_compile_item,
                )
                if not is_ok or not self._valid_runtime_bytecode(final_bytecode):
                    # Constructor simulation cannot repair a provenance or layout
                    # mismatch: it may initialize a different state altogether.
                    code = diagnostic.split(":", 1)[0] if not is_ok else "runtime_generation_failed"
                    if code not in {"original_runtime_mismatch", "storage_layout_unavailable",
                                    "storage_layout_changed", "immutable_layout_mismatch", "constructor_or_immutable_changed"}:
                        code = "runtime_generation_failed"
                    reason = f"Contract {address}: {diagnostic}; no attack replay was executed."
                    if code in REPAIRABLE_RUNTIME_REJECTIONS:
                        runtime_rejection = code, reason
                        break
                    return self._stop("blocked", "runtime_generation", code,
                                      reason,
                                      patches=patches, retry_count=retry_count)
                historical_code = BytecodeTransplanter._code(on_chain_bytecodes[address])
                patched_code = BytecodeTransplanter._code(final_bytecode)
                original_end, _ = BytecodeTransplanter._metadata(historical_code)
                patched_end, _ = BytecodeTransplanter._metadata(patched_code)
                if historical_code[:original_end] == patched_code[:patched_end]:
                    runtime_rejection = (
                        'patch_runtime_unchanged',
                        f"Contract {address}: applied source edits do not change executable runtime; no attack replay was executed.",
                    )
                    break
                addr2runtime_bytecode[address] = final_bytecode
                runtime_integrity["contracts"][address.lower()] = {
                    "original_runtime_sha256": hashlib.sha256(historical_code).hexdigest(),
                    "original_compiled_runtime_sha256": hashlib.sha256(BytecodeTransplanter._code(original_compile_results[address].bytecode)).hexdigest(),
                    "patched_runtime_sha256": hashlib.sha256(patched_code).hexdigest(),
                    "storage_layout_checked": True, "immutable_checked": True,
                }
            if runtime_rejection is not None:
                retry_count += 1
                last_error = self._reject_runtime_candidate(patch_digest, *runtime_rejection)
                continue
            self._runtime_integrity = runtime_integrity
            patch_attribution = build_patch_attribution(
                address2contracts, updated_contracts, compile_result_or_error,
                addr2runtime_bytecode, patches,
            )

            try:
                tenderly_transactions = await self.prepare_bundle_data()
                self._check_cancelled()
            except Exception as exc:
                return self._stop_error(exc, "replay_preparation", "replay_preparation_error",
                                        patches=patches, retry_count=retry_count)
            if not isinstance(tenderly_transactions, list) or not tenderly_transactions:
                return self._stop("blocked", "replay_preparation", "no_replay_transactions",
                                  "No original attack transactions are available for replay.",
                                  patches=patches, retry_count=retry_count)
            self._set_verification("unverified", "replay", "replay_pending",
                                   "The patched transaction replay has started; its outcome is not yet established.",
                                   replay_attempted=True)
            try:
                self._replayed_patch_digests.add(replay_key)
                execution_success, replay_logs = await self.run_patch_verification_from_tenderly(
                    tenderly_transactions, addr2runtime_bytecode)
                self._check_cancelled()
            except Exception as exc:
                return self._stop_error(exc, "replay", "replay_service_error", patches=patches,
                                        retry_count=retry_count, replay_attempted=True)
            if isinstance(replay_logs, dict):
                replay_logs["runtime_integrity"] = runtime_integrity
                replay_logs["patch_attribution"] = patch_attribution
                replay_logs["required_trigger_transaction_hashes"] = list(self._required_replay_triggers)
                self.replay_evidence = replay_logs
            if not execution_success:
                stopped = self._stop("error", "replay", "replay_service_error",
                                  replay_logs if isinstance(replay_logs, str) and replay_logs else
                                  "The replay service did not return usable execution evidence; patch effectiveness is unknown.",
                                  patches=patches, retry_count=retry_count, replay_attempted=True)
                return (stopped[0], replay_logs, stopped[2], stopped[3]) if isinstance(replay_logs, dict) else stopped
            if (not isinstance(replay_logs, dict) or replay_logs.get("schema_version") not in (1, 2)
                    or replay_logs.get("status") != "completed"
                    or replay_logs.get("control_validation") != "validated"
                    or not isinstance(replay_logs.get("transactions"), list)
                    or not replay_logs["transactions"]):
                return self._stop("error", "replay", "invalid_replay_response",
                                  "The replay service returned no execution evidence; patch effectiveness is unknown.",
                                  patches=patches, retry_count=retry_count, replay_attempted=True)
            replay_logs["applied_patch_sha256"] = hashlib.sha256(patches.encode()).hexdigest()
            self.replay_evidence = replay_logs
            # An EVM revert is completed execution. The coordinator's evidence
            # gate must constrain the model's interpretation of effectiveness.
            self._set_verification("unverified", "replay", "replay_completed_pending_review",
                                   "Patched execution evidence is available and awaits effectiveness review.",
                                   replay_attempted=True, replay_completed=True)
            return True, replay_logs, patches, retry_count

        # Local generation/compile retries are already exhausted. Repeating the
        # same preconditions in another outer loop cannot add execution proof.
        if self._patch_generation_requests >= MAX_PATCH_GENERATION_REQUESTS:
            return self._stop_generation_budget(patches=patches, retry_count=retry_count)
        self.verification.update(terminal=True, retryable=False, next_action="inspect_patch_generation")
        return False, self.verification["reason"], patches, retry_count

    def _update_contracts_with_patch(
            self,
            original_contracts: Dict[str, ContractEntityForCompile],
            patched_contracts: Dict[str, str]
    ) -> Dict[str, ContractEntityForCompile]:
        import copy
        contracts_copy = copy.deepcopy(original_contracts)
        changed_addresses = set()

        for unique_id, patched_code in patched_contracts.items():
            if "::" not in unique_id: continue
            addr, file_path = unique_id.split("::", 1)

            if not isinstance(patched_code, str):
                continue

            if addr in contracts_copy:
                entity = contracts_copy[addr]
                if not entity.sources or file_path not in entity.sources or entity.sources[file_path].splitlines() == patched_code.splitlines():
                    continue
                changed_addresses.add(addr)

                if entity.full_file_map:
                    for file_id, file_info in entity.full_file_map.items():
                        if file_info.get("path") == file_path:
                            entity.full_file_map[file_id]["source"] = patched_code

                if entity.sources and file_path in entity.sources:
                    entity.sources[file_path] = patched_code
        return {address: contracts_copy[address] for address in changed_addresses}

    def _replay_selection(self):
        """Keep every submitted step, including preparations labelled auxiliary."""
        tx_list = self.processed_data.get("transaction_hash_list", [])
        tx2detail = self.processed_data.get("transaction_to_detail", {})
        candidates = self.processed_data.get("attack_transactions", [])
        triggers = getattr(self, "_patch_trigger_transactions", {})
        if (not isinstance(tx_list, list) or not isinstance(tx2detail, dict)
                or not isinstance(candidates, list) or not isinstance(triggers, dict)
                or any(not isinstance(group, (set, list, tuple)) for group in triggers.values())):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'replay_selection'})
        required = {tx for group in triggers.values() for tx in group}
        requested = list(tx_list) + list(candidates) + list(required)
        if any(not isinstance(tx, str) or re.fullmatch(r'0x[0-9a-fA-F]{64}', tx) is None
               for tx in tx_list + requested + list(tx2detail)):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'original_transaction_hash'})
        ordered = list(dict.fromkeys(tx.lower() for tx in tx_list))
        details = {tx.lower(): detail for tx, detail in tx2detail.items()}
        if len(details) != len(tx2detail):
            raise HistoricalReplayValidationError('inconsistent', 'context_mismatch',
                                                  details={'field': 'replay_selection'})
        required = {tx.lower() for tx in required}
        selected = {tx.lower() for tx in requested}
        if (not selected.issubset(ordered)
                or any(not isinstance(details.get(tx), dict) for tx in selected)):
            raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                  details={'field': 'required_replay_transaction'})
        if len(selected) > MAX_REPLAY_TRANSACTIONS:
            raise PatchReplayBudgetError(transaction_limit=True)
        # Changing only candidate order must not bypass duplicate protection;
        # adding a newly located trigger permits the same patch to be measured.
        self._replay_scope = tuple(sorted(selected))
        self._required_replay_triggers = [tx for tx in ordered if tx in required]
        return [(tx, details[tx]) for tx in ordered if tx in selected]

    def _resolve_verification_plan(self, fix_report):
        from app.attackpilot.utils.security_checks import resolve_task_verification_plan
        dapp = self.processed_data.get('dapp') or {}
        explicit = dapp.get('verification_plan', self.processed_data.get('verification_plan'))
        known = self.processed_data.get('transaction_hash_list') or dapp.get('transaction_hash') or []
        proposed = fix_report.get('verification_plan')
        if proposed is None and explicit is None:
            return None
        return resolve_task_verification_plan(proposed, explicit=explicit, network_id=self.chain_id,
                                              transaction_hashes=known)

    async def _prepare_normal_regression_contexts(self):
        """Fetch explicitly declared normal inputs, outside attack classification."""
        from app.attackpilot.utils.replay_validation import validate_original_transaction
        plan = getattr(self, '_verification_plan', None)
        cases = plan.get('normal_regression_cases', []) if isinstance(plan, dict) else []
        hashes = list(dict.fromkeys(tx for case in cases for tx in case['transaction_hashes']))
        blocks = []
        for transaction_hash in hashes:
            self._check_cancelled()
            rpc_url = await self.rpc_bucket.get()
            transaction = await TxDownloader(rpc_url=rpc_url).download(transaction_hash=transaction_hash)
            self._check_cancelled()
            receipt = await TxReceiptDownloader(rpc_url=rpc_url).download(transaction_hash=transaction_hash)
            self._check_cancelled()
            context = validate_original_transaction(transaction_hash, self.chain_id, transaction, receipt)
            blocks.append(context['block_number'])
        if blocks:
            timestamps = await self._load_transaction_time(list(dict.fromkeys(blocks)))
            self._check_cancelled()
            if any(type(timestamps.get(block)) is not int or timestamps[block] < 0 for block in blocks):
                raise ValueError('正常业务回归缺少经过校验的历史区块时间戳')

    async def prepare_bundle_data(self):
        selection = self._replay_selection()
        await self._prepare_normal_regression_contexts()
        block_numbers = list(dict.fromkeys(detail["block_number"] for _, detail in selection))
        block2time = await self._load_transaction_time(block_numbers)
        tenderly_transactions = []
        for tx, detail in selection:
            block = detail["block_number"]
            timestamp = block2time.get(block)
            if type(timestamp) is not int or timestamp < 0:
                raise ValueError(f"Failed to fetch timestamp for block {block}; replay was not started.")
            # Do not mutate classification or the saved original detail. The
            # DAO still validates this identity against the task's RPC cache.
            tenderly_transactions.append({**detail, "original_transaction_hash": tx, "timestamp": timestamp})
        return tenderly_transactions

    async def run_patch_verification_from_tenderly(self, transactions, addr2bytecode):
        dao = BundleTenderlyDao(_platform=self._platform)
        plan = getattr(self, '_verification_plan', None)
        try:
            budget = self._preflight_replay_budget(dao, transactions, addr2bytecode,
                                                   verification_plan=plan)
        except Exception as exc:
            # A preflight failure precedes every paid request, including an
            # invalid source context rather than only an exhausted budget.
            exc.replay_attempted = False
            raise
        arguments = {'verification_plan': deepcopy(plan)} if plan is not None else {}
        verification_success, verification_result = await dao.bundle_simulate_txs_in_tenderly(
            transactions, addr2bytecode, **arguments)
        planned = budget.get('planned_requests', 2 * len(transactions))
        self._last_replay_request_budget = {
            "max_requests_per_task": MAX_REPLAY_REQUESTS,
            "max_transactions": MAX_REPLAY_TRANSACTIONS,
            "new_requests_this_round": budget['required_requests'],
            "reused_requests_this_round": planned - budget['required_requests'],
            "remaining_requests": budget['remaining_requests'] - budget['required_requests'],
        }
        if isinstance(verification_result, dict):
            verification_result.setdefault('request_budget', {}).update(self._last_replay_request_budget)
        return verification_success, verification_result

    @staticmethod
    def _preflight_replay_budget(dao, transactions, addr2bytecode, verification_plan=None):
        """Do not start a paid round that cannot finish all independent pairs.

        Historical controls are immutable and reused across source revisions;
        only cache misses consume the fixed task budget. Reservations in the
        DAO remain the final atomic limit when a request is actually sent.
        """
        estimate = getattr(type(dao), 'estimate_replay_budget', None)
        if callable(estimate):
            return dao.estimate_replay_budget(
                transactions, addr2bytecode, verification_plan=verification_plan)
        if dao.chain_id is None or not isinstance(transactions, list) or not transactions:
            raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
        if len(transactions) > MAX_REPLAY_TRANSACTIONS:
            error = PatchReplayBudgetError(transaction_limit=True)
            error.replay_attempted = False
            raise error
        overrides = runtime_overrides(addr2bytecode)
        missing, seen = 0, set()
        for detail in transactions:
            if not isinstance(detail, dict):
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
            original_hash = detail.get('original_transaction_hash') or detail.get('hash')
            context, original = dao.evidence_store.original_context(original_hash, dao.chain_id)
            if context['transaction_hash'] in seen:
                raise TenderlyAPIError('simulate_bundle', error_code='invalid_request')
            seen.add(context['transaction_hash'])
            for changes in (None, overrides):
                if dao.evidence_store.cached_response(historical_payload(context, original, changes)) is None:
                    missing += 1
        occupied = sum((dao.evidence_store.root / 'requests' / f'{number:02}.json').exists()
                       for number in range(1, MAX_REPLAY_REQUESTS + 1))
        remaining = MAX_REPLAY_REQUESTS - occupied
        if missing > remaining:
            error = PatchReplayBudgetError()
            error.replay_attempted = False
            error.required_requests, error.remaining_requests = missing, remaining
            raise error
        return {'required_requests': missing, 'remaining_requests': remaining}

    async def compile_patched_codes(self, patched_contracts):
        """
        compile patched contracts
        """
        if not isinstance(patched_contracts, dict) or not patched_contracts:
            return False, "Patched contract is none. Patch application is wrong."

        for addr, entity in patched_contracts.items():
            if not entity:
                return False, f"Pre-compile Check Failed: Entity for address {addr} is None."

            if not hasattr(entity, 'sources') or not entity.sources:
                return False, f"Pre-compile Check Failed: Contract {addr} has no 'sources' dictionary. It might be an unverified contract."

            if any(not isinstance(source_code, str) or not source_code.strip()
                   for source_code in entity.sources.values()):
                return False, (
                    f"Pre-compile Check Failed: Contract {addr} contains file entries but source code is empty. "
                    f"This usually happens when attempting to patch a Bytecode-Only contract.")

        addr2compile = await self._load_compile_result(patched_contracts)
        if not isinstance(addr2compile, dict) or set(addr2compile) != set(patched_contracts):
            return False, "Compilation returned incomplete contract results."

        for addr, compile_item in addr2compile.items():
            if compile_item is None:
                return False, f"Compilation returned no result for address: {addr}"
            has_bytecode = compile_item.bytecode and len(compile_item.bytecode) > 2 \
                           and compile_item.creation_bytecode and len(compile_item.creation_bytecode) > 2

            if not has_bytecode:
                error_lines = [f"Compilation failed for address: {addr}"]
                if compile_item.errors:
                    for err in compile_item.errors:
                        if isinstance(err, str):
                            error_lines.append(err)
                            continue
                        msg = err.get("formattedMessage") or err.get("message", "Unknown Error")
                        severity = err.get("severity", "unknown")
                        error_lines.append(f"[{severity.upper()}] {msg}")
                else:
                    error_lines.append("Reason: Unknown (No bytecode generated and no error logs returned).")
                return False, "\n".join(error_lines)
        return True, addr2compile

    async def _load_compile_result(self, address2contracts) -> Dict[str, ContractCompileItem]:
        async def _create_task(_contracts: ContractEntityForCompile):
            return await ContractDao(downloader=ContractSourceDownloader(apikey="")).get_compile_item_from_entity(
                _contracts)

        tasks = [_create_task(contracts) for addr, contracts in address2contracts.items()]
        result = await asyncio.gather(*tasks)
        return {addr: result[i] for i, addr in enumerate(address2contracts.keys())}

    async def _load_transaction_time(self, block_numbers: List[Union[int, str]]) -> Dict[Union[int, str], int]:
        unique_blocks = list(set(block_numbers))

        async def _create_task(block_number):
            ts = await BlockTimestampDownloader(
                rpc_url=await self.rpc_bucket.get(),
            ).download(block_number=block_number)
            return block_number, ts

        tasks = [_create_task(bn) for bn in unique_blocks]
        results = await asyncio.gather(*tasks)
        return {bn: ts for bn, ts in results}

    def _validated_runtime_context(self, store, transaction_hash):
        """Recheck cached original replay provenance before using its contracts."""
        context, _ = store.original_context(transaction_hash, self.chain_id)
        details = self.processed_data.get('transaction_to_detail', {})
        detail = details.get(transaction_hash, {}) if isinstance(details, dict) else {}
        baseline = detail.get('baseline_validation') if isinstance(detail, dict) else None
        receipt_digest = hashlib.sha256(json.dumps({
            key: context[key] for key in ('transaction_hash', 'chain_id', 'block_hash', 'block_number',
                                         'transaction_index', 'status', 'gas_used', 'logs')
        }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected = {
            'schema_version': 1, 'status': 'validated', 'method': 'rpc_receipt_vs_tenderly_original_replay',
            'original_transaction_hash': context['transaction_hash'], 'network_id': str(context['chain_id']),
            'block_number': context['block_number'], 'block_hash': context['block_hash'],
            'transaction_index': context['transaction_index'], 'receipt_status': context['status'],
            'gas_used': context['gas_used'], 'log_count': len(context['logs']), 'receipt_digest': receipt_digest,
            'ordered_logs_sha256': hashlib.sha256(json.dumps(context['logs'], separators=(',', ':')).encode()).hexdigest(),
        }
        if (not isinstance(baseline, dict) or type(baseline.get('schema_version')) is not int
                or any(baseline.get(key) != value for key, value in expected.items())):
            raise HistoricalRuntimeError('historical_runtime_context_mismatch')
        simulation_id = baseline.get('simulation_id')
        if simulation_id is None:
            return context, None
        if not isinstance(simulation_id, str) or re.fullmatch(r'[a-zA-Z0-9-]{1,128}', simulation_id) is None:
            raise HistoricalRuntimeError('historical_runtime_context_mismatch')
        path = Path(store.cache_root) / 'trace' / 'simulation_result' / f'{simulation_id}.json'
        try:
            full_result = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return context, None
        except (OSError, ValueError, UnicodeDecodeError):
            raise HistoricalRuntimeError('historical_runtime_context_mismatch') from None
        validated = validate_simulated_transaction(context, full_result)
        if (validated.get('simulation_id') != simulation_id
                or any(validated.get(key) != value for key, value in expected.items())
                or full_result.get('simulation', {}).get('state_objects')):
            raise HistoricalRuntimeError('historical_runtime_context_mismatch')
        return context, full_result

    async def _load_runtime_bytecode(self, contract_addresses: List[str]) -> Dict[str, str]:
        triggers = getattr(self, '_patch_trigger_transactions', {})
        if any(not triggers.get(address.lower()) for address in contract_addresses):
            raise HistoricalRuntimeError('historical_runtime_unavailable')
        store = PatchReplayEvidenceStore()
        transactions = set(self.processed_data.get('attack_transactions') or [])
        transactions.update(tx for group in triggers.values() for tx in group)
        contexts = {tx: self._validated_runtime_context(store, tx) for tx in sorted(transactions)}
        self._runtime_source_evidence = {}
        historical_codes = {}
        result = {}
        for address in contract_addresses:
            target = address.lower()
            versions, evidence = set(), []
            self._runtime_source_evidence[target] = evidence
            for tx_hash, (context, full_result) in contexts.items():
                contracts = full_result.get('contracts', []) if isinstance(full_result, dict) else []
                if not isinstance(contracts, list):
                    raise HistoricalRuntimeError('historical_runtime_context_mismatch')
                matches = [item for item in contracts if isinstance(item, dict)
                           and isinstance(item.get('address'), str) and item['address'].lower() == target]
                observed = {str(context.get('to')).lower()}
                if isinstance(full_result, dict):
                    trace = trace_summary(full_result.get('transaction', {}).get('transaction_info', {}), [])
                    observed.update(trace.get('call_targets', []))
                if tx_hash not in triggers[target] and not matches and target not in observed:
                    continue
                code = None
                for contract in matches:
                    candidate = contract.get('deployed_bytecode')
                    if candidate in (None, '', '0x'):
                        continue
                    if (str(contract.get('network_id')) != str(context['chain_id'])
                            or not self._valid_runtime_bytecode(candidate)):
                        raise HistoricalRuntimeError('historical_runtime_context_mismatch')
                    candidate = '0x' + candidate.removeprefix('0x').lower()
                    if code is not None and code != candidate:
                        raise HistoricalRuntimeError('historical_runtime_conflict')
                    code = candidate
                from_simulation = code is not None
                if code is None:
                    quantity = hex(context['block_number'])
                    cache_key = (target, quantity)
                    if cache_key not in historical_codes:
                        historical_codes[cache_key] = await ContractBytecodeDownloader(
                            rpc_url=await self.rpc_bucket.get(),
                        ).download(contract_address=target, quantity=quantity)
                    code = historical_codes[cache_key]
                    if not self._valid_runtime_bytecode(code):
                        raise HistoricalRuntimeError('historical_runtime_unavailable')
                    code = '0x' + code.removeprefix('0x').lower()
                versions.add(code)
                evidence.append({
                    'original_transaction_hash': tx_hash, 'network_id': str(context['chain_id']),
                    'block_number': context['block_number'], 'transaction_index': context['transaction_index'],
                    'simulation_id': full_result['simulation']['id'] if from_simulation else None,
                    'source': 'validated_original_simulation' if from_simulation else 'historical_block_rpc',
                    'scope': 'original_transaction_context' if from_simulation else 'historical_block_end',
                    'transaction_state_verified': from_simulation,
                    'bytecode_sha256': hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(),
                })
                if len(versions) > 1:
                    raise HistoricalRuntimeError('historical_runtime_conflict')
            if not versions:
                raise HistoricalRuntimeError('historical_runtime_unavailable')
            result[address] = versions.pop()
        return result

    def get_format_contracts(self, uid2faults: Dict[str, List], uid2source: Dict[str, str],
                             address2contracts: Dict[str, ContractEntityForCompile]):
        lines = ["=" * 60]
        for unique_id, source_code in uid2source.items():
            fault_indexes = uid2faults.get(unique_id, [])
            contract = address2contracts[unique_id.split('::', 1)[0]]
            # Match ContractDao's effective settings; a pragma alone cannot
            # identify the deployed compiler or its optimizer/EVM options.
            compiler_settings = contract.compiler_settings or {}
            if compiler_settings:
                optimizer = compiler_settings.get('optimizer', {'enabled': False, 'runs': 200})
                evm_version = compiler_settings.get('evmVersion') or 'compiler default'
            else:
                optimizer = {'enabled': contract.optimizations_used,
                             'runs': contract.optimization_runs or 200}
                evm_version = contract.evm_version or 'compiler default'
                if str(evm_version).lower() == 'default':
                    evm_version = 'compiler default'
            lines.append(f"# File: {unique_id}")
            lines.append('Compilation target: ' + json.dumps({
                'compiler_version': contract.compiler_version,
                'evm_version': evm_version,
                'optimizer': optimizer,
            }, ensure_ascii=False, sort_keys=True))
            lines.append(f"Faulty functions in this file: {fault_indexes}")
            lines.append("-" * 20)
            lines.append(source_code)
            lines.append("=" * 60)
            lines.append("\n")
        return "\n".join(lines)

    def process_fix_report(self, fix_report) -> Tuple[bool, Dict]:
        if fix_report is None:
            return False, {}
        if isinstance(fix_report, dict):
            return True, fix_report
        fix_report = (
            str(fix_report)
            .replace('\xa0', ' ')
            .replace('\r\n', '\n')
            .replace('\u200b', '')
            .strip()
        )
        parse_result = self.parser.process_response(fix_report, _format="json")
        if not isinstance(parse_result, dict):
            return self.final_process(parse_result)
        if "result" in parse_result:
            return self.final_process(parse_result["result"])
        return True, parse_result

    def final_process(self, parse_result):
        if isinstance(parse_result, dict):
            return True, parse_result
        try:
            parse_result = json.loads(parse_result)
        except (TypeError, ValueError):
            try:
                parse_result = ast.literal_eval(parse_result)
            except Exception:
                return False, "can't parse fix report"
        return isinstance(parse_result, dict), parse_result
