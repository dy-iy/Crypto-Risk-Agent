import asyncio
import sys
from . import settings, store
from .privacy import redact, redact_text

async def run(task_id: str):
    settings.prepare_work_dir()
    task = store.get_task(task_id)
    if not task or task["status"] != "running":
        return

    def log(message):
        store.append_log(task_id, redact(message.model_dump(mode="json")))
    log.task_id = task_id

    def cancelled():
        current = store.get_task(task_id)
        return not current or current["status"] in store.TERMINAL

    try:
        from .workflow import WorkFlow
        workflow = WorkFlow(log_callback=log, cancellation_checker=cancelled, use_report_cache=False, write_report_cache=False)
        outcome = await workflow.process_single_dapp(task["payload"], processed_path=str(settings.WORK_ROOT / "processed.json"), report_path=str(settings.WORK_ROOT / "report.json"))
        report = outcome[1] if isinstance(outcome, (tuple, list)) and len(outcome) > 1 else outcome
        if not report or isinstance(report, str) and report.startswith(("RUNTIME_ERROR:", "ERROR", "FAILED:", "empty attack transaction!")):
            raise RuntimeError(getattr(workflow, 'last_error', None) or "分析未生成有效报告，请查看任务文件日志。")
        result = getattr(workflow, "last_result", None) or {"report": report, "verification": {"status": "not_run"}}
        store.transition(task_id, "completed", result=redact(result))
    except asyncio.CancelledError:
        store.transition(task_id, "cancelled", error="任务已取消。")
    except Exception as exc:
        store.append_log(task_id, {"agent": "Workflow", "level": "error", "message": redact_text(str(exc))})
        store.transition(task_id, "failed", error=redact_text(str(exc)))

if __name__ == "__main__":
    asyncio.run(run(sys.argv[1]))
