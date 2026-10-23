import { ApiRequestError, requestJson } from "@/lib/api";
import type { AgentLogFileResponse, AgentLogFilesResponse, AssistantChatRequest, AssistantChatResponse, AutomatedReviewResponse, DappCatalogResponse, FullLogResponse, MacroAnalysisResponse, RagSearchRequest, RagSearchResponse, Task, TaskCreateRequest, TaskLogPageResponse, TxDetectRequest, TxDetectResponse, TxReviewRequest, TxReviewResponse, VulnerabilityKnowledgeResponse } from "../types";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await requestJson<T>(`/api/attackpilot${path}`, init);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 401 && typeof window !== "undefined") window.dispatchEvent(new Event("attackpilot:login"));
    if (error instanceof Error && error.name === "TimeoutError") {
      throw new Error(path === "/tasks" || path === "/tx-review/deep-analysis"
        ? "创建请求等待超时，请先在任务库检查是否已创建任务，再决定是否重试。"
        : "请求等待超时，请稍后重试。");
    }
    throw error;
  }
}
const post = <T,>(path: string, payload?: unknown, signal?: AbortSignal) => request<T>(path, { method: "POST", body: payload === undefined ? undefined : JSON.stringify(payload), signal });
const id = encodeURIComponent;
export const listTasks = (includeArchived = false, signal?: AbortSignal) => request<Task[]>(`/tasks?include_archived=${includeArchived}`, { signal });
export const listDapps = () => request<DappCatalogResponse>("/dapps");
export const listVulnerabilityKnowledge = () => request<VulnerabilityKnowledgeResponse>("/knowledge/vulnerabilities");
export const reviewTransaction = (payload: TxReviewRequest, signal?: AbortSignal) => post<TxReviewResponse>("/tx-review", payload, signal);
export const detectTransactions = (payload: TxDetectRequest, signal?: AbortSignal) => post<TxDetectResponse>("/tx-detect", payload, signal);
export const startTransactionDeepAnalysis = (payload: TxReviewRequest, signal?: AbortSignal) => post<Task>("/tx-review/deep-analysis", payload, signal);
export const chatWithAssistant = (payload: AssistantChatRequest, signal?: AbortSignal) => post<AssistantChatResponse>("/assistant/chat", payload, signal);
export const searchRagKnowledge = (payload: RagSearchRequest, signal?: AbortSignal) => post<RagSearchResponse>("/rag/search", payload, signal);
export const getTask = (taskId: string, signal?: AbortSignal) => request<Task>(`/tasks/${id(taskId)}`, { signal });
export type ReportTranslation = {
  task_id: string;
  language: "zh-CN";
  source_language: "zh-CN" | "en" | "mixed" | "unknown";
  source_hash: string;
  status: "ready" | "missing" | "original";
  translated_report: string | null;
  cached: boolean;
  model: string | null;
  translated_at: string | null;
};
export const getReportTranslation = (taskId: string) => request<ReportTranslation>(`/tasks/${id(taskId)}/report-translation`);
export const createReportTranslation = (taskId: string) => post<ReportTranslation>(`/tasks/${id(taskId)}/report-translation`);
export const getMacroAnalysis = (taskId: string, signal?: AbortSignal) => request<MacroAnalysisResponse>(`/tasks/${id(taskId)}/macro-analysis`, { signal });
export const getAutomatedReview = (taskId: string, signal?: AbortSignal) => request<AutomatedReviewResponse>(`/tasks/${id(taskId)}/automated-review`, { signal });
export const createTask = (payload: TaskCreateRequest & { modules?: string[] }, signal?: AbortSignal) => post<Task>("/tasks", payload, signal);
export const cancelTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/cancel`);
export const archiveTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/archive`);
export const unarchiveTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/unarchive`);
export const deleteTask = (taskId: string) => request<void>(`/tasks/${id(taskId)}`, { method: "DELETE" });
export const getFullLog = (taskId: string, logId: string) => request<FullLogResponse>(`/task/${id(taskId)}/log/${id(logId)}`);
export function getTaskLogs(taskId: string, params: { limit?: number; before_id?: number | null; after_id?: number | null } = {}, signal?: AbortSignal) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null) query.set(key, String(value));
  return request<TaskLogPageResponse>(`/tasks/${id(taskId)}/logs?${query}`, { signal });
}
export const listAgentLogFiles = (taskId: string) => request<AgentLogFilesResponse>(`/tasks/${id(taskId)}/agent-log-files`);
export const getAgentLogFile = (taskId: string, fileId: string, maxBytes = 2_000_000) => request<AgentLogFileResponse>(`/tasks/${id(taskId)}/agent-log-files/${id(fileId)}?max_bytes=${maxBytes}`);

export type Capabilities = {
  model: { name: string; configured: boolean };
  chains: Record<string, { rpc: boolean; explorer: boolean }>;
  tenderly: boolean; compiler: boolean; node: boolean; node_modules: boolean;
  missing_dependencies: string[]; note: string;
};
export const getCapabilities = () => request<Capabilities>("/capabilities");

export function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.detail?.trim()) return error.detail;
    if (error.status === 401) return "请先登录后重试。";
    if (error.status === 403) return "当前账户无权执行此操作。";
    if (error.status === 404) return "请求的任务或记录不存在，或当前账户无权访问。";
    if (error.status === 429) return "请求过于频繁，请稍后重试。";
    if (error.status >= 500) return "分析服务暂时不可用，请稍后重试。";
    return "请求未成功，请检查输入或刷新任务后重试。";
  }
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}
