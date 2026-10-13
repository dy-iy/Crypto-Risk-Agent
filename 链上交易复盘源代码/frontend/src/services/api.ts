import axios from "axios";
import { BACKEND_HTTP_URL } from "../config/appConfig";
import {
  getDemoAutomatedReview,
  getDemoFullLog,
  getDemoMacroAnalysis,
  getDemoTask,
  getDemoTaskLogs,
  getDemoAgentLogFile,
  getDemoAgentLogFiles,
  hasDemoSnapshot,
  listDemoTasks,
} from "../utils/demoSnapshots";
import {
  AgentLogFileResponse,
  AgentLogFilesResponse,
  AssistantChatRequest,
  AssistantChatResponse,
  AutomatedReviewResponse,
  DappCatalogResponse,
  FullLogResponse,
  MacroAnalysisResponse,
  RagSearchRequest,
  RagSearchResponse,
  Task,
  TaskCreateRequest,
  TxDetectRequest,
  TxDetectResponse,
  TaskLogPageResponse,
  TxReviewRequest,
  TxReviewResponse,
  VulnerabilityKnowledgeResponse,
} from "../types";

export const api = axios.create({
  baseURL: BACKEND_HTTP_URL,
});

export async function listTasks(includeArchived = false): Promise<Task[]> {
  try {
    const response = await api.get<Task[]>("/api/tasks", {
      params: includeArchived ? { include_archived: true } : undefined,
    });
    const remoteIds = new Set(response.data.map((task) => task.task_id));
    const offlineDemos = listDemoTasks().filter((task) => !remoteIds.has(task.task_id));
    return [...response.data, ...offlineDemos];
  } catch {
    return listDemoTasks();
  }
}

export async function listDapps(): Promise<DappCatalogResponse> {
  const response = await api.get<DappCatalogResponse>("/api/dapps");
  return response.data;
}


export async function listVulnerabilityKnowledge(): Promise<VulnerabilityKnowledgeResponse> {
  const response = await api.get<VulnerabilityKnowledgeResponse>("/api/knowledge/vulnerabilities");
  return response.data;
}

export async function reviewTransaction(payload: TxReviewRequest): Promise<TxReviewResponse> {
  const response = await api.post<TxReviewResponse>("/api/tx-review", payload);
  return response.data;
}

export async function detectTransactions(payload: TxDetectRequest): Promise<TxDetectResponse> {
  const response = await api.post<TxDetectResponse>("/api/tx-detect", payload);
  return response.data;
}

export async function startTransactionDeepAnalysis(payload: TxReviewRequest): Promise<Task> {
  const response = await api.post<Task>("/api/tx-review/deep-analysis", payload);
  return response.data;
}

export async function chatWithAssistant(payload: AssistantChatRequest): Promise<AssistantChatResponse> {
  const response = await api.post<AssistantChatResponse>("/api/assistant/chat", payload);
  return response.data;
}

export async function searchRagKnowledge(payload: RagSearchRequest): Promise<RagSearchResponse> {
  const response = await api.post<RagSearchResponse>("/api/rag/search", payload);
  return response.data;
}

export async function getTask(taskId: string): Promise<Task> {
  const demoTask = getDemoTask(taskId);
  if (demoTask) return demoTask;
  const response = await api.get<Task>(`/api/tasks/${taskId}`);
  return response.data;
}

export async function getMacroAnalysis(taskId: string): Promise<MacroAnalysisResponse> {
  const demoMacro = getDemoMacroAnalysis(taskId);
  if (demoMacro) return demoMacro;
  if (hasDemoSnapshot(taskId)) throw new Error("Offline demo macro analysis is not available.");
  const response = await api.get<MacroAnalysisResponse>(`/api/tasks/${taskId}/macro-analysis`);
  return response.data;
}

export async function getAutomatedReview(taskId: string): Promise<AutomatedReviewResponse> {
  const demoReview = getDemoAutomatedReview(taskId);
  if (demoReview) return demoReview;
  if (hasDemoSnapshot(taskId)) throw new Error("Offline demo automated review is not available.");
  const response = await api.get<AutomatedReviewResponse>(`/api/tasks/${taskId}/automated-review`);
  return response.data;
}

export async function createTask(payload: TaskCreateRequest): Promise<Task> {
  const response = await api.post<Task>("/api/tasks", payload);
  return response.data;
}

export async function cancelTask(taskId: string): Promise<void> {
  await api.post(`/api/tasks/${taskId}/cancel`);
}

export async function deleteTask(taskId: string): Promise<void> {
  await api.delete(`/api/tasks/${taskId}`);
}

export async function archiveTask(taskId: string): Promise<void> {
  await api.post(`/api/tasks/${taskId}/archive`);
}

export async function unarchiveTask(taskId: string): Promise<void> {
  await api.post(`/api/tasks/${taskId}/unarchive`);
}

export async function getFullLog(taskId: string, logId: string): Promise<FullLogResponse> {
  const demoLog = await getDemoFullLog(taskId, logId);
  if (demoLog) return { content: demoLog, source: "cache" };
  const response = await api.get<FullLogResponse>(`/api/task/${taskId}/log/${logId}`);
  return response.data;
}

export async function getTaskLogs(
  taskId: string,
  params: { limit?: number; before_id?: number | null } = {},
): Promise<TaskLogPageResponse> {
  const demoLogs = getDemoTaskLogs(taskId, params);
  if (demoLogs) return demoLogs;
  const response = await api.get<TaskLogPageResponse>(`/api/tasks/${taskId}/logs`, { params });
  return response.data;
}

export async function listAgentLogFiles(taskId: string): Promise<AgentLogFilesResponse> {
  const demoFiles = await getDemoAgentLogFiles(taskId);
  if (demoFiles) return demoFiles;
  const response = await api.get<AgentLogFilesResponse>(`/api/tasks/${taskId}/agent-log-files`);
  return response.data;
}

export async function getAgentLogFile(
  taskId: string,
  fileId: string,
  maxBytes = 2_000_000,
): Promise<AgentLogFileResponse> {
  const demoFile = await getDemoAgentLogFile(taskId, fileId);
  if (demoFile) return demoFile;
  const response = await api.get<AgentLogFileResponse>(`/api/tasks/${taskId}/agent-log-files/${fileId}`, {
    params: { max_bytes: maxBytes },
  });
  return response.data;
}
