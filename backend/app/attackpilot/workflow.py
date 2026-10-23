import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Union, List, Tuple, Callable, Optional
from app.attackpilot.agents.TraceAgent import TraceAgent
from app.attackpilot.mcp_tools.mcp_client import MCPClient, MCPToolError
from app.attackpilot.process.analyze import DAppAnalyze
from app.attackpilot.process.pyg import DAppProcess
from app.attackpilot.settings import PROJECT_PATH, WORK_ROOT, SCAN_APIKEYS, JSONRPCS, MCP_SERVER_PATH, PLATFORM_TO_CHAIN_ID
from app.attackpilot.utils.bucket import AsyncItemBucket
from app.attackpilot.utils.patch_quality_metrics import PatchQualityMetrics
from app.attackpilot.web.models import LogMessage
from app.attackpilot.errors import (failure_message, exception_chain, AgentContractError,
                                    EvidencePersistenceError, HistoricalReplayContextError,
                                    HistoricalReplayValidationError)
from app.attackpilot.utils.verification import verification_state
from app.attackpilot.utils.price import pricing_policy_fingerprint, collect_price_evidence, price_evidence_retryable, price_quote_scope
from app.attackpilot.privacy import redact_text

DEFAULT_ENABLED_MODULES = {
    "attack_detection",
    "fault_localization",
    "rag_retrieval",
    "patch_generation",
    "patch_verification",
}
REPORT_POLICY_VERSION = 18
ANALYSIS_POLICY_VERSION = 11


def normalize_enabled_modules(dapp: dict) -> set:
    from app.attackpilot.schemas import normalize_modules
    return set(normalize_modules(dapp.get("enabled_modules")))


