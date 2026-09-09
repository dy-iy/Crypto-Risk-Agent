import type { TaskEvent } from "../types";
import { TaskStatus } from "../types";
import { getTask, getTaskLogs } from "./api";

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

  private setState(state: State | null) {
    this.state = state;
    this.statusListeners.forEach(listener => listener(state));
  }
  private emit(event: TaskEvent) {
    if (event.type === "LOG" && event.log_id) {
      if (this.logIds.has(event.log_id)) return;
      this.logIds.add(event.log_id);
      this.logCursor = Math.max(this.logCursor, event.persisted_id || 0);
    }
    this.history = [...this.history, event].slice(-5000);
    this.listeners.forEach(listener => listener(event));
  }
  connect(taskId: string, onConnect: () => void, onError: (message: string) => void) {
    this.disconnect();
    const generation = this.generation;
    this.setState(0);
    this.source = new EventSource(`/api/attackpilot/tasks/${encodeURIComponent(taskId)}/events`);
    this.source.onopen = () => { if (generation === this.generation) { this.setState(1); onConnect(); } };
    this.source.onmessage = message => {
      if (generation !== this.generation) return;
      try {
        const event = JSON.parse(message.data) as TaskEvent;
        this.emit(event);
        if (event.type === "TASK_FINAL") this.disconnect();
      } catch { onError("实时事件格式异常，请刷新任务。"); }
    };
    this.source.onerror = () => { if (generation === this.generation) this.setState(0); };
    // Poll persisted logs while SSE reconnects; retrieve every page before advancing.
    this.timer = setInterval(async () => {
      if (this.state === 1 || this.polling) return;
      this.polling = true;
      try {
        let more = true;
        while (more && generation === this.generation) {
          const page = await getTaskLogs(taskId, { after_id: this.logCursor, limit: 500 });
          if (generation !== this.generation) return;
          page.events.forEach(event => this.emit(event));
          more = page.has_more && page.events.length > 0;
        }
        const task = await getTask(taskId);
        if (generation !== this.generation) return;
        const terminal = [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED].includes(task.status);
        this.emit({ ...task, type: terminal ? "TASK_FINAL" : "TASK_STATUS" });
        if (terminal) this.disconnect();
      } catch { if (generation === this.generation) onError("连接暂时中断，正在自动重试。"); }
      finally { if (generation === this.generation) this.polling = false; }
    }, 3000);
  }
  disconnect() {
    this.generation++;
    this.polling = false;
    this.source?.close(); this.source = null;
    if (this.timer) clearInterval(this.timer);
    this.timer = null; this.setState(null);
  }
  clearHistory() { this.history = []; this.logIds.clear(); this.logCursor = 0; }
  getHistory() { return this.history; }
  getConnectionState() { return this.state; }
  subscribe(listener: (event: TaskEvent) => void) { this.listeners.add(listener); }
  unsubscribe(listener: (event: TaskEvent) => void) { this.listeners.delete(listener); }
  subscribeStatus(listener: (state: State | null) => void) { this.statusListeners.add(listener); }
  unsubscribeStatus(listener: (state: State | null) => void) { this.statusListeners.delete(listener); }
}
const taskEvents = new TaskEvents();
export default taskEvents;
