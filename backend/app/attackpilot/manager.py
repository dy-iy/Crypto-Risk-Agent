"""Single scheduler for this FastAPI instance, with cancellable process groups."""
import asyncio
import fcntl
import os
import signal
import shutil
import sys
from pathlib import Path
from . import settings, store
from .privacy import redact_text

class TaskManager:
    def __init__(self):
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.runners: dict[str, asyncio.Task] = {}
        self.scheduler: asyncio.Task | None = None
        self.lock_file = None
        self.closing = False

    async def start(self):
        if self.scheduler:
            return
        settings.RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        self.lock_file = (settings.RUNTIME_ROOT / "scheduler.lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close(); self.lock_file = None
            return  # Another FastAPI process owns the scheduler; SQLite is shared.
        for task in store.unfinished():
            await self._terminate(None, store.task_dir(task["task_id"]))
            store.transition(task["task_id"], "failed", error="后端进程中断，请重新创建分析任务。")
        self.closing = False
        self.scheduler = asyncio.create_task(self._schedule())

    async def _schedule(self):
        while not self.closing:
            limit = max(1, min(int(os.getenv("ATTACKPILOT_MAX_TASKS", "1")), 4))
            for task in store.unfinished():
                if len(self.runners) >= limit:
                    break
                if task["status"] == "pending" and task["task_id"] not in self.runners:
                    task_id = task["task_id"]
                    runner = asyncio.create_task(self._run(task))
                    self.runners[task_id] = runner
                    runner.add_done_callback(lambda _future, key=task_id: self.runners.pop(key, None))
            await asyncio.sleep(.5)

    async def _run(self, task):
        task_id = task["task_id"]
        if not store.transition(task_id, "running"):
            return
        work = store.task_dir(task_id); work.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONPATH": str(settings.BACKEND_ROOT), "ATTACKPILOT_WORK_DIR": str(work), "ATTACKPILOT_OWNER_ID": task["owner_id"], "ATTACKPILOT_DB_PATH": str(settings.DATABASE_PATH), "ATTACKPILOT_RUNTIME_DIR": str(settings.RUNTIME_ROOT)}
        process = None
        try:
            # stdout is diagnostic-only; structured logs are written through store.append_log.
            with (work / "worker.log").open("wb") as output:
                process = await asyncio.create_subprocess_exec(sys.executable, "-m", "app.attackpilot.worker", task_id, cwd=str(settings.PACKAGE_ROOT), env=env, stdout=output, stderr=output, start_new_session=True)
                self.processes[task_id] = process
                started = asyncio.get_running_loop().time()
                deadline = max(30, int(os.getenv("ATTACKPILOT_TASK_TIMEOUT", "3600")))
                while process.returncode is None:
                    current = store.get_task(task_id)
                    if not current or current["status"] in store.TERMINAL or self.closing:
                        await self._terminate(process, work); break
                    if asyncio.get_running_loop().time() - started > deadline:
                        store.transition(task_id, "failed", error="分析超过时间上限，请缩小交易范围后重试。")
                        await self._terminate(process, work); break
                    try:
                        await asyncio.wait_for(process.wait(), timeout=.5)
                    except asyncio.TimeoutError:
                        pass
                current = store.get_task(task_id)
                if current and current["status"] not in store.TERMINAL:
                    store.transition(task_id, "failed", error="分析进程未正常完成，请查看任务日志。")
        except Exception as exc:
            store.transition(task_id, "failed", error=redact_text(f"无法运行分析进程：{type(exc).__name__}"))
        finally:
            if process:
                await self._terminate(process, work)
            self.processes.pop(task_id, None)
            if not store.get_task(task_id):
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _task_groups(work):
        """MCP opens a separate session; inherited task identity also finds orphans."""
        if work is None: return set()
        marker = b"ATTACKPILOT_WORK_DIR=" + os.fsencode(str(work))
        groups = set()
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit(): continue
            try:
                if marker not in (directory / "environ").read_bytes().split(b"\0"):
                    continue
                group = os.getpgid(int(directory.name))
                if group != os.getpgrp(): groups.add(group)
            except (OSError, ValueError):
                continue
        return groups

    async def _terminate(self, process, work=None):
        groups = self._task_groups(work)
        if process and process.returncode is None:
            try: groups.add(os.getpgid(process.pid))
            except ProcessLookupError: pass
        groups.discard(os.getpgrp())
        def signal_groups(sig):
            for group in groups:
                try: os.killpg(group, sig)
                except ProcessLookupError: pass
        signal_groups(signal.SIGTERM)
        if process:
            try: await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError: pass
        elif groups:
            await asyncio.sleep(.1)
        signal_groups(signal.SIGKILL)
        if process: await process.wait()

    async def stop(self):
        self.closing = True
        if self.scheduler:
            self.scheduler.cancel()
            await asyncio.gather(self.scheduler, return_exceptions=True)
            self.scheduler = None
        for task_id in list(self.runners):
            store.transition(task_id, "failed", error="后端服务停止，任务已中断。")
        await asyncio.gather(*list(self.runners.values()), return_exceptions=True)
        if self.lock_file:
            self.lock_file.close(); self.lock_file = None

manager = TaskManager()
