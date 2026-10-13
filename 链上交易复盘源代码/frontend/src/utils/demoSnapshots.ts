import snapshots from "../data/demoSnapshots.json";
import {
  AgentLogFileResponse,
  AutomatedReviewResponse,
  LogMessage,
  MacroAnalysisResponse,
  Task,
  TaskLogPageResponse,
} from "../types";

type DemoSnapshot = {
  id: string;
  source_task_id?: string | null;
  name: string;
  task: Task;
  logs: LogMessage[];
  macro?: MacroAnalysisResponse | null;
  review?: AutomatedReviewResponse | null;
};

type DemoLogPack = {
  demo_id: string;
  full_logs?: Record<string, string>;
  agent_log_dir?: string | null;
  agent_log_files?: AgentLogFileResponse[];
};

const demoCases = (snapshots as { cases: DemoSnapshot[] }).cases;
const logPackCache = new Map<string, Promise<DemoLogPack | null>>();

async function loadDemoLogPack(taskId: string): Promise<DemoLogPack | null> {
  const snapshot = getDemoSnapshot(taskId);
  if (!snapshot) return null;

  const cached = logPackCache.get(snapshot.id);
  if (cached) return cached;

  const request = fetch(`/demo-logs/${snapshot.id}.json`)
    .then((response) => (response.ok ? response.json() as Promise<DemoLogPack> : null))
    .catch(() => null);
  logPackCache.set(snapshot.id, request);
  return request;
}

export function getDemoSnapshot(taskId: string): DemoSnapshot | undefined {
  return demoCases.find((item) => item.id === taskId || item.source_task_id === taskId);
}

export function hasDemoSnapshot(taskId: string): boolean {
  return Boolean(getDemoSnapshot(taskId));
}

export function getDemoTaskIdForDapp(dappName: string): string | null {
  const normalized = dappName.trim().toLowerCase();
  return demoCases.find((item) => item.name.trim().toLowerCase() === normalized)?.id ?? null;
}

export function getDemoTask(taskId: string): Task | null {
  return getDemoSnapshot(taskId)?.task ?? null;
}

export function getDemoTaskLogs(
  taskId: string,
  params: { limit?: number; before_id?: number | null } = {},
): TaskLogPageResponse | null {
  const snapshot = getDemoSnapshot(taskId);
  if (!snapshot) return null;

  const sorted = [...snapshot.logs].sort((a, b) => (a.persisted_id ?? 0) - (b.persisted_id ?? 0));
  const beforeId = params.before_id;
  const filtered = beforeId == null ? sorted : sorted.filter((event) => (event.persisted_id ?? 0) < beforeId);
  const limit = params.limit ?? 200;
  const pageEvents = filtered.slice(Math.max(filtered.length - limit, 0));
  const nextBeforeId = pageEvents[0]?.persisted_id ?? null;

  return {
    events: pageEvents,
    next_before_id: filtered.length > pageEvents.length ? nextBeforeId : null,
    has_more: filtered.length > pageEvents.length,
    total: sorted.length,
  };
}

export function getDemoMacroAnalysis(taskId: string): MacroAnalysisResponse | null {
  return getDemoSnapshot(taskId)?.macro ?? null;
}

export function getDemoAutomatedReview(taskId: string): AutomatedReviewResponse | null {
  return getDemoSnapshot(taskId)?.review ?? null;
}

export async function getDemoFullLog(taskId: string, logId: string): Promise<string | null> {
  const snapshot = getDemoSnapshot(taskId);
  const logPack = await loadDemoLogPack(taskId);
  const fullLog = logPack?.full_logs?.[logId];
  if (fullLog) return fullLog;
  const log = snapshot?.logs.find((item) => item.log_id === logId || String(item.persisted_id) === logId);
  return log?.message ?? null;
}

export async function getDemoAgentLogFiles(taskId: string) {
  const snapshot = getDemoSnapshot(taskId);
  if (!snapshot) return null;
  const logPack = await loadDemoLogPack(taskId);
  return {
    task_id: snapshot.task.task_id,
    dapp_name: snapshot.task.dapp_name,
    log_dir: logPack?.agent_log_dir ?? null,
    files: (logPack?.agent_log_files ?? []).map((file) => ({
      id: file.id,
      name: file.name,
      agent: file.agent,
      size: file.size,
      modified_at: file.modified_at,
    })),
  };
}

export async function getDemoAgentLogFile(taskId: string, fileId: string): Promise<AgentLogFileResponse | null> {
  const snapshot = getDemoSnapshot(taskId);
  const logPack = await loadDemoLogPack(taskId);
  const file = logPack?.agent_log_files?.find((item) => item.id === fileId);
  return file ? { ...file, task_id: snapshot?.task.task_id ?? taskId } : null;
}

export function listDemoTasks(): Task[] {
  return demoCases.map((item) => item.task);
}
