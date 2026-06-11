from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4

from app.agents.daily_report_agent import run_daily_report_agent
from app.agents.ranking_agent.graph import run_ranking_agent
from app.data.update_news import update_news_dataset
from app.services.auth_service import get_user_by_id
from app.services.daily_report_store import save_daily_report
from app.services.daily_report_subscription_service import list_subscribed_daily_report_user_ids
from app.services.portfolio_service import DEFAULT_USER_ID
from app.services.runtime_json_store import load_runtime_json_or_quarantine, write_runtime_json_atomic
from app.services.task_audit_service import record_task_event


SCHEDULER_STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "daily_scheduler_state.json"
DEFAULT_SCHEDULE_HOUR = 8
DEFAULT_SCHEDULE_MINUTE = 0
POLL_SECONDS = 30

_state_lock = Lock()
_run_lock = Lock()
_stop_event = Event()
_scheduler_thread: Thread | None = None


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _env_default_enabled() -> bool:
    return os.getenv("DAILY_SCHEDULER_ENABLED", "1").strip() != "0"


def _default_state() -> dict[str, Any]:
    return {
        "enabled": _env_default_enabled(),
        "schedule_hour": DEFAULT_SCHEDULE_HOUR,
        "schedule_minute": DEFAULT_SCHEDULE_MINUTE,
        "last_run_date": "",
        "last_started_at": "",
        "last_finished_at": "",
        "last_status": "idle",
        "last_message": "等待每日 08:00 自动运行",
        "last_job_id": "",
        "last_result": None,
        "updated_at": _now_text(),
    }


def _load_state_unlocked() -> dict[str, Any]:
    raw = load_runtime_json_or_quarantine(SCHEDULER_STATE_PATH)
    state = _default_state()
    if isinstance(raw, dict):
        state.update(raw)
    state["enabled"] = bool(state.get("enabled"))
    state["schedule_hour"] = int(state.get("schedule_hour") or DEFAULT_SCHEDULE_HOUR)
    state["schedule_minute"] = int(state.get("schedule_minute") or DEFAULT_SCHEDULE_MINUTE)
    state["last_result"] = state.get("last_result") if isinstance(state.get("last_result"), dict) else None
    return state


