import asyncio
import json
import os
import re
import time
from typing import Union, List, Tuple, Callable, Optional
from agents.TraceAgent import TraceAgent
from mcp_tools.mcp_client import MCPClient
from process.analyze import DAppAnalyze
from process.pyg import DAppProcess
from settings import PROJECT_PATH, SCAN_APIKEYS, JSONRPCS, MCP_SERVER_PATH
from utils.bucket import AsyncItemBucket
from utils.patch_quality_metrics import PatchQualityMetrics
from app.models import LogMessage

DEFAULT_ENABLED_MODULES = {
    "attack_detection",
    "fault_localization",
    "rag_retrieval",
    "patch_generation",
    "patch_verification",
}


def normalize_enabled_modules(dapp: dict) -> set:
    modules = dapp.get("enabled_modules")
    if not isinstance(modules, list) or not modules:
        return set(DEFAULT_ENABLED_MODULES)
    enabled = {str(module) for module in modules if str(module) in DEFAULT_ENABLED_MODULES}
    if "patch_verification" in enabled:
        enabled.add("patch_generation")
    if "fault_localization" in enabled:
        enabled.add("rag_retrieval")
    return enabled


def build_macro_only_report(dapp_name: str, processed_data: dict, enabled_modules: set) -> str:
    txs = processed_data.get("transaction_hash_list") or processed_data.get("transactions_need_analyze") or []
    attack_txs = processed_data.get("attack_transactions") or []
    auxiliary_txs = processed_data.get("auxiliary_transactions") or []
    bug_summary = processed_data.get("bug_summary") or "No macro bug summary generated."
    rag_context = processed_data.get("rag_context") or {}
    rag_items = rag_context.get("items") if isinstance(rag_context, dict) else []
    return "\n".join([
        f"# {dapp_name} Macro Review",
        "",
        "Fault localization module was disabled, so AttackPilot stopped after macro transaction analysis.",
        "",
        f"- Enabled modules: {', '.join(sorted(enabled_modules)) or 'none'}",
        f"- Transactions collected: {len(txs)}",
        f"- Attack candidates: {len(attack_txs)}",
        f"- Auxiliary candidates: {len(auxiliary_txs)}",
        f"- RAG context chunks: {len(rag_items) if isinstance(rag_items, list) else 0}",
        "",
        "## Macro Findings",
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
            self.log_callback(agent, level, message)
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
        return sorted([os.path.join(PROJECT_PATH, "experiment_result", 'pilot_report', '%s.json' % fn.split('.')[0])
                       for fn in os.listdir(path)])

    @staticmethod
    def _safe_cache_name(dapp_name: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", dapp_name.strip())
        return safe.strip("._") or "adhoc_dapp"

    def _default_processed_path(self, dapp_name: str) -> str:
        return os.path.join(self.root, "processed", "adhoc", f"{self._safe_cache_name(dapp_name)}.json")

    def _default_report_path(self, dapp_name: str) -> str:
        return os.path.join(PROJECT_PATH, "experiment_result", "pilot_report", "adhoc", f"{self._safe_cache_name(dapp_name)}.json")

    async def process_single_dapp(self, dapp, i=None, processed_path: Optional[str] = None, report_path: Optional[str] = None):
        async with self.semaphore:
            self._check_cancelled()
            dapp_name = dapp.get("name")
            enabled_modules = normalize_enabled_modules(dapp)
            local_mcp_client = MCPClient(MCP_SERVER_PATH)
            fault_report = ""
            try:
                self._check_cancelled()
                await local_mcp_client.connect()
                if processed_path is None:
                    processed_path = self.processed_data_names[i] if i is not None and i >= 0 else self._default_processed_path(dapp_name)
                if report_path is None:
                    report_path = self.fault_report_names[i] if i is not None and i >= 0 else self._default_report_path(dapp_name)

                self._check_cancelled()
                cached_processed_data = self.check_cache(dapp_name, processed_path)
                cached_fault_report = self.check_cache(dapp_name, report_path) if self.use_report_cache else {}
                if cached_fault_report:
                    print(f"✅ Cache hit for report: {dapp_name}")
                    return dapp_name, cached_fault_report

                if cached_processed_data:
                    processed_data = cached_processed_data
                    transaction_debugger = await self.reload_debugger(processed_data, local_mcp_client)
                else:
                    # Macro Analysis (Process)
                    print(f"🚀 Start processing: {dapp_name}")
                    self._check_cancelled()
                    processed_data, transaction_debugger = await DAppProcess(
                        net2rpc_bucket=self._net2rpc_bucket,
                        net2apikey_bucket=self._net2apikey_bucket,
                        mcp_client=local_mcp_client,
                        log_callback=self.log_callback,
                        cancellation_checker=self.cancellation_checker,
                        enabled_modules=sorted(enabled_modules),
                    ).process(dapp)
                    self._check_cancelled()
                    self.write_cache(dapp_name, processed_path, processed_data)

                if "fault_localization" not in enabled_modules:
                    macro_only_report = build_macro_only_report(dapp_name, processed_data, enabled_modules)
                    final_output = {
                        "report": macro_only_report,
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
                    if self.write_report_cache:
                        self.write_cache(dapp_name, report_path, final_output)
                    return dapp_name, macro_only_report

                # Micro Analysis (Analyze)
                if processed_data and transaction_debugger:
                    start_time = time.time()
                    self._check_cancelled()
                    fault_report, analyze_items = await DAppAnalyze(
                        processed_data=processed_data,
                        transaction_debugger=transaction_debugger,
                        net2apikey_bucket=self._net2apikey_bucket,
                        net2rpc_bucket=self._net2rpc_bucket,
                        mcp_client=local_mcp_client,
                        metrics_collector=self.metrics_collector,
                        log_callback=self.log_callback,
                        cancellation_checker=self.cancellation_checker,
                        enabled_modules=sorted(enabled_modules),
                    ).analyze()
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
                    if final_output and self.write_report_cache:
                        self.write_cache(dapp_name, report_path, final_output)
                    return dapp_name, fault_report
                return dapp_name, fault_report

            except asyncio.CancelledError:
                print(f"[CANCELLED] {dapp_name} analysis cancelled by user.")
                if self.metrics_collector:
                    self.metrics_collector.finalize_case(dapp_name, "CANCELLED")
                raise
            except Exception as e:
                import traceback
                print(f"❌ Error processing {dapp_name}: {e}")
                traceback.print_exc()

                error_stack = traceback.format_exc()
                error_log_dir = os.path.join(PROJECT_PATH, "experiment_result", 'pilot_report', 'errors')
                os.makedirs(error_log_dir, exist_ok=True)
                error_file_path = os.path.join(error_log_dir, f"{dapp_name}_error.log")

                with open(error_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Error processing {dapp_name}:\n")
                    f.write(error_stack)

                print(f"❌ [FAILED] {dapp_name} - Log saved to {error_file_path}")
                if self.metrics_collector:
                    self.metrics_collector.finalize_case(dapp_name, "ERROR")
                return dapp_name, f"RUNTIME_ERROR: See log at {error_file_path}\nDetails: {str(e)}"
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

    async def main_workflow(self):
        dapps = []
        for fn in self.raw_file_names:
            with open(fn, 'r', encoding="utf-8") as f:
                dapps.append(json.load(f))
        try:
            tasks = []
            for i, dapp in enumerate(dapps):
                if dapp["name"] != "SushiSwap":
                    continue
                task = asyncio.create_task(self.process_single_dapp(dapp, i))
                tasks.append(task)
            results = await asyncio.gather(*tasks)

            for name, _report in results:
                if _report:
                    self.dapp2report[name] = _report
            return self.dapp2report
        except Exception as e:
            raise e

    async def reload_debugger(self, processed_data, mcp_client):
        transaction_debugger = TraceAgent(
            processed_data,
            mcp_client=mcp_client,
            dapp_name=processed_data["dapp"]["name"]
        )
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
        try:
            os.makedirs(os.path.dirname(cache_file_path), exist_ok=True)
            with open(cache_file_path, 'w', encoding='utf-8') as f:
                json.dump(processed_data, f, ensure_ascii=False, indent=2)
            print(f'Saved cached data for {dapp_name} to {cache_file_path}')
        except Exception as e:
            print(f'Error saving cached data for {dapp_name}: {e}')


async def main():
    return await WorkFlow(semaphore_num=1).main_workflow()


if __name__ == '__main__':
    report = asyncio.run(main())
    print(f"The Final Localization Report: \n{report}")