def request_fingerprint(dapp: dict) -> str:
    request = {**dapp, "enabled_modules": sorted(normalize_enabled_modules(dapp)),
               "analysis_policy_version": ANALYSIS_POLICY_VERSION,
               "pricing_policy": pricing_policy_fingerprint()}
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validated_baselines(data: dict, dapp: dict) -> dict:
    """Legacy processed data/reports must not bypass the original-replay gate."""
    txs = dapp.get("transaction_hash") or []
    network_id = PLATFORM_TO_CHAIN_ID.get(dapp.get("platform"))
    if not isinstance(data, dict) or not isinstance(txs, list) or not txs or network_id is None:
        return {}
    if data.get("request_fingerprint") != request_fingerprint(dapp):
        return {}
    details = data.get("transaction_to_detail") or {}
    report_evidence = data.get("baseline_validation") or {}
    if not isinstance(details, dict) or not isinstance(report_evidence, dict):
        return {}
    saved = report_evidence.get("transactions") or {}
    if not isinstance(saved, dict):
        return {}
    result = {}
    for tx in txs:
        if not isinstance(tx, str):
            return {}
        detail = details.get(tx) or {}
        if not isinstance(detail, dict):
            return {}
        evidence = detail.get("baseline_validation") or saved.get(tx)
        if (not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int
                or evidence.get("schema_version") != 1 or evidence.get("status") != "validated"
                or evidence.get('method') != 'rpc_receipt_vs_tenderly_original_replay'):
            return {}
        original_hash = evidence.get("original_transaction_hash")
        if str(evidence.get("network_id")) != str(network_id) or not isinstance(original_hash, str) or original_hash.lower() != tx.lower():
            return {}
        if (any(type(evidence.get(key)) is not int or evidence[key] < 0
                for key in ('block_number', 'transaction_index', 'gas_used', 'log_count'))
                or type(evidence.get('receipt_status')) is not int or evidence['receipt_status'] not in (0, 1)
                or not isinstance(evidence.get('block_hash'), str)
                or not re.fullmatch(r'0x[0-9a-fA-F]{64}', evidence['block_hash'])
                or any(not isinstance(evidence.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', evidence[key])
                       for key in ('ordered_logs_sha256', 'receipt_digest'))):
            return {}
        result[tx] = evidence
    return {"schema_version": 1, "transactions": result}


def _validate_runtime_artifacts(replay: dict, contracts: dict, task_root: Path | str | None = None) -> None:
    """Rebuild observed execution and bind guard PCs to durable runtime bytes."""
    from app.attackpilot.revalidate import _artifact
    from app.attackpilot.errors import TenderlyAPIError
    from app.attackpilot.utils.bytecode_transplanter import BytecodeTransplanter
    from app.attackpilot.utils.patch_attribution import attribution_digest, _instruction_boundaries
    from app.attackpilot.utils.patch_replay import execution_summary, historical_payload

    try:
        task_root = Path(WORK_ROOT if task_root is None else task_root).resolve()
        attribution = replay.get('patch_attribution')
        attributed_contracts = attribution.get('contracts') if isinstance(attribution, dict) else None
        if (not isinstance(attribution, dict) or type(attribution.get('schema_version')) is not int
                or attribution['schema_version'] != 1 or attribution.get('status') != 'available'
                or attribution.get('applied_patch_sha256') != replay.get('applied_patch_sha256')
                or attribution.get('evidence_sha256') != attribution_digest(attribution)
                or not isinstance(attributed_contracts, dict) or set(attributed_contracts) != set(contracts)):
            raise ValueError('Missing or inconsistent guard attribution evidence')
        patched_addresses = replay.get('patched_addresses')
        if (not isinstance(patched_addresses, list) or set(patched_addresses) != set(contracts)):
            raise ValueError('Patched address scope does not match integrity records')
        for pair in replay['transactions']:
            context = pair['context']
            for role in ('control', 'patched'):
                request, response = _artifact(task_root, pair[role]['artifact'], role,
                                              pair['original_transaction_hash'])
                simulations = request.get('simulations')
                if not isinstance(simulations, list) or len(simulations) != 1 or not isinstance(simulations[0], dict):
                    raise ValueError('Invalid replay request')
                simulation = simulations[0]
                overrides = simulation.get('state_objects')
                if role == 'control':
                    if overrides is not None:
                        raise ValueError('The control request contains state overrides')
                else:
                    if not isinstance(overrides, dict) or set(overrides) != set(contracts):
                        raise ValueError('Runtime override addresses do not match integrity records')
                    for address, override in overrides.items():
                        if not isinstance(override, dict) or set(override) != {'code'}:
                            raise ValueError('The patched request changes state beyond runtime code')
                        code = override['code']
                        if not isinstance(code, str) or re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+', code) is None:
                            raise ValueError('Invalid runtime override bytecode')
                        raw_code = bytes.fromhex(code[2:])
                        runtime_digest = hashlib.sha256(raw_code).hexdigest()
                        if runtime_digest != contracts[address]['patched_runtime_sha256']:
                            raise ValueError('Runtime override bytecode does not match its integrity digest')
                        attributed = attributed_contracts[address]
                        if (not isinstance(attributed, dict)
                                or attributed.get('patched_runtime_sha256') != runtime_digest
                                or not isinstance(attributed.get('guards'), list)):
                            raise ValueError('Guard attribution does not match the actual override runtime')
                        executable_end, _ = BytecodeTransplanter._metadata(raw_code)
                        boundaries = _instruction_boundaries(raw_code[:executable_end])
                        claimed_pcs = set()
                        for guard in attributed['guards']:
                            pcs = guard.get('revert_pcs') if isinstance(guard, dict) else None
                            if (not isinstance(pcs, list) or not pcs
                                    or any(type(pc) is not int or pc not in boundaries
                                           or pc >= executable_end or raw_code[pc] != 0xfd for pc in pcs)
                                    or len(set(pcs)) != len(pcs) or claimed_pcs.intersection(pcs)):
                                raise ValueError('Guard PC is ambiguous or is not an executable REVERT instruction')
                            claimed_pcs.update(pcs)
                rebuilt = execution_summary(
                    response, pair[role]['artifact'], patched_addresses,
                    runtime_codes={address: item['code'] for address, item in overrides.items()}
                    if role == 'patched' else None,
                )
                for key in ('completed', 'status', 'gas_used', 'logs', 'trace', 'execution_effects'):
                    if rebuilt.get(key) != pair[role].get(key):
                        raise ValueError(f'Recorded {role} {key} does not match its replay artifact')
                transaction = {'accessList': context.get('access_list', [])} if 'access_list' in simulation else {}
                expected = historical_payload({**context, 'chain_id': int(context['network_id'])},
                                              transaction, overrides)
                if request != expected:
                    raise ValueError('Artifact request does not match the recorded historical transaction')
    except (OSError, ValueError, TypeError, KeyError, AttributeError,
            HistoricalReplayValidationError, TenderlyAPIError) as exc:
        raise AgentContractError('report', 'analysis_report_invalid') from exc


def validate_completed_result(dapp: dict, result, report) -> None:
    """Only coherent, input-bound artifacts may become a completed live task."""
    if (not isinstance(report, str) or not report.strip()
            or not isinstance(result, dict) or result.get('report') != report
            or result.get('report_policy_version') != REPORT_POLICY_VERSION
            or result.get('request_fingerprint') != request_fingerprint(dapp)
            or not validated_baselines(result, dapp)
            or result.get('enabled_modules') != sorted(normalize_enabled_modules(dapp))):
        raise AgentContractError('report', 'analysis_report_invalid')
    state = result.get('verification')
    if (not isinstance(state, dict) or state.get('status') not in
            {'verified', 'unverified', 'blocked', 'error', 'skipped'}):
        raise AgentContractError('report', 'analysis_report_invalid')
    if state['status'] == 'verified':
        if 'patch_verification' not in normalize_enabled_modules(dapp):
            raise AgentContractError('report', 'analysis_report_invalid')
        from app.attackpilot.utils.report_evidence import report_evidence
        evidence = report_evidence({'verification': state, 'verdict': state.get('judge_verdict')},
                                   result.get('replay_evidence'))
        patches = result.get('applied_patches')
        if (not evidence['evidence_trusted'] or not isinstance(patches, str)
                or hashlib.sha256(patches.encode()).hexdigest() != state.get('applied_patch_sha256')):
            raise AgentContractError('report', 'analysis_report_invalid')
        replay = result.get('replay_evidence')
        baselines = validated_baselines(result, dapp)['transactions']
        known = {tx.lower(): baseline for tx, baseline in baselines.items()}
        for pair in replay.get('transactions', []):
            tx = pair.get('original_transaction_hash') if isinstance(pair, dict) else None
            control = pair.get('control') if isinstance(pair, dict) else None
            baseline = control.get('baseline_validation') if isinstance(control, dict) else None
            if (not isinstance(tx, str) or tx.lower() not in known or not isinstance(baseline, dict)
                    or any(baseline.get(key) != known[tx.lower()].get(key) for key in (
                        'receipt_digest', 'block_hash', 'block_number', 'transaction_index', 'network_id'))):
                raise AgentContractError('report', 'analysis_report_invalid')
        integrity = replay.get('runtime_integrity') if isinstance(replay, dict) else None
        contracts = integrity.get('contracts') if isinstance(integrity, dict) else None
        addresses = state.get('coverage', {}).get('modified_addresses', [])
        if (not isinstance(integrity, dict) or type(integrity.get('schema_version')) is not int
                or integrity['schema_version'] != 1 or integrity.get('status') != 'validated'
                or integrity.get('applied_patch_sha256') != state.get('applied_patch_sha256')
                or not isinstance(contracts, dict) or not contracts
                or set(contracts) != {address.lower() for address in addresses}):
            raise AgentContractError('report', 'analysis_report_invalid')
        for contract in contracts.values():
            if (not isinstance(contract, dict) or contract.get('storage_layout_checked') is not True
                    or contract.get('immutable_checked') is not True
                    or any(not isinstance(contract.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', contract[key])
                           for key in ('original_runtime_sha256', 'original_compiled_runtime_sha256', 'patched_runtime_sha256'))):
                raise AgentContractError('report', 'analysis_report_invalid')
        _validate_runtime_artifacts(replay, contracts)
        from app.attackpilot.utils.verification import adjudicate_patch_verification
        rebuilt_verdict = adjudicate_patch_verification(
            {'verdict': state.get('judge_verdict')}, replay, patches)
        if (rebuilt_verdict.get('status') != 'verified'
                or rebuilt_verdict.get('checked') != state.get('checked')
                or rebuilt_verdict.get('coverage') != state.get('coverage')):
            raise AgentContractError('report', 'analysis_report_invalid')


def build_macro_only_report(dapp_name: str, processed_data: dict, enabled_modules: set) -> str:
    txs = processed_data.get("transaction_hash_list") or processed_data.get("transactions_need_analyze") or []
    attack_txs = processed_data.get("attack_transactions") or []
    auxiliary_txs = processed_data.get("auxiliary_transactions") or []
    bug_summary = processed_data.get("bug_summary") or "尚未生成宏观漏洞摘要。"
    rag_context = processed_data.get("rag_context") or {}
    rag_items = rag_context.get("items") if isinstance(rag_context, dict) else []
    return "\n".join([
        f"# {dapp_name} 宏观交易复盘",
        "",
        "当前未启用漏洞定位模块，AttackPilot 已完成宏观交易分析。",
        "",
        f"- 已启用模块：{', '.join({'attack_detection': '攻击检测', 'fault_localization': '漏洞定位', 'rag_retrieval': '知识检索', 'patch_generation': '补丁生成', 'patch_verification': '补丁验证'}.get(module, module) for module in sorted(enabled_modules)) or '无'}",
        f"- 已收集交易：{len(txs)}",
        f"- 候选攻击交易：{len(attack_txs)}",
        f"- 候选辅助交易：{len(auxiliary_txs)}",
        f"- 检索知识片段：{len(rag_items) if isinstance(rag_items, list) else 0}",
        "",
        "## 宏观分析结果",
        str(bug_summary),
    ])


class WorkFlow:
    def __init__(
            self,
            semaphore_num=1,
            log_callback: Optional[Callable[[LogMessage], None]] = None,
            cancellation_checker: Optional[Callable[[], bool]] = None,
            use_report_cache: bool = True,
            write_report_cache: bool = True):
        self.root = os.path.join(PROJECT_PATH, 'dataset')
        self.dapp2processed = {}
        self.dapp2report = {}
        self.last_result = None
        self.last_error = None
        self._net2rpc_bucket = {
            net: AsyncItemBucket(items=_rpc_urls, qps=1)
            for net, _rpc_urls in JSONRPCS.items()
        }
        self._net2apikey_bucket = {
            net: AsyncItemBucket(items=_apikeys, qps=1)
            for net, _apikeys in SCAN_APIKEYS.items()
        }

        self.semaphore = asyncio.Semaphore(semaphore_num)
        self.metrics_collector = PatchQualityMetrics()
        self.log_callback = log_callback  # 新增日志回调函数
        self.cancellation_checker = cancellation_checker or (lambda: False)
        self.use_report_cache = use_report_cache
        self.write_report_cache = write_report_cache

    def _check_cancelled(self):
        if self.cancellation_checker():
            raise asyncio.CancelledError("Task was cancelled")

    def _log(self, agent: str, level: str, message: str):
        """统一的日志输出方法"""
        if self.log_callback:
            self.log_callback(LogMessage(agent=agent, level=level, message_type="text", message=message))
        else:
            print(message)

    @property
    def raw_file_names(self) -> Union[str, List[str], Tuple]:
        path = os.path.join(self.root, 'raw')
        return sorted([os.path.join(path, fn) for fn in os.listdir(path)])

    @property
    def processed_data_names(self) -> Union[str, List[str], Tuple]:
        path = os.path.join(self.root, 'raw')
        return sorted([os.path.join(self.root, 'processed', '%s.json' % fn.split('.')[0])
                       for fn in os.listdir(path)])

    @property
    def fault_report_names(self) -> Union[str, List[str], Tuple]:
        path = os.path.join(self.root, 'raw')
        return sorted([os.path.join(str(WORK_ROOT), "experiment_result", 'pilot_report', '%s.json' % fn.split('.')[0])
                       for fn in os.listdir(path)])

    @staticmethod
    def _safe_cache_name(dapp_name: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", dapp_name.strip())
        return safe.strip("._") or "adhoc_dapp"

    def _default_processed_path(self, dapp_name: str) -> str:
        return os.path.join(self.root, "processed", "adhoc", f"{self._safe_cache_name(dapp_name)}.json")

    def _default_report_path(self, dapp_name: str) -> str:
        return os.path.join(str(WORK_ROOT), "experiment_result", "pilot_report", "adhoc", f"{self._safe_cache_name(dapp_name)}.json")

    async def process_single_dapp(self, dapp, i=None, processed_path: Optional[str] = None, report_path: Optional[str] = None):
        async with self.semaphore, price_quote_scope():
            self._check_cancelled()
            dapp_name = dapp.get("name")
            enabled_modules = normalize_enabled_modules(dapp)
            local_mcp_client = None
            transaction_debugger = None
            fault_report = ""
            self.last_error = None
            self.last_result = None
            analyzer = None
            stage = '初始化分析工具'
            try:
                self._check_cancelled()
                if processed_path is None:
                    processed_path = self.processed_data_names[i] if i is not None and i >= 0 else self._default_processed_path(dapp_name)
                if report_path is None:
                    report_path = self.fault_report_names[i] if i is not None and i >= 0 else self._default_report_path(dapp_name)

                self._check_cancelled()
                cached_processed_data = self.check_cache(dapp_name, processed_path)
                cached_fault_report = self.check_cache(dapp_name, report_path) if self.use_report_cache else {}
                if not validated_baselines(cached_processed_data, dapp) or price_evidence_retryable(cached_processed_data):
                    cached_processed_data = {}
                if not validated_baselines(cached_fault_report, dapp) or price_evidence_retryable(cached_fault_report):
                    cached_fault_report = {}
                if cached_fault_report.get("report_policy_version") != REPORT_POLICY_VERSION:
                    cached_fault_report = {}
                if cached_fault_report:
                    try:
                        validate_completed_result(dapp, cached_fault_report, cached_fault_report.get('report'))
                    except AgentContractError:
                        cached_fault_report = {}
                if cached_fault_report:
                    print(f"✅ Cache hit for report: {dapp_name}")
                    self.last_result = cached_fault_report
                    return dapp_name, cached_fault_report.get("report", "")

                if cached_processed_data:
                    processed_data = cached_processed_data
                    if "fault_localization" in enabled_modules:
                        local_mcp_client = MCPClient(MCP_SERVER_PATH)
                        await local_mcp_client.connect()
                        transaction_debugger = await self.reload_debugger(processed_data, local_mcp_client)
                else:
                    # Macro Analysis (Process)
                    stage = '读取交易数据与宏观分析'
                    print(f"🚀 Start processing: {dapp_name}")
                    self._check_cancelled()
                    local_mcp_client = MCPClient(MCP_SERVER_PATH)
                    await local_mcp_client.connect()
                    processed_data, transaction_debugger = await DAppProcess(
                        net2rpc_bucket=self._net2rpc_bucket,
                        net2apikey_bucket=self._net2apikey_bucket,
                        mcp_client=local_mcp_client,
                        log_callback=self.log_callback,
                        cancellation_checker=self.cancellation_checker,
                        enabled_modules=sorted(enabled_modules),
                    ).process(dapp)
                    self._check_cancelled()
                    processed_data["request_fingerprint"] = request_fingerprint(dapp)
                    if not validated_baselines(processed_data, dapp):
                        raise HistoricalReplayValidationError('unavailable', 'missing_evidence',
                                                               details={'field': 'analysis.baselines'})
                    self.write_cache(dapp_name, processed_path, processed_data)

                if "fault_localization" not in enabled_modules:
                    macro_only_report = build_macro_only_report(dapp_name, processed_data, enabled_modules)
                    final_output = {
                        "report": macro_only_report,
                        "report_policy_version": REPORT_POLICY_VERSION,
                        "request_fingerprint": request_fingerprint(dapp),
                        "verification": verification_state(
                            "skipped", stage="module_selection", reason_code="module_disabled",
                            reason="本次任务仅执行宏观分析，未启用补丁回放。", terminal=True,
                        ),
                        "baseline_validation": validated_baselines(processed_data, dapp),
                        "price_evidence": collect_price_evidence(processed_data),
                        "time": {
                            "macro": processed_data.get("time_used", {}),
                            "micro": {}
                        },
                        "token": {
                            "macro": processed_data.get("token_used", {}),
                            "micro": {}
                        },
                        "enabled_modules": sorted(enabled_modules),
                    }
                    validate_completed_result(dapp, final_output, macro_only_report)
                    if self.write_report_cache:
                        self.write_cache(dapp_name, report_path, final_output)
                    self.last_result = final_output
                    return dapp_name, macro_only_report

                # Micro Analysis (Analyze)
                if processed_data and transaction_debugger:
                    stage = '根因定位与补丁分析'
                    start_time = time.time()
                    self._check_cancelled()
                    analyzer = DAppAnalyze(
                        processed_data=processed_data,
                        transaction_debugger=transaction_debugger,
                        net2apikey_bucket=self._net2apikey_bucket,
                        net2rpc_bucket=self._net2rpc_bucket,
                        mcp_client=local_mcp_client,
                        metrics_collector=self.metrics_collector,
                        log_callback=self.log_callback,
                        cancellation_checker=self.cancellation_checker,
                        enabled_modules=sorted(enabled_modules),
                    )
                    fault_report, analyze_items = await analyzer.analyze()
                    self._check_cancelled()
                    if fault_report.startswith("ERROR"):
                        print(f"LLM Fault: {fault_report}")

                    elapsed_time = time.time() - start_time
                    final_output = {}
                    if analyze_items:
                        analyze_times = analyze_items["time"]
                        analyze_tokens = analyze_items["token"]

                        analyze_times["total_time"] = elapsed_time
                        final_output = {
                            "report": fault_report,
                            "report_policy_version": REPORT_POLICY_VERSION,
                            "request_fingerprint": request_fingerprint(dapp),
                            "verification": analyze_items.get("verification", {"status": "not_run"}),
                            "replay_evidence": analyze_items.get("replay_evidence"),
                            "applied_patches": analyze_items.get("applied_patches", ""),
                            "report_generation": analyze_items.get("report_generation", {"status": "not_run"}),
                            "baseline_validation": validated_baselines(processed_data, dapp),
                            "price_evidence": collect_price_evidence(processed_data),
                            "time": {
                                "macro": processed_data["time_used"],
                                "micro": analyze_times
                            },
                            "token": {
                                "macro": processed_data["token_used"],
                                "micro": analyze_tokens
                            },
                            "enabled_modules": sorted(enabled_modules),
                        }
                    validate_completed_result(dapp, final_output, fault_report)
                    if self.write_report_cache:
                        self.write_cache(dapp_name, report_path, final_output)
                    self.last_result = final_output
                    return dapp_name, fault_report
                raise AgentContractError('report', 'analysis_report_invalid')

            except asyncio.CancelledError:
                print(f"[CANCELLED] {dapp_name} analysis cancelled by user.")
                if self.metrics_collector:
                    try:
                        self.metrics_collector.finalize_case(dapp_name, "CANCELLED")
                    except Exception:
                        pass
                raise
            except Exception as e:
                import traceback
                print(f"❌ Error processing {dapp_name}: {e}")
                traceback.print_exc()

                error_stack = traceback.format_exc()
                error_log_dir = os.path.join(str(WORK_ROOT), "experiment_result", 'pilot_report', 'errors')
                error_file_path = os.path.join(error_log_dir, f"{self._safe_cache_name(dapp_name)}_error.log")

                try:
                    os.makedirs(error_log_dir, exist_ok=True)
                    with open(error_file_path, 'w', encoding='utf-8') as f:
                        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                        f.write(f"Error processing {dapp_name}:\n")
                        f.write(redact_text(error_stack))
                except OSError:
                    # A full/read-only disk must not hide the original failure.
                    pass

                print(f"❌ [FAILED] {dapp_name} - Log saved to {error_file_path}")
                if self.metrics_collector:
                    try:
                        self.metrics_collector.finalize_case(dapp_name, "ERROR")
                    except Exception:
                        pass
                self.last_error = failure_message(e, stage)
                causes = exception_chain(e)
                baseline_error = next((item for item in causes if isinstance(item, (HistoricalReplayValidationError, HistoricalReplayContextError))), None)
                contract_error = next((item for item in causes if isinstance(item, AgentContractError)), None)
                tool_error = next((item for item in causes if isinstance(item, MCPToolError)), None)
                if baseline_error is not None:
                    baseline_status = baseline_error.status if isinstance(baseline_error, HistoricalReplayValidationError) else "unavailable"
                    self.last_result = {
                        "verification": verification_state(
                            "blocked", stage="baseline_validation",
                            reason_code=f"baseline_{baseline_status}", reason=self.last_error, terminal=True,
                        ),
                        "baseline_validation": {
                            "schema_version": 1, "status": baseline_status,
                            "reason_code": getattr(baseline_error, "reason_code", "missing_context"),
                            "details": getattr(baseline_error, "details", {}),
                        },
                    }
                elif contract_error is not None or tool_error is not None or any(isinstance(item, EvidencePersistenceError) for item in causes):
                    previous = getattr(analyzer, "verification", {}) or {}
                    self.last_result = {
                        "report_policy_version": REPORT_POLICY_VERSION,
                        "verification": verification_state(
                            "error", stage=contract_error.stage if contract_error else "tool_execution" if tool_error else "evidence_persistence",
                            reason_code=contract_error.reason_code if contract_error else "mcp_tool_failed" if tool_error else "evidence_persistence_failed",
                            reason=self.last_error, terminal=True,
                            replay_attempted=previous.get("replay_attempted") is True,
                            replay_completed=previous.get("replay_completed") is True,
                        ),
                        "replay_evidence": getattr(analyzer, "replay_evidence", None),
                        "applied_patches": getattr(analyzer, "applied_patches", ""),
                    }
                elif analyzer is not None and isinstance(analyzer.verification, dict):
                    self.last_result = {
                        "report_policy_version": REPORT_POLICY_VERSION,
                        "verification": analyzer.verification,
                        "replay_evidence": getattr(analyzer, "replay_evidence", None),
                        "applied_patches": getattr(analyzer, "applied_patches", ""),
                        "price_evidence": collect_price_evidence(processed_data) if 'processed_data' in locals() else None,
                    }
                self._log('Workflow', 'error', self.last_error)
                return dapp_name, f"RUNTIME_ERROR: {self.last_error}"
            finally:
                if 'transaction_debugger' in locals() and transaction_debugger:
                    try:
                        await transaction_debugger.close()
                    except Exception as e:
                        print(f"⚠️ Warning: Failed to close transaction_debugger: {e}")
                if local_mcp_client:
                    try:
                        await local_mcp_client.close()
                    except Exception as e:
                        print(f"⚠️ Warning: Failed to close MCP client: {e}")

    async def main_workflow(self, dapps=None, *, input_paths=None):
        self._check_cancelled()
        if dapps is None and input_paths is None:
            raise ValueError('Provide an explicit dapps list or input_paths list.')
        if dapps is not None and input_paths is not None:
            raise ValueError('Provide either dapps or input_paths, not both.')
        if input_paths is not None:
            if not isinstance(input_paths, (list, tuple)):
                raise ValueError('input_paths must be an explicit list of JSON input files.')
            dapps = []
            for fn in input_paths:
                self._check_cancelled()
                if Path(fn).suffix.lower() != '.json':
                    raise ValueError('Every input path must name a JSON file.')
                with open(fn, 'r', encoding="utf-8") as f:
                    dapps.append(json.load(f))
        if not isinstance(dapps, (list, tuple)) or any(not isinstance(dapp, dict) for dapp in dapps):
            raise ValueError('dapps must be an explicit list of input objects.')
        tasks = []
        try:
            for dapp in dapps:
                self._check_cancelled()
                task = asyncio.create_task(self.process_single_dapp(dapp))
                tasks.append(task)
            results = await asyncio.gather(*tasks)

            reports = {}
            reserved_names = {name for name, _ in results}
            for name, _report in results:
                if _report:
                    result_key = name
                    if result_key in reports:
                        suffix = 2
                        while f'{name} [{suffix}]' in reports or f'{name} [{suffix}]' in reserved_names:
                            suffix += 1
                        result_key = f'{name} [{suffix}]'
                    reports[result_key] = _report
            self.dapp2report = reports
            return self.dapp2report
        finally:
            # A failed or cancelled batch must not leave sibling analyses
            # running after the caller has already received its outcome.
            for task in tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def reload_debugger(self, processed_data, mcp_client):
        transaction_debugger = TraceAgent(
            processed_data,
            mcp_client=mcp_client,
            dapp_name=processed_data["dapp"]["name"],
            log_callback=self.log_callback,
        )
        transaction_debugger.set_cancellation_checker(self.cancellation_checker)
        await transaction_debugger.init()
        return transaction_debugger

    @staticmethod
    def check_cache(dapp_name, cache_file_path):
        if os.path.exists(cache_file_path):
            print(f'Loading cached data for {dapp_name} from {cache_file_path}')
            try:
                with open(cache_file_path, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    return cached_data
            except Exception as e:
                print(f'Error loading cached data for {dapp_name}: {e}')
                return {}
        return {}

    @staticmethod
    def write_cache(dapp_name, cache_file_path, processed_data):
        temp_path = None
        try:
            parent = os.path.dirname(os.path.abspath(cache_file_path))
            os.makedirs(parent, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=parent, prefix='.evidence-', suffix='.tmp', delete=False) as f:
                temp_path = f.name
                json.dump(processed_data, f, ensure_ascii=False, indent=2, allow_nan=False)
            os.replace(temp_path, cache_file_path)
            temp_path = None
            print(f'Saved cached data for {dapp_name} to {cache_file_path}')
        except (OSError, ValueError, TypeError) as exc:
            raise EvidencePersistenceError('Required analysis evidence could not be saved') from exc
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


async def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description='Analyze explicitly supplied JSON inputs.')
    parser.add_argument('input_paths', metavar='JSON_INPUT', nargs='*',
                        help='One or more JSON input files to analyze.')
    args = parser.parse_args(argv)
    if not args.input_paths:
        parser.print_usage()
        return {}
    return await WorkFlow(semaphore_num=1).main_workflow(input_paths=args.input_paths)


if __name__ == '__main__':
    asyncio.run(main())