def _save_state_unlocked(state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = _now_text()
    write_runtime_json_atomic(SCHEDULER_STATE_PATH, state)
    return dict(state)


def get_daily_scheduler_status() -> dict[str, Any]:
    with _state_lock:
        state = _load_state_unlocked()
    return {
        **state,
        "running": _run_lock.locked(),
        "thread_alive": bool(_scheduler_thread and _scheduler_thread.is_alive()),
    }


def set_daily_scheduler_enabled(enabled: bool) -> dict[str, Any]:
    with _state_lock:
        state = _load_state_unlocked()
        state["enabled"] = bool(enabled)
        state["last_message"] = "每日定时任务已启动" if enabled else "每日定时任务已暂停"
        saved = _save_state_unlocked(state)
    return {
        **saved,
        "running": _run_lock.locked(),
        "thread_alive": bool(_scheduler_thread and _scheduler_thread.is_alive()),
    }


def _should_run(now: datetime, state: dict[str, Any]) -> bool:
    if not state.get("enabled"):
        return False
    scheduled_time_reached = (now.hour, now.minute) >= (
        int(state.get("schedule_hour") or DEFAULT_SCHEDULE_HOUR),
        int(state.get("schedule_minute") or DEFAULT_SCHEDULE_MINUTE),
    )
    return scheduled_time_reached and state.get("last_run_date") != now.date().isoformat()


def run_daily_scheduler_once(*, force: bool = False) -> dict[str, Any]:
    if not _run_lock.acquire(blocking=False):
        status = get_daily_scheduler_status()
        status["last_status"] = "running"
        status["last_message"] = "每日定时任务正在运行"
        return status
    lock_acquired = True

    job_id = f"daily-scheduler-{uuid4().hex}"
    started_at = _now_text()
    run_date = datetime.now().date().isoformat()
    with _state_lock:
        state = _load_state_unlocked()
        if not force and not state.get("enabled"):
            _run_lock.release()
            lock_acquired = False
            state["last_status"] = "paused"
            state["last_message"] = "每日定时任务已暂停"
            return {
                **state,
                "running": False,
                "thread_alive": bool(_scheduler_thread and _scheduler_thread.is_alive()),
            }
        state.update({
            "last_job_id": job_id,
            "last_started_at": started_at,
            "last_finished_at": "",
            "last_status": "running",
            "last_message": "正在更新新闻并生成订阅用户资产日报",
        })
        _save_state_unlocked(state)

    record_task_event(
        job_kind="daily_scheduler",
        job_id=job_id,
        event_type="started",
        status="running",
        stage="news_update",
        message="每日 08:00 定时任务开始",
    )

    try:
        update_result = update_news_dataset()
        ranking = run_ranking_agent("all", date_filter="7d", limit=10)
        subscribed_user_ids = list_subscribed_daily_report_user_ids()
        generated_reports: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []

        for user_id in subscribed_user_ids:
            if user_id != DEFAULT_USER_ID:
                user = get_user_by_id(user_id)
                if not user:
                    errors.append({"user_id": user_id, "error": "user_not_found"})
                    continue
                display_name = user.display_name
            else:
                display_name = "Demo 用户"

            try:
                report = run_daily_report_agent(
                    "24h",
                    user_id=user_id,
                    user_display_name=display_name,
                )
                saved = save_daily_report(user_id, report)
                generated_reports.append({
                    "user_id": user_id,
                    "report_id": str(saved.get("report_id") or ""),
                })
            except Exception as exc:
                errors.append({"user_id": user_id, "error": str(exc)})

        status = "success" if not errors else "partial_success"
        result = {
            "run_date": run_date,
            "crawler": update_result,
            "ranking_date": ranking.get("date"),
            "subscribed_user_count": len(subscribed_user_ids),
            "generated_report_count": len(generated_reports),
            "generated_reports": generated_reports,
            "errors": errors,
        }
        message = (
            f"每日定时任务完成：订阅用户 {len(subscribed_user_ids)} 个，"
            f"已生成日报 {len(generated_reports)} 份。"
        )
        if errors:
            message += f" 失败 {len(errors)} 个。"

        with _state_lock:
            state = _load_state_unlocked()
            state.update({
                "last_run_date": run_date,
                "last_finished_at": _now_text(),
                "last_status": status,
                "last_message": message,
                "last_result": result,
            })
            saved = _save_state_unlocked(state)

        record_task_event(
            job_kind="daily_scheduler",
            job_id=job_id,
            event_type="finished",
            status=status,
            stage="done",
            message=message,
            payload=result,
        )
        return {
            **saved,
            "running": False,
            "thread_alive": bool(_scheduler_thread and _scheduler_thread.is_alive()),
        }
    except Exception as exc:
        message = f"每日定时任务失败：{exc}"
        with _state_lock:
            state = _load_state_unlocked()
            state.update({
                "last_finished_at": _now_text(),
                "last_status": "error",
                "last_message": message,
                "last_result": {"error": str(exc), "run_date": run_date},
            })
            saved = _save_state_unlocked(state)
        record_task_event(
            job_kind="daily_scheduler",
            job_id=job_id,
            event_type="failed",
            status="error",
            stage="error",
            message=message,
            payload={"error": str(exc), "run_date": run_date},
        )
        return {
            **saved,
            "running": False,
            "thread_alive": bool(_scheduler_thread and _scheduler_thread.is_alive()),
        }
    finally:
        if lock_acquired:
            _run_lock.release()


def run_daily_scheduler_if_due(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now()
    with _state_lock:
        state = _load_state_unlocked()
    if not _should_run(current, state):
        return {
            **get_daily_scheduler_status(),
            "due": False,
        }
    return {
        **run_daily_scheduler_once(),
        "due": True,
    }


def _scheduler_loop() -> None:
    while not _stop_event.wait(POLL_SECONDS):
        run_daily_scheduler_if_due()


def start_daily_scheduler_thread() -> None:
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = Thread(target=_scheduler_loop, name="daily-scheduler", daemon=True)
    _scheduler_thread.start()


def stop_daily_scheduler_thread() -> None:
    _stop_event.set()
