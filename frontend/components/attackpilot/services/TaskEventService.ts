import type { TaskEvent } from "../types";
import { TaskStatus } from "../types";
import { ApiRequestError } from "@/lib/api";
import { errorMessage, getTask, getTaskLogs } from "./api";

type State = 0 | 1 | 2 | 3;
class TaskEvents {
  private source: EventSource | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private listeners = new Set<(event: TaskEvent) => void>();
  private statusListeners = new Set<(state: State | null) => void>();
  private history: TaskEvent[] = [];
  private state: State | null = null;
  private generation = 0;
  private logCursor = 0;
  private polling = false;
  private logIds = new Set<string>();
  private controller: AbortController | null = null;
  private taskId: string | null = null;
  private lastStatus: string | null = null;

  private setState(state: State | null) {
    this.state = state;
    this.statusListeners.forEach(listener => listener(state));
  }
  private emit(event: TaskEvent) {
    if (event.type === "TASK_STATUS") {
      const status = JSON.stringify([event.task_id, event.dapp_name, event.status, event.created_at ?? null,
        event.completed_at ?? null, event.duration ?? null, event.error ?? null, event.archived ?? false]);
      if (status === this.lastStatus) return;
      this.lastStatus = status;
    }
    if (event.type === "LOG" && Number.isSafeInteger(event.persisted_id) && event.persisted_id! > 0) {
      this.logCursor = Math.max(this.logCursor, event.persisted_id!);
    }
    if (event.type === "LOG" && event.log_id) {
      if (this.logIds.has(event.log_id)) return;
      this.logIds.add(event.log_id);
    }
    this.history = [...this.history, event].slice(-5000);
    this.listeners.forEach(listener => listener(event));
  }
  connect(taskId: string, onConnect: () => void, onError: (message: string) => void) {
    this.disconnect();
    if (this.taskId !== taskId) this.clearHistory();
    this.taskId = taskId;
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    this.setState(0);
    try {
      this.source = new EventSource(`/api/attackpilot/tasks/${encodeURIComponent(taskId)}/events`);
      this.source.onopen = () => { if (generation === this.generation) { this.setState(1); onConnect(); } };
      this.source.onmessage = message => {
        if (generation !== this.generation) return;
        try {
          const event = JSON.parse(message.data) as TaskEvent;
          if (!event || typeof event !== "object" || typeof event.type !== "string") throw new Error("Invalid event");
          if (event.task_id && event.task_id !== taskId) return;
          if ((event.type === "TASK_STATUS" || event.type === "TASK_FINAL")
            && (event.task_id !== taskId || !Object.values(TaskStatus).includes(event.status))) throw new Error("Invalid task status");
          if (event.type === "TASK_FINAL"
            && ![TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED].includes(event.status)) throw new Error("Invalid final status");
          this.emit(event);
          if (event.type === "TASK_FINAL") this.disconnect();
        } catch { onError("实时事件格式异常，正在通过任务接口恢复。"); }
      };
      this.source.onerror = () => { if (generation === this.generation) this.setState(0); };
    } catch {
      onError("实时连接暂不可用，正在通过任务接口恢复。");
    }
    const fetchLogs = async () => {
      let more = true;
      while (more && generation === this.generation) {
        const previousCursor = this.logCursor;
        const page = await getTaskLogs(taskId, { after_id: previousCursor, limit: 500 }, controller.signal);
        if (generation !== this.generation) return;
        page.events.forEach(event => this.emit(event));
        if (Number.isSafeInteger(page.next_after_id) && page.next_after_id! > this.logCursor) this.logCursor = page.next_after_id!;
        more = page.has_more;
        if (more && this.logCursor <= previousCursor) throw new Error("日志分页没有前进");
      }
    };
    // Check the persisted status even while SSE is open: proxies can leave a
    // connection open after silently dropping the final event.
    this.timer = setInterval(async () => {
      if (this.polling || generation !== this.generation) return;
      this.polling = true;
      try {
        const task = await getTask(taskId, controller.signal);
        if (generation !== this.generation) return;
        const terminal = [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED].includes(task.status);
        onConnect();
        if (terminal) {
          this.source?.close(); this.source = null;
          this.setState(null);
        }
        // A broken logs endpoint must not hide a completed report or freeze
        // task status recovery. Publish the persisted state independently.
        this.emit({ ...task, type: terminal ? "TASK_FINAL" : "TASK_STATUS" });
        let logError: unknown;
        if (terminal || this.state !== 1) {
          try { await fetchLogs(); } catch (error) { logError = error; }
        }
        if (generation !== this.generation) return;
        if (terminal) this.disconnect();
        if (logError) {
          const unavailable = logError instanceof ApiRequestError && [401, 403, 404].includes(logError.status);
          onError(unavailable ? errorMessage(logError) : "任务状态已恢复，但部分日志暂不可用；可在日志页重试加载。");
          if (unavailable && !terminal) this.disconnect();
        }
      } catch (error) {
        if (generation === this.generation) {
          const unavailable = error instanceof ApiRequestError && [401, 403, 404].includes(error.status);
          onError(unavailable ? errorMessage(error) : "连接暂时中断，正在自动重试。");
          if (unavailable) this.disconnect();
        }
      }
      finally { if (generation === this.generation) this.polling = false; }
    }, 3000);
  }
  disconnect() {
    this.generation++;
    this.polling = false;
    this.controller?.abort(); this.controller = null;
    this.source?.close(); this.source = null;
    if (this.timer) clearInterval(this.timer);
    this.timer = null; this.setState(null);
  }
  clearHistory() { this.history = []; this.logIds.clear(); this.logCursor = 0; this.lastStatus = null; }
  getHistory() { return this.history; }
  getConnectionState() { return this.state; }
  subscribe(listener: (event: TaskEvent) => void) { this.listeners.add(listener); }
  unsubscribe(listener: (event: TaskEvent) => void) { this.listeners.delete(listener); }
  subscribeStatus(listener: (state: State | null) => void) { this.statusListeners.add(listener); }
  unsubscribeStatus(listener: (state: State | null) => void) { this.statusListeners.delete(listener); }
}
const taskEvents = new TaskEvents();
export default taskEvents;
