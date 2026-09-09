import { ApiRequestError, requestJson } from "@/lib/api";
import type { AgentLogFileResponse, AgentLogFilesResponse, AssistantChatRequest, AssistantChatResponse, AutomatedReviewResponse, DappCatalogResponse, FullLogResponse, MacroAnalysisResponse, RagSearchRequest, RagSearchResponse, Task, TaskCreateRequest, TaskLogPageResponse, TxDetectRequest, TxDetectResponse, TxReviewRequest, TxReviewResponse, VulnerabilityKnowledgeResponse } from "../types";

const prefix = "/api/attackpilot";
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await requestJson<T>(`${prefix}${path}`, init);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 401) window.dispatchEvent(new Event("attackpilot:login"));
    throw error;
  }
}
const post = <T,>(path: string, payload?: unknown) => request<T>(path, { method: "POST", body: payload === undefined ? undefined : JSON.stringify(payload) });
const id = encodeURIComponent;
export const listTasks = (includeArchived = false) => request<Task[]>(`/tasks?include_archived=${includeArchived}`);
export const listDapps = () => request<DappCatalogResponse>("/dapps");
export const listVulnerabilityKnowledge = () => request<VulnerabilityKnowledgeResponse>("/knowledge/vulnerabilities");
export const reviewTransaction = (payload: TxReviewRequest) => post<TxReviewResponse>("/tx-review", payload);
export const detectTransactions = (payload: TxDetectRequest) => post<TxDetectResponse>("/tx-detect", payload);
export const startTransactionDeepAnalysis = (payload: TxReviewRequest) => post<Task>("/tx-review/deep-analysis", payload);
export const chatWithAssistant = (payload: AssistantChatRequest) => post<AssistantChatResponse>("/assistant/chat", payload);
export const searchRagKnowledge = (payload: RagSearchRequest) => post<RagSearchResponse>("/rag/search", payload);
export const getTask = (taskId: string) => request<Task>(`/tasks/${id(taskId)}`);
export const getMacroAnalysis = (taskId: string) => request<MacroAnalysisResponse>(`/tasks/${id(taskId)}/macro-analysis`);
export const getAutomatedReview = (taskId: string) => request<AutomatedReviewResponse>(`/tasks/${id(taskId)}/automated-review`);
export const createTask = (payload: TaskCreateRequest & { modules?: string[] }) => post<Task>("/tasks", payload);
export const cancelTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/cancel`);
export const archiveTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/archive`);
export const unarchiveTask = (taskId: string) => post<void>(`/tasks/${id(taskId)}/unarchive`);
export const deleteTask = (taskId: string) => request<void>(`/tasks/${id(taskId)}`, { method: "DELETE" });
export const getFullLog = (taskId: string, logId: string) => request<FullLogResponse>(`/task/${id(taskId)}/log/${id(logId)}`);
export function getTaskLogs(taskId: string, params: { limit?: number; before_id?: number | null; after_id?: number | null } = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null) query.set(key, String(value));
  return request<TaskLogPageResponse>(`/tasks/${id(taskId)}/logs?${query}`);
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
  if (error instanceof ApiRequestError) return typeof error.detail === "string" ? error.detail : "输入格式不正确，请检查交易与模块选择。";
  return error instanceof Error ? error.message : "请求失败，请稍后重试。";
}
