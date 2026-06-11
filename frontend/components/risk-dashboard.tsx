"use client";

import { FormEvent, MouseEvent as ReactMouseEvent, ReactNode, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AgentProgress, LoadingDots } from "@/components/ui/loading-states";
import {
  buildNewsAnalysisInput,
  clearPendingNewsAnalysisInput,
  readPendingNewsAnalysisInput,
} from "@/lib/news-analysis";
import {
  clearApiCache,
  CoinLibraryItem,
  CoinRankingItem,
  DailyRiskReport,
  DailyReportSubscription,
  DailySchedulerStatus,
  fetchCoinRanking,
  fetchCoinLibrary,
  fetchDailyReportSubscription,
  fetchDailyRiskReport,
  fetchDailySchedulerStatus,
  fetchCurrentNewsUpdateJob,
  fetchNewsDetail,
  fetchNewsUpdateJob,
  fetchNewsRanking,
  fetchRiskOverview,
  FinalContextMeta,
  NewsUpdateJob,
  NewsUpdateProgress,
  NewsUpdateResponse,
  NewsRankingItem,
  readCachedCoinRanking,
  readCachedDailyRiskReport,
  readCachedNewsRanking,
  readCachedRiskOverview,
  RiskOverview,
  ChatProgressStage,
  ChatAgentResult,
  AdviceGeneration,
  ImpactAnalysis,
  RiskReport,
  RiskTypeBranch,
  startNewsUpdateJob,
  streamChatMessage,
  streamRiskAssistant,
  AccountSecurityEvent,
  AuthSessionItem,
  AuthUser,
  FavoriteItem,
  FavoriteType,
  AnalysisDisposition,
  ApiRequestError,
  AuditPruneResult,
  AuditSummary,
  addFavorite,
  changePassword,
  createUserAsset,
  deleteAccountData,
  deleteAnalysisReport,
  deleteFavorite,
  exportAccountData,
  fetchAuditSummary,
  fetchAnalysisReports,
  fetchAccountSecurityEvents,
  fetchCurrentUser,
  fetchFavorites,
  fetchAuthSessions,
  fetchBackupManifest,
  fetchRateLimitStatus,
  fetchStorageInventory,
  fetchSystemReadiness,
  fetchSystemTaskEvents,
  fetchUserAssets,
  generateDailyRiskReport,
  loginUser,
  logoutUser,
  PortfolioWatchlistItem,
  pruneExpiredAuthSessions,
  pruneGuestSimAccounts,
  pruneInvalidJsonBackups,
  pruneRuntimeJobs,
  pruneTaskEvents,
  RateLimitStatus,
  registerUser,
  revokeOtherAuthSessions,
  runDailySchedulerNow,
  saveAnalysisReport,
  BackupManifest,
  StorageInventory,
  SystemReadiness,
  SystemTaskEvent,
  updateDailyReportSubscription,
  updateDailySchedulerStatus,
  updateAnalysisReportDisposition,
  updateUserAsset,
} from "@/lib/api";

type ActiveView = "home" | "chat" | "news" | "coin" | "daily" | "portfolio" | "sim" | "reports" | "favoriteNews" | "favoriteReports" | "my" | "settings";
type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
};

type NewsFilter = "all" | "top10" | "high" | "medium" | "low" | "red";
type NewsSort = "time_desc" | "time_asc" | "score_desc" | "score_asc";
type CoinFilter = "all" | "top10" | "high" | "medium" | "low";
type CoinSort = "score_desc" | "score_asc" | "news_desc" | "news_asc";
type RankingRange = "24h" | "7d";
type MetricTone = "blue" | "red" | "orange" | "green" | "purple";
type DailyRiskTheme = {
  themeId: string;
  title: string;
  riskType: string;
  affectedAssets: string[];
  eventCount: number;
  maxPersonalScore: number;
  riskLevel: string;
  summary: string;
  severityReason?: string;
  evidenceSummary: string[];
  monitoringItems: string[];
};
type DailyAssetReport = {
  assetSymbol: string;
  assetName: string;
  isHolding: boolean;
  exposureLabel: string;
  exposureMode?: string;
  exposureBucket?: string;
  marketValue?: number;
  priceChange24h?: number;
  alertThreshold?: number;
  personalRiskScore: number;
  riskLevel: string;
  summary: string;
  riskTypes: string[];
  keyDrivers: string[];
  evidenceSummary: string[];
  monitoringItems: string[];
  actions: string[];
  sourceEventCount: number;
};
type TrendPoint = {
  label: string;
  value: number;
  timestamp?: number;
  meta?: Record<string, number | string>;
};
type NewsTrendBucket = {
  avgScore: number;
  highCount: number;
  label: string;
  newsCount: number;
  redCount: number;
  timestamp: number;
};
type MyVaultTab = "overview" | "assets" | "news" | "reports" | "alerts" | "reviews";
type UserAssetFormState = {
  alertThreshold: string;
  isHolding: boolean;
  symbol: string;
};
type AccountCenterStats = {
  favoriteNews: number;
  favoriteReports: number;
  highRiskAssets: number;
  loadingAssets: boolean;
  pendingAlerts: number;
  watchedAssets: number;
};

type AnalysisRecord = {
  id: string;
  title: string;
  createdAt: string;
  input: string;
  report: RiskReport;
  disposition?: AnalysisDisposition;
  dispositionNote?: string;
};

const PortfolioRiskRadar = dynamic(() => import("@/components/portfolio-risk-radar"), {
  loading: () => <DeferredPanelLoader title="组合风险雷达加载中" />,
  ssr: false,
});

const SimTradingPanel = dynamic(() => import("@/components/sim-trading-panel"), {
  loading: () => <DeferredPanelLoader title="模拟交易面板加载中" />,
  ssr: false,
});

type RankingDataStatus = {
  mode: "real" | "demo";
  updatedAt: string;
  newsSourceStatus: "connected" | "fallback" | "unknown";
  agentStatus: "ready" | "fallback" | "unknown";
  message: string;
};

type AnalysisTaskSnapshot = {
  id: string;
  input: string;
  status: "running" | "success" | "error";
  stage: ChatProgressStage;
  startedAt: string;
  updatedAt: string;
  recordId?: string;
  error?: string;
};

type NavItem = {
  key: ActiveView;
  label: string;
  icon: ReactNode;
};

const examplePrompts = [
  "某交易所宣布暂停所有提现，官方称钱包系统维护，但社群出现大量无法提款反馈，请评估风险。",
  "SOL 链上大额转账数量激增，多个巨鲸地址向交易所转入 SOL，社交媒体负面讨论快速上升。",
  "某 DeFi 协议疑似遭遇 flash loan attack，攻击者从资金池转出约 1200 万美元资产。",
  "USDT 在多个交易对出现短时脱锚，链上兑换量异常放大，市场担心储备透明度。",
];

const forbiddenAdviceTerms = ["买入", "卖出", "做空", "梭哈"];

const fallbackNews: NewsRankingItem[] = [
  {
    rank: 1,
    news_id: "demo-1",
    title: "某交易所暂停所有提现，系统维护中",
    content: "交易所公告称钱包系统维护，多个用户反馈长时间无法提现。",
    risk_score: 96,
    risk_level: "高风险",
    risk_type: "交易所风险",
    published_at: "2026-04-20 10:28:00",
    coins: ["--"],
    summary: "提现暂停叠加用户投诉，需关注资产流动性与运营稳定性。",
    evidence: "官方暂停提现公告、社群投诉增加、恢复时间不明确。",
  },
  {
    rank: 2,
    news_id: "demo-2",
    title: "稳定币短时脱锚，USDT 跌至 0.92",
    content: "多个交易对出现异常价差，链上兑换量升高。",
    risk_score: 92,
    risk_level: "高风险",
    risk_type: "稳定币风险",
    published_at: "2026-04-20 10:15:00",
    coins: ["USDT"],
    summary: "价格偏离锚定区间，可能引发赎回压力与流动性风险。",
    evidence: "价格脱锚、兑换量异常、市场担忧储备透明度。",
  },
  {
    rank: 3,
    news_id: "demo-3",
    title: "知名项目 Rug Pull，团队疑似跑路",
    content: "项目社媒停止更新，合约资金被快速转移。",
    risk_score: 89,
    risk_level: "高风险",
    risk_type: "项目风险",
    published_at: "2026-04-20 09:57:00",
    coins: ["XYZ"],
    summary: "团队失联与资金转移同时出现，投资者保护风险较高。",
    evidence: "资金外流、社群无法联系团队、公告缺失。",
  },
];

const fallbackCoins: CoinRankingItem[] = [
  {
    rank: 1,
    symbol: "SOL",
    name: "Solana",
    final_score: 92,
    risk_level: "高风险",
    news_count: 186,
    main_risk_type: "交易活跃异常 / 市场波动风险",
    top_news_title: "SOL 链上大额转账数量激增",
    summary: "链上转账与交易所流入同时升高，短期波动风险上升。",
    related_news: [],
  },
  {
    rank: 2,
    symbol: "FTT",
    name: "FTX Token",
    final_score: 88,
    risk_level: "高风险",
    news_count: 142,
    main_risk_type: "流动性风险",
    top_news_title: "FTT 相关地址出现异常转移",
    summary: "相关风险事件集中出现，需观察流动性变化。",
    related_news: [],
  },
  {
    rank: 3,
    symbol: "LUNC",
    name: "Terra Classic",
    final_score: 76,
    risk_level: "中风险",
    news_count: 128,
    main_risk_type: "社群风险",
    top_news_title: "LUNC 社群治理争议升温",
    summary: "舆情升温但直接资产风险仍需更多证据确认。",
    related_news: [],
  },
];

const initialRankingDataStatus: RankingDataStatus = {
  mode: "real",
  updatedAt: "",
  newsSourceStatus: "unknown",
  agentStatus: "unknown",
  message: "正在读取风险排行榜数据",
};

const demoRankingDataStatus: RankingDataStatus = {
  mode: "demo",
  updatedAt: "演示样例",
  newsSourceStatus: "fallback",
  agentStatus: "fallback",
  message: "后端排行榜暂未连接，当前展示本地演示数据",
};

const emptyNewsItem: NewsRankingItem = {
  rank: 0,
  news_id: "empty-news",
  title: "暂无新闻风险数据",
  content: "",
  risk_score: 0,
  risk_level: "低风险",
  risk_type: "暂无数据",
  published_at: "",
  coins: [],
  summary: "等待爬虫和 Agent 标注完成后展示。",
  evidence: "",
};

const emptyCoinItem: CoinRankingItem = {
  rank: 0,
  symbol: "--",
  name: "暂无币种",
  final_score: 0,
  risk_level: "低风险",
  news_count: 0,
  main_risk_type: "暂无数据",
  top_news_title: "等待排行榜生成",
  summary: "等待新闻标注结果聚合后展示。",
  related_news: [],
};

const viewRoutes: Record<ActiveView, string> = {
  home: "/",
  chat: "/analysis",
  news: "/news",
  coin: "/coins",
  daily: "/daily",
  portfolio: "/portfolio",
  sim: "/sim",
  reports: "/reports",
  favoriteNews: "/favorites/news",
  favoriteReports: "/favorites/reports",
  my: "/my",
  settings: "/settings",
};

function resolveViewFromPathname(pathname: string | null, fallback: ActiveView): ActiveView {
  if (!pathname || pathname === "/") return "home";
  if (pathname.startsWith("/analysize") || pathname.startsWith("/analysis")) return "chat";
  if (pathname.startsWith("/news")) return "news";
  if (pathname.startsWith("/coins")) return "coin";
  if (pathname.startsWith("/daily")) return "daily";
  if (pathname.startsWith("/portfolio")) return "portfolio";
  if (pathname.startsWith("/sim")) return "sim";
  if (pathname.startsWith("/reports")) return "reports";
  if (pathname.startsWith("/favorites/news")) return "favoriteNews";
  if (pathname.startsWith("/favorites/reports")) return "favoriteReports";
  if (pathname.startsWith("/my")) return "my";
  if (pathname.startsWith("/settings")) return "settings";
  return fallback;
}

function parseMyVaultTab(value: string | null): MyVaultTab {
  if (value === "assets" || value === "news" || value === "reports" || value === "alerts" || value === "reviews") {
    return value;
  }
  return "overview";
}

function getWindowSearch() {
  return typeof window === "undefined" ? "" : window.location.search;
}

function getSearchFromPath(path: string) {
  const queryStart = path.indexOf("?");
  return queryStart >= 0 ? path.slice(queryStart) : "";
}

const analysisRecordsStorageKey = "cryptorisk.analysisRecords";
const selectedRecordStorageKey = "cryptorisk.selectedRecordId";
const chatMessagesStorageKey = "cryptorisk.chatMessages";
const activeAnalysisTaskStorageKey = "cryptorisk.activeAnalysisTask";
const newsUpdateJobStorageKey = "cryptorisk.newsUpdateJobId";
const authUsernameStorageKey = "cryptorisk.auth.username";
const reportCreatedEventName = "cryptorisk:analysis-record-created";
const userAssetsUpdatedEventName = "cryptorisk:user-assets-updated";
const maxStoredAnalysisRecords = 80;
const maxStoredChatMessages = 120;
const maxRankingTableRows = 60;
const newsRankingFetchLimit = 0;
const storageWriteDelayMs = 250;
const defaultUserAssetForm: UserAssetFormState = {
  alertThreshold: "70",
  isHolding: false,
  symbol: "",
};

const initialChatProgressStage: ChatProgressStage = "input_standardization";
const chatProgressLabels: Record<ChatProgressStage, string> = {
  input_standardization: "输入标准化",
  risk_signal_scan: "风险信号扫描",
  evidence_extraction: "证据抽取",
  report_generation: "报告生成",
};
const chatProgressSteps = Object.values(chatProgressLabels);

const initialChatMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "你好，我是 CryptoRisk Agent。输入新闻、公告、链上事件或交易所异常，我会输出风险评分、证据摘要、影响分析和处置建议。",
  },
];

function readStoredAnalysisRecords() {
  if (typeof window === "undefined") return [];

  try {
    const raw = window.localStorage.getItem(analysisRecordsStorageKey);
    const parsed = raw ? (JSON.parse(raw) as AnalysisRecord[]) : [];
    return Array.isArray(parsed) ? trimAnalysisRecords(parsed) : [];
  } catch {
    return [];
  }
}

function readStoredSelectedRecordId() {
  if (typeof window === "undefined") return "";
  const recordId = new URLSearchParams(window.location.search).get("record");
  if (recordId) return recordId;
  return window.localStorage.getItem(selectedRecordStorageKey) || "";
}

function readStoredChatMessages() {
  if (typeof window === "undefined") return initialChatMessages;

  try {
    const raw = window.localStorage.getItem(chatMessagesStorageKey);
    const parsed = raw ? JSON.parse(raw) : initialChatMessages;
    return Array.isArray(parsed) ? trimChatMessages(parsed as ChatMessage[]) : initialChatMessages;
  } catch {
    return initialChatMessages;
  }
}

function trimChatMessages(messages: ChatMessage[]) {
  if (messages.length <= maxStoredChatMessages) return messages;
  return messages.slice(-maxStoredChatMessages);
}

function trimAnalysisRecords(records: AnalysisRecord[]) {
  const normalized = records.map(normalizeAnalysisRecord);
  if (normalized.length <= maxStoredAnalysisRecords) return normalized;
  return normalized
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, maxStoredAnalysisRecords);
}

function compactContextText(value: string | undefined, maxLength = 160) {
  const text = (value || "").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 3)}...`;
}

function buildNewsTableAIContext(item: NewsRankingItem) {
  return JSON.stringify({
    type: "news",
    id: item.news_id,
    coin: item.coins,
    title: compactContextText(item.title),
    riskLevel: item.risk_level,
    riskScore: item.risk_score,
    riskType: item.risk_type,
    time: item.published_at,
  });
}

function buildCoinTableAIContext(item: CoinRankingItem) {
  return JSON.stringify({
    type: "coin",
    coin: item.symbol,
    title: compactContextText(item.top_news_title),
    riskLevel: item.risk_level,
    riskScore: item.final_score,
    riskType: item.main_risk_type,
  });
}

function writeStoredChatMessages(messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(chatMessagesStorageKey, JSON.stringify(trimChatMessages(messages)));
}

function writeStoredAnalysisRecords(records: AnalysisRecord[]) {
  if (typeof window === "undefined") return;
  const trimmed = trimAnalysisRecords(records);
  if (trimmed.length) {
    window.localStorage.setItem(analysisRecordsStorageKey, JSON.stringify(trimmed));
  } else {
    window.localStorage.removeItem(analysisRecordsStorageKey);
  }
}

function normalizeAnalysisRecord(record: AnalysisRecord): AnalysisRecord {
  return {
    ...record,
    disposition: record.disposition || "pending",
    dispositionNote: record.dispositionNote || "",
  };
}

function mergeAnalysisRecords(localRecords: AnalysisRecord[], remoteRecords: AnalysisRecord[]) {
  const byId = new Map<string, AnalysisRecord>();
  [...localRecords, ...remoteRecords].forEach((record) => {
    const existing = byId.get(record.id);
    byId.set(record.id, normalizeAnalysisRecord(existing ? { ...existing, ...record } : record));
  });
  return trimAnalysisRecords(Array.from(byId.values()).sort((a, b) => b.createdAt.localeCompare(a.createdAt)));
}

function toAnalysisReportPayload(record: AnalysisRecord) {
  const normalized = normalizeAnalysisRecord(record);
  return {
    id: normalized.id,
    title: normalized.title,
    created_at: normalized.createdAt,
    input: normalized.input,
    report: normalized.report,
    disposition: normalized.disposition,
    disposition_note: normalized.dispositionNote,
  };
}

function persistRemoteAnalysisReport(record: AnalysisRecord) {
  return saveAnalysisReport(toAnalysisReportPayload(record)).catch(() => undefined);
}

function mapRemoteAnalysisReport(item: {
  id: string;
  title: string;
  created_at: string;
  input: string;
  report: RiskReport;
  disposition?: AnalysisDisposition;
  disposition_note?: string;
}): AnalysisRecord {
  return normalizeAnalysisRecord({
    id: item.id,
    title: item.title,
    createdAt: item.created_at,
    input: item.input,
    report: item.report,
    disposition: item.disposition || "pending",
    dispositionNote: item.disposition_note || "",
  });
}

function readStoredAuthUsername() {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(authUsernameStorageKey) || "";
}

function writeStoredAuthUsername(username: string) {
  if (typeof window === "undefined") return;
  const normalized = username.trim().toLowerCase();
  if (normalized) {
    window.localStorage.setItem(authUsernameStorageKey, normalized);
  }
}

function appendStoredChatMessages(messages: ChatMessage[]) {
  const existing = readStoredChatMessages();
  const existingIds = new Set(existing.map((item) => item.id));
  const nextMessages = [
    ...existing,
    ...messages.filter((item) => !existingIds.has(item.id)),
  ];
  writeStoredChatMessages(nextMessages);
  return nextMessages;
}

function updateStoredChatMessage(messageId: string, updater: (message: ChatMessage) => ChatMessage) {
  const nextMessages = readStoredChatMessages().map((message) =>
    message.id === messageId ? updater(message) : message
  );
  writeStoredChatMessages(nextMessages);
  notifyAnalysisTaskListeners();
  return nextMessages;
}

function persistAnalysisTaskSnapshot(snapshot: AnalysisTaskSnapshot | null) {
  if (typeof window === "undefined") return;
  if (!snapshot || snapshot.status !== "running") {
    window.sessionStorage.removeItem(activeAnalysisTaskStorageKey);
    return;
  }
  window.sessionStorage.setItem(activeAnalysisTaskStorageKey, JSON.stringify(snapshot));
}

function clearStoredAnalysisTaskSnapshot() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(activeAnalysisTaskStorageKey);
}

let activeAnalysisTask: AnalysisTaskSnapshot | null = null;
let activeAnalysisPromise: Promise<void> | null = null;
const analysisTaskListeners = new Set<(snapshot: AnalysisTaskSnapshot | null) => void>();

function notifyAnalysisTaskListeners() {
  analysisTaskListeners.forEach((listener) => listener(activeAnalysisTask));
}

function getActiveAnalysisTaskSnapshot() {
  return activeAnalysisTask;
}

function subscribeAnalysisTask(listener: (snapshot: AnalysisTaskSnapshot | null) => void) {
  analysisTaskListeners.add(listener);
  listener(activeAnalysisTask);
  return () => {
    analysisTaskListeners.delete(listener);
  };
}

function startAnalysisTask(input: string) {
  const trimmed = input.trim();
  if (!trimmed) return null;
  if (activeAnalysisTask?.status === "running" && activeAnalysisPromise) {
    return activeAnalysisTask;
  }

  const now = new Date();
  const taskId = `analysis-${now.getTime()}`;
  const userMessageId = `user-${now.getTime()}`;
  const snapshot: AnalysisTaskSnapshot = {
    id: taskId,
    input: trimmed,
    status: "running",
    stage: initialChatProgressStage,
    startedAt: now.toISOString(),
    updatedAt: now.toISOString(),
  };

  activeAnalysisTask = snapshot;
  persistAnalysisTaskSnapshot(snapshot);
  appendStoredChatMessages([{ id: userMessageId, role: "user", content: trimmed }]);
  notifyAnalysisTaskListeners();

  activeAnalysisPromise = (async () => {
    try {
      const response = await streamChatMessage(trimmed, (event) => {
        activeAnalysisTask = {
          ...(activeAnalysisTask || snapshot),
          stage: event.stage,
          updatedAt: new Date().toISOString(),
        };
        persistAnalysisTaskSnapshot(activeAnalysisTask);
        notifyAnalysisTaskListeners();
      });
      const record: AnalysisRecord = {
        id: `report-${Date.now()}`,
        title: buildReportTitle(trimmed, response.data),
        createdAt: formatTimestamp(new Date()),
        input: trimmed,
        report: response.data,
        disposition: "pending",
        dispositionNote: "",
      };
      const nextRecords = [record, ...readStoredAnalysisRecords()];
      writeStoredAnalysisRecords(nextRecords);
      void persistRemoteAnalysisReport(record);
      window.localStorage.setItem(selectedRecordStorageKey, record.id);
      const followUpQuestion = extractEventAnalysisFollowUpQuestion(trimmed);
      const assistantMessageId = `assistant-${Date.now()}`;
      appendStoredChatMessages([{
        id: assistantMessageId,
        role: "assistant",
        content: followUpQuestion
          ? `${buildBriefAnalysis(record)}\n\n**风控助手追问回答**\n`
          : `${buildBriefAnalysis(record)}\n\n完整事件分析链路已完成，报告已生成并保存。`,
      }]);
      activeAnalysisTask = {
        ...snapshot,
        status: "success",
        stage: "report_generation",
        recordId: record.id,
        updatedAt: new Date().toISOString(),
      };
      persistAnalysisTaskSnapshot(activeAnalysisTask);
      notifyAnalysisTaskListeners();
      if (followUpQuestion) {
        window.setTimeout(() => {
          void streamRiskAssistant(
            followUpQuestion,
            {
              active_view: "chat",
              assistant_memory: {
                event_analysis: {
                  analysis_input: trimmed,
                  report_id: record.id,
                  report_title: record.title,
                  report_created_at: record.createdAt,
                  report: record.report,
                },
              },
            },
            (chunk) => {
              updateStoredChatMessage(assistantMessageId, (message) => ({
                ...message,
                content: message.content + chunk,
              }));
            },
            {
              selectedText: trimmed,
              userQuestion: followUpQuestion,
            },
          ).catch((assistantError) => {
            console.error(assistantError);
            updateStoredChatMessage(assistantMessageId, (message) => ({
              ...message,
              content: `${buildBriefAnalysis(record)}\n\n完整事件分析链路已完成，报告已生成并保存。助手追问回答暂时失败，请稍后再试。`,
            }));
          });
        }, 0);
      }
    } catch (error) {
      console.error(error);
      activeAnalysisTask = {
        ...snapshot,
        status: "error",
        stage: activeAnalysisTask?.stage || snapshot.stage,
        error: error instanceof Error ? error.message : "请求后端失败",
        updatedAt: new Date().toISOString(),
      };
    } finally {
      activeAnalysisPromise = null;
      clearStoredAnalysisTaskSnapshot();
      notifyAnalysisTaskListeners();
    }
  })();

  return snapshot;
}

function isActiveNewsUpdateJob(job: NewsUpdateJob | null) {
  return Boolean(job && (job.status === "queued" || job.status === "running"));
}

function readStoredNewsUpdateJobId() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(newsUpdateJobStorageKey) || "";
}

function storeNewsUpdateJobId(jobId: string) {
  if (typeof window === "undefined" || !jobId) return;
  window.sessionStorage.setItem(newsUpdateJobStorageKey, jobId);
}

function clearStoredNewsUpdateJobId() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(newsUpdateJobStorageKey);
}

type InitialDashboardSnapshot = {
  analysisRecords: AnalysisRecord[];
  chatMessages: ChatMessage[];
  coinRanking: CoinRankingItem[];
  dailyReport: DailyRiskReport | null;
  overview: RiskOverview | null;
  rankingLoading: boolean;
  rankingRange: RankingRange;
  newsRanking: NewsRankingItem[];
};

function shouldLoadRankingsForView(view: ActiveView) {
  return view === "home" || view === "news" || view === "coin";
}

function getRankingFetchLimitForView(view: ActiveView) {
  if (view === "home") return 10;
  if (view === "news") return newsRankingFetchLimit;
  if (view === "coin") return 500;
  return 10;
}

function shouldFetchNewsRankingForView(view: ActiveView) {
  return view === "home" || view === "news";
}

function shouldFetchCoinRankingForView(view: ActiveView) {
  return view === "coin";
}

function shouldLoadFavoritesForView(view: ActiveView) {
  return view === "home" || view === "news" || view === "reports" || view === "favoriteNews" || view === "favoriteReports" || view === "my";
}

function favoriteTypesForView(view: ActiveView): FavoriteType[] {
  if (view === "home" || view === "news" || view === "favoriteNews") return ["news"];
  if (view === "reports" || view === "favoriteReports") return ["report"];
  if (view === "my") return ["report", "news"];
  return [];
}

function shouldSyncReportsForView(view: ActiveView) {
  return view === "chat" || view === "reports" || view === "favoriteReports" || view === "my";
}

function shouldLoadAccountAssetsForView(view: ActiveView) {
  return view === "daily" || view === "my";
}

function shouldReadChatHistoryForView(view: ActiveView) {
  return view === "chat";
}

function shouldReadAnalysisRecordsForView(view: ActiveView) {
  return view === "chat" || view === "reports" || view === "favoriteReports" || view === "my";
}

function readInitialDashboardSnapshot(view: ActiveView): InitialDashboardSnapshot {
  const rankingRange = readRankingRange();
  const shouldPrimeRankings = shouldLoadRankingsForView(view);
  const shouldPrimeNews = shouldFetchNewsRankingForView(view);
  const shouldPrimeCoins = shouldFetchCoinRankingForView(view);
  const overview = shouldPrimeRankings ? readCachedRiskOverview(rankingRange) : null;
  const newsRanking = shouldPrimeRankings && shouldPrimeNews ? readCachedNewsRanking(10, rankingRange)?.items || [] : [];
  const coinRanking = shouldPrimeRankings && shouldPrimeCoins ? readCachedCoinRanking(10, rankingRange)?.items || [] : [];

  return {
    analysisRecords: shouldReadAnalysisRecordsForView(view) ? readStoredAnalysisRecords() : [],
    chatMessages: shouldReadChatHistoryForView(view) ? readStoredChatMessages() : initialChatMessages,
    coinRanking,
    dailyReport: view === "daily" ? readCachedDailyRiskReport(rankingRange) : null,
    overview,
    rankingLoading: shouldPrimeRankings && !overview && !newsRanking.length && !coinRanking.length,
    rankingRange,
    newsRanking,
  };
}

function DeferredPanelLoader({ title }: { title: string }) {
  return (
    <section className="risk-card rounded-lg p-6">
      <LoadingDots label={title} />
    </section>
  );
}

export default function RiskDashboard({ initialView = "home" }: { initialView?: ActiveView }) {
  const router = useRouter();
  const pathname = usePathname();
  const [currentSearch, setCurrentSearch] = useState(() => getWindowSearch());
  const recordIdFromUrl = useMemo(() => new URLSearchParams(currentSearch).get("record") || "", [currentSearch]);
  const activeView = resolveViewFromPathname(pathname, initialView);
  const [initialSnapshot] = useState(() => readInitialDashboardSnapshot(activeView));
  const [rankingRange, setRankingRange] = useState<RankingRange>(initialSnapshot.rankingRange);
  const [overview, setOverview] = useState<RiskOverview | null>(initialSnapshot.overview);
  const [newsRanking, setNewsRanking] = useState<NewsRankingItem[]>(initialSnapshot.newsRanking);
  const [coinRanking, setCoinRanking] = useState<CoinRankingItem[]>(initialSnapshot.coinRanking);
  const [dailyReport, setDailyReport] = useState<DailyRiskReport | null>(initialSnapshot.dailyReport);
  const [rankingDataStatus, setRankingDataStatus] = useState<RankingDataStatus>(initialRankingDataStatus);
  const [dailyReportFetching, setDailyReportFetching] = useState(false);
  const [dailyReportLoading, setDailyReportLoading] = useState(false);
  const [dailyReportError, setDailyReportError] = useState("");
  const [dailyReportSubscription, setDailyReportSubscription] = useState<DailyReportSubscription | null>(null);
  const [dailyReportSubscriptionLoading, setDailyReportSubscriptionLoading] = useState(false);
  const [rankingLoading, setRankingLoading] = useState(initialSnapshot.rankingLoading);
  const [rankingError, setRankingError] = useState("");
  const [newsUpdateLoading, setNewsUpdateLoading] = useState(false);
  const [newsUpdateError, setNewsUpdateError] = useState("");
  const [newsUpdateResult, setNewsUpdateResult] = useState<NewsUpdateResponse | null>(null);
  const [newsUpdateJob, setNewsUpdateJob] = useState<NewsUpdateJob | null>(null);
  const [systemReadiness, setSystemReadiness] = useState<SystemReadiness | null>(null);
  const [auditSummary, setAuditSummary] = useState<AuditSummary | null>(null);
  const [systemTaskEvents, setSystemTaskEvents] = useState<SystemTaskEvent[]>([]);
  const [rateLimitStatus, setRateLimitStatus] = useState<RateLimitStatus | null>(null);
  const [storageInventory, setStorageInventory] = useState<StorageInventory | null>(null);
  const [backupManifest, setBackupManifest] = useState<BackupManifest | null>(null);
  const [dailySchedulerStatus, setDailySchedulerStatus] = useState<DailySchedulerStatus | null>(null);
  const [systemStatusLoading, setSystemStatusLoading] = useState(false);
  const [systemStatusError, setSystemStatusError] = useState("");
  const [dailySchedulerActionLoading, setDailySchedulerActionLoading] = useState(false);
  const [dailySchedulerMessage, setDailySchedulerMessage] = useState("");
  const [auditPruneLoading, setAuditPruneLoading] = useState(false);
  const [auditPruneResult, setAuditPruneResult] = useState<AuditPruneResult | null>(null);
  const [simPruneLoading, setSimPruneLoading] = useState(false);
  const [simPruneMessage, setSimPruneMessage] = useState("");
  const [sessionPruneLoading, setSessionPruneLoading] = useState(false);
  const [sessionPruneMessage, setSessionPruneMessage] = useState("");
  const [runtimeJobPruneLoading, setRuntimeJobPruneLoading] = useState(false);
  const [runtimeJobPruneMessage, setRuntimeJobPruneMessage] = useState("");
  const [invalidBackupPruneLoading, setInvalidBackupPruneLoading] = useState(false);
  const [invalidBackupPruneMessage, setInvalidBackupPruneMessage] = useState("");
  const [accountExportLoading, setAccountExportLoading] = useState(false);
  const [accountExportMessage, setAccountExportMessage] = useState("");
  const [accountDeleteLoading, setAccountDeleteLoading] = useState(false);
  const updatePollGenerationRef = useRef(0);

  const [message, setMessage] = useState(examplePrompts[0]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(initialSnapshot.chatMessages);
  const [analysisRecords, setAnalysisRecords] = useState<AnalysisRecord[]>(initialSnapshot.analysisRecords);
  const [storedSelectedRecordId, setStoredSelectedRecordId] = useState(() => readStoredSelectedRecordId());
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authError, setAuthError] = useState("");
  const [favoriteReportIds, setFavoriteReportIds] = useState<Set<string>>(() => new Set());
  const [favoriteNewsIds, setFavoriteNewsIds] = useState<Set<string>>(() => new Set());
  const [favoriteReports, setFavoriteReports] = useState<FavoriteItem[]>([]);
  const [favoriteNews, setFavoriteNews] = useState<FavoriteItem[]>([]);
  const [favoriteActionLoadingId, setFavoriteActionLoadingId] = useState("");
  const [accountAssets, setAccountAssets] = useState<PortfolioWatchlistItem[]>([]);
  const [accountAssetsLoading, setAccountAssetsLoading] = useState(false);
  const [reportSidebarCollapsed, setReportSidebarCollapsed] = useState(false);
  const reportSyncUserRef = useRef("");
  const [chatLoading, setChatLoading] = useState(() => getActiveAnalysisTaskSnapshot()?.status === "running");
  const [chatError, setChatError] = useState(() => {
    const task = getActiveAnalysisTaskSnapshot();
    return task?.status === "error" ? `分析失败：${task.error || "请求后端失败"}` : "";
  });
  const [chatProgressStage, setChatProgressStage] = useState<ChatProgressStage>(() => getActiveAnalysisTaskSnapshot()?.stage || initialChatProgressStage);
  const pendingNewsAnalysisIdRef = useRef("");

  useEffect(() => {
    let ignore = false;
    if (!shouldLoadRankingsForView(activeView)) {
      return;
    }

    async function loadRankings() {
      const rankingLimit = getRankingFetchLimitForView(activeView);
      const shouldFetchNews = shouldFetchNewsRankingForView(activeView);
      const shouldFetchCoins = shouldFetchCoinRankingForView(activeView);
      const hasCachedData = Boolean(
        readCachedRiskOverview(rankingRange)
          || (shouldFetchNews && readCachedNewsRanking(rankingLimit, rankingRange)?.items.length)
          || (shouldFetchCoins && readCachedCoinRanking(rankingLimit, rankingRange)?.items.length)
      );
      if (!hasCachedData) setRankingLoading(true);
      setRankingError("");
      try {
        const [overviewData, newsData, coinData] = await Promise.all([
          fetchRiskOverview(rankingRange),
          shouldFetchNews ? fetchNewsRanking(rankingLimit, rankingRange) : Promise.resolve(null),
          shouldFetchCoins ? fetchCoinRanking(rankingLimit, rankingRange) : Promise.resolve(null),
        ]);
        if (ignore) return;
        const overviewNews = overviewData.top_news_preview?.length ? overviewData.top_news_preview : overviewData.top_news ? [overviewData.top_news] : [];
        const overviewCoins = overviewData.top_coin_preview?.length ? overviewData.top_coin_preview : overviewData.top_coin ? [overviewData.top_coin] : [];
        setOverview(overviewData);
        setNewsRanking(newsData?.items || overviewNews);
        setCoinRanking(coinData?.items || overviewCoins);
        setRankingDataStatus({
          mode: "real",
          updatedAt: overviewData.date || newsData?.date || coinData?.date || formatTimestamp(new Date()),
          newsSourceStatus: "connected",
          agentStatus: "ready",
          message: "已连接后端风险排行榜，展示真实新闻标注结果",
        });
      } catch (error) {
        console.error(error);
        if (!ignore) {
          setRankingError("排行数据暂未连接，当前展示本地演示数据。请确认 FastAPI 后端已启动。");
          setNewsRanking(fallbackNews);
          setCoinRanking(fallbackCoins);
          setRankingDataStatus(demoRankingDataStatus);
        }
      } finally {
        if (!ignore) setRankingLoading(false);
      }
    }

    void loadRankings();

    return () => {
      ignore = true;
    };
  }, [activeView, rankingRange]);

  useEffect(() => {
    let ignore = false;
    if (activeView !== "daily") return;

    async function loadSavedDailyReport() {
      setDailyReportFetching(true);
      setDailyReportError("");
      try {
        const data = await fetchDailyRiskReport(rankingRange);
        if (!ignore) setDailyReport(data);
      } catch (error) {
        console.error(error);
        if (!ignore) setDailyReportError("已保存的资产日报读取失败，仍可重新生成。");
      } finally {
        if (!ignore) setDailyReportFetching(false);
      }
    }

    void loadSavedDailyReport();
    return () => {
      ignore = true;
    };
  }, [activeView, authUser?.id, rankingRange]);

  useEffect(() => {
    let ignore = false;
    if (activeView !== "daily") return;

    async function loadDailySubscription() {
      setDailyReportSubscriptionLoading(true);
      try {
        const data = await fetchDailyReportSubscription();
        if (!ignore) setDailyReportSubscription(data);
      } catch (error) {
        console.error(error);
        if (!ignore) setDailyReportError("日报订阅状态读取失败，仍可手动生成日报。");
      } finally {
        if (!ignore) setDailyReportSubscriptionLoading(false);
      }
    }

    void loadDailySubscription();

    return () => {
      ignore = true;
    };
  }, [activeView, authUser?.id]);

  useEffect(() => {
    function handlePopState() {
      setCurrentSearch(getWindowSearch());
    }

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!shouldReadChatHistoryForView(activeView)) return;
    const timer = window.setTimeout(() => {
      setChatMessages(readStoredChatMessages());
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeView]);

  useEffect(() => {
    if (!shouldReadAnalysisRecordsForView(activeView)) return;
    const timer = window.setTimeout(() => {
      setAnalysisRecords(readStoredAnalysisRecords());
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeView]);

  useEffect(() => {
    function handleReportCreated(event: Event) {
      if (!shouldReadAnalysisRecordsForView(activeView)) return;
      const detail = (event as CustomEvent<{ recordId?: string }>).detail;
      const records = readStoredAnalysisRecords();
      const recordId = detail?.recordId || records[0]?.id || "";
      setAnalysisRecords(records);
      if (!recordId) return;
      setStoredSelectedRecordId(recordId);
      if (pathname === "/reports") {
        setCurrentSearch(`?record=${encodeURIComponent(recordId)}`);
      }
    }

    window.addEventListener(reportCreatedEventName, handleReportCreated);
    return () => window.removeEventListener(reportCreatedEventName, handleReportCreated);
  }, [activeView, pathname]);

  useEffect(() => {
    let ignore = false;

    async function loadCurrentUser() {
      try {
        const user = await fetchCurrentUser();
        if (!ignore) setAuthUser(user);
      } catch (error) {
        console.error(error);
        if (!ignore) setAuthUser(null);
      }
    }

    const timer = window.setTimeout(() => {
      void loadCurrentUser();
    }, 250);
    return () => {
      ignore = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let ignore = false;
    if (!authUser || !shouldLoadFavoritesForView(activeView)) return;
    const favoriteTypes = favoriteTypesForView(activeView);
    if (!favoriteTypes.length) return;

    async function loadFavoriteReports() {
      try {
        const results = await Promise.all(favoriteTypes.map(async (type) => [type, await fetchFavorites(type)] as const));
        if (!ignore) {
          for (const [type, items] of results) {
            if (type === "report") {
              setFavoriteReports(items);
              setFavoriteReportIds(new Set(items.map((item) => item.item_id)));
            } else {
              setFavoriteNews(items);
              setFavoriteNewsIds(new Set(items.map((item) => item.item_id)));
            }
          }
        }
      } catch (error) {
        console.error(error);
        if (!ignore) {
          if (favoriteTypes.includes("report")) {
            setFavoriteReports([]);
            setFavoriteReportIds(new Set());
          }
          if (favoriteTypes.includes("news")) {
            setFavoriteNews([]);
            setFavoriteNewsIds(new Set());
          }
        }
      }
    }

    void loadFavoriteReports();
    return () => {
      ignore = true;
    };
  }, [activeView, authUser]);

  useEffect(() => {
    let ignore = false;
    if (!authUser) {
      reportSyncUserRef.current = "";
      return;
    }
    if (!shouldSyncReportsForView(activeView)) return;
    const currentUser = authUser;

    async function syncReports() {
      try {
        const remoteItems = await fetchAnalysisReports();
        if (ignore) return;
        const localRecords = readStoredAnalysisRecords().map(normalizeAnalysisRecord);
        const remoteRecords = remoteItems.map(mapRemoteAnalysisReport);
        const merged = mergeAnalysisRecords(localRecords, remoteRecords);
        setAnalysisRecords(merged);
        writeStoredAnalysisRecords(merged);
        reportSyncUserRef.current = currentUser.id;

        const remoteIds = new Set(remoteRecords.map((record) => record.id));
        await Promise.all(localRecords.filter((record) => !remoteIds.has(record.id)).map(persistRemoteAnalysisReport));
      } catch (error) {
        console.error(error);
      }
    }

    void syncReports();
    return () => {
      ignore = true;
    };
  }, [activeView, authUser]);

  useEffect(() => {
    let ignore = false;
    if (!authUser || !shouldLoadAccountAssetsForView(activeView)) {
      return;
    }

    async function loadAccountAssets(showLoading = true) {
      if (showLoading) setAccountAssetsLoading(true);
      try {
        const items = await fetchUserAssets();
        if (!ignore) setAccountAssets(items);
      } catch (error) {
        console.error(error);
        if (!ignore) setAccountAssets([]);
      } finally {
        if (!ignore) setAccountAssetsLoading(false);
      }
    }

    function handleUserAssetsUpdated() {
      void loadAccountAssets(false);
    }

    void loadAccountAssets();
    window.addEventListener(userAssetsUpdatedEventName, handleUserAssetsUpdated);
    return () => {
      ignore = true;
      window.removeEventListener(userAssetsUpdatedEventName, handleUserAssetsUpdated);
    };
  }, [activeView, authUser]);

  useEffect(() => {
    if (pathname !== "/reports" || !recordIdFromUrl) return;
    window.localStorage.setItem(selectedRecordStorageKey, recordIdFromUrl);
  }, [pathname, recordIdFromUrl]);

  useEffect(() => {
    if (!shouldReadAnalysisRecordsForView(activeView)) return;
    const timer = window.setTimeout(() => {
      writeStoredAnalysisRecords(analysisRecords);
    }, storageWriteDelayMs);
    return () => window.clearTimeout(timer);
  }, [activeView, analysisRecords]);

  useEffect(() => {
    if (!storedSelectedRecordId) return;
    window.localStorage.setItem(selectedRecordStorageKey, storedSelectedRecordId);
  }, [storedSelectedRecordId]);

  useEffect(() => {
    if (!shouldReadChatHistoryForView(activeView)) return;
    const timer = window.setTimeout(() => {
      writeStoredChatMessages(chatMessages);
    }, storageWriteDelayMs);
    return () => window.clearTimeout(timer);
  }, [activeView, chatMessages]);

  useEffect(() => {
    return subscribeAnalysisTask((task) => {
      setChatLoading(task?.status === "running");
      setChatProgressStage(task?.stage || initialChatProgressStage);
      setChatError(task?.status === "error" ? `分析失败：${task.error || "请求后端失败"}` : "");
      if (!task) return;
      if (shouldReadChatHistoryForView(activeView)) {
        setChatMessages(readStoredChatMessages());
      }
      if (shouldReadAnalysisRecordsForView(activeView)) {
        setAnalysisRecords(readStoredAnalysisRecords());
      }

      if (task?.recordId) {
        setStoredSelectedRecordId(task.recordId);
        return;
      }
    });
  }, [activeView]);

  useEffect(() => {
    if (activeView !== "chat" || chatLoading) return;
    const pending = readPendingNewsAnalysisInput();
    if (!pending || pending.id === pendingNewsAnalysisIdRef.current) return;
    pendingNewsAnalysisIdRef.current = pending.id;
    setMessage(pending.input);
    const timer = window.setTimeout(() => {
      if (getActiveAnalysisTaskSnapshot()?.status === "running") return;
      clearPendingNewsAnalysisInput();
      runAnalysis(pending.input);
    }, 120);
    return () => window.clearTimeout(timer);
  }, [activeView, chatLoading]);

  const displayNews = newsRanking;
  const displayCoins = coinRanking;
  const topNews = displayNews[0] || emptyNewsItem;
  const topCoin = displayCoins[0] || emptyCoinItem;
  const reportRecords = analysisRecords;
  const selectedRecordId = recordIdFromUrl || storedSelectedRecordId;
  const selectedRecord = useMemo(
    () => reportRecords.find((record) => record.id === selectedRecordId)
      || (!selectedRecordId ? reportRecords[0] || null : null),
    [reportRecords, selectedRecordId],
  );
  const selectedVaultTab = parseMyVaultTab(new URLSearchParams(currentSearch).get("tab"));
  const accountStats = useMemo<AccountCenterStats>(() => {
    const riskyAssets = accountAssets.filter((item) => item.risk_score >= 80 || ["high", "critical"].includes(item.risk_level));
    const pendingAssets = accountAssets.filter((item) => item.risk_score >= item.alert_threshold || ["high", "critical"].includes(item.risk_level));
    return {
      favoriteNews: favoriteNews.length,
      favoriteReports: favoriteReports.length,
      highRiskAssets: riskyAssets.length,
      loadingAssets: accountAssetsLoading || Boolean(authUser && !shouldLoadAccountAssetsForView(activeView) && accountAssets.length === 0),
      pendingAlerts: pendingAssets.length,
      watchedAssets: accountAssets.length,
    };
  }, [accountAssets, accountAssetsLoading, activeView, authUser, favoriteNews.length, favoriteReports.length]);

  const pageMeta = getPageMeta(activeView);

  function handleChangeView(view: ActiveView) {
    const nextPath = view === "reports" && selectedRecordId
      ? `/reports?record=${encodeURIComponent(selectedRecordId)}`
      : viewRoutes[view];
    navigateTo(nextPath);
  }

  function handleSelectRecord(id: string) {
    setStoredSelectedRecordId(id);
    window.localStorage.setItem(selectedRecordStorageKey, id);
  }

  function handleSelectReportRecord(id: string) {
    handleSelectRecord(id);
    navigateTo(`/reports?record=${encodeURIComponent(id)}`);
  }

  function navigateTo(nextPath: string, mode: "push" | "replace" = "push") {
    if (typeof window !== "undefined") {
      const currentPath = `${window.location.pathname}${window.location.search}`;
      if (currentPath === nextPath) return;
    }
    setCurrentSearch(getSearchFromPath(nextPath));
    if (mode === "replace") {
      router.replace(nextPath);
      return;
    }
    router.push(nextPath);
  }

  function handleChangeRankingRange(range: RankingRange) {
    setRankingRange(range);
    syncRankingUrl(activeView === "coin" ? "coin" : "news", { range });
  }

  function handleDailyRangeChange(range: RankingRange) {
    setDailyReport(null);
    setDailyReportError("");
    handleChangeRankingRange(range);
  }

  async function handleGenerateDailyReport() {
    setDailyReportLoading(true);
    setDailyReportError("");
    try {
      const data = await generateDailyRiskReport(rankingRange);
      setDailyReport(data);
    } catch (error) {
      console.error(error);
      setDailyReportError("资产日报生成失败，请稍后重试或检查后端 Agent 服务。");
    } finally {
      setDailyReportLoading(false);
    }
  }

  async function handleToggleDailyReportSubscription(enabled: boolean) {
    setDailyReportSubscriptionLoading(true);
    setDailyReportError("");
    try {
      const data = await updateDailyReportSubscription(enabled);
      setDailyReportSubscription(data);
    } catch (error) {
      console.error(error);
      setDailyReportError("日报订阅状态更新失败，请稍后重试。");
    } finally {
      setDailyReportSubscriptionLoading(false);
    }
  }

  const refreshRankingsAfterUpdate = useCallback(async (silent = false) => {
    if (!silent) setRankingLoading(true);
    setRankingError("");
    try {
      clearApiCache();
      const rankingLimit = getRankingFetchLimitForView(activeView);
      const shouldFetchNews = shouldFetchNewsRankingForView(activeView);
      const shouldFetchCoins = shouldFetchCoinRankingForView(activeView);
      const [overviewData, newsData, coinData] = await Promise.all([
        fetchRiskOverview(rankingRange),
        shouldFetchNews ? fetchNewsRanking(rankingLimit, rankingRange) : Promise.resolve(null),
        shouldFetchCoins ? fetchCoinRanking(rankingLimit, rankingRange) : Promise.resolve(null),
      ]);
      const overviewNews = overviewData.top_news_preview?.length ? overviewData.top_news_preview : overviewData.top_news ? [overviewData.top_news] : [];
      const overviewCoins = overviewData.top_coin_preview?.length ? overviewData.top_coin_preview : overviewData.top_coin ? [overviewData.top_coin] : [];
      setOverview(overviewData);
      setNewsRanking(newsData?.items || overviewNews);
      setCoinRanking(coinData?.items || overviewCoins);
      setRankingDataStatus({
        mode: "real",
        updatedAt: overviewData.date || newsData?.date || coinData?.date || formatTimestamp(new Date()),
        newsSourceStatus: "connected",
        agentStatus: "ready",
        message: "新闻更新后排行榜已刷新",
      });
    } catch (error) {
      console.error(error);
      setRankingError("新闻已更新，但排行榜刷新失败，请稍后重新打开排行榜。");
    } finally {
      if (!silent) setRankingLoading(false);
    }
  }, [activeView, rankingRange]);

  const loadSystemStatus = useCallback(async () => {
    setSystemStatusLoading(true);
    setSystemStatusError("");
    try {
      const readiness = await fetchSystemReadiness();
      setSystemReadiness(readiness);
      const [auditResult, taskEventsResult, rateLimitResult, storageResult, backupResult, schedulerResult] = await Promise.allSettled([
        fetchAuditSummary(24),
        fetchSystemTaskEvents(12),
        fetchRateLimitStatus(),
        fetchStorageInventory(),
        fetchBackupManifest(),
        fetchDailySchedulerStatus(),
      ]);
      const protectedErrors = [auditResult, taskEventsResult, rateLimitResult, storageResult, backupResult, schedulerResult]
        .filter((item): item is PromiseRejectedResult => item.status === "rejected")
        .map((item) => item.reason);

      if (auditResult.status === "fulfilled") setAuditSummary(auditResult.value);
      else setAuditSummary(null);
      if (taskEventsResult.status === "fulfilled") setSystemTaskEvents(taskEventsResult.value.items);
      else setSystemTaskEvents([]);
      if (rateLimitResult.status === "fulfilled") setRateLimitStatus(rateLimitResult.value);
      else setRateLimitStatus(null);
      if (storageResult.status === "fulfilled") setStorageInventory(storageResult.value);
      else setStorageInventory(null);
      if (backupResult.status === "fulfilled") setBackupManifest(backupResult.value);
      else setBackupManifest(null);
      if (schedulerResult.status === "fulfilled") setDailySchedulerStatus(schedulerResult.value);
      else setDailySchedulerStatus(null);

      if (protectedErrors.some((error) => error instanceof ApiRequestError && error.status === 401)) {
        setSystemStatusError("管理员登录后可查看审计汇总和限流状态；公开健康检查已显示。");
      } else if (protectedErrors.some((error) => error instanceof ApiRequestError && error.status === 403)) {
        setSystemStatusError("当前账号没有管理员权限；公开健康检查已显示。");
      } else if (protectedErrors.length) {
        setSystemStatusError("部分系统运行状态读取失败，请稍后重试。");
      }
    } catch (error) {
      console.error(error);
      setSystemStatusError("系统运行状态读取失败，请稍后重试。");
    } finally {
      setSystemStatusLoading(false);
    }
  }, []);

  const handlePruneAuditEvents = useCallback(async () => {
    setAuditPruneLoading(true);
    setSystemStatusError("");
    try {
      const result = await pruneTaskEvents();
      setAuditPruneResult(result);
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能清理审计账本。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法清理审计账本。");
      } else {
        setSystemStatusError("审计账本清理失败，请稍后重试。");
      }
    } finally {
      setAuditPruneLoading(false);
    }
  }, [loadSystemStatus]);

  const handlePruneGuestSimAccounts = useCallback(async () => {
    setSimPruneLoading(true);
    setSimPruneMessage("");
    setSystemStatusError("");
    try {
      const result = await pruneGuestSimAccounts(14);
      setSimPruneMessage(`游客模拟账户已清理：删除 ${result.deleted_accounts} 个，剩余 ${result.remaining_accounts} 个，保留窗口 ${result.retention_days} 天。`);
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能清理游客模拟账户。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法清理游客模拟账户。");
      } else {
        setSystemStatusError("游客模拟账户清理失败，请稍后重试。");
      }
    } finally {
      setSimPruneLoading(false);
    }
  }, [loadSystemStatus]);

  const handlePruneExpiredAuthSessions = useCallback(async () => {
    setSessionPruneLoading(true);
    setSessionPruneMessage("");
    setSystemStatusError("");
    try {
      const result = await pruneExpiredAuthSessions();
      setSessionPruneMessage(`过期登录会话已清理：删除 ${result.deleted_sessions} 个，剩余 ${result.remaining_sessions} 个。`);
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能清理过期登录会话。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法清理过期登录会话。");
      } else {
        setSystemStatusError("过期登录会话清理失败，请稍后重试。");
      }
    } finally {
      setSessionPruneLoading(false);
    }
  }, [loadSystemStatus]);

  const handlePruneRuntimeJobs = useCallback(async () => {
    setRuntimeJobPruneLoading(true);
    setRuntimeJobPruneMessage("");
    setSystemStatusError("");
    try {
      const result = await pruneRuntimeJobs(14, 100);
      const deletedNews = result.news_update.deleted_by_age + result.news_update.deleted_by_count;
      const deletedPortfolio = result.portfolio_refresh.deleted_by_age + result.portfolio_refresh.deleted_by_count;
      setRuntimeJobPruneMessage(
        `运行态任务状态已清理：新闻更新删除 ${deletedNews} 个，组合刷新删除 ${deletedPortfolio} 个，保留上限 ${result.max_jobs} 个。`
      );
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能清理运行态任务状态。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法清理运行态任务状态。");
      } else {
        setSystemStatusError("运行态任务状态清理失败，请稍后重试。");
      }
    } finally {
      setRuntimeJobPruneLoading(false);
    }
  }, [loadSystemStatus]);

  const handlePruneInvalidJsonBackups = useCallback(async () => {
    setInvalidBackupPruneLoading(true);
    setInvalidBackupPruneMessage("");
    setSystemStatusError("");
    try {
      const result = await pruneInvalidJsonBackups(30);
      setInvalidBackupPruneMessage(
        `损坏 JSON 隔离备份已清理：删除 ${result.deleted_files} 个（${formatBytes(result.deleted_bytes)}），剩余 ${result.remaining_files} 个，保留窗口 ${result.retention_days} 天。`
      );
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能清理损坏 JSON 隔离备份。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法清理损坏 JSON 隔离备份。");
      } else {
        setSystemStatusError("损坏 JSON 隔离备份清理失败，请稍后重试。");
      }
    } finally {
      setInvalidBackupPruneLoading(false);
    }
  }, [loadSystemStatus]);

  const handleToggleDailyScheduler = useCallback(async (enabled: boolean) => {
    setDailySchedulerActionLoading(true);
    setDailySchedulerMessage("");
    setSystemStatusError("");
    try {
      const result = await updateDailySchedulerStatus(enabled);
      setDailySchedulerStatus(result);
      setDailySchedulerMessage(enabled ? "每日 08:00 定时任务已启动。" : "每日 08:00 定时任务已暂停。");
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能管理每日定时任务。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法管理每日定时任务。");
      } else {
        setSystemStatusError("每日定时任务状态更新失败，请稍后重试。");
      }
    } finally {
      setDailySchedulerActionLoading(false);
    }
  }, [loadSystemStatus]);

  const handleRunDailySchedulerNow = useCallback(async () => {
    setDailySchedulerActionLoading(true);
    setDailySchedulerMessage("");
    setSystemStatusError("");
    try {
      const result = await runDailySchedulerNow();
      setDailySchedulerStatus(result);
      setDailySchedulerMessage(result.last_message || "每日定时任务已执行。");
      await loadSystemStatus();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("管理员登录后才能手动执行每日定时任务。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError("当前账号没有管理员权限，无法手动执行每日定时任务。");
      } else {
        setSystemStatusError("每日定时任务执行失败，请稍后重试。");
      }
    } finally {
      setDailySchedulerActionLoading(false);
    }
  }, [loadSystemStatus]);

  const handleExportAccountData = useCallback(async () => {
    setAccountExportLoading(true);
    setAccountExportMessage("");
    setSystemStatusError("");
    try {
      const payload = await exportAccountData();
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cryptorisk-account-export-${payload.user.username}-${payload.exported_at.slice(0, 10)}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setAccountExportMessage(
        `已导出：报告 ${payload.summary.analysis_reports}，收藏 ${payload.summary.favorites}，资产 ${payload.summary.portfolio_watchlist}，日报 ${payload.summary.daily_reports}，模拟交易 ${payload.summary.sim_account || 0} 个，会话 ${payload.summary.auth_sessions || 0} 个，安全事件 ${payload.summary.account_security_events || 0} 条。`
      );
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("登录后才能导出账号数据。");
      } else {
        setSystemStatusError("账号数据导出失败，请稍后重试。");
      }
    } finally {
      setAccountExportLoading(false);
    }
  }, []);

  const handleDeleteAccountData = useCallback(async (currentPassword: string) => {
    if (accountDeleteLoading) return;
    if (!currentPassword) {
      setSystemStatusError("请输入当前密码后再删除账号数据。");
      return;
    }
    setAccountDeleteLoading(true);
    setSystemStatusError("");
    try {
      const result = await deleteAccountData(currentPassword);
      clearApiCache();
      setAuthUser(null);
      setFavoriteReports([]);
      setFavoriteNews([]);
      setFavoriteReportIds(new Set());
      setFavoriteNewsIds(new Set());
      setAnalysisRecords([]);
      setStoredSelectedRecordId("");
      window.localStorage.removeItem(analysisRecordsStorageKey);
      window.localStorage.removeItem(selectedRecordStorageKey);
      window.localStorage.removeItem(chatMessagesStorageKey);
      setChatMessages(initialChatMessages);
      setAccountExportMessage(
        `账号数据已删除：报告 ${result.summary.analysis_reports_deleted}，收藏 ${result.summary.favorites_deleted}，资产 ${result.summary.portfolio_watchlist_deleted}，日报 ${result.summary.daily_reports_deleted}，模拟交易 ${result.summary.sim_accounts_deleted || 0}，审计事件 ${result.summary.audit_events_deleted || 0}。`
      );
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSystemStatusError("登录后才能删除账号数据。");
      } else if (error instanceof ApiRequestError && error.status === 403) {
        setSystemStatusError(error.detail || "当前密码错误，账号数据未删除。");
      } else {
        setSystemStatusError("账号数据删除失败，请稍后重试。");
      }
    } finally {
      setAccountDeleteLoading(false);
    }
  }, [accountDeleteLoading]);

  async function handleUpdateTodayNews() {
    if (newsUpdateLoading) return;
    setNewsUpdateLoading(true);
    setNewsUpdateError("");
    setNewsUpdateResult(null);
    setNewsUpdateJob(null);
    try {
      const job = await startNewsUpdateJob();
      await pollNewsUpdateJob(job);
    } catch (error) {
      console.error(error);
      setNewsUpdateError(
        error instanceof Error
          ? `更新失败：${error.message}`
          : "更新失败，请稍后重试。"
      );
    } finally {
      setNewsUpdateLoading(false);
    }
  }

  const pollNewsUpdateJob = useCallback(async (initialJob: NewsUpdateJob) => {
    const generation = updatePollGenerationRef.current + 1;
    updatePollGenerationRef.current = generation;
    setNewsUpdateLoading(isActiveNewsUpdateJob(initialJob));
    setNewsUpdateJob(initialJob);
    storeNewsUpdateJobId(initialJob.job_id);

    let job = initialJob;
    while (isActiveNewsUpdateJob(job)) {
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      if (updatePollGenerationRef.current !== generation) return;

      job = await fetchNewsUpdateJob(job.job_id);
      if (updatePollGenerationRef.current !== generation) return;

      setNewsUpdateJob(job);
      storeNewsUpdateJobId(job.job_id);
      if (job.stage === "agent" || job.stage === "ranking") {
        void refreshRankingsAfterUpdate(true);
      }
    }

    clearStoredNewsUpdateJobId();
    if (job.status === "error") {
      throw new Error(job.error || job.message || "新闻更新任务失败");
    }

    if (job.result) setNewsUpdateResult(job.result);
    setNewsUpdateLoading(false);
    await refreshRankingsAfterUpdate();
  }, [refreshRankingsAfterUpdate]);

  useEffect(() => {
    if (activeView !== "settings") return;
    let ignore = false;

    async function resumeNewsUpdateJob() {
      const storedJobId = readStoredNewsUpdateJobId();
      let job: NewsUpdateJob | null = null;

      if (storedJobId) {
        try {
          job = await fetchNewsUpdateJob(storedJobId);
        } catch {
          job = null;
        }
      }

      if (!job || !isActiveNewsUpdateJob(job)) {
        try {
          job = await fetchCurrentNewsUpdateJob();
        } catch {
          job = null;
        }
      }

      if (ignore || !job) return;
      if (isActiveNewsUpdateJob(job)) {
        void pollNewsUpdateJob(job).catch((error) => {
          console.error(error);
          if (!ignore) {
            setNewsUpdateError(error instanceof Error ? `更新失败：${error.message}` : "更新任务恢复失败。");
            setNewsUpdateLoading(false);
          }
        });
        return;
      }

      setNewsUpdateJob(job);
      if (job.status === "success" && job.result) setNewsUpdateResult(job.result);
      clearStoredNewsUpdateJobId();
    }

    void resumeNewsUpdateJob();

    return () => {
      ignore = true;
      updatePollGenerationRef.current += 1;
    };
  }, [activeView, pollNewsUpdateJob]);

  useEffect(() => {
    if (activeView !== "settings") return;
    const timer = window.setTimeout(() => {
      void loadSystemStatus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [activeView, authUser?.id, loadSystemStatus]);

  function runAnalysis(input: string) {
    const trimmed = input.trim();
    if (!trimmed) return;
    if (getActiveAnalysisTaskSnapshot()?.status === "running") return;

    setMessage("");
    setChatLoading(true);
    setChatProgressStage(initialChatProgressStage);
    setChatError("");
    startAnalysisTask(trimmed);
  }

  function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    runAnalysis(message);
  }

  function handleReanalyze(input: string) {
    navigateTo(viewRoutes.chat);
    runAnalysis(input);
  }

  async function handleDeepAnalyzeNews(item: NewsRankingItem) {
    const detail = await fetchNewsDetail(String(item.news_id), rankingRange).catch(() => item);
    const input = buildNewsAnalysisInput(detail);
    window.dispatchEvent(new CustomEvent("cryptorisk:open-risk-assistant", {
      detail: {
        mode: "deep_analysis",
        selectedText: detail.content || detail.summary || detail.title,
        sourceInput: input,
        news: detail,
      },
    }));
  }

  function handleDeepAnalyzeNewsInput(input: string) {
    window.dispatchEvent(new CustomEvent("cryptorisk:open-risk-assistant", {
      detail: {
        mode: "deep_analysis",
        selectedText: input,
        sourceInput: input,
      },
    }));
  }

  function handleClearChatHistory() {
    setChatMessages(initialChatMessages);
    writeStoredChatMessages(initialChatMessages);
  }

  async function handleAuthSubmit(mode: "login" | "register", username: string, password: string) {
    if (authLoading) return;
    setAuthLoading(true);
    setAuthError("");
    try {
      const response = mode === "login"
        ? await loginUser(username, password)
        : await registerUser(username, password);
      writeStoredAuthUsername(response.user.username);
      setAuthUser(response.user);
      setAuthModalOpen(false);
    } catch (error) {
      console.error(error);
      const message = error instanceof Error ? error.message.replace(/^Request failed: \d+:\s*/, "") : "登录失败，请稍后重试";
      setAuthError(mode === "register" && message.includes("用户名已存在") ? "用户名已存在，请切换到登录，不需要重新注册。" : message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleLogout() {
    if (authLoading) return;
    setAuthLoading(true);
    setAuthError("");
    try {
      await logoutUser();
      setAuthUser(null);
      setFavoriteReports([]);
      setFavoriteNews([]);
      setFavoriteReportIds(new Set());
      setFavoriteNewsIds(new Set());
    } catch (error) {
      console.error(error);
      setAuthError("退出登录失败，请稍后重试");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleToggleReportFavorite(record: AnalysisRecord) {
    if (!authUser) {
      setAuthError("请先登录后再收藏报告");
      setAuthModalOpen(true);
      return;
    }
    if (favoriteActionLoadingId) return;

    const isFavorite = favoriteReportIds.has(record.id);
    setFavoriteActionLoadingId(record.id);
    setAuthError("");
    try {
      if (isFavorite) {
        await deleteFavorite("report", record.id);
        setFavoriteReports((items) => items.filter((item) => item.item_id !== record.id));
        setFavoriteReportIds((ids) => {
          const next = new Set(ids);
          next.delete(record.id);
          return next;
        });
      } else {
        const favorite = await addFavorite({
          item_type: "report",
          item_id: record.id,
          title: record.title,
          payload: {
            id: record.id,
            title: record.title,
            createdAt: record.createdAt,
            input: record.input,
            report: record.report,
          },
        });
        setFavoriteReports((items) => [favorite, ...items.filter((item) => item.item_id !== favorite.item_id)]);
        setFavoriteReportIds((ids) => new Set(ids).add(record.id));
      }
    } catch (error) {
      console.error(error);
      setAuthError(error instanceof Error ? error.message.replace(/^Request failed: \d+:\s*/, "") : "收藏报告失败");
      if (!authUser) setAuthModalOpen(true);
    } finally {
      setFavoriteActionLoadingId("");
    }
  }

  async function handleToggleNewsFavorite(item: NewsRankingItem) {
    if (!authUser) {
      setAuthError("请先登录后再收藏新闻");
      setAuthModalOpen(true);
      return;
    }

    const itemId = String(item.news_id);
    if (favoriteActionLoadingId) return;
    const isFavorite = favoriteNewsIds.has(itemId);
    setFavoriteActionLoadingId(`news:${itemId}`);
    setAuthError("");
    try {
      if (isFavorite) {
        await deleteFavorite("news", itemId);
        setFavoriteNews((items) => items.filter((favorite) => favorite.item_id !== itemId));
        setFavoriteNewsIds((ids) => {
          const next = new Set(ids);
          next.delete(itemId);
          return next;
        });
      } else {
        const detail = await fetchNewsDetail(itemId, rankingRange).catch(() => item);
        const favorite = await addFavorite({
          item_type: "news",
          item_id: itemId,
          title: detail.title,
          payload: {
            news_id: detail.news_id,
            title: detail.title,
            content: detail.content,
            published_at: detail.published_at || detail.date,
            risk_score: detail.risk_score,
            risk_level: detail.risk_level,
            risk_type: detail.risk_type,
            coins: detail.coins,
            summary: detail.summary,
            evidence: detail.evidence,
            source_url: detail.source_url,
          },
        });
        setFavoriteNews((items) => [favorite, ...items.filter((existing) => existing.item_id !== favorite.item_id)]);
        setFavoriteNewsIds((ids) => new Set(ids).add(itemId));
      }
    } catch (error) {
      console.error(error);
      setAuthError(error instanceof Error ? error.message.replace(/^Request failed: \d+:\s*/, "") : "收藏新闻失败");
    } finally {
      setFavoriteActionLoadingId("");
    }
  }

  function handleDeleteRecord(id: string) {
    void deleteAnalysisReport(id).catch(() => undefined);
    setAnalysisRecords((items) => {
      const nextRecords = items.filter((item) => item.id !== id);
      if (nextRecords.length) {
        writeStoredAnalysisRecords(nextRecords);
        const selectedStillExists = nextRecords.some((record) => record.id === selectedRecordId);
        const nextSelected = selectedStillExists ? selectedRecordId : nextRecords[0].id;
        window.localStorage.setItem(selectedRecordStorageKey, nextSelected);
        setStoredSelectedRecordId(nextSelected);
        if (activeView === "reports") {
          navigateTo(`/reports?record=${encodeURIComponent(nextSelected)}`, "replace");
        }
      } else {
        window.localStorage.removeItem(analysisRecordsStorageKey);
        window.localStorage.removeItem(selectedRecordStorageKey);
        setStoredSelectedRecordId("");
        if (activeView === "reports") navigateTo("/reports", "replace");
      }
      return nextRecords;
    });
  }

  function handleDeleteAllRecords() {
    analysisRecords.forEach((record) => {
      void deleteAnalysisReport(record.id).catch(() => undefined);
    });
    setAnalysisRecords([]);
    setStoredSelectedRecordId("");
    window.localStorage.removeItem(analysisRecordsStorageKey);
    window.localStorage.removeItem(selectedRecordStorageKey);
    if (activeView === "reports") navigateTo("/reports", "replace");
  }

  function handleChangeRecordDisposition(recordId: string, disposition: AnalysisDisposition, note = "") {
    setAnalysisRecords((items) => {
      const nextRecords = items.map((record) => {
        if (record.id !== recordId) return record;
        const nextRecord = normalizeAnalysisRecord({
          ...record,
          disposition,
          dispositionNote: note,
        });
        void updateAnalysisReportDisposition(recordId, disposition, note)
          .catch(() => persistRemoteAnalysisReport(nextRecord));
        return nextRecord;
      });
      writeStoredAnalysisRecords(nextRecords);
      return nextRecords;
    });
  }

  return (
    <main className="risk-shell min-h-screen bg-[#f4f7fb] text-slate-900">
      <div className="flex min-h-screen">
        <Sidebar activeView={activeView} onChangeView={handleChangeView} />

        <div className="min-w-0 flex-1 lg:pl-[248px]">
          <TopBar
            authLoading={authLoading}
            authUser={authUser}
            stats={accountStats}
            onLoginClick={() => {
              setAuthError("");
              setAuthModalOpen(true);
            }}
            onLogout={handleLogout}
            onNavigate={navigateTo}
            title={pageMeta.title}
            subtitle={pageMeta.subtitle}
          />
          <MobileNav activeView={activeView} onChangeView={handleChangeView} />

          <div className="px-3 py-4 sm:px-6 sm:py-5 2xl:px-8">
            <div className="min-w-0 space-y-5">
              {shouldLoadRankingsForView(activeView) && rankingError && <Notice tone="amber" text={rankingError} />}
              {shouldLoadRankingsForView(activeView) && (
                <RankingDataStatusBar status={rankingDataStatus} />
              )}

              {activeView !== "chat" && activeView !== "portfolio" && activeView !== "sim" && activeView !== "daily" && activeView !== "reports" && activeView !== "favoriteNews" && activeView !== "favoriteReports" && activeView !== "my" && activeView !== "settings" && (
                <MetricGrid
                  activeView={activeView}
                  coinItems={displayCoins}
                  loading={rankingLoading}
                  newsItems={displayNews}
                  overview={overview}
                  topCoin={topCoin}
                  topNews={topNews}
                />
              )}

              {activeView === "home" && (
                <DashboardHome
                  coinItems={displayCoins}
                  favoriteActionLoadingId={favoriteActionLoadingId}
                  favoriteNewsIds={favoriteNewsIds}
                  newsItems={displayNews}
                  onAnalyzeNews={handleDeepAnalyzeNews}
                  onChangeView={handleChangeView}
                  onToggleNewsFavorite={handleToggleNewsFavorite}
                />
              )}

              {activeView === "chat" && (
                <ChatView
                  chatError={chatError}
                  chatLoading={chatLoading}
                  chatMessages={chatMessages}
                  chatProgressStage={chatProgressStage}
                  message={message}
                  onClearChatHistory={handleClearChatHistory}
                  onExampleClick={setMessage}
                  onMessageChange={setMessage}
                  onSelectRecord={handleSelectRecord}
                  onSubmit={handleChatSubmit}
                  records={analysisRecords}
                />
              )}

              {activeView === "news" && (
                <NewsView
                  items={displayNews}
                  favoriteActionLoadingId={favoriteActionLoadingId}
                  favoriteNewsIds={favoriteNewsIds}
                  range={rankingRange}
                  onAnalyzeNews={handleDeepAnalyzeNews}
                  onChangeRange={handleChangeRankingRange}
                  onToggleNewsFavorite={handleToggleNewsFavorite}
                />
              )}
              {activeView === "coin" && (
                <CoinView
                  items={displayCoins}
                  range={rankingRange}
                  onChangeRange={handleChangeRankingRange}
                />
              )}
              {activeView === "daily" && (
                <DailyReportView
                  agentReport={dailyReport}
                  error={dailyReportError}
                  fetching={dailyReportFetching}
                  loading={dailyReportLoading}
                  onChangeRange={handleDailyRangeChange}
                  onGenerate={handleGenerateDailyReport}
                  onToggleSubscription={handleToggleDailyReportSubscription}
                  range={rankingRange}
                  subscription={dailyReportSubscription}
                  subscriptionLoading={dailyReportSubscriptionLoading}
                />
              )}
              {activeView === "portfolio" && (
                <PortfolioRiskRadar />
              )}
              {activeView === "sim" && (
                <SimTradingPanel key={authUser?.id || "guest"} embedded />
              )}
              {activeView === "reports" && (
                <ReportsView
                  collapsed={reportSidebarCollapsed}
                  onDeleteAllRecords={handleDeleteAllRecords}
                  onDeleteRecord={handleDeleteRecord}
                  onChangeView={handleChangeView}
                  onSelectRecord={handleSelectReportRecord}
                  favoriteReportIds={favoriteReportIds}
                  favoriteActionLoadingId={favoriteActionLoadingId}
                  onToggleCollapsed={() => setReportSidebarCollapsed((value) => !value)}
                  onToggleFavorite={handleToggleReportFavorite}
                  onChangeDisposition={handleChangeRecordDisposition}
                  onReanalyze={handleReanalyze}
                  records={reportRecords}
                  selectedRecord={selectedRecord}
                />
              )}
              {activeView === "favoriteNews" && (
                <FavoriteNewsView
                  favorites={favoriteNews}
                  onAnalyzeNewsInput={handleDeepAnalyzeNewsInput}
                  onChangeView={handleChangeView}
                  onLoginClick={() => {
                    setAuthError("");
                    setAuthModalOpen(true);
                  }}
                  user={authUser}
                />
              )}
              {activeView === "favoriteReports" && (
                <FavoriteReportsView
                  favorites={favoriteReports}
                  onChangeView={handleChangeView}
                  onLoginClick={() => {
                    setAuthError("");
                    setAuthModalOpen(true);
                  }}
                  user={authUser}
                />
              )}
              {activeView === "my" && (
                <MyView
                  key={selectedVaultTab}
                  favoriteNews={favoriteNews}
                  favoriteReports={favoriteReports}
                  onChangeView={handleChangeView}
                  onLoginClick={() => {
                    setAuthError("");
                    setAuthModalOpen(true);
                  }}
                  selectedTab={selectedVaultTab}
                  user={authUser}
                />
              )}
              {activeView === "settings" && (
                <SettingsView
                  accountExportLoading={accountExportLoading}
                  accountExportMessage={accountExportMessage}
                  accountDeleteLoading={accountDeleteLoading}
                  auditSummary={auditSummary}
                  backupManifest={backupManifest}
                  dailySchedulerActionLoading={dailySchedulerActionLoading}
                  dailySchedulerMessage={dailySchedulerMessage}
                  dailySchedulerStatus={dailySchedulerStatus}
                  auditPruneLoading={auditPruneLoading}
                  auditPruneResult={auditPruneResult}
                  onExportAccountData={handleExportAccountData}
                  onDeleteAccountData={handleDeleteAccountData}
                  onPruneAuditEvents={handlePruneAuditEvents}
                  onPruneExpiredAuthSessions={handlePruneExpiredAuthSessions}
                  onPruneGuestSimAccounts={handlePruneGuestSimAccounts}
                  onPruneInvalidJsonBackups={handlePruneInvalidJsonBackups}
                  onPruneRuntimeJobs={handlePruneRuntimeJobs}
                  onRunDailySchedulerNow={handleRunDailySchedulerNow}
                  onToggleDailyScheduler={handleToggleDailyScheduler}
                  onRefreshSystemStatus={loadSystemStatus}
                  rateLimitStatus={rateLimitStatus}
                  storageInventory={storageInventory}
                  systemTaskEvents={systemTaskEvents}
                  systemReadiness={systemReadiness}
                  systemStatusError={systemStatusError}
                  systemStatusLoading={systemStatusLoading}
                  sessionPruneLoading={sessionPruneLoading}
                  sessionPruneMessage={sessionPruneMessage}
                  runtimeJobPruneLoading={runtimeJobPruneLoading}
                  runtimeJobPruneMessage={runtimeJobPruneMessage}
                  invalidBackupPruneLoading={invalidBackupPruneLoading}
                  invalidBackupPruneMessage={invalidBackupPruneMessage}
                  simPruneLoading={simPruneLoading}
                  simPruneMessage={simPruneMessage}
                  updateJob={newsUpdateJob}
                  updateError={newsUpdateError}
                  updateLoading={newsUpdateLoading}
                  updateResult={newsUpdateResult}
                  onUpdateTodayNews={handleUpdateTodayNews}
                />
              )}
            </div>

          </div>

          <footer className="px-3 pb-6 text-center text-xs text-slate-500 sm:px-6 2xl:px-8">
            粤ICP备2026061707号-1
          </footer>
        </div>
      </div>
      {authModalOpen && (
        <AuthModal
          error={authError}
          loading={authLoading}
          onClose={() => {
            if (!authLoading) setAuthModalOpen(false);
          }}
          onSubmit={handleAuthSubmit}
        />
      )}
    </main>
  );
}

function Sidebar({
  activeView,
  onChangeView,
}: {
  activeView: ActiveView;
  onChangeView: (view: ActiveView) => void;
}) {
  const [rankingCollapsedByUser, setRankingCollapsedByUser] = useState(false);
  const rankingActive = activeView === "news" || activeView === "coin";
  const rankingOpen = rankingActive || !rankingCollapsedByUser;
  const navItems: NavItem[] = [
    { key: "home", label: "首页总览", icon: <HomeIcon /> },
    { key: "chat", label: "事件风险分析", icon: <ChatIcon /> },
    { key: "reports", label: "分析报告", icon: <FileIcon /> },
    { key: "portfolio", label: "我的风险资产", icon: <PortfolioIcon /> },
    { key: "daily", label: "资产日报", icon: <BotIcon /> },
    { key: "sim", label: "模拟交易盘", icon: <TradeIcon /> },
  ];

  return (
    <aside className="risk-sidebar fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-blue-100 lg:flex lg:flex-col">
      <div className="flex h-[92px] items-center gap-3 border-b border-blue-100 px-6">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-white shadow-lg shadow-blue-200">
          <ShieldIcon />
        </div>
        <div>
          <p className="text-xl font-bold leading-6 text-slate-950">CryptoRisk</p>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Agent</p>
        </div>
      </div>

      <nav className="flex-1 space-y-2 px-4 py-6">
        {navItems.slice(0, 5).map((item) => (
          <SidebarButton
            key={item.key}
            active={isSidebarItemActive(activeView, item.key)}
            icon={item.icon}
            label={item.label}
            onClick={() => onChangeView(item.key)}
          />
        ))}

        <div>
          <button
            type="button"
            onClick={() => setRankingCollapsedByUser((collapsed) => !collapsed)}
            className={`flex h-12 w-full items-center gap-3 rounded-lg px-4 text-sm font-semibold transition-colors duration-200 ${
              rankingActive
                ? "bg-blue-50 text-blue-700 shadow-sm"
                : "text-slate-400 hover:bg-slate-50 hover:text-blue-700"
            }`}
            aria-expanded={rankingOpen}
          >
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-md ${
                rankingActive ? "bg-blue-600 text-white" : "text-slate-500"
              }`}
            >
              <ChartIcon />
            </span>
            <span className="flex-1 text-left">排行榜</span>
            <span className="text-slate-400">{rankingOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
          </button>

          {rankingOpen && (
            <div className="ml-7 mt-2 space-y-1 border-l border-blue-100 pl-3">
              <SidebarSubButton active={activeView === "news"} label="新闻风险榜" onClick={() => onChangeView("news")} />
              <SidebarSubButton active={activeView === "coin"} label="币种风险榜" onClick={() => onChangeView("coin")} />
            </div>
          )}
        </div>

        {navItems.slice(5).map((item) => (
          <SidebarButton
            key={item.key}
            active={isSidebarItemActive(activeView, item.key)}
            icon={item.icon}
            label={item.label}
            onClick={() => onChangeView(item.key)}
          />
        ))}
      </nav>

      <div className="mx-4 mb-6 rounded-lg border border-blue-100 bg-blue-50/50 p-4 shadow-sm shadow-blue-100/50">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          系统状态
        </div>
        <p className="mt-2 text-xl font-bold text-emerald-600">运行中</p>
        <p className="mt-1 text-xs text-slate-500">所有 Agent 正常运行</p>
      </div>

      <div className="px-6 pb-6 text-xs leading-6 text-slate-400">
        <p>© 2026 CryptoRisk Agent</p>
        <p>v1.0.0</p>
        <p>粤ICP备2026061707号-1</p>
      </div>
    </aside>
  );
}

function SidebarButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-12 w-full items-center gap-3 rounded-lg px-4 text-sm font-semibold transition-colors duration-200 ${
        active
          ? "bg-blue-50 text-blue-700 shadow-sm"
          : "text-slate-400 hover:bg-slate-50 hover:text-blue-700"
      }`}
    >
      <span className={`flex h-7 w-7 items-center justify-center rounded-md ${active ? "bg-blue-600 text-white" : "text-slate-500"}`}>
        {icon}
      </span>
      {label}
    </button>
  );
}

function isSidebarItemActive(activeView: ActiveView, itemKey: ActiveView) {
  return activeView === itemKey || (itemKey === "my" && (activeView === "favoriteNews" || activeView === "favoriteReports"));
}

function SidebarSubButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-10 w-full items-center rounded-lg px-3 text-sm font-semibold transition-colors duration-200 ${
        active ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:bg-white hover:text-blue-700"
      }`}
    >
      {label}
    </button>
  );
}

function TopBar({
  authLoading,
  authUser,
  onLoginClick,
  onLogout,
  onNavigate,
  stats,
  title,
  subtitle,
}: {
  authLoading: boolean;
  authUser: AuthUser | null;
  onLoginClick: () => void;
  onLogout: () => void;
  onNavigate: (path: string, mode?: "push" | "replace") => void;
  stats: AccountCenterStats;
  title: string;
  subtitle: string;
}) {
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!accountOpen) return;

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node | null;
      if (target && accountRef.current?.contains(target)) return;
      setAccountOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setAccountOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [accountOpen]);

  function handleNavigate(path: string) {
    setAccountOpen(false);
    onNavigate(path);
  }

  return (
    <header className="risk-topbar sticky top-0 z-20 border-b border-blue-100 backdrop-blur-xl">
      <div className="flex min-h-[76px] items-center gap-4 px-4 sm:min-h-[92px] sm:px-6 2xl:px-8">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xl font-bold tracking-tight text-slate-950 sm:text-2xl">{title}</p>
          <p className="mt-1 line-clamp-2 text-sm text-slate-500">{subtitle}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {authUser ? (
            <div className="relative" ref={accountRef}>
              <button
                type="button"
                onClick={() => setAccountOpen((value) => !value)}
                disabled={authLoading}
                aria-expanded={accountOpen}
                aria-haspopup="dialog"
                className="inline-flex h-11 cursor-pointer items-center gap-2 rounded-lg border border-blue-100 bg-white px-2 text-sm font-bold text-slate-700 shadow-sm transition-colors duration-200 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50 sm:px-3"
              >
                <AccountAvatar user={authUser} />
                <span className="hidden min-w-0 text-right sm:block">
                  <span className="block max-w-[120px] truncate text-sm font-bold text-slate-900">{authUser.display_name || authUser.username}</span>
                  <span className="block text-xs font-semibold text-emerald-600">已登录</span>
                </span>
                <ChevronDownIcon />
              </button>
              {accountOpen && (
                <AccountCenterPopover
                  authLoading={authLoading}
                  onLogout={() => {
                    setAccountOpen(false);
                    onLogout();
                  }}
                  onNavigate={handleNavigate}
                  stats={stats}
                  user={authUser}
                />
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={onLoginClick}
              disabled={authLoading}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50 sm:px-4"
            >
              <UsersIcon />
              登录
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function AccountAvatar({ large = false, user }: { large?: boolean; user: AuthUser }) {
  const name = user.display_name || user.username || "U";
  const initial = name.trim().slice(0, 1).toUpperCase() || "U";
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-full bg-blue-600 font-bold text-white shadow-sm shadow-blue-200 ${large ? "h-14 w-14 text-lg" : "h-8 w-8 text-sm"}`}>
      {initial}
    </span>
  );
}

function AccountCenterPopover({
  authLoading,
  onLogout,
  onNavigate,
  stats,
  user,
}: {
  authLoading: boolean;
  onLogout: () => void;
  onNavigate: (path: string) => void;
  stats: AccountCenterStats;
  user: AuthUser;
}) {
  const userName = user.display_name || user.username;
  const email = user.email || "邮箱未绑定";
  const statsItems = [
    ["关注资产", stats.loadingAssets ? "--" : String(stats.watchedAssets), "text-blue-700"],
    ["高风险", stats.loadingAssets ? "--" : String(stats.highRiskAssets), "text-red-600"],
    ["未处理预警", stats.loadingAssets ? "--" : String(stats.pendingAlerts), "text-orange-600"],
    ["收藏报告", String(stats.favoriteReports), "text-violet-700"],
  ] as const;
  const shortcuts = [
    { badge: stats.loadingAssets ? "--" : String(stats.watchedAssets), icon: <PortfolioIcon />, label: "设置关注资产", path: "/my?tab=assets" },
    { badge: String(stats.favoriteNews), icon: <ChartIcon />, label: "收藏新闻", path: "/favorites/news" },
    { badge: String(stats.favoriteReports), icon: <FileIcon />, label: "收藏报告", path: "/favorites/reports" },
  ];

  return (
    <div
      className="absolute right-0 top-14 z-50 w-[min(92vw,360px)] overflow-hidden rounded-lg border border-blue-100 bg-white shadow-2xl shadow-slate-900/15"
      role="dialog"
      aria-label="我的风控中心"
    >
      <div className="border-b border-blue-100 bg-blue-50/70 px-4 py-4">
        <div className="flex items-center gap-3">
          <AccountAvatar large user={user} />
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">我的风控中心</p>
            <p className="mt-1 truncate text-base font-bold text-slate-950">{userName}</p>
            <p className="mt-0.5 truncate text-xs font-semibold text-slate-500">{email}</p>
          </div>
        </div>
      </div>

      <div className="p-4">
        <div className="grid grid-cols-2 gap-2">
          {statsItems.map(([label, value, tone]) => (
            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5" key={label}>
              <p className="text-xs font-bold text-slate-500">{label}</p>
              <p className={`mt-1 text-xl font-bold tabular-nums ${tone}`}>{value}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 space-y-1">
          {shortcuts.map((item) => (
            <button
              className="flex h-10 w-full cursor-pointer items-center gap-3 rounded-lg px-3 text-left text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 hover:text-blue-700"
              key={item.label}
              onClick={() => onNavigate(item.path)}
              type="button"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-50 text-blue-700">{item.icon}</span>
              <span className="flex-1">{item.label}</span>
              {"badge" in item && <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-500">{item.badge}</span>}
              <ChevronRightIcon />
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-2">
          <button
            className="h-10 cursor-pointer rounded-lg bg-blue-600 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700"
            onClick={() => onNavigate("/my")}
            type="button"
          >
            查看完整档案库
          </button>
          <div className="grid grid-cols-2 gap-2">
            <button
              className="h-10 cursor-pointer rounded-lg border border-blue-100 bg-white text-sm font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50"
              onClick={() => onNavigate("/settings")}
              type="button"
            >
              系统设置
            </button>
            <button
              className="h-10 cursor-pointer rounded-lg border border-slate-200 bg-white text-sm font-bold text-slate-600 transition-colors duration-200 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-50"
              disabled={authLoading}
              onClick={onLogout}
              type="button"
            >
              退出登录
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AuthModal({
  error,
  loading,
  onClose,
  onSubmit,
}: {
  error: string;
  loading: boolean;
  onClose: () => void;
  onSubmit: (mode: "login" | "register", username: string, password: string) => void;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState(() => readStoredAuthUsername());
  const [password, setPassword] = useState("");
  const passwordStrength = getPasswordStrength(password, username);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(mode, username.trim(), password);
  }

  function handleGeneratePassword() {
    const generated = generateStrongPassword();
    setPassword(generated);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 py-6 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-lg border border-blue-100 bg-white shadow-2xl shadow-slate-900/20">
        <div className="flex items-center justify-between gap-3 border-b border-blue-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-600 text-white">
              <UsersIcon />
            </div>
            <div>
              <h2 className="text-lg font-bold text-slate-950">{mode === "login" ? "用户登录" : "注册账号"}</h2>
              <p className="text-xs font-semibold text-slate-500">CryptoRisk Agent</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-blue-100 bg-white text-slate-500 transition-colors duration-200 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="关闭登录窗口"
          >
            <CloseIcon />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
          <div className="grid grid-cols-2 rounded-lg border border-blue-100 bg-slate-50 p-1">
            {[
              ["login", "登录"],
              ["register", "注册"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value as "login" | "register")}
                className={`h-9 rounded-md text-sm font-bold transition-colors duration-200 ${
                  mode === value ? "bg-white text-blue-700 shadow-sm" : "text-slate-500 hover:text-blue-700"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <label className="block">
            <span className="text-sm font-bold text-slate-700">用户名</span>
            <input
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
                writeStoredAuthUsername(event.target.value);
              }}
              className="mt-2 h-11 w-full rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition-colors duration-200 placeholder:text-slate-400 focus:border-blue-400 focus:ring-4 focus:ring-blue-100"
              autoComplete="username"
              minLength={3}
              maxLength={32}
              required
            />
          </label>

          <label className="block">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-bold text-slate-700">密码</span>
              {mode === "register" && (
                <button
                  type="button"
                  onClick={handleGeneratePassword}
                  className="text-xs font-bold text-blue-700 transition-colors duration-200 hover:text-blue-900"
                >
                  生成强密码
                </button>
              )}
            </div>
            <div className="mt-2 flex overflow-hidden rounded-lg border border-blue-100 bg-white focus-within:border-blue-400 focus-within:ring-4 focus-within:ring-blue-100">
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-11 min-w-0 flex-1 bg-transparent px-3 text-sm font-semibold text-slate-800 outline-none placeholder:text-slate-400"
                placeholder={mode === "login" ? "输入密码" : "至少 10 位，建议使用强密码"}
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                minLength={mode === "login" ? 6 : 10}
                maxLength={128}
                required
              />
            </div>
          </label>

          {mode === "register" && (
            <div className="rounded-lg border border-blue-100 bg-blue-50/70 p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs font-bold text-slate-600">密码强度</span>
                <span className={`text-xs font-bold ${passwordStrength.color}`}>{passwordStrength.label}</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white">
                <div className={`h-full rounded-full ${passwordStrength.bar}`} style={{ width: `${passwordStrength.percent}%` }} />
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || username.trim().length < 3 || password.length < (mode === "login" ? 6 : 10)}
            className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? (mode === "login" ? "正在登录..." : "正在注册...") : mode === "login" ? "登录" : "注册并登录"}
          </button>
          {mode === "register" && (
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setPassword("");
              }}
              className="w-full text-center text-xs font-bold text-slate-500 transition-colors duration-200 hover:text-blue-700"
            >
              已有账号？切换到登录
            </button>
          )}
        </form>
      </div>
    </div>
  );
}

function generateStrongPassword() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*_-+=";
  const required = ["A", "z", "7", "!"];
  const bytes = new Uint32Array(18);
  if (typeof window !== "undefined" && window.crypto?.getRandomValues) {
    window.crypto.getRandomValues(bytes);
  } else {
    bytes.forEach((_, index) => {
      bytes[index] = Math.floor(Math.random() * chars.length);
    });
  }
  return [...required, ...Array.from(bytes, (value) => chars[value % chars.length])]
    .sort(() => Math.random() - 0.5)
    .join("");
}

function getPasswordStrength(password: string, username: string) {
  if (!password) {
    return { label: "待输入", percent: 8, color: "text-slate-400", bar: "bg-slate-200" };
  }

  const lowered = password.toLowerCase();
  const normalizedUsername = username.trim().toLowerCase();
  let score = 0;
  if (password.length >= 10) score += 25;
  if (password.length >= 14) score += 20;
  if (/[a-z]/.test(password)) score += 12;
  if (/[A-Z]/.test(password)) score += 12;
  if (/\d/.test(password)) score += 12;
  if (/[^A-Za-z0-9]/.test(password)) score += 19;
  if (normalizedUsername && lowered.includes(normalizedUsername)) score -= 30;
  if (/^(.)\1+$/.test(password) || /123456|password|qwerty|admin/i.test(password)) score -= 35;

  const clamped = Math.max(8, Math.min(100, score));
  if (clamped >= 80) return { label: "强", percent: clamped, color: "text-emerald-600", bar: "bg-emerald-500" };
  if (clamped >= 55) return { label: "中", percent: clamped, color: "text-amber-600", bar: "bg-amber-500" };
  return { label: "偏弱", percent: clamped, color: "text-rose-600", bar: "bg-rose-500" };
}

function MobileNav({
  activeView,
  onChangeView,
}: {
  activeView: ActiveView;
  onChangeView: (view: ActiveView) => void;
}) {
  const items: Array<[ActiveView, string]> = [
    ["home", "总览"],
    ["chat", "对话"],
    ["reports", "报告"],
    ["portfolio", "资产"],
    ["daily", "日报"],
    ["news", "新闻榜"],
    ["coin", "币种榜"],
    ["sim", "模拟盘"],
  ];

  return (
    <nav className="risk-scroll sticky top-[76px] z-10 flex gap-2 overflow-x-auto border-b border-blue-100 bg-white px-3 py-2.5 sm:top-[92px] sm:px-4 sm:py-3 lg:hidden">
      {items.map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChangeView(key)}
          className={`shrink-0 rounded-lg px-3 py-2 text-sm font-semibold transition-colors duration-200 sm:px-4 ${
            isSidebarItemActive(activeView, key)
              ? "bg-blue-600 text-white"
              : "border border-blue-100 bg-white text-slate-600"
          }`}
        >
          {label}
        </button>
      ))}
    </nav>
  );
}

function MetricGrid({
  activeView,
  coinItems,
  loading,
  newsItems,
  overview,
  topCoin,
  topNews,
}: {
  activeView: ActiveView;
  coinItems: CoinRankingItem[];
  loading: boolean;
  newsItems: NewsRankingItem[];
  overview: RiskOverview | null;
  topCoin: CoinRankingItem;
  topNews: NewsRankingItem;
}) {
  const deferredNewsItems = useDeferredValue(newsItems);
  const deferredCoinItems = useDeferredValue(coinItems);
  const metrics = useMemo(
    () => getMetrics(activeView, overview, topNews, topCoin, loading, deferredNewsItems, deferredCoinItems),
    [activeView, deferredCoinItems, deferredNewsItems, loading, overview, topCoin, topNews],
  );

  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-onboarding-id="home-metrics">
      {metrics.map((metric) => (
        <MetricCard key={metric.label} {...metric} />
      ))}
    </section>
  );
}

function MetricCard({
  deltaPercent,
  icon,
  label,
  series,
  value,
  delta,
  deltaTone = "neutral",
  tone,
}: {
  deltaPercent?: string;
  icon: ReactNode;
  label: string;
  series?: TrendPoint[];
  value: string;
  delta: string;
  deltaTone?: "up" | "down" | "neutral";
  tone: MetricTone;
}) {
  const toneStyle = {
    blue: "bg-blue-50 text-blue-600",
    red: "bg-red-50 text-red-600",
    orange: "bg-orange-50 text-orange-600",
    green: "bg-emerald-50 text-emerald-600",
    purple: "bg-violet-50 text-violet-600",
  }[tone];

  return (
    <article className="risk-card rounded-lg p-5">
      <div className="flex items-start justify-between gap-4">
        <div className={`flex h-14 w-14 items-center justify-center rounded-full ${toneStyle}`}>{icon}</div>
        <SparklineChart
          ariaLabel={`${label}最近趋势`}
          className="mt-7 h-9 w-24"
          series={series || buildFallbackTrendSeries(clampScore(Number(value) || 0 || 40))}
          tone={tone}
        />
      </div>
      <div className="mt-3">
        <p className="text-sm font-semibold text-slate-600">{label}</p>
        <p className={`mt-1 text-3xl font-bold ${toneStyle.split(" ")[1]}`}>{value}</p>
        <p className="mt-2 text-xs text-slate-500">
          较昨日{" "}
          <span className={`font-semibold ${deltaTextClass(deltaTone)}`}>{delta}</span>
          {deltaPercent && <span className={`ml-1 font-semibold ${deltaTextClass(deltaTone)}`}>{deltaPercent}</span>}
        </p>
      </div>
    </article>
  );
}

function RankingDataStatusBar({ status }: { status: RankingDataStatus }) {
  const isDemo = status.mode === "demo";
  const tone = isDemo
    ? "border-amber-200 bg-amber-50 text-amber-800"
    : "border-emerald-200 bg-emerald-50 text-emerald-800";
  const agentLabel = {
    ready: "Agent 标注正常",
    fallback: "Agent 兜底/离线",
    unknown: "Agent 状态检测中",
  }[status.agentStatus];
  const sourceLabel = {
    connected: "新闻源已连接",
    fallback: "新闻源未连接",
    unknown: "新闻源检测中",
  }[status.newsSourceStatus];

  return (
    <section className={`rounded-lg border px-4 py-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className={`rounded-md px-2.5 py-1 text-xs font-bold ${isDemo ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
            {isDemo ? "演示数据" : "真实数据"}
          </span>
          <span className="text-sm font-bold">{status.message}</span>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-bold">
          <span className="rounded-md bg-white/70 px-2.5 py-1">更新时间：{status.updatedAt || "--"}</span>
          <span className="rounded-md bg-white/70 px-2.5 py-1">{sourceLabel}</span>
          <span className="rounded-md bg-white/70 px-2.5 py-1">{agentLabel}</span>
        </div>
      </div>
    </section>
  );
}

function DashboardHome({
  coinItems,
  favoriteActionLoadingId,
  favoriteNewsIds,
  newsItems,
  onAnalyzeNews,
  onChangeView,
  onToggleNewsFavorite,
}: {
  coinItems: CoinRankingItem[];
  favoriteActionLoadingId: string;
  favoriteNewsIds: Set<string>;
  newsItems: NewsRankingItem[];
  onAnalyzeNews: (item: NewsRankingItem) => void;
  onChangeView: (view: ActiveView) => void;
  onToggleNewsFavorite: (item: NewsRankingItem) => void;
}) {
  const topCoin = coinItems[0] || emptyCoinItem;
  const topNews = newsItems[0] || emptyNewsItem;
  const priorities = buildHomePriorities(newsItems, coinItems);

  return (
    <>
      <CommandHero topCoin={topCoin} topNews={topNews} onStart={() => onChangeView("chat")} />
      <TodayPriorityPanel priorities={priorities} onChangeView={onChangeView} />
      <div className="grid gap-5 xl:grid-cols-2">
        <RankingCard title="新闻风险排行榜 Top 10" action="查看全部" onAction={() => onChangeView("news")}>
          <NewsTable
            compact
            favoriteActionLoadingId={favoriteActionLoadingId}
            favoriteNewsIds={favoriteNewsIds}
            items={newsItems.slice(0, 10)}
            onAnalyzeNews={onAnalyzeNews}
            onToggleFavorite={onToggleNewsFavorite}
          />
        </RankingCard>
        <RankingCard title="币种风险排行榜 Top 10" action="查看全部" onAction={() => onChangeView("coin")}>
          <CoinTable items={coinItems.slice(0, 10)} compact />
        </RankingCard>
      </div>
    </>
  );
}

function CommandHero({
  onStart,
  topCoin,
  topNews,
}: {
  onStart: () => void;
  topCoin: CoinRankingItem;
  topNews: NewsRankingItem;
}) {
  return (
    <section className="risk-card grid gap-5 rounded-lg p-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]" data-onboarding-id="home-command">
      <div className="relative z-10">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-emerald-700/20 bg-emerald-100 px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-emerald-800">
            Live Risk Command
          </span>
          <span className="rounded-full border border-sky-700/20 bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-800">
            DeepSeek + LangGraph Multi-Agent
          </span>
        </div>
        <h1 className="mt-5 max-w-3xl text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">
          加密资产事件风控指挥舱
        </h1>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-400 sm:text-base">
          聚合新闻、公告、链上异常与交易所事件，自动完成风险识别、风险类型分支审核、影响对象分析和处置建议生成。
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onStart}
            className="inline-flex h-11 items-center gap-2 rounded-lg bg-blue-600 px-5 text-sm font-bold text-white shadow-lg shadow-blue-200 transition-colors duration-200 hover:bg-blue-700"
          >
            <ChatIcon />
            开始事件分析
          </button>
          <div className="flex h-11 items-center gap-2 rounded-lg border border-blue-100 bg-slate-50 px-4 text-sm font-semibold text-slate-600">
            <span className="h-2 w-2 rounded-full bg-emerald-400" />
            Agent 工作流在线
          </div>
        </div>
      </div>

      <div className="relative z-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
        <HeroSignal label="最高风险新闻" value={topNews.title} score={topNews.risk_score} tone="red" />
        <HeroSignal label="最高风险币种" value={`${topCoin.symbol} / ${formatScoreReasonText(topCoin.main_risk_type)}`} score={topCoin.final_score} tone="orange" />
      </div>
    </section>
  );
}

function TodayPriorityPanel({
  onChangeView,
  priorities,
}: {
  onChangeView: (view: ActiveView) => void;
  priorities: Array<{ title: string; detail: string; action: string; view: ActiveView; tone: "red" | "orange" | "blue" }>;
}) {
  return (
    <section className="risk-card rounded-lg p-5" data-onboarding-id="home-priorities">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PanelTitle icon={<AlertIcon />} title="今天我应该先看什么" />
        <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">优先级队列</span>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        {priorities.map((item, index) => {
          const toneStyle = {
            red: "border-rose-200 bg-rose-50 text-rose-800",
            orange: "border-amber-200 bg-amber-50 text-amber-800",
            blue: "border-blue-200 bg-blue-50 text-blue-800",
          }[item.tone];
          return (
            <button
              key={`${item.title}-${index}`}
              type="button"
              onClick={() => onChangeView(item.view)}
              className={`min-h-[132px] rounded-lg border p-4 text-left transition-colors duration-200 hover:bg-white ${toneStyle}`}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="rounded-md bg-white px-2 py-1 text-xs font-bold">P{index + 1}</span>
                <ChevronRightIcon />
              </div>
              <p className="mt-3 text-sm font-bold leading-6 text-slate-950">{item.title}</p>
              <p className="mt-1 text-xs font-semibold leading-5 text-slate-600">{item.detail}</p>
              <p className="mt-3 text-xs font-bold">{item.action}</p>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function HeroSignal({
  label,
  score,
  tone,
  value,
}: {
  label: string;
  score: number;
  tone: "red" | "orange";
  value: string;
}) {
  const toneStyle = tone === "red" ? "text-rose-800 bg-rose-50 border-rose-200" : "text-orange-800 bg-orange-50 border-orange-200";

  return (
    <div className={`rounded-lg border p-4 ${toneStyle}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-bold uppercase tracking-[0.16em] opacity-80">{label}</p>
        <span className="text-2xl font-bold">{clampScore(score)}</span>
      </div>
      <p className="mt-3 line-clamp-2 text-sm font-semibold leading-6 text-slate-900">{value}</p>
    </div>
  );
}

function ChatView({
  chatError,
  chatLoading,
  chatMessages,
  chatProgressStage,
  message,
  onClearChatHistory,
  onExampleClick,
  onMessageChange,
  onSelectRecord,
  onSubmit,
  records,
}: {
  chatError: string;
  chatLoading: boolean;
  chatMessages: ChatMessage[];
  chatProgressStage: ChatProgressStage;
  message: string;
  onClearChatHistory: () => void;
  onExampleClick: (value: string) => void;
  onMessageChange: (value: string) => void;
  onSelectRecord: (id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  records: AnalysisRecord[];
}) {
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const messageLength = message.trim().length;
  const visibleChatMessages = useMemo(() => trimChatMessages(chatMessages), [chatMessages]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [visibleChatMessages, chatLoading]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [message]);

  return (
    <section className="grid min-h-[calc(100vh-168px)] gap-4 sm:gap-5 xl:h-[calc(100vh-170px)] xl:grid-cols-[minmax(0,4fr)_minmax(230px,1fr)]">
      <div className="risk-card flex min-h-[calc(100vh-168px)] overflow-hidden rounded-lg xl:h-full xl:min-h-0">
        <div className="flex min-w-0 flex-1 flex-col bg-white">
          <div className="border-b border-blue-100 bg-gradient-to-r from-white via-blue-50 to-emerald-50 px-4 py-4 sm:px-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-white shadow-sm shadow-blue-200">
                  <ChatIcon />
                </div>
                <div className="min-w-0">
                  <p className="text-base font-bold text-slate-950">事件研判对话</p>
                  <p className="mt-1 text-xs font-semibold text-slate-500">粘贴新闻正文、公告或链上异常，生成风险分析报告</p>
                </div>
              </div>
              <div className="rounded-full border border-emerald-100 bg-white px-3 py-1.5 text-xs font-bold text-emerald-700 shadow-sm">
                Agent 待命
              </div>
            </div>
          </div>

          <div className="risk-scroll min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(rgba(37,99,235,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(37,99,235,0.035)_1px,transparent_1px)] bg-[size:40px_40px] px-3 py-5 sm:px-8 sm:py-6 lg:px-10">
            <div className="mx-auto max-w-5xl space-y-5">
              {visibleChatMessages.map((item) => (
                <div key={item.id} className={`flex items-end gap-3 ${item.role === "user" ? "justify-end" : "justify-start"}`}>
                  {item.role === "assistant" && (
                    <div className="mb-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-white shadow-sm">
                      <ShieldIcon />
                    </div>
                  )}
                  <div
                    className={`max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-7 shadow-sm sm:max-w-[76%] sm:px-5 sm:py-4 ${
                      item.role === "user"
                        ? "rounded-br-md bg-emerald-700 text-white shadow-emerald-100"
                        : "rounded-bl-md border border-blue-100 bg-white/95 text-slate-700 shadow-blue-100/70"
                    }`}
                  >
                    {item.role === "assistant" && !item.content ? <LoadingDots label="正在生成简要分析" /> : item.content}
                  </div>
                  {item.role === "user" && (
                    <div className="mb-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white shadow-sm">
                      <UserIcon />
                    </div>
                  )}
                </div>
              ))}
              {chatLoading && (
                <div className="flex justify-start">
                  <div className="w-full max-w-3xl">
                    <AgentProgress
                      activeStage={chatProgressStage}
                      icon={<ShieldIcon />}
                      title={`Agent 正在执行：${chatProgressLabels[chatProgressStage]}`}
                      steps={chatProgressSteps}
                    />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          </div>

          <div className="border-t border-blue-100 bg-white/95 px-3 py-3 backdrop-blur sm:px-8 sm:py-4">
            <div className="mx-auto max-w-4xl">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="risk-scroll flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1">
                  {examplePrompts.slice(0, 3).map((item, index) => (
                    <button
                      key={item}
                      type="button"
                      onClick={() => onExampleClick(item)}
                      className="shrink-0 rounded-full border border-blue-100 bg-blue-50 px-4 py-2 text-xs font-bold text-blue-700 shadow-sm transition-colors duration-200 hover:bg-blue-100"
                    >
                      示例 {index + 1}
                    </button>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={onClearChatHistory}
                  disabled={chatLoading}
                  className="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 text-xs font-bold text-rose-700 transition-colors duration-200 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <TrashIcon />
                  清除聊天
                </button>
              </div>

              <form onSubmit={onSubmit} className="rounded-2xl border border-blue-100 bg-white p-3 shadow-xl shadow-blue-100/70" data-onboarding-id="chat-input">
                <textarea
                  ref={textareaRef}
                  value={message}
                  onChange={(event) => onMessageChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      event.currentTarget.form?.requestSubmit();
                    }
                  }}
                  className="max-h-40 min-h-24 w-full resize-none bg-transparent px-1 text-sm leading-7 text-slate-700 outline-none placeholder:text-slate-400"
                  placeholder="粘贴新闻正文、公告、链上事件或交易所异常，开始风险分析..."
                  rows={3}
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500">
                    <span>Enter 发送</span>
                    <span className="h-1 w-1 rounded-full bg-slate-300" />
                    <span>Shift + Enter 换行</span>
                    <span className="h-1 w-1 rounded-full bg-slate-300" />
                    <span>{messageLength} 字</span>
                  </div>
                  <button
                    type="submit"
                    disabled={chatLoading || !message.trim()}
                    className="inline-flex h-11 items-center gap-2 rounded-xl bg-emerald-700 px-4 text-sm font-bold text-white shadow-sm shadow-emerald-100 transition-colors duration-200 hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label="发送分析事件"
                  >
                    <SendIcon />
                    开始分析
                  </button>
                </div>
              </form>
              {chatError && <div className="mt-3"><Notice tone="red" text={chatError} /></div>}
            </div>
          </div>
        </div>
      </div>
      <AnalysisCardsPanel records={records} onSelectRecord={onSelectRecord} />
    </section>
  );
}

function AnalysisCardsPanel({
  onSelectRecord,
  records,
}: {
  onSelectRecord: (id: string) => void;
  records: AnalysisRecord[];
}) {
  return (
    <aside className="risk-card flex max-h-[420px] min-h-0 flex-col rounded-lg p-4 sm:max-h-[520px] xl:h-[calc(100vh-170px)] xl:max-h-[calc(100vh-170px)]">
      <div className="flex items-center justify-between gap-3 border-b border-blue-100 pb-3">
        <PanelTitle icon={<FileIcon />} title="精简报告" />
        <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{records.length}</span>
      </div>

      <div className="risk-scroll mt-4 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {records.length ? (
          records.map((record) => (
            <Link
              key={record.id}
              href={`/reports?record=${encodeURIComponent(record.id)}`}
              onClick={() => {
                window.localStorage.setItem(selectedRecordStorageKey, record.id);
                onSelectRecord(record.id);
              }}
              className="block rounded-lg border border-blue-100 bg-white p-3 shadow-sm transition-colors duration-200 hover:border-blue-300 hover:bg-blue-50"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="line-clamp-2 text-sm font-bold leading-6 text-slate-950">{record.title}</p>
                <span className="shrink-0 text-xl font-bold text-red-500">{clampScore(record.report.risk_score)}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <RiskBadge level={record.report.risk_level} />
              </div>
              <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-600">{formatScoreReasonText(record.report.summary || record.input)}</p>
              <p className="mt-3 text-xs font-semibold text-blue-700">{record.createdAt}</p>
            </Link>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-blue-200 bg-blue-50/60 p-4 text-sm leading-6 text-slate-600">
            分析完成后，这里会累积对应的精简报告卡片。
          </div>
        )}
      </div>
    </aside>
  );
}

function NewsView({
  favoriteActionLoadingId,
  favoriteNewsIds,
  items,
  onAnalyzeNews,
  onChangeRange,
  onToggleNewsFavorite,
  range,
}: {
  favoriteActionLoadingId: string;
  favoriteNewsIds: Set<string>;
  items: NewsRankingItem[];
  onAnalyzeNews: (item: NewsRankingItem) => void;
  onChangeRange: (range: RankingRange) => void;
  onToggleNewsFavorite: (item: NewsRankingItem) => void;
  range: RankingRange;
}) {
  const [filter, setFilter] = useState<NewsFilter>(() => readRankingFilter("news", "filter", "top10", isNewsFilter));
  const [sort, setSort] = useState<NewsSort>(() => readRankingFilter("news", "sort", "score_desc", isNewsSort));
  const deferredItems = useDeferredValue(items);
  const deferredFilter = useDeferredValue(filter);
  const deferredSort = useDeferredValue(sort);
  const visibleItems = useMemo(() => getVisibleNewsItems(deferredItems, deferredFilter, deferredSort), [deferredFilter, deferredItems, deferredSort]);
  const distribution = useMemo(() => getNewsDistribution(deferredItems), [deferredItems]);

  useEffect(() => {
    syncRankingUrl("news", { filter, sort, range });
    restoreRankingScroll();
  }, [filter, range, sort, visibleItems.length]);

  function handleChangeFilter(nextFilter: NewsFilter) {
    syncRankingUrl("news", { filter: nextFilter, sort });
    setFilter(nextFilter);
  }

  function handleChangeSort(nextSort: NewsSort) {
    syncRankingUrl("news", { filter, sort: nextSort });
    setSort(nextSort);
  }

  return (
    <>
      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.4fr)_minmax(0,0.6fr)]">
        <DistributionCard {...distribution} />
        <NewsRiskOverviewCard items={deferredItems} />
      </div>
      <NewsRankingPanel
        favoriteActionLoadingId={favoriteActionLoadingId}
        favoriteNewsIds={favoriteNewsIds}
        filter={filter}
        items={visibleItems}
        onAnalyzeNews={onAnalyzeNews}
        onChangeFilter={handleChangeFilter}
        onChangeRange={onChangeRange}
        onChangeSort={handleChangeSort}
        onToggleFavorite={onToggleNewsFavorite}
        range={range}
        sort={sort}
        total={items.length}
      />
    </>
  );
}

function CoinView({
  items,
  onChangeRange,
  range,
}: {
  items: CoinRankingItem[];
  onChangeRange: (range: RankingRange) => void;
  range: RankingRange;
}) {
  const [filter, setFilter] = useState<CoinFilter>(() => readRankingFilter("coin", "filter", "top10", isCoinFilter));
  const [sort, setSort] = useState<CoinSort>(() => readRankingFilter("coin", "sort", "score_desc", isCoinSort));
  const deferredItems = useDeferredValue(items);
  const deferredFilter = useDeferredValue(filter);
  const deferredSort = useDeferredValue(sort);
  const visibleItems = useMemo(() => getVisibleCoinItems(deferredItems, deferredFilter, deferredSort), [deferredFilter, deferredItems, deferredSort]);
  const distribution = useMemo(() => getCoinDistribution(deferredItems), [deferredItems]);

  useEffect(() => {
    syncRankingUrl("coin", { filter, sort, range });
    restoreRankingScroll();
  }, [filter, range, sort, visibleItems.length]);

  function handleChangeFilter(nextFilter: CoinFilter) {
    syncRankingUrl("coin", { filter: nextFilter, sort });
    setFilter(nextFilter);
  }

  function handleChangeSort(nextSort: CoinSort) {
    syncRankingUrl("coin", { filter, sort: nextSort });
    setSort(nextSort);
  }

  return (
    <>
      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.4fr)_minmax(0,0.6fr)]">
        <DistributionCard {...distribution} />
        <CoinRiskTrendCard items={deferredItems} range={range} />
      </div>
      <CoinRankingPanel
        filter={filter}
        items={visibleItems}
        onChangeFilter={handleChangeFilter}
        onChangeRange={onChangeRange}
        onChangeSort={handleChangeSort}
        range={range}
        sort={sort}
        total={items.length}
      />
    </>
  );
}

function DailyReportView({
  agentReport,
  error,
  fetching,
  loading,
  onChangeRange,
  onGenerate,
  onToggleSubscription,
  range,
  subscription,
  subscriptionLoading,
}: {
  agentReport: DailyRiskReport | null;
  error: string;
  fetching: boolean;
  loading: boolean;
  onChangeRange: (range: RankingRange) => void;
  onGenerate: () => void;
  onToggleSubscription: (enabled: boolean) => void;
  range: RankingRange;
  subscription: DailyReportSubscription | null;
  subscriptionLoading: boolean;
}) {
  const report = useMemo(() => (agentReport ? buildDailyRiskReport(range, agentReport) : null), [agentReport, range]);
  const sourceLabel = report?.source === "llm" ? "LangGraph Agent 生成" : report ? "LangGraph 规则兜底" : loading ? "Agent 生成中" : fetching ? "读取已保存日报" : "等待生成";
  const busy = loading || fetching;
  const subscriptionEnabled = Boolean(subscription?.enabled);

  return (
    <section className="space-y-5">
      {error && <Notice tone="amber" text={error} />}
      <div className="risk-card rounded-lg p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-3 py-1 text-xs font-bold ${riskLevelStyle(report?.alertLevel || "低风险")}`}>
                {report?.alertLevel || "未生成"}
              </span>
              <span className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">
                {range === "24h" ? "近1天" : "近7天"}资产日报
              </span>
              <span className="rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
                {sourceLabel}
              </span>
            </div>
            <h1 className="mt-4 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">
              {report?.headline || "生成你的今日资产日报"}
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
              {report?.summary || "点击按钮后，系统会调用 LangGraph Agent，自动聚合今日新闻中与你已添加资产相关的风险信号，并按资产生成 BTC、ETH 等分项分析。"}
            </p>
            <p className="mt-3 text-xs font-semibold text-slate-400">
              {report
                ? `生成日期：${report.createdAt || report.generationDate || "--"} · 数据基准：${report.generatedAt} · 关注资产 ${report.userAssetsCount} 个 · 命中资产 ${report.affectedAssets.length} 个 · 新闻样本 ${report.newsCount} 条`
                : "只展示你在“我的风险资产”中添加的资产，不会混入全市场排行榜结果。"}
            </p>
            {report && (report.impactSummary || report.focusPoints.length > 0) && (
              <div className="mt-4 rounded-lg border border-blue-100 bg-slate-50 p-3">
                {report.impactSummary && (
                  <p className="text-sm font-semibold leading-6 text-slate-700">{report.impactSummary}</p>
                )}
                {report.focusPoints.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {report.focusPoints.map((item) => (
                      <span key={item} className="rounded-md bg-white px-2.5 py-1 text-xs font-bold text-blue-700 shadow-sm">
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => onToggleSubscription(!subscriptionEnabled)}
              disabled={subscriptionLoading}
              className={`inline-flex h-10 items-center gap-2 rounded-lg border px-3 text-sm font-bold transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${
                subscriptionEnabled
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              <span className={`h-2.5 w-2.5 rounded-full ${subscriptionEnabled ? "bg-emerald-500" : "bg-slate-300"}`} />
              {subscriptionLoading ? "更新订阅" : subscriptionEnabled ? "已订阅 08:00 日报" : "订阅 08:00 日报"}
            </button>
            <RangeSegmentedControl range={range} onChangeRange={onChangeRange} />
            <button
              type="button"
              onClick={onGenerate}
              disabled={busy}
              className="inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
            >
              <span className={loading ? "animate-spin" : ""}>{loading ? <RefreshIcon /> : <BotIcon />}</span>
              生成今日资产日报
            </button>
          </div>
        </div>

        {report && (
          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <DailyMetricCard label="个人风险分" value={String(report.personalScore)} tone="blue" icon={<TrendIcon />} />
            <DailyMetricCard label="相关高风险事件" value={String(report.personalHighCount)} tone="red" icon={<AlertIcon />} />
            <DailyMetricCard label="资产分项报告" value={String(report.assetReports.length)} tone="purple" icon={<FileIcon />} />
            <DailyMetricCard label="关注/持仓资产" value={`${report.userAssetsCount}/${report.holdingAssetsCount}`} tone="green" icon={<CoinIcon />} />
          </div>
        )}
      </div>

      {!report && (
        <section className="risk-card rounded-lg p-6">
          {busy ? (
            <AgentProgress
              activeStage="report_generation"
              icon={<BotIcon />}
              title={loading ? "Agent 正在生成资产日报" : "正在读取已保存日报"}
              steps={loading ? ["读取用户资产", "匹配今日新闻", "聚合分资产风险", "保存日报"] : ["定位用户日报库", "读取最近生成记录", "恢复页面展示"]}
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,0.62fr)_minmax(280px,0.38fr)]">
              <div>
                <PanelTitle icon={<BotIcon />} title="按用户资产生成" />
                <p className="mt-3 text-sm leading-7 text-slate-600">
                  日报会先读取你的关注/持仓资产，再从已有新闻风险数据中筛选直接相关事件，最后由 Agent 生成聚合分析。没有添加到资产库的币种不会出现在这里。
                </p>
              </div>
              <div className="rounded-lg border border-dashed border-blue-200 bg-blue-50/60 p-4">
                <p className="text-sm font-bold text-slate-800">生成后将看到</p>
                <div className="mt-3 space-y-2 text-sm font-semibold text-slate-600">
                  <p>每个已添加资产的独立风险结论</p>
                  <p>命中新闻的聚合风险驱动</p>
                  <p>接下来 24 小时监控项与处置清单</p>
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {report && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,0.58fr)_minmax(320px,0.42fr)]">
          <section className="risk-card rounded-lg p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <PanelTitle icon={<FileIcon />} title="资产分项报告" />
              <span className="text-xs font-semibold text-slate-500">只包含你已添加的关注/持仓资产</span>
            </div>
            <div className="mt-4 space-y-4">
              {report.assetReports.length ? report.assetReports.map((asset) => (
                <DailyAssetReportCard key={asset.assetSymbol} asset={asset} />
              )) : (
                <div className="rounded-lg border border-dashed border-blue-200 bg-blue-50/60 p-6 text-center text-sm font-semibold text-slate-500">
                  {report.userAssetsCount === 0 ? "你还没有添加关注资产。请先到“我的风险资产”添加币种后再生成日报。" : "本期未生成资产分项报告"}
                </div>
              )}
            </div>
          </section>

          <aside className="space-y-5">
            <section className="risk-card rounded-lg p-5">
              <PanelTitle icon={<ChartIcon />} title="跨资产聚合主题" />
              <div className="mt-4 space-y-3">
                {report.riskThemes.length ? report.riskThemes.map((theme) => (
                  <div key={theme.themeId} className="rounded-lg border border-blue-100 bg-slate-50 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-bold leading-5 text-slate-800">{theme.title}</p>
                        <p className="mt-1 text-xs font-semibold leading-5 text-slate-500">{theme.summary}</p>
                      </div>
                      <p className={`shrink-0 text-lg font-bold ${riskScoreTextStyle(theme.maxPersonalScore, theme.riskLevel)}`}>{theme.maxPersonalScore}</p>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className="rounded-md bg-white px-2 py-1 text-xs font-bold text-blue-700">{theme.riskType}</span>
                      <span className="rounded-md bg-white px-2 py-1 text-xs font-bold text-slate-500">{theme.eventCount} 个聚合信号</span>
                    </div>
                  </div>
                )) : (
                  <p className="rounded-lg border border-dashed border-blue-100 bg-slate-50 px-3 py-6 text-center text-sm font-semibold text-slate-500">暂无跨资产聚合主题</p>
                )}
              </div>
            </section>

            <section className="risk-card rounded-lg p-5">
              <PanelTitle icon={<AlertIcon />} title="风险类型热区" />
              <div className="mt-4 space-y-3">
                {report.riskTypes.length ? report.riskTypes.map((item) => (
                  <div key={item.name} className="rounded-lg border border-blue-100 bg-slate-50 p-3">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="font-bold text-slate-800">{item.name}</span>
                      <span className="font-bold text-blue-700">{item.count} 条</span>
                    </div>
                    <div className="mt-2 h-2 rounded-full bg-white">
                      <div className="h-2 rounded-full bg-blue-600" style={{ width: `${item.weight}%` }} />
                    </div>
                    <p className="mt-2 text-xs font-semibold text-slate-500">最高风险分 {item.maxScore} · 高风险 {item.highCount} 条</p>
                  </div>
                )) : (
                  <p className="rounded-lg border border-dashed border-blue-100 bg-slate-50 px-3 py-6 text-center text-sm font-semibold text-slate-500">暂无风险类型数据</p>
                )}
              </div>
            </section>

            <section className="risk-card rounded-lg p-5">
              <PanelTitle icon={<CheckIcon />} title="用户处置清单" />
              <div className="mt-4 space-y-2">
                {report.actions.map((action) => (
                  <div key={action} className="flex gap-3 rounded-lg border border-emerald-100 bg-emerald-50/70 px-3 py-2 text-sm font-semibold leading-6 text-slate-700">
                    <span className="mt-0.5 text-emerald-600"><CheckIcon /></span>
                    <span>{action}</span>
                  </div>
                ))}
              </div>
            </section>
          </aside>
        </div>
      )}
    </section>
  );
}

function DailyAssetReportCard({ asset }: { asset: DailyAssetReport }) {
  const hasEvidence = asset.evidenceSummary.length > 0;
  const holdingLabel = asset.isHolding ? "持仓" : "关注";
  const priceTone = (asset.priceChange24h || 0) >= 0 ? "text-emerald-600" : "text-rose-600";

  return (
    <article className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <CoinMark symbol={asset.assetName || asset.assetSymbol} />
            <div>
              <h2 className="text-base font-bold leading-6 text-slate-950">{asset.assetName || asset.assetSymbol}</h2>
              <p className="text-xs font-semibold text-slate-500">{asset.assetSymbol} · {asset.exposureLabel || holdingLabel}</p>
            </div>
            <span className="rounded-md bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">{holdingLabel}</span>
            <span className="rounded-md bg-slate-50 px-2 py-1 text-xs font-bold text-slate-500">命中 {asset.sourceEventCount} 个聚合信号</span>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-600">{asset.summary}</p>
          {asset.riskTypes.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {asset.riskTypes.slice(0, 5).map((item) => (
                <span key={item} className="rounded-md bg-amber-50 px-2 py-1 text-xs font-bold text-amber-700">{item}</span>
              ))}
            </div>
          )}
        </div>
        <div className="min-w-[112px] text-right">
          <p className={`text-3xl font-bold ${riskScoreTextStyle(asset.personalRiskScore, asset.riskLevel)}`}>{asset.personalRiskScore}</p>
          <p className="mb-1 text-xs font-semibold text-slate-400">资产风险分</p>
          <RiskBadge level={asset.riskLevel} />
          {asset.alertThreshold !== undefined && (
            <p className="mt-2 text-xs font-semibold text-slate-400">阈值 {asset.alertThreshold}</p>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs font-bold text-slate-500">风险驱动</p>
          <div className="mt-2 space-y-2">
            {asset.keyDrivers.slice(0, 4).map((item, index) => (
              <p key={`${item}-${index}`} className="text-xs font-semibold leading-5 text-slate-600">{item}</p>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs font-bold text-slate-500">证据摘要</p>
          <div className="mt-2 space-y-2">
            {hasEvidence ? asset.evidenceSummary.slice(0, 4).map((item, index) => (
              <p key={`${item}-${index}`} className="text-xs font-semibold leading-5 text-slate-600">{item}</p>
            )) : (
              <p className="text-xs font-semibold leading-5 text-slate-400">今日暂无直接命中证据，保持基础监控。</p>
            )}
          </div>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
          <p className="text-xs font-bold text-slate-500">资产状态</p>
          <div className="mt-2 space-y-1 text-xs font-semibold leading-5 text-slate-600">
            <p>市值：{asset.marketValue ? formatCurrency(asset.marketValue) : "--"}</p>
            <p className={priceTone}>24h：{asset.priceChange24h !== undefined ? formatVaultPercent(asset.priceChange24h) : "--"}</p>
            <p>暴露：{asset.exposureMode || "bucket"} / {asset.exposureBucket || "none"}</p>
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3">
          <p className="text-xs font-bold text-blue-700">24 小时监控项</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {asset.monitoringItems.slice(0, 5).map((item) => (
              <span key={item} className="rounded-md bg-white px-2 py-1 text-xs font-bold text-blue-700">{item}</span>
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/70 p-3">
          <p className="text-xs font-bold text-emerald-700">处置建议</p>
          <div className="mt-2 space-y-2">
            {asset.actions.slice(0, 4).map((item, index) => (
              <div key={`${item}-${index}`} className="flex gap-2 text-xs font-semibold leading-5 text-slate-700">
                <span className="mt-0.5 text-emerald-600"><CheckIcon /></span>
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </article>
  );
}

function CoinRankingPanel({
  filter,
  items,
  onChangeFilter,
  onChangeRange,
  onChangeSort,
  range,
  sort,
  total,
}: {
  filter: CoinFilter;
  items: CoinRankingItem[];
  onChangeFilter: (filter: CoinFilter) => void;
  onChangeRange: (range: RankingRange) => void;
  onChangeSort: (sort: CoinSort) => void;
  range: RankingRange;
  sort: CoinSort;
  total: number;
}) {
  const renderedCount = Math.min(items.length, maxRankingTableRows);
  const filters: Array<[CoinFilter, string]> = [
    ["all", "全部币种"],
    ["top10", "Top10 风险币种"],
    ["high", "高风险"],
    ["medium", "中风险"],
    ["low", "低风险"],
  ];
  const sortOptions: Array<[CoinSort, string]> = [
    ["score_desc", "风险分：高 → 低"],
    ["score_asc", "风险分：低 → 高"],
    ["news_desc", "相关新闻：多 → 少"],
    ["news_asc", "相关新闻：少 → 多"],
  ];

  return (
    <section className="risk-card rounded-lg">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-blue-100 px-5 py-4">
        <PanelTitle icon={<CoinIcon />} title="币种风险排行榜" />
        <div className="flex flex-wrap items-center gap-2">
          <RangeSegmentedControl range={range} onChangeRange={onChangeRange} />
          <label className="text-xs font-bold text-slate-500" htmlFor="coin-sort">排序</label>
          <select
            id="coin-sort"
            value={sort}
            onChange={(event) => onChangeSort(event.target.value as CoinSort)}
            className="h-10 rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-700 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-blue-300"
          >
            {sortOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="p-5">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div className="risk-scroll flex min-w-0 flex-1 gap-1 overflow-x-auto border-b border-blue-100 pb-0">
            {filters.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => onChangeFilter(value)}
                className={`relative h-10 shrink-0 px-3 text-sm font-bold transition-colors duration-200 ${
                  filter === value
                    ? "text-blue-700"
                    : "text-slate-500 hover:text-blue-700"
                }`}
                aria-current={filter === value ? "page" : undefined}
              >
                {label}
                {filter === value && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-blue-600" />}
              </button>
            ))}
          </div>
          <p className="shrink-0 text-xs font-semibold text-slate-500">
            基于相关新闻风险分、均值和事件数量聚合
          </p>
        </div>

        <div className="risk-scroll max-h-[640px] overflow-auto rounded-lg border border-blue-100">
          <CoinTable items={items} />
        </div>
        <TableFooter text={`当前显示 ${renderedCount} 个 / 筛选后 ${items.length} 个 / 全部 ${total} 个币种`} />
      </div>
    </section>
  );
}

function NewsRankingPanel({
  favoriteActionLoadingId,
  favoriteNewsIds,
  filter,
  items,
  onAnalyzeNews,
  onChangeFilter,
  onChangeRange,
  onChangeSort,
  onToggleFavorite,
  range,
  sort,
  total,
}: {
  favoriteActionLoadingId: string;
  favoriteNewsIds: Set<string>;
  filter: NewsFilter;
  items: NewsRankingItem[];
  onAnalyzeNews: (item: NewsRankingItem) => void;
  onChangeFilter: (filter: NewsFilter) => void;
  onChangeRange: (range: RankingRange) => void;
  onChangeSort: (sort: NewsSort) => void;
  onToggleFavorite: (item: NewsRankingItem) => void;
  range: RankingRange;
  sort: NewsSort;
  total: number;
}) {
  const [categoryFilter, setCategoryFilter] = useState("all");
  const filters: Array<[NewsFilter, string]> = [
    ["all", "全部新闻"],
    ["top10", "Top10 风险新闻"],
    ["high", "高风险"],
    ["medium", "中风险"],
    ["low", "低风险"],
    ["red", "红色预警"],
  ];
  const sortOptions: Array<[NewsSort, string]> = [
    ["time_desc", "发布时间：晚 → 早"],
    ["time_asc", "发布时间：早 → 晚"],
    ["score_desc", "风险分：高 → 低"],
    ["score_asc", "风险分：低 → 高"],
  ];
  const categoryOptions = useMemo(() => getNewsCategoryOptions(items), [items]);
  const panelItems = useMemo(() => {
    return items.filter((item) => {
      const categoryMatched = categoryFilter === "all" || normalizeRiskType(item.risk_type) === categoryFilter;
      return categoryMatched;
    });
  }, [categoryFilter, items]);
  const maxRows = panelItems.length;
  const renderedCount = maxRows;

  return (
    <section className="risk-card rounded-lg">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-blue-100 px-5 py-4">
        <PanelTitle icon={<ChartIcon />} title="新闻风险排行榜" />
        <div className="flex flex-wrap items-center gap-2">
          <RangeSegmentedControl range={range} onChangeRange={onChangeRange} />
          <label className="text-xs font-bold text-slate-500" htmlFor="news-sort">排序</label>
          <select
            id="news-sort"
            value={sort}
            onChange={(event) => onChangeSort(event.target.value as NewsSort)}
            className="h-10 rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-700 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-blue-300"
          >
            {sortOptions.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <label className="text-xs font-bold text-slate-500" htmlFor="news-category">类别</label>
          <select
            id="news-category"
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
            className="h-10 rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-700 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-blue-300"
          >
            <option value="all">全部类别</option>
            {categoryOptions.map((category) => (
              <option key={category} value={category}>{category}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="p-5">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div className="risk-scroll flex min-w-0 flex-1 gap-1 overflow-x-auto border-b border-blue-100 pb-0">
            {filters.map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => onChangeFilter(value)}
                className={`relative h-10 shrink-0 px-3 text-sm font-bold transition-colors duration-200 ${
                  filter === value
                    ? "text-blue-700"
                    : "text-slate-500 hover:text-blue-700"
                }`}
                aria-current={filter === value ? "page" : undefined}
              >
                {label}
                {filter === value && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-blue-600" />}
              </button>
            ))}
          </div>
          <p className="shrink-0 text-xs font-semibold text-slate-500">
            默认按风险分降序，优先呈现高风险事件
          </p>
        </div>

        <div className="risk-scroll max-h-[640px] overflow-auto rounded-lg border border-blue-100">
          <NewsTable
            favoriteActionLoadingId={favoriteActionLoadingId}
            favoriteNewsIds={favoriteNewsIds}
            items={panelItems}
            maxRows={maxRows}
            onAnalyzeNews={onAnalyzeNews}
            onToggleFavorite={onToggleFavorite}
          />
        </div>
        <TableFooter text={`当前显示 ${renderedCount} 条 / 筛选后 ${panelItems.length} 条 / 全部 ${total} 条`} />
      </div>
    </section>
  );
}

function ReportsView({
  collapsed,
  favoriteActionLoadingId,
  favoriteReportIds,
  onDeleteAllRecords,
  onDeleteRecord,
  onChangeView,
  onChangeDisposition,
  onReanalyze,
  onSelectRecord,
  onToggleFavorite,
  onToggleCollapsed,
  records,
  selectedRecord,
}: {
  collapsed: boolean;
  favoriteActionLoadingId: string;
  favoriteReportIds: Set<string>;
  onDeleteAllRecords: () => void;
  onDeleteRecord: (id: string) => void;
  onChangeView: (view: ActiveView) => void;
  onChangeDisposition: (recordId: string, disposition: AnalysisDisposition, note?: string) => void;
  onReanalyze: (input: string) => void;
  onSelectRecord: (id: string) => void;
  onToggleFavorite: (record: AnalysisRecord) => void;
  onToggleCollapsed: () => void;
  records: AnalysisRecord[];
  selectedRecord: AnalysisRecord | null;
}) {
  return (
    <section className={`risk-card grid min-h-[calc(100vh-168px)] rounded-lg ${collapsed ? "lg:grid-cols-[68px_minmax(0,1fr)]" : "lg:grid-cols-[280px_minmax(0,1fr)]"}`}>
      <aside className="border-b border-blue-100 bg-slate-50/80 lg:border-b-0 lg:border-r">
        <div className={`flex items-center gap-2 border-b border-blue-100 p-4 ${collapsed ? "justify-center" : ""}`}>
          {!collapsed && (
            <button
              type="button"
              onClick={() => onChangeView("chat")}
              className="flex h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700"
              aria-label="新建分析"
            >
              <PlusIcon />
              <span>新建分析</span>
            </button>
          )}
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-blue-100 bg-white text-slate-500 transition-colors duration-200 hover:bg-blue-50"
            aria-label="切换历史记录"
          >
            {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
          </button>
        </div>

        {!collapsed && (
          <>
            <div className="border-b border-blue-100 p-3">
              <button
                type="button"
                onClick={onDeleteAllRecords}
                disabled={!records.length}
                className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-rose-200 bg-rose-50 text-sm font-bold text-rose-700 transition-colors duration-200 hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <TrashIcon />
                删除所有报告
              </button>
            </div>
            <div className="risk-scroll max-h-64 space-y-2 overflow-y-auto p-3 lg:max-h-[calc(100vh-305px)]">
              {records.length ? (
                records.map((record) => {
                  const selected = record.id === selectedRecord?.id;
                  return (
                    <button
                      key={record.id}
                      type="button"
                      onClick={() => onSelectRecord(record.id)}
                      className={`relative w-full rounded-lg p-3 text-left transition-colors duration-200 ${
                        selected ? "bg-blue-50 shadow-sm" : "bg-white hover:bg-slate-100"
                      }`}
                    >
                      {selected && <span className="absolute left-0 top-3 h-12 w-1 rounded-r-full bg-blue-600" />}
                      <div className="pl-2">
                        <div className="flex items-start justify-between gap-2">
                          <p className="min-w-0 truncate text-sm font-bold text-slate-900">{record.title}</p>
                          <div className="flex shrink-0 items-center gap-1">
                            {favoriteReportIds.has(record.id) && <StarIcon filled />}
                            <DispositionBadge disposition={record.disposition || "pending"} />
                            <RiskBadge level={record.report.risk_level} />
                          </div>
                        </div>
                        <p className="mt-2 text-xs text-slate-500">{record.createdAt}</p>
                      </div>
                    </button>
                  );
                })
              ) : (
                <div className="rounded-lg border border-dashed border-blue-200 bg-white p-4 text-center text-sm font-semibold text-slate-500">
                  未添加报告
                </div>
              )}
            </div>
          </>
        )}
      </aside>

      {selectedRecord ? (
        <ReportDocument
          favoriteLoading={favoriteActionLoadingId === selectedRecord.id}
          isFavorite={favoriteReportIds.has(selectedRecord.id)}
          onDeleteRecord={onDeleteRecord}
          onChangeDisposition={onChangeDisposition}
          onReanalyze={onReanalyze}
          onToggleFavorite={onToggleFavorite}
          record={selectedRecord}
        />
      ) : (
        <EmptyReportsView onChangeView={onChangeView} />
      )}
    </section>
  );
}

function EmptyReportsView({ onChangeView }: { onChangeView: (view: ActiveView) => void }) {
  return (
    <article className="flex min-h-[420px] min-w-0 items-center justify-center bg-white p-4 sm:p-6 lg:min-h-[calc(100vh-170px)]">
      <div className="max-w-md rounded-lg border border-dashed border-blue-200 bg-blue-50/70 p-6 text-center sm:p-8">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-white text-blue-600 shadow-sm">
          <FileIcon />
        </div>
        <h2 className="mt-4 text-xl font-bold text-slate-950">未添加报告</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          当前没有可查看的分析报告。完成一次事件风险分析后，报告会出现在这里。
        </p>
        <button
          type="button"
          onClick={() => onChangeView("chat")}
          className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700"
        >
          <PlusIcon />
          新建分析
        </button>
      </div>
    </article>
  );
}

function MyView({
  favoriteNews,
  favoriteReports,
  onChangeView,
  onLoginClick,
  selectedTab,
  user,
}: {
  favoriteNews: FavoriteItem[];
  favoriteReports: FavoriteItem[];
  onChangeView: (view: ActiveView) => void;
  onLoginClick: () => void;
  selectedTab: MyVaultTab;
  user: AuthUser | null;
}) {
  const [activeTab, setActiveTab] = useState<MyVaultTab>(selectedTab);
  const [watchlist, setWatchlist] = useState<PortfolioWatchlistItem[]>([]);
  const [coinLibrary, setCoinLibrary] = useState<CoinLibraryItem[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(true);
  const [loadingCoinLibrary, setLoadingCoinLibrary] = useState(true);
  const [assetForm, setAssetForm] = useState<UserAssetFormState>(defaultUserAssetForm);
  const [assetSaving, setAssetSaving] = useState(false);
  const [assetActionError, setAssetActionError] = useState("");
  const [assetActionMessage, setAssetActionMessage] = useState("");
  const [alertDrafts, setAlertDrafts] = useState<Record<string, string>>({});
  const [alertSavingSymbol, setAlertSavingSymbol] = useState("");
  const [alertActionError, setAlertActionError] = useState("");
  const [alertActionMessage, setAlertActionMessage] = useState("");
  const highRiskAssets = watchlist.filter((item) => item.risk_score >= 80 || ["high", "critical"].includes(item.risk_level));
  const pendingAlerts = watchlist.filter((item) => item.risk_score >= item.alert_threshold || ["high", "critical"].includes(item.risk_level));
  const recentReports = favoriteReports.slice(0, 4);
  const recentNews = favoriteNews.slice(0, 4);
  const latestAssetUpdated = watchlist.map((item) => item.updated_at).filter(Boolean).sort().pop();
  const lastUpdated = latestAssetUpdated || favoriteNews[0]?.created_at || favoriteReports[0]?.created_at || "--";
  const selectedSymbols = new Set(watchlist.map((item) => item.symbol));
  const availableCoins = coinLibrary.filter((coin) => !selectedSymbols.has(coin.symbol) || coin.symbol === assetForm.symbol);
  const tabs: Array<[MyVaultTab, string]> = [
    ["overview", "总览"],
    ["assets", "关注资产"],
    ["news", "收藏新闻"],
    ["reports", "收藏报告"],
    ["alerts", "预警规则"],
    ["reviews", "风险复盘"],
  ];

  function changeTab(tab: MyVaultTab) {
    setActiveTab(tab);
  }

  useEffect(() => {
    let ignore = false;
    async function loadWatchlist() {
      setLoadingAssets(true);
      setLoadingCoinLibrary(true);
      try {
        const [items, coins] = await Promise.all([
          fetchUserAssets(),
          fetchCoinLibrary(undefined, 200),
        ]);
        if (!ignore) {
          setWatchlist(items);
          setCoinLibrary(coins);
        }
      } catch (error) {
        console.error(error);
        if (!ignore) {
          setWatchlist([]);
          setCoinLibrary([]);
        }
      } finally {
        if (!ignore) {
          setLoadingAssets(false);
          setLoadingCoinLibrary(false);
        }
      }
    }
    void loadWatchlist();
    return () => {
      ignore = true;
    };
  }, [user?.id]);

  async function handleAddUserAsset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = assetForm.symbol;
    if (!symbol) {
      setAssetActionError("请选择币种");
      return;
    }
    setAssetSaving(true);
    setAssetActionError("");
    setAssetActionMessage("");
    try {
      await createUserAsset({
        symbol,
        is_watched: true,
        is_holding: assetForm.isHolding,
        exposure_mode: "bucket",
        exposure_bucket: assetForm.isHolding ? "medium" : "none",
        alert_threshold: parseVaultAlertThreshold(assetForm.alertThreshold),
      });
      const items = await fetchUserAssets();
      setWatchlist(items);
      setAssetForm(defaultUserAssetForm);
      const coinName = coinLibrary.find((coin) => coin.symbol === symbol)?.name || symbol;
      setAssetActionMessage(`${coinName} 已加入关注资产库，全站风险功能会使用同一份数据。`);
      window.dispatchEvent(new CustomEvent(userAssetsUpdatedEventName, { detail: { symbol } }));
    } catch (error) {
      console.error(error);
      setAssetActionError("添加关注资产失败，请检查代码后重试。");
    } finally {
      setAssetSaving(false);
    }
  }

  async function handleSaveAlertThreshold(symbol: string) {
    if (!symbol || alertSavingSymbol) return;
    const item = watchlist.find((entry) => entry.symbol === symbol);
    const threshold = parseVaultAlertThreshold(alertDrafts[symbol] ?? String(item?.alert_threshold ?? 70));
    setAlertSavingSymbol(symbol);
    setAlertActionError("");
    setAlertActionMessage("");
    try {
      await updateUserAsset(symbol, { alert_threshold: threshold });
      const items = await fetchUserAssets();
      setWatchlist(items);
      setAlertDrafts((drafts) => ({ ...drafts, [symbol]: String(threshold) }));
      setAlertActionMessage(`${symbol} 预警线已更新为 ${threshold}`);
      window.dispatchEvent(new CustomEvent(userAssetsUpdatedEventName, { detail: { symbol } }));
    } catch (error) {
      console.error(error);
      setAlertActionError("预警线保存失败，请稍后重试。");
    } finally {
      setAlertSavingSymbol("");
    }
  }

  if (selectedTab === "assets") {
    return (
      <section>
        <VaultPanel title="我的关注资产">
          <VaultAssetQuickAdd
            coinOptions={availableCoins}
            error={assetActionError}
            form={assetForm}
            loadingCoins={loadingCoinLibrary}
            message={assetActionMessage}
            onChange={setAssetForm}
            onSubmit={handleAddUserAsset}
            saving={assetSaving}
          />
          {!user && (
            <button
              type="button"
              onClick={onLoginClick}
              className="mb-3 inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white transition-colors duration-200 hover:bg-blue-700"
            >
              <UserIcon />
              登录后同步
            </button>
          )}
          <VaultAssetTable items={watchlist} loading={loadingAssets} />
        </VaultPanel>
      </section>
    );
  }

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-blue-100 bg-white p-5 shadow-sm shadow-blue-100/60 sm:p-6" data-onboarding-id="risk-vault">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-blue-600">My Risk Vault</p>
            <h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">我的风控档案库</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              沉淀全站共享的关注资产库、收藏新闻、分析报告、预警规则和复盘记录；账户资料继续放在系统设置里。
            </p>
          </div>
          <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3 text-right">
            <p className="text-xs font-bold text-blue-600">{user ? "当前用户" : "访客模式"}</p>
            <p className="mt-1 max-w-[220px] truncate text-sm font-bold text-slate-950">{user?.display_name || user?.username || "未登录"}</p>
            <p className="mt-1 text-xs font-semibold text-slate-500">最近更新：{lastUpdated}</p>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <VaultStatusCard label="关注资产" value={loadingAssets ? "--" : String(watchlist.length)} helper="用户资产库" tone="blue" />
          <VaultStatusCard label="高风险资产" value={loadingAssets ? "--" : String(highRiskAssets.length)} helper="风险分 >= 80" tone="red" />
          <VaultStatusCard label="收藏新闻" value={String(favoriteNews.length)} helper="风险情报收藏" tone="green" />
          <VaultStatusCard label="收藏报告" value={String(favoriteReports.length)} helper="AI 分析档案" tone="purple" />
          <VaultStatusCard label="未处理预警" value={loadingAssets ? "--" : String(pendingAlerts.length)} helper="达到提醒线" tone="orange" />
        </div>

        {!user && (
          <button
            type="button"
            onClick={onLoginClick}
            className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700"
          >
            <UserIcon />
            登录后同步风控档案
          </button>
        )}
      </div>

      <section className="rounded-lg border border-blue-100 bg-white shadow-sm shadow-blue-100/60">
        <div className="risk-scroll flex gap-1 overflow-x-auto border-b border-blue-100 px-4 pt-3">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => changeTab(key)}
              className={`relative h-11 shrink-0 px-3 text-sm font-bold transition-colors duration-200 ${
                activeTab === key ? "text-blue-700" : "text-slate-500 hover:text-blue-700"
              }`}
              aria-pressed={activeTab === key}
            >
              {label}
              {activeTab === key && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-blue-600" />}
            </button>
          ))}
        </div>

        <div className="p-4 sm:p-5">
          {activeTab === "overview" && (
            <div className="grid gap-5 xl:grid-cols-2">
              <VaultMiniList
                actionLabel="去新闻收藏"
                items={recentNews.map((item) => ({
                  href: `/news/${encodeURIComponent(item.item_id)}`,
                  meta: `${formatScoreReasonText(favoriteString(item, "risk_type", "综合风险"))} · ${favoriteString(item, "published_at", item.created_at)}`,
                  score: favoriteNumber(item, "risk_score"),
                  title: item.title,
                }))}
                onAction={() => onChangeView("favoriteNews")}
                title="最近收藏新闻"
              />
              <VaultMiniList
                actionLabel="去报告收藏"
                items={recentReports.map((item) => {
                  const report = favoriteRecord(item, "report");
                  return {
                    href: `/reports?record=${encodeURIComponent(item.item_id)}`,
                    meta: `收藏时间：${item.created_at}`,
                    score: typeof report?.risk_score === "number" ? clampScore(report.risk_score) : 0,
                    title: item.title,
                  };
                })}
                onAction={() => onChangeView("favoriteReports")}
                title="最近保存报告"
              />
            </div>
          )}

          {activeTab === "assets" && (
            <div className="space-y-4">
              <VaultAssetQuickAdd
                error={assetActionError}
                coinOptions={availableCoins}
                form={assetForm}
                loadingCoins={loadingCoinLibrary}
                message={assetActionMessage}
                onChange={setAssetForm}
                onSubmit={handleAddUserAsset}
                saving={assetSaving}
              />
              <VaultAssetTable items={watchlist} loading={loadingAssets} />
            </div>
          )}

          {activeTab === "news" && (
            <VaultMiniList
              actionLabel="进入收藏新闻页"
              items={favoriteNews.map((item) => ({
                href: `/news/${encodeURIComponent(item.item_id)}`,
                meta: `${favoriteStringArray(item, "coins").join(", ") || "--"} · ${formatScoreReasonText(favoriteString(item, "risk_type", "综合风险"))}`,
                score: favoriteNumber(item, "risk_score"),
                title: item.title,
              }))}
              onAction={() => onChangeView("favoriteNews")}
              title="收藏新闻"
            />
          )}

          {activeTab === "reports" && (
            <VaultMiniList
              actionLabel="进入收藏报告页"
              items={favoriteReports.map((item) => {
                const report = favoriteRecord(item, "report");
                return {
                  href: `/reports?record=${encodeURIComponent(item.item_id)}`,
                  meta: `生成/收藏时间：${item.created_at}`,
                  score: typeof report?.risk_score === "number" ? clampScore(report.risk_score) : 0,
                  title: item.title,
                };
              })}
              onAction={() => onChangeView("favoriteReports")}
              title="收藏报告"
            />
          )}

          {activeTab === "alerts" && (
            <VaultAlertRules
              drafts={alertDrafts}
              error={alertActionError}
              items={watchlist}
              loading={loadingAssets}
              message={alertActionMessage}
              onChangeThreshold={(symbol, value) => {
                setAlertActionError("");
                setAlertActionMessage("");
                setAlertDrafts((drafts) => ({ ...drafts, [symbol]: value }));
              }}
              onSaveThreshold={handleSaveAlertThreshold}
              savingSymbol={alertSavingSymbol}
            />
          )}

          {activeTab === "reviews" && (
            <VaultReviewList reports={favoriteReports} watchlist={watchlist} />
          )}
        </div>
      </section>
    </section>
  );
}

function VaultStatusCard({
  helper,
  label,
  tone,
  value,
}: {
  helper: string;
  label: string;
  tone: "blue" | "green" | "orange" | "purple" | "red";
  value: string;
}) {
  const toneClass = {
    blue: "border-blue-100 bg-blue-50 text-blue-700",
    green: "border-emerald-100 bg-emerald-50 text-emerald-700",
    orange: "border-orange-100 bg-orange-50 text-orange-700",
    purple: "border-violet-100 bg-violet-50 text-violet-700",
    red: "border-red-100 bg-red-50 text-red-700",
  }[tone];
  return (
    <article className={`min-h-[104px] rounded-lg border p-4 ${toneClass}`}>
      <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-80">{label}</p>
      <p className="mt-2 text-3xl font-bold text-slate-950">{value}</p>
      <p className="mt-2 text-xs font-semibold text-slate-600">{helper}</p>
    </article>
  );
}

function VaultPanel({
  actionLabel,
  children,
  onAction,
  title,
}: {
  actionLabel?: string;
  children: ReactNode;
  onAction?: () => void;
  title: string;
}) {
  return (
    <section className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm shadow-blue-100/60">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-bold text-slate-950">{title}</h3>
        {actionLabel && (
          <button
            type="button"
            onClick={onAction}
            className="h-8 rounded-lg border border-blue-100 bg-white px-3 text-xs font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50"
          >
            {actionLabel}
          </button>
        )}
      </div>
      {children}
    </section>
  );
}

function VaultAssetQuickAdd({
  coinOptions,
  compact = false,
  error,
  form,
  loadingCoins,
  message,
  onChange,
  onSubmit,
  saving,
}: {
  coinOptions: CoinLibraryItem[];
  compact?: boolean;
  error: string;
  form: UserAssetFormState;
  loadingCoins: boolean;
  message: string;
  onChange: (form: UserAssetFormState) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
}) {
  const selectDisabled = loadingCoins || !coinOptions.length || saving;

  return (
    <form
      onSubmit={onSubmit}
      className={`mb-4 rounded-lg border border-blue-100 bg-blue-50/50 p-3 ${compact ? "" : "sm:p-4"}`}
    >
      <div className="grid gap-3 md:grid-cols-[minmax(160px,1fr)_120px_auto_auto]">
        <label className="min-w-0">
          <span className="text-xs font-bold text-slate-500">选择币种</span>
          <select
            value={form.symbol}
            onChange={(event) => onChange({ ...form, symbol: event.target.value })}
            disabled={selectDisabled}
            className="mt-1 h-10 w-full cursor-pointer rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-slate-950 outline-none transition-colors duration-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          >
            <option value="">{loadingCoins ? "正在加载币种库" : coinOptions.length ? "从币种库选择" : "暂无可添加币种"}</option>
            {coinOptions.map((coin) => (
              <option key={coin.symbol} value={coin.symbol}>
                {coin.name} · {coin.symbol} · {coin.category}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="text-xs font-bold text-slate-500">预警线</span>
          <input
            type="number"
            min={0}
            max={100}
            value={form.alertThreshold}
            onChange={(event) => onChange({ ...form, alertThreshold: event.target.value })}
            className="mt-1 h-10 w-full rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-slate-950 outline-none transition-colors duration-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
        </label>
        <label className="flex h-10 items-center gap-2 self-end rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-slate-600">
          <input
            type="checkbox"
            checked={form.isHolding}
            onChange={(event) => onChange({ ...form, isHolding: event.target.checked })}
            className="h-4 w-4 rounded border-blue-200 text-blue-600"
          />
          持仓
        </label>
        <button
          type="submit"
          disabled={saving || !form.symbol}
          className="inline-flex h-10 cursor-pointer items-center justify-center gap-2 self-end rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
        >
          {saving ? <RefreshIcon /> : <PlusIcon />}
          添加关注资产
        </button>
      </div>
      {(error || message) && (
        <p className={`mt-2 text-xs font-semibold ${error ? "text-red-600" : "text-emerald-700"}`}>
          {error || message}
        </p>
      )}
    </form>
  );
}

function VaultAssetTable({
  compact = false,
  items,
  loading,
}: {
  compact?: boolean;
  items: PortfolioWatchlistItem[];
  loading: boolean;
}) {
  if (loading) return <VaultEmpty text="正在加载关注资产" />;
  if (!items.length) return <VaultEmpty text="暂无关注资产，可在上方添加币种" />;
  return (
    <div className="risk-scroll overflow-x-auto rounded-lg border border-blue-100">
      <table className={`w-full text-left text-sm ${compact ? "min-w-[720px]" : "min-w-[980px]"}`}>
        <thead className="border-b border-blue-100 bg-slate-50 text-xs font-bold text-slate-500">
          <tr>
            <th className="px-3 py-3">资产</th>
            {!compact && <th className="px-3 py-3">当前价格</th>}
            <th className="px-3 py-3 text-center">风险分</th>
            <th className="px-3 py-3 text-center">风险等级</th>
            <th className="px-3 py-3 text-center">今日预警</th>
            <th className="px-3 py-3 text-center">24H</th>
            <th className="px-3 py-3 text-center">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-blue-50">
          {items.map((item) => {
            const alerting = item.risk_score >= item.alert_threshold || ["high", "critical"].includes(item.risk_level);
            return (
              <tr key={item.symbol} className="transition-colors duration-200 hover:bg-blue-50/50">
                <td className="px-3 py-3">
                  <div className="flex items-center gap-2">
                    <CoinMark symbol={item.symbol} />
                    <div>
                      <p className="font-bold text-slate-950">{item.symbol}</p>
                      <p className="text-xs font-semibold text-slate-500">{item.is_holding ? "持仓中" : "关注中"}</p>
                    </div>
                  </div>
                </td>
                {!compact && <td className="px-3 py-3 font-semibold tabular-nums text-slate-700">{formatCurrency(item.current_price)}</td>}
                <td className={`px-3 py-3 text-center font-bold tabular-nums ${riskScoreTextStyle(item.risk_score, item.risk_level)}`}>{clampScore(item.risk_score)}</td>
                <td className="px-3 py-3 text-center"><RiskBadge level={formatPortfolioVaultRiskLevel(item.risk_level)} /></td>
                <td className="px-3 py-3 text-center font-bold text-orange-600">{alerting ? 1 : 0}</td>
                <td className={`px-3 py-3 text-center font-bold ${item.price_change_24h >= 0 ? "text-emerald-600" : "text-red-600"}`}>{formatVaultPercent(item.price_change_24h)}</td>
                <td className="px-3 py-3 text-center">
                  <Link
                    href={`/portfolio?asset=${encodeURIComponent(item.symbol)}`}
                    className="inline-flex h-9 items-center justify-center rounded-lg bg-blue-600 px-3 text-xs font-bold text-white transition-colors duration-200 hover:bg-blue-700"
                  >
                    查看雷达
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function VaultMiniList({
  actionLabel,
  items,
  onAction,
  title,
}: {
  actionLabel: string;
  items: Array<{ href: string; meta: string; score: number; title: string }>;
  onAction: () => void;
  title: string;
}) {
  return (
    <VaultPanel actionLabel={actionLabel} onAction={onAction} title={title}>
      <div className="space-y-2">
        {items.length ? items.slice(0, 8).map((item) => (
          <Link
            className="flex items-center gap-3 rounded-lg border border-blue-100 bg-white px-3 py-3 transition-colors duration-200 hover:bg-blue-50"
            href={item.href}
            key={`${item.href}-${item.title}`}
          >
            <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-sm font-bold ${item.score >= 80 ? "bg-red-50 text-red-600" : item.score >= 50 ? "bg-orange-50 text-orange-600" : "bg-blue-50 text-blue-600"}`}>
              {item.score || "--"}
            </span>
            <span className="min-w-0 flex-1">
              <span className="line-clamp-1 font-bold text-slate-950">{item.title}</span>
              <span className="mt-1 block truncate text-xs font-semibold text-slate-500">{item.meta}</span>
            </span>
            <ChevronRightIcon />
          </Link>
        )) : (
          <VaultEmpty text="暂无档案内容" />
        )}
      </div>
    </VaultPanel>
  );
}

function VaultAlertRules({
  drafts,
  error,
  items,
  loading,
  message,
  onChangeThreshold,
  onSaveThreshold,
  savingSymbol,
}: {
  drafts: Record<string, string>;
  error: string;
  items: PortfolioWatchlistItem[];
  loading: boolean;
  message: string;
  onChangeThreshold: (symbol: string, value: string) => void;
  onSaveThreshold: (symbol: string) => void;
  savingSymbol: string;
}) {
  if (loading) return <VaultEmpty text="正在加载预警规则" />;
  if (!items.length) return <VaultEmpty text="暂无预警规则，添加关注资产后会生成默认风险分提醒线" />;
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <form
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-100 bg-white px-4 py-3"
          key={item.symbol}
          onSubmit={(event) => {
            event.preventDefault();
            onSaveThreshold(item.symbol);
          }}
        >
          <div>
            <p className="font-bold text-slate-950">{item.symbol}</p>
            <p className="mt-1 text-xs font-semibold text-slate-500">当前 AI 风险分 {clampScore(item.risk_score)}，达到设置阈值时提醒</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex h-9 items-center gap-2 rounded-lg border border-blue-100 bg-blue-50/50 px-3 text-xs font-bold text-slate-600">
              预警线
              <input
                className="h-7 w-16 rounded-md border border-blue-100 bg-white px-2 text-sm font-bold text-slate-950 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                max={100}
                min={0}
                onChange={(event) => onChangeThreshold(item.symbol, event.target.value)}
                type="number"
                value={drafts[item.symbol] ?? String(item.alert_threshold ?? 70)}
              />
            </label>
            <span className={`rounded-lg px-2 py-1 text-xs font-bold ${item.risk_score >= item.alert_threshold ? "bg-orange-50 text-orange-700" : "bg-emerald-50 text-emerald-700"}`}>
              {item.risk_score >= item.alert_threshold ? "已触发" : "监控中"}
            </span>
            <button
              className="h-9 rounded-lg border border-blue-100 bg-white px-3 text-xs font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={savingSymbol === item.symbol}
              type="submit"
            >
              {savingSymbol === item.symbol ? "保存中" : "保存"}
            </button>
          </div>
        </form>
      ))}
      {(error || message) && (
        <p className={`text-xs font-semibold ${error ? "text-red-600" : "text-emerald-700"}`}>
          {error || message}
        </p>
      )}
    </div>
  );
}

function VaultReviewList({ reports, watchlist }: { reports: FavoriteItem[]; watchlist: PortfolioWatchlistItem[] }) {
  if (!reports.length) return <VaultEmpty text="暂无风险复盘记录。收藏报告后，这里会展示当时风险分与当前风险分对比。" />;
  return (
    <div className="space-y-3">
      {reports.slice(0, 8).map((favorite) => {
        const report = favoriteRecord(favorite, "report");
        const savedScore = typeof report?.risk_score === "number" ? clampScore(report.risk_score) : 0;
        const symbol = inferAssetSymbolFromFavorite(favorite);
        const currentScore = watchlist.find((item) => symbol && item.symbol.includes(symbol))?.risk_score;
        const diff = typeof currentScore === "number" ? currentScore - savedScore : null;
        return (
          <Link
            className="grid gap-3 rounded-lg border border-blue-100 bg-white p-4 transition-colors duration-200 hover:bg-blue-50 md:grid-cols-[minmax(0,1fr)_160px]"
            href={`/reports?record=${encodeURIComponent(favorite.item_id)}`}
            key={favorite.id}
          >
            <div className="min-w-0">
              <p className="line-clamp-1 font-bold text-slate-950">{favorite.title}</p>
              <p className="mt-1 text-xs font-semibold text-slate-500">保存时风险分 {savedScore} · {favorite.created_at}</p>
            </div>
            <div className="text-sm font-bold text-slate-700">
              当前：{typeof currentScore === "number" ? currentScore : "--"}
              {diff !== null && <span className={diff <= 0 ? "ml-2 text-emerald-600" : "ml-2 text-red-600"}>{diff >= 0 ? "+" : ""}{diff}</span>}
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function VaultEmpty({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-blue-100 bg-blue-50/50 px-4 py-8 text-center text-sm font-semibold text-slate-500">{text}</div>;
}

function parseVaultAlertThreshold(value: string) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 70;
  return Math.max(0, Math.min(100, Math.round(numeric)));
}

function formatPortfolioVaultRiskLevel(level: string) {
  if (level === "critical") return "极高风险";
  if (level === "high") return "高风险";
  if (level === "medium") return "中风险";
  return "低风险";
}

function formatCurrency(value: number) {
  if (!Number.isFinite(value)) return "--";
  return `${formatVaultNumber(value, value >= 100 ? 2 : 6)} USDT`;
}

function formatVaultNumber(value: number, digits = 2) {
  if (!Number.isFinite(value)) return "--";
  return value.toLocaleString("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: value >= 100 ? 2 : 0,
  });
}

function formatVaultPercent(value: number) {
  if (!Number.isFinite(value)) return "--";
  const normalized = Math.abs(value) > 1 ? value / 100 : value;
  return `${normalized >= 0 ? "+" : ""}${(normalized * 100).toFixed(2)}%`;
}

function inferAssetSymbolFromFavorite(favorite: FavoriteItem) {
  const coins = favoriteStringArray(favorite, "coins");
  if (coins[0]) return coins[0].replace(/USDT$/, "");
  const input = favoriteString(favorite, "input", favorite.title);
  const match = input.match(/\b[A-Z]{2,12}USDT\b|\b(BTC|ETH|SOL|BNB|XRP|SUI|TON)\b/);
  return match?.[0]?.replace(/USDT$/, "") || "";
}

function FavoriteNewsView({
  favorites,
  onAnalyzeNewsInput,
  onChangeView,
  onLoginClick,
  user,
}: {
  favorites: FavoriteItem[];
  onAnalyzeNewsInput: (input: string) => void;
  onChangeView: (view: ActiveView) => void;
  onLoginClick: () => void;
  user: AuthUser | null;
}) {
  return (
    <FavoriteVaultShell
      actionLabel="去新闻榜发现风险"
      count={favorites.length}
      emptyText="还没有收藏新闻。你可以在新闻榜星标关键事件，形成自己的风险情报流。"
      eyebrow="News Collection"
      onAction={() => onChangeView("news")}
      onLoginClick={onLoginClick}
      title="收藏新闻"
      user={user}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        {favorites.map((favorite) => {
          const score = favoriteNumber(favorite, "risk_score");
          const level = favoriteString(favorite, "risk_level", "未标记");
          const publishedAt = favoriteString(favorite, "published_at", favorite.created_at);
          const coins = favoriteStringArray(favorite, "coins");
          return (
            <article key={favorite.id} className="group rounded-lg border border-blue-100 bg-white p-4 shadow-sm shadow-blue-100/60 transition-colors duration-200 hover:border-blue-300 hover:bg-blue-50/40">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-xs font-bold uppercase tracking-[0.2em] text-blue-600">Risk News</p>
                  <h3 className="mt-3 line-clamp-2 text-lg font-bold leading-7 text-slate-950">{favorite.title}</h3>
                </div>
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-center text-amber-700">
                  <p className="text-[10px] font-bold uppercase tracking-[0.16em]">Score</p>
                  <p className="text-2xl font-bold">{score}</p>
                </div>
              </div>
              <p className="mt-4 line-clamp-3 text-sm leading-6 text-slate-600">{favoriteString(favorite, "summary", "暂无摘要。")}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <RiskBadge level={level} />
                {coins.slice(0, 4).map((coin) => (
                  <span key={coin} className="rounded-md border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">{coin}</span>
                ))}
              </div>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-blue-50 pt-4">
                <p className="text-xs font-semibold text-slate-500">{publishedAt}</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onAnalyzeNewsInput(buildFavoriteNewsAnalysisInput(favorite))}
                    className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white transition-colors duration-200 hover:bg-blue-700"
                  >
                    <ShieldIcon />
                    深入分析
                  </button>
                  <Link
                    href={`/news/${encodeURIComponent(favorite.item_id)}`}
                    className="inline-flex h-9 items-center gap-2 rounded-lg border border-blue-100 bg-white px-3 text-xs font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50"
                  >
                    查看新闻
                    <ChevronRightIcon />
                  </Link>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </FavoriteVaultShell>
  );
}

function FavoriteReportsView({
  favorites,
  onChangeView,
  onLoginClick,
  user,
}: {
  favorites: FavoriteItem[];
  onChangeView: (view: ActiveView) => void;
  onLoginClick: () => void;
  user: AuthUser | null;
}) {
  return (
    <FavoriteVaultShell
      actionLabel="去分析报告"
      count={favorites.length}
      emptyText="还没有收藏报告。完成事件分析后，在报告详情页收藏高价值研判。"
      eyebrow="Report Collection"
      onAction={() => onChangeView("reports")}
      onLoginClick={onLoginClick}
      title="收藏报告"
      user={user}
    >
      <div className="space-y-4">
        {favorites.map((favorite) => {
          const report = favoriteRecord(favorite, "report");
          const score = typeof report?.risk_score === "number" ? clampScore(report.risk_score) : 0;
          const level = typeof report?.risk_level === "string" ? report.risk_level : "未标记";
          const input = favoriteString(favorite, "input", "暂无原始输入。");
          return (
            <article key={favorite.id} className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm shadow-blue-100/60 transition-colors duration-200 hover:border-blue-300 hover:bg-blue-50/40 sm:p-5">
              <div className="grid gap-4 lg:grid-cols-[120px_minmax(0,1fr)_160px]">
                <div className="rounded-lg border border-violet-100 bg-violet-50 p-4 text-center text-violet-700">
                  <p className="text-xs font-bold uppercase tracking-[0.16em]">Risk</p>
                  <p className="mt-2 text-4xl font-bold">{score}</p>
                  <div className="mt-3 flex justify-center"><RiskBadge level={level} /></div>
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-bold uppercase tracking-[0.2em] text-blue-600">Agent Report</p>
                  <h3 className="mt-3 break-words text-xl font-bold leading-8 text-slate-950">{favorite.title}</h3>
                  <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{formatScoreReasonText(typeof report?.summary === "string" ? report.summary : input)}</p>
                  <p className="mt-3 text-xs font-semibold text-slate-500">收藏时间：{favorite.created_at}</p>
                </div>
                <div className="flex items-end lg:justify-end">
                  <Link
                    href={`/reports?record=${encodeURIComponent(favorite.item_id)}`}
                    className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700 lg:w-auto"
                  >
                    查看报告
                    <ChevronRightIcon />
                  </Link>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </FavoriteVaultShell>
  );
}

function FavoriteVaultShell({
  actionLabel,
  children,
  count,
  emptyText,
  eyebrow,
  onAction,
  onLoginClick,
  title,
  user,
}: {
  actionLabel: string;
  children: ReactNode;
  count: number;
  emptyText: string;
  eyebrow: string;
  onAction: () => void;
  onLoginClick: () => void;
  title: string;
  user: AuthUser | null;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-blue-100 bg-white shadow-xl shadow-blue-100/60">
      <div className="border-b border-blue-100 bg-[linear-gradient(135deg,#f8fbff_0%,#eef6ff_62%,#fff9ed_100%)] p-5 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.22em] text-blue-600">{eyebrow}</p>
            <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-950 sm:text-4xl">{title}</h2>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-600">
              星标沉淀高价值风险材料，形成可复盘、可追踪、可展示的个人风控资产。
            </p>
          </div>
          <div className="rounded-lg border border-blue-100 bg-white/80 px-5 py-4 text-right shadow-sm shadow-blue-100">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">Saved</p>
            <p className="mt-1 text-4xl font-bold text-slate-950">{count}</p>
          </div>
        </div>
      </div>

      <div className="p-5 sm:p-8">
        {!user ? (
          <div className="rounded-lg border border-dashed border-blue-200 bg-blue-50/70 p-6 text-center">
            <p className="text-lg font-bold text-slate-950">登录后查看收藏</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">收藏内容按用户保存到 SQLite，需要先登录才能读取。</p>
            <button type="button" onClick={onLoginClick} className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700">
              <UserIcon />
              登录
            </button>
          </div>
        ) : count ? (
          children
        ) : (
          <div className="rounded-lg border border-dashed border-blue-200 bg-slate-50 p-6 text-center text-blue-600">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-sm"><StarIcon /></div>
            <p className="mt-3 text-lg font-bold text-slate-950">收藏夹还是空的</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">{emptyText}</p>
            <button type="button" onClick={onAction} className="mt-5 inline-flex h-10 items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700">
              {actionLabel}
              <ChevronRightIcon />
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function SettingsView({
  accountDeleteLoading,
  accountExportLoading,
  accountExportMessage,
  auditPruneLoading,
  auditPruneResult,
  auditSummary,
  backupManifest,
  dailySchedulerActionLoading,
  dailySchedulerMessage,
  dailySchedulerStatus,
  onDeleteAccountData,
  onExportAccountData,
  onPruneAuditEvents,
  onPruneExpiredAuthSessions,
  onPruneGuestSimAccounts,
  onPruneInvalidJsonBackups,
  onPruneRuntimeJobs,
  onRunDailySchedulerNow,
  onToggleDailyScheduler,
  onRefreshSystemStatus,
  onUpdateTodayNews,
  rateLimitStatus,
  storageInventory,
  systemTaskEvents,
  systemReadiness,
  systemStatusError,
  systemStatusLoading,
  sessionPruneLoading,
  sessionPruneMessage,
  runtimeJobPruneLoading,
  runtimeJobPruneMessage,
  invalidBackupPruneLoading,
  invalidBackupPruneMessage,
  simPruneLoading,
  simPruneMessage,
  updateError,
  updateJob,
  updateLoading,
  updateResult,
}: {
  accountDeleteLoading: boolean;
  accountExportLoading: boolean;
  accountExportMessage: string;
  auditPruneLoading: boolean;
  auditPruneResult: AuditPruneResult | null;
  auditSummary: AuditSummary | null;
  backupManifest: BackupManifest | null;
  dailySchedulerActionLoading: boolean;
  dailySchedulerMessage: string;
  dailySchedulerStatus: DailySchedulerStatus | null;
  onDeleteAccountData: (currentPassword: string) => void;
  onExportAccountData: () => void;
  onPruneAuditEvents: () => void;
  onPruneExpiredAuthSessions: () => void;
  onPruneGuestSimAccounts: () => void;
  onPruneInvalidJsonBackups: () => void;
  onPruneRuntimeJobs: () => void;
  onRunDailySchedulerNow: () => void;
  onToggleDailyScheduler: (enabled: boolean) => void;
  onRefreshSystemStatus: () => void;
  onUpdateTodayNews: () => void;
  rateLimitStatus: RateLimitStatus | null;
  storageInventory: StorageInventory | null;
  systemTaskEvents: SystemTaskEvent[];
  systemReadiness: SystemReadiness | null;
  systemStatusError: string;
  systemStatusLoading: boolean;
  sessionPruneLoading: boolean;
  sessionPruneMessage: string;
  runtimeJobPruneLoading: boolean;
  runtimeJobPruneMessage: string;
  invalidBackupPruneLoading: boolean;
  invalidBackupPruneMessage: string;
  simPruneLoading: boolean;
  simPruneMessage: string;
  updateError: string;
  updateJob: NewsUpdateJob | null;
  updateLoading: boolean;
  updateResult: NewsUpdateResponse | null;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordChangeLoading, setPasswordChangeLoading] = useState(false);
  const [passwordChangeMessage, setPasswordChangeMessage] = useState("");
  const [passwordChangeError, setPasswordChangeError] = useState("");
  const [authSessions, setAuthSessions] = useState<AuthSessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsMessage, setSessionsMessage] = useState("");
  const [sessionsError, setSessionsError] = useState("");
  const [securityEvents, setSecurityEvents] = useState<AccountSecurityEvent[]>([]);
  const [activeSettingsSectionId, setActiveSettingsSectionId] = useState("settings-automation");
  const [deleteCurrentPassword, setDeleteCurrentPassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const passwordStrength = getPasswordStrength(newPassword, "");
  const canDeleteAccount = Boolean(deleteCurrentPassword) && deleteConfirmation === "DELETE";
  const invalidJsonBackups = storageInventory?.runtime.invalid_json_backups ?? 0;
  const storageIssueCount = (storageInventory?.sqlite_errors.length ?? 0) + invalidJsonBackups;
  const backupInvalidTargetCount = backupManifest?.items.filter((item) => item.kind === "runtime_json_invalid_backup").length ?? 0;

  const loadAuthSessions = useCallback(async () => {
    setSessionsLoading(true);
    setSessionsError("");
    try {
      const [sessions, events] = await Promise.all([
        fetchAuthSessions(),
        fetchAccountSecurityEvents(8),
      ]);
      setAuthSessions(sessions);
      setSecurityEvents(events.items);
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSessionsError("登录后才能查看会话。");
      } else {
        setSessionsError("登录会话读取失败。");
      }
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAuthSessions();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadAuthSessions]);

  async function handlePasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (passwordChangeLoading) return;
    setPasswordChangeMessage("");
    setPasswordChangeError("");
    if (newPassword !== confirmPassword) {
      setPasswordChangeError("两次输入的新密码不一致。");
      return;
    }
    setPasswordChangeLoading(true);
    try {
      const result = await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordChangeMessage(`${result.message} 已撤销其他会话 ${result.sessions_revoked} 个。`);
      await loadAuthSessions();
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setPasswordChangeError("登录后才能修改密码。");
      } else if (error instanceof ApiRequestError && error.detail) {
        setPasswordChangeError(error.detail);
      } else {
        setPasswordChangeError("密码修改失败，请稍后重试。");
      }
    } finally {
      setPasswordChangeLoading(false);
    }
  }

  async function handleRevokeOtherSessions() {
    if (sessionsLoading) return;
    setSessionsLoading(true);
    setSessionsMessage("");
    setSessionsError("");
    try {
      const result = await revokeOtherAuthSessions();
      setSessionsMessage(`${result.message} 已撤销 ${result.sessions_revoked} 个。`);
      const [sessions, events] = await Promise.all([
        fetchAuthSessions(),
        fetchAccountSecurityEvents(8),
      ]);
      setAuthSessions(sessions);
      setSecurityEvents(events.items);
    } catch (error) {
      console.error(error);
      if (error instanceof ApiRequestError && error.status === 401) {
        setSessionsError("登录后才能管理会话。");
      } else if (error instanceof ApiRequestError && error.detail) {
        setSessionsError(error.detail);
      } else {
        setSessionsError("会话撤销失败，请稍后重试。");
      }
    } finally {
      setSessionsLoading(false);
    }
  }

  function handleDeleteAccountSubmit() {
    if (!canDeleteAccount || accountDeleteLoading) return;
    onDeleteAccountData(deleteCurrentPassword);
    setDeleteCurrentPassword("");
    setDeleteConfirmation("");
  }

  const fallbackJob: NewsUpdateJob = updateJob || {
    job_id: "",
    status: updateLoading ? "running" : "queued",
    stage: updateLoading ? "crawler" : "idle",
    message: updateLoading ? "正在启动新闻更新任务" : "等待点击更新新闻",
    crawler: {
      label: "爬虫",
      status: updateLoading ? "running" : "pending",
      current: 0,
      total: 0,
      percent: 0,
      message: updateLoading ? "正在连接新闻源" : "抓取近 7 天 Binance Square 新闻",
    },
    dedupe: {
      label: "去重入库",
      status: "pending",
      current: 0,
      total: 0,
      percent: 0,
      message: "按链接或内容指纹避免重复入库",
    },
    agent: {
      label: "Agent 标注",
      status: "pending",
      current: 0,
      total: 0,
      percent: 0,
      message: "只对未处理新闻增量评分",
    },
    ranking: {
      label: "排行榜",
      status: "pending",
      current: 0,
      total: 0,
      percent: 0,
      message: "刷新近 1 天 / 近 7 天新闻和币种风险榜",
    },
    result: null,
    error: "",
    started_at: "",
    updated_at: "",
    finished_at: "",
  };
  const progressItems = [fallbackJob.crawler, fallbackJob.dedupe, fallbackJob.agent, fallbackJob.ranking];
  const completedStages = progressItems.filter((progress) => progress.status === "success").length;
  const activeStage = progressItems.find((progress) => progress.status === "running")?.label || "待命";
  const hasWarning = Boolean(updateResult?.crawler.crawler_error || progressItems.some((progress) => progress.status === "warning"));
  const hasError = Boolean(updateError || progressItems.some((progress) => progress.status === "error"));
  const readinessStatus = systemReadiness?.status || "unknown";
  const readinessTone = readinessStatus === "ready" ? "emerald" : readinessStatus === "degraded" ? "amber" : readinessStatus === "not_ready" ? "rose" : "slate";
  const auditErrorCount = auditSummary?.by_kind.reduce((total, item) => total + item.error, 0) || 0;
  const auditRunningCount = auditSummary?.by_kind.reduce((total, item) => total + item.running + item.queued, 0) || 0;
  const agentStatusText = hasError ? "异常" : hasWarning ? "降级运行" : "正常";
  const agentStatusStyle = hasError
    ? "border-rose-200 bg-rose-50 text-rose-700"
    : hasWarning
      ? "border-amber-200 bg-amber-50 text-amber-700"
      : "border-emerald-200 bg-emerald-50 text-emerald-700";
  const agentCards = [
    { name: "新闻采集 Agent", detail: "监听新闻更新", status: fallbackJob.crawler.status },
    { name: "信号扫描 Agent", detail: "规则粗筛风险方向", status: fallbackJob.agent.status === "running" ? "running" : hasError ? "error" : "success" },
    { name: "风险类型分支 Agent", detail: "并行审核风险类型证据", status: fallbackJob.agent.status === "running" ? "running" : hasError ? "error" : "success" },
    { name: "影响对象 Agent", detail: "生成影响范围与不确定性", status: fallbackJob.agent.status === "running" ? "running" : hasWarning ? "warning" : "success" },
    { name: "处置建议 Agent", detail: "生成可执行核验与处置动作", status: fallbackJob.agent.status === "running" ? "running" : hasWarning ? "warning" : "success" },
    { name: "决策校准 Agent", detail: "应用 cap / floor 校验", status: fallbackJob.agent.status === "running" ? "running" : hasWarning ? "warning" : "success" },
    { name: "排行榜 Agent", detail: "刷新风险榜单", status: fallbackJob.ranking.status },
    { name: "报告生成 Agent", detail: "生成证据链报告", status: hasError ? "error" : "success" },
  ] satisfies Array<{ name: string; detail: string; status: NewsUpdateProgress["status"] }>;
  const schedulerEnabled = Boolean(dailySchedulerStatus?.enabled);
  const schedulerStatusText = dailySchedulerStatus?.running
    ? "运行中"
    : schedulerEnabled
      ? "已启动"
      : dailySchedulerStatus
        ? "已暂停"
        : "未读取";
  const schedulerTone: "emerald" | "amber" | "rose" | "blue" | "slate" = dailySchedulerStatus?.running ? "blue" : schedulerEnabled ? "emerald" : "amber";
  const schedulerTime = dailySchedulerStatus
    ? `${String(dailySchedulerStatus.schedule_hour).padStart(2, "0")}:${String(dailySchedulerStatus.schedule_minute).padStart(2, "0")}`
    : "08:00";
  const settingsSections = {
    automation: {
      id: "settings-automation",
      title: "任务自动化",
      summary: "每日调度、新闻更新流水线和自动生成日报。",
      icon: <ClockIcon />,
    },
    observability: {
      id: "settings-observability",
      title: "运行观测",
      summary: "系统 Readiness、审计、限流、存储和备份状态。",
      icon: <ChartIcon />,
    },
    accountSecurity: {
      id: "settings-account-security",
      title: "账号安全",
      summary: "密码、登录会话、安全事件和账号数据删除。",
      icon: <ShieldIcon />,
    },
    agentHealth: {
      id: "settings-agent-health",
      title: "Agent 状态",
      summary: "多 Agent 节点健康度和当前任务阶段。",
      icon: <BotIcon />,
    },
  } satisfies Record<string, SettingsSectionMeta>;
  const settingsSectionList = [
    settingsSections.automation,
    settingsSections.observability,
    settingsSections.accountSecurity,
    settingsSections.agentHealth,
  ];
  const activeSettingsSection = settingsSectionList.find((section) => section.id === activeSettingsSectionId) || settingsSections.automation;

  return (
    <section className="risk-card overflow-hidden rounded-lg border border-blue-100 bg-white">
      <div className="border-b border-blue-100 bg-gradient-to-r from-white via-blue-50/70 to-emerald-50/60 px-5 py-5 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <PanelTitle icon={<GearIcon />} title="系统设置" />
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <span className={`inline-flex h-9 items-center gap-2 rounded-lg border px-3 text-sm font-bold ${agentStatusStyle}`}>
                <span className="h-2 w-2 rounded-full bg-current" />
                Agent 状态：{agentStatusText}
              </span>
              <span className="inline-flex h-9 items-center rounded-lg border border-blue-100 bg-blue-50 px-3 text-sm font-bold text-blue-700">
                当前阶段：{activeStage}
              </span>
              <span className="inline-flex h-9 items-center rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm font-bold text-slate-600">
                已完成 {completedStages}/4
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-gradient-to-br from-white via-slate-50 to-blue-50/70 px-5 py-5 sm:px-6">
        {systemStatusError && <Notice tone="amber" text={systemStatusError} />}
        {updateError && <Notice tone="red" text={updateError} />}
        {updateResult && (
          <div className="mb-5 rounded-lg border border-emerald-200 bg-white/80 p-4 text-sm leading-6 text-emerald-900 shadow-sm">
            <p className="font-bold">{updateResult.message}</p>
            <p className="mt-1">
              新抓取 {updateResult.crawler.fetched_count} 条，净新增 {updateResult.crawler.added_count} 条，Agent 本次处理 {updateResult.agent.processed_count} 条。
            </p>
            {updateResult.crawler.crawler_error && (
              <p className="mt-1 text-amber-800">
                新闻更新遇到网络波动，已保留现有数据。
              </p>
            )}
          </div>
        )}

        <div className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)]">
          <SettingsSubSidebar
            activeSectionId={activeSettingsSection.id}
            onSelect={setActiveSettingsSectionId}
            sections={settingsSectionList}
          />

          <div className="min-w-0 space-y-5">
            {activeSettingsSection.id === settingsSections.automation.id && (
            <SettingsSection
              {...settingsSections.automation}
            >
        <div className="rounded-lg border border-emerald-100 bg-white/90 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-600">Daily Scheduler</p>
              <h3 className="mt-1 text-lg font-bold text-slate-950">每日新闻与资产日报定时任务</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                每天 {schedulerTime} 自动更新新闻，并只为已订阅用户生成近 1 天资产日报。
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onToggleDailyScheduler(!schedulerEnabled)}
                disabled={dailySchedulerActionLoading}
                className={`inline-flex h-10 items-center gap-2 rounded-lg px-3 text-sm font-bold text-white transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${schedulerEnabled ? "bg-amber-600 hover:bg-amber-700" : "bg-emerald-700 hover:bg-emerald-800"}`}
              >
                {schedulerEnabled ? <PauseIcon /> : <PlayIcon />}
                {dailySchedulerActionLoading ? "处理中" : schedulerEnabled ? "暂停定时" : "启动定时"}
              </button>
              <button
                type="button"
                onClick={onRunDailySchedulerNow}
                disabled={dailySchedulerActionLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 text-sm font-bold text-emerald-800 transition-colors duration-200 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshIcon />
                立即执行一次
              </button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <SystemMetricCard
              label="Scheduler"
              tone={schedulerTone}
              value={schedulerStatusText}
              detail={dailySchedulerStatus?.thread_alive ? "后台线程运行中" : "后台线程未确认"}
            />
            <SystemMetricCard
              label="Last Run"
              tone={dailySchedulerStatus?.last_status === "error" ? "rose" : dailySchedulerStatus?.last_run_date ? "emerald" : "slate"}
              value={dailySchedulerStatus?.last_run_date || "--"}
              detail={dailySchedulerStatus?.last_message || "等待首次执行"}
            />
            <SystemMetricCard
              label="Generated"
              tone="blue"
              value={String((dailySchedulerStatus?.last_result?.generated_report_count as number | undefined) ?? 0)}
              detail={`订阅用户 ${(dailySchedulerStatus?.last_result?.subscribed_user_count as number | undefined) ?? 0} 个`}
            />
          </div>
          {dailySchedulerMessage && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-800">
              {dailySchedulerMessage}
            </p>
          )}
        </div>

            </SettingsSection>
            )}

            {activeSettingsSection.id === settingsSections.observability.id && (
            <SettingsSection
              {...settingsSections.observability}
            >
        <div className="rounded-lg border border-blue-100 bg-white/90 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Operations</p>
              <h3 className="mt-1 text-lg font-bold text-slate-950">系统运行概览</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={onExportAccountData}
                disabled={accountExportLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 text-sm font-bold text-emerald-800 transition-colors duration-200 hover:bg-emerald-100 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <DownloadIcon />
                {accountExportLoading ? "导出中" : "导出数据"}
              </button>
              <button
                type="button"
                onClick={onPruneAuditEvents}
                disabled={auditPruneLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 text-sm font-bold text-amber-800 transition-colors duration-200 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {auditPruneLoading ? "清理中" : "清理审计"}
              </button>
              <button
                type="button"
                onClick={onPruneGuestSimAccounts}
                disabled={simPruneLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-cyan-200 bg-cyan-50 px-3 text-sm font-bold text-cyan-800 transition-colors duration-200 hover:bg-cyan-100 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {simPruneLoading ? "清理中" : "清理游客模拟"}
              </button>
              <button
                type="button"
                onClick={onPruneExpiredAuthSessions}
                disabled={sessionPruneLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-violet-200 bg-violet-50 px-3 text-sm font-bold text-violet-800 transition-colors duration-200 hover:bg-violet-100 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {sessionPruneLoading ? "清理中" : "清理过期会话"}
              </button>
              <button
                type="button"
                onClick={onPruneRuntimeJobs}
                disabled={runtimeJobPruneLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 text-sm font-bold text-indigo-800 transition-colors duration-200 hover:bg-indigo-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {runtimeJobPruneLoading ? "清理中" : "清理任务状态"}
              </button>
              <button
                type="button"
                onClick={onPruneInvalidJsonBackups}
                disabled={invalidBackupPruneLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-3 text-sm font-bold text-orange-800 transition-colors duration-200 hover:bg-orange-100 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {invalidBackupPruneLoading ? "清理中" : "清理损坏备份"}
              </button>
              <button
                type="button"
                onClick={onRefreshSystemStatus}
                disabled={systemStatusLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshIcon />
                {systemStatusLoading ? "读取中" : "刷新状态"}
              </button>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <SystemMetricCard
              label="Readiness"
              tone={readinessTone}
              value={formatReadinessStatus(readinessStatus)}
              detail={systemReadiness ? `失败检查 ${systemReadiness.summary.failed_checks}/${systemReadiness.summary.total_checks}` : "等待读取"}
            />
            <SystemMetricCard
              label="24h Audit"
              tone={auditErrorCount > 0 ? "rose" : auditRunningCount > 0 ? "blue" : "emerald"}
              value={auditSummary ? `${auditSummary.window_events} 事件` : "--"}
              detail={auditSummary ? `失败 ${auditErrorCount}，运行/排队 ${auditRunningCount}` : "等待读取"}
            />
            <SystemMetricCard
              label="Rate Limit"
              tone={rateLimitStatus?.enabled ? "emerald" : "amber"}
              value={rateLimitStatus ? (rateLimitStatus.enabled ? "已开启" : "已关闭") : "--"}
              detail={rateLimitStatus ? `${rateLimitStatus.rules.length} 条规则，${rateLimitStatus.active_buckets} 个活跃桶` : "等待读取"}
            />
            <SystemMetricCard
              label="Storage"
              tone={storageIssueCount ? "amber" : storageInventory ? "emerald" : "slate"}
              value={storageInventory ? formatBytes(storageInventory.total_size_bytes) : "--"}
              detail={storageInventory ? `模拟账户 ${storageInventory.runtime.sim_accounts}，异常 ${storageIssueCount}，损坏备份 ${invalidJsonBackups}` : "管理员可见"}
            />
            <SystemMetricCard
              label="Backup"
              tone={backupManifest?.warnings.length ? "amber" : backupManifest ? "emerald" : "slate"}
              value={backupManifest ? `${backupManifest.target_count} 项` : "--"}
              detail={backupManifest ? `${formatBytes(backupManifest.total_size_bytes)}，缺失 ${backupManifest.missing_expected_targets.length}，隔离 ${backupInvalidTargetCount}` : "管理员可见"}
            />
            <SystemMetricCard
              label="Uptime"
              tone="slate"
              value={systemReadiness ? formatDuration(systemReadiness.uptime_seconds) : "--"}
              detail={systemReadiness ? `版本 ${systemReadiness.version || "local"}` : "等待读取"}
            />
          </div>

          {storageInventory ? (
            <div className="mt-4 overflow-x-auto rounded-lg border border-slate-100">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-3 py-3">
                <div>
                  <p className="text-sm font-bold text-slate-900">运行时存储盘点</p>
                  <p className="mt-0.5 text-xs font-semibold text-slate-500">生成时间：{formatCompactDateTime(storageInventory.generated_at)}</p>
                </div>
                <span className="rounded-lg border border-blue-100 bg-white px-2.5 py-1 text-xs font-bold text-blue-700">
                  {storageInventory.datastores.length} data stores
                </span>
              </div>
              <table className="min-w-[760px] w-full text-left text-sm">
                <thead className="bg-white text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-3 py-3">数据域</th>
                    <th className="px-3 py-3">状态</th>
                    <th className="px-3 py-3 text-right">规模</th>
                    <th className="px-3 py-3 text-right">大小</th>
                    <th className="px-3 py-3">明细</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {storageInventory.datastores.map((store) => (
                    <tr key={store.name} className="bg-white">
                      <td className="px-3 py-3 font-bold text-slate-800">{formatDatastoreName(store.name)}</td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg border px-2 py-1 text-xs font-bold ${store.error ? "border-amber-200 bg-amber-50 text-amber-800" : store.exists ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                          {store.error ? "读取异常" : store.exists ? "已存在" : "未创建"}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-slate-700">{formatDatastoreScale(store)}</td>
                      <td className="px-3 py-3 text-right font-mono text-slate-700">{formatBytes(store.size_bytes)}</td>
                      <td className="px-3 py-3 text-xs font-semibold text-slate-500">{formatDatastoreDetail(store)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-500">
              管理员登录后可查看运行时存储盘点，包括账号、报告、资产、审计和日报数据规模。
            </p>
          )}

          {backupManifest ? (
            <div className="mt-4 rounded-lg border border-emerald-100 bg-emerald-50/40 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-bold text-slate-900">备份清单</p>
                  <p className="mt-1 text-xs font-semibold text-slate-500">
                    生成时间：{formatCompactDateTime(backupManifest.generated_at)} · 根目录：{backupManifest.root}
                  </p>
                </div>
                <span className="rounded-lg border border-emerald-200 bg-white px-2.5 py-1 text-xs font-bold text-emerald-700">
                  {backupManifest.target_count} targets
                </span>
              </div>
              {backupManifest.warnings.length > 0 && (
                <div className="mt-3 space-y-2">
                  {backupManifest.warnings.map((warning) => (
                    <p key={warning} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
                      {warning}
                    </p>
                  ))}
                </div>
              )}
              <div className="mt-4 overflow-x-auto rounded-lg border border-emerald-100 bg-white">
                <table className="min-w-[760px] w-full text-left text-sm">
                  <thead className="bg-emerald-50 text-xs font-bold uppercase tracking-[0.12em] text-emerald-700">
                    <tr>
                      <th className="px-3 py-3">目标</th>
                      <th className="px-3 py-3">类型</th>
                      <th className="px-3 py-3">状态</th>
                      <th className="px-3 py-3 text-right">大小</th>
                      <th className="px-3 py-3">路径</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-emerald-50">
                    {backupManifest.items.filter((item) => item.backup_required).slice(0, 6).map((item) => (
                      <tr key={`${item.name}:${item.display_path}`}>
                        <td className="px-3 py-3 font-bold text-slate-800">{item.name}</td>
                        <td className="px-3 py-3 text-xs font-bold text-slate-500">{formatBackupKind(item.kind)}</td>
                        <td className="px-3 py-3">
                          <span className={`rounded-lg border px-2 py-1 text-xs font-bold ${item.exists ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                            {item.exists ? "已发现" : "未创建"}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-slate-700">{formatBytes(item.size_bytes)}</td>
                        <td className="px-3 py-3 text-xs font-semibold text-slate-500">{item.display_path}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-emerald-200 bg-emerald-50/40 px-3 py-3 text-sm font-semibold text-emerald-700">
              管理员登录后可查看备份清单，确认 SQLite、日报目录和运行态 JSON 是否纳入持久化备份。
            </p>
          )}

          {auditSummary?.by_kind.length ? (
            <div className="mt-4 overflow-x-auto rounded-lg border border-slate-100">
              <table className="min-w-[760px] w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-3 py-3">类型</th>
                    <th className="px-3 py-3 text-right">总数</th>
                    <th className="px-3 py-3 text-right">成功</th>
                    <th className="px-3 py-3 text-right">失败</th>
                    <th className="px-3 py-3 text-right">错误率</th>
                    <th className="px-3 py-3">最近事件</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {auditSummary.by_kind.map((item) => (
                    <tr key={item.job_kind} className="bg-white">
                      <td className="px-3 py-3 font-bold text-slate-800">{formatJobKind(item.job_kind)}</td>
                      <td className="px-3 py-3 text-right font-mono text-slate-700">{item.total}</td>
                      <td className="px-3 py-3 text-right font-mono text-emerald-700">{item.success}</td>
                      <td className="px-3 py-3 text-right font-mono text-rose-700">{item.error}</td>
                      <td className="px-3 py-3 text-right font-mono text-slate-700">{Math.round(item.error_rate * 100)}%</td>
                      <td className="px-3 py-3 text-xs font-semibold text-slate-500">
                        {item.latest_event ? `${formatAuditStatus(item.latest_event.status)} · ${item.latest_event.message || item.latest_event.stage}` : "暂无"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-4 rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm font-semibold text-slate-500">
              暂无审计事件，运行 Chat 分析、风险助手或新闻更新后会在这里汇总。
            </p>
          )}

          {systemTaskEvents.length ? (
            <div className="mt-4 overflow-x-auto rounded-lg border border-blue-100">
              <table className="min-w-[860px] w-full text-left text-sm">
                <thead className="bg-blue-50 text-xs font-bold uppercase tracking-[0.12em] text-blue-700">
                  <tr>
                    <th className="px-3 py-3">最近事件</th>
                    <th className="px-3 py-3">状态</th>
                    <th className="px-3 py-3">阶段</th>
                    <th className="px-3 py-3">用户</th>
                    <th className="px-3 py-3">计数摘要</th>
                    <th className="px-3 py-3 text-right">时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-blue-50 bg-white">
                  {systemTaskEvents.map((event) => (
                    <tr key={event.id}>
                      <td className="px-3 py-3">
                        <p className="font-bold text-slate-800">{formatJobKind(event.job_kind)}</p>
                        <p className="mt-0.5 text-xs font-semibold text-slate-500">{event.message || event.event_type}</p>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`rounded-lg border px-2 py-1 text-xs font-bold ${event.status === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : event.status === "error" ? "border-rose-200 bg-rose-50 text-rose-700" : "border-slate-200 bg-slate-50 text-slate-600"}`}>
                          {formatAuditStatus(event.status)}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-xs font-semibold text-slate-500">{event.stage || event.event_type}</td>
                      <td className="px-3 py-3 font-mono text-xs text-slate-500">{formatAuditUser(event.user_id)}</td>
                      <td className="px-3 py-3 text-xs font-semibold text-slate-500">{formatAuditPayloadSummary(event.payload)}</td>
                      <td className="px-3 py-3 text-right text-xs font-semibold text-slate-500">{formatCompactDateTime(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : auditSummary ? (
            <p className="mt-4 rounded-lg border border-dashed border-blue-100 bg-blue-50/50 px-3 py-3 text-sm font-semibold text-blue-700">
              暂无最近审计明细。
            </p>
          ) : null}
          {auditPruneResult && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-800">
              审计账本已清理：按时间删除 {auditPruneResult.deleted_by_age} 条，按数量上限删除 {auditPruneResult.deleted_by_count} 条，剩余 {auditPruneResult.remaining_events} 条。
            </p>
          )}
          {simPruneMessage && (
            <p className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-bold text-cyan-800">
              {simPruneMessage}
            </p>
          )}
          {sessionPruneMessage && (
            <p className="mt-3 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm font-bold text-violet-800">
              {sessionPruneMessage}
            </p>
          )}
          {runtimeJobPruneMessage && (
            <p className="mt-3 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-bold text-indigo-800">
              {runtimeJobPruneMessage}
            </p>
          )}
          {invalidBackupPruneMessage && (
            <p className="mt-3 rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-sm font-bold text-orange-800">
              {invalidBackupPruneMessage}
            </p>
          )}
          {accountExportMessage && (
            <p className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-bold text-emerald-800">
              {accountExportMessage}
            </p>
          )}
        </div>

            </SettingsSection>
            )}

            {activeSettingsSection.id === settingsSections.accountSecurity.id && (
            <SettingsSection
              {...settingsSections.accountSecurity}
            >
        <div className="space-y-4">
        <div className="rounded-lg border border-rose-100 bg-rose-50/80 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-rose-600">Danger Zone</p>
              <h3 className="mt-1 flex items-center gap-2 text-lg font-bold text-slate-950">
                <TrashIcon />
                删除账号数据
              </h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                删除会清除账号、登录会话、收藏、分析报告、资产 watchlist、日报和模拟交易状态。请输入当前密码并确认 DELETE。
              </p>
            </div>
            <div className="grid w-full gap-3 lg:max-w-2xl lg:grid-cols-[minmax(160px,1fr)_150px_auto]">
              <input
                value={deleteCurrentPassword}
                onChange={(event) => setDeleteCurrentPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                placeholder="当前密码"
                className="h-10 rounded-lg border border-rose-100 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition-colors duration-200 placeholder:text-slate-400 focus:border-rose-400 focus:ring-4 focus:ring-rose-100"
              />
              <input
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                placeholder="输入 DELETE"
                className="h-10 rounded-lg border border-rose-100 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition-colors duration-200 placeholder:text-slate-400 focus:border-rose-400 focus:ring-4 focus:ring-rose-100"
              />
              <button
                type="button"
                onClick={handleDeleteAccountSubmit}
                disabled={!canDeleteAccount || accountDeleteLoading}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-rose-600 px-3 text-sm font-bold text-white transition-colors duration-200 hover:bg-rose-700 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <TrashIcon />
                {accountDeleteLoading ? "删除中" : "删除账号"}
              </button>
            </div>
          </div>
        </div>

        <form onSubmit={handlePasswordChange} className="rounded-lg border border-blue-100 bg-white/90 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Account Security</p>
              <h3 className="mt-1 flex items-center gap-2 text-lg font-bold text-slate-950">
                <KeyIcon />
                修改登录密码
              </h3>
            </div>
            <button
              type="submit"
              disabled={passwordChangeLoading || currentPassword.length < 1 || newPassword.length < 10 || confirmPassword.length < 10}
              className="inline-flex h-10 items-center gap-2 rounded-lg bg-slate-950 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <ShieldIcon />
              {passwordChangeLoading ? "更新中" : "更新密码"}
            </button>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <label className="block">
              <span className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">当前密码</span>
              <input
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                type="password"
                autoComplete="current-password"
                className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-900 outline-none transition-colors duration-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </label>
            <label className="block">
              <span className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">新密码</span>
              <input
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                minLength={10}
                className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-900 outline-none transition-colors duration-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                <div className={`h-full rounded-full ${passwordStrength.bar}`} style={{ width: `${passwordStrength.percent}%` }} />
              </div>
            </label>
            <label className="block">
              <span className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">确认新密码</span>
              <input
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                autoComplete="new-password"
                minLength={10}
                className="mt-2 h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-900 outline-none transition-colors duration-200 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm font-semibold">
            {newPassword && <span className={passwordStrength.color}>密码强度：{passwordStrength.label}</span>}
            {passwordChangeError && <span className="text-rose-700">{passwordChangeError}</span>}
            {passwordChangeMessage && <span className="text-emerald-700">{passwordChangeMessage}</span>}
          </div>
        </form>

        <div className="rounded-lg border border-blue-100 bg-white/90 p-4 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Sessions</p>
              <h3 className="mt-1 flex items-center gap-2 text-lg font-bold text-slate-950">
                <UsersIcon />
                登录会话
              </h3>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={loadAuthSessions}
                disabled={sessionsLoading}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-blue-700 transition-colors duration-200 hover:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <RefreshIcon />
                {sessionsLoading ? "读取中" : "刷新会话"}
              </button>
              <button
                type="button"
                onClick={handleRevokeOtherSessions}
                disabled={sessionsLoading || authSessions.filter((session) => !session.is_current).length === 0}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 text-sm font-bold text-amber-800 transition-colors duration-200 hover:bg-amber-100 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <ShieldIcon />
                撤销其他会话
              </button>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <SystemMetricCard
              label="Active Sessions"
              tone={authSessions.length > 1 ? "amber" : authSessions.length === 1 ? "emerald" : "slate"}
              value={sessionsLoading ? "--" : String(authSessions.length)}
              detail={authSessions.length > 1 ? `其他会话 ${authSessions.filter((session) => !session.is_current).length}` : "当前账号会话"}
            />
            {authSessions.slice(0, 2).map((session) => (
              <div key={session.session_id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-xs font-bold text-slate-700">{session.session_id}</p>
                  {session.is_current && (
                    <span className="rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-bold text-emerald-700">
                      当前
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs font-semibold text-slate-500">创建：{formatCompactDateTime(session.created_at)}</p>
                <p className="mt-1 text-xs font-semibold text-slate-500">过期：{formatCompactDateTime(session.expires_at)}</p>
                <p className="mt-1 truncate text-xs font-semibold text-slate-500">客户端：{formatSessionUserAgent(session.user_agent)}</p>
                <p className="mt-1 text-xs font-semibold text-slate-500">IP 摘要：{session.client_ip_hash || "--"}</p>
              </div>
            ))}
          </div>
          {(sessionsError || sessionsMessage) && (
            <p className={`mt-3 rounded-lg border px-3 py-2 text-sm font-bold ${sessionsError ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}>
              {sessionsError || sessionsMessage}
            </p>
          )}
          <div className="mt-4 rounded-lg border border-slate-100 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-bold text-slate-900">最近账号安全事件</p>
              <span className="text-xs font-bold uppercase tracking-[0.12em] text-slate-400">{securityEvents.length} events</span>
            </div>
            {securityEvents.length ? (
              <div className="mt-3 divide-y divide-slate-200">
                {securityEvents.slice(0, 5).map((event) => (
                  <div key={event.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <div>
                      <p className="text-sm font-bold text-slate-800">{formatSecurityEventType(event.event_type)}</p>
                      <p className="mt-0.5 text-xs font-semibold text-slate-500">{event.message || event.stage}</p>
                      <p className="mt-0.5 text-xs font-semibold text-slate-500">{formatSecurityEventContext(event)}</p>
                    </div>
                    <span className="text-xs font-bold text-slate-500">{formatCompactDateTime(event.created_at)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm font-semibold text-slate-500">暂无账号安全事件。</p>
            )}
          </div>
        </div>

        </div>
            </SettingsSection>
            )}

            {activeSettingsSection.id === settingsSections.agentHealth.id && (
            <SettingsSection
              {...settingsSections.agentHealth}
            >
        <div className="grid gap-5 xl:grid-cols-[minmax(300px,0.42fr)_minmax(0,0.58fr)]">
          <div className="rounded-lg border border-blue-100 bg-white/90 p-4 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Agent Health</p>
                <h3 className="mt-1 text-lg font-bold text-slate-950">Agent 运行状态</h3>
              </div>
              <span className={`inline-flex rounded-lg border px-2.5 py-1 text-xs font-bold ${agentStatusStyle}`}>
                {agentStatusText}
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {agentCards.map((agent) => (
                <AgentStatusCard key={agent.name} agent={agent} />
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-blue-100 bg-white/80 p-4 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Pipeline</p>
                <h3 className="mt-1 text-lg font-bold text-slate-950">新闻更新流水线</h3>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-lg border border-blue-100 bg-slate-50 px-3 py-2 text-xs font-bold text-slate-600">
                  {fallbackJob.message}
                </span>
                <button
                  type="button"
                  onClick={onUpdateTodayNews}
                  disabled={updateLoading}
                  className="inline-flex h-10 items-center gap-2 rounded-lg bg-emerald-700 px-4 text-sm font-bold text-white shadow-sm shadow-emerald-200 transition-colors duration-200 hover:bg-emerald-800 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <RefreshIcon />
                  {updateLoading ? "更新中" : "更新新闻"}
                </button>
              </div>
            </div>
            <div className="mt-4 divide-y divide-blue-50">
              {progressItems.map((progress) => (
                <UpdateProgressRow key={progress.label} progress={progress} />
              ))}
            </div>
          </div>
        </div>
            </SettingsSection>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

type SettingsSectionMeta = {
  id: string;
  icon: ReactNode;
  summary: string;
  title: string;
};

function SettingsSubSidebar({
  activeSectionId,
  onSelect,
  sections,
}: {
  activeSectionId: string;
  onSelect: (sectionId: string) => void;
  sections: SettingsSectionMeta[];
}) {
  return (
    <aside className="xl:sticky xl:top-5 xl:self-start">
      <nav aria-label="系统设置索引" className="rounded-lg border border-blue-100 bg-white/90 p-3 shadow-sm">
        <p className="px-2 text-xs font-bold uppercase tracking-[0.18em] text-blue-600">Settings Index</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          {sections.map((section) => (
            <button
              key={section.id}
              type="button"
              onClick={() => onSelect(section.id)}
              aria-current={activeSectionId === section.id ? "page" : undefined}
              className={`group flex min-h-[64px] w-full items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
                activeSectionId === section.id
                  ? "border-blue-200 bg-blue-50 text-blue-800 shadow-sm"
                  : "border-transparent text-slate-600 hover:border-blue-100 hover:bg-blue-50"
              }`}
            >
              <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border transition-colors duration-200 ${
                activeSectionId === section.id
                  ? "border-blue-200 bg-white text-blue-700"
                  : "border-blue-100 bg-blue-50 text-blue-700 group-hover:bg-white"
              }`}>
                {section.icon}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-bold text-slate-950">{section.title}</span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">{section.summary}</span>
              </span>
            </button>
          ))}
        </div>
      </nav>
    </aside>
  );
}

function SettingsSection({ children, icon, id, summary, title }: SettingsSectionMeta & { children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-5 rounded-lg border border-blue-100 bg-white/70 p-3 shadow-sm sm:p-4">
      <div className="mb-4 flex items-start gap-3 border-b border-blue-50 pb-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-blue-100 bg-blue-50 text-blue-700">
          {icon}
        </span>
        <div className="min-w-0">
          <h3 className="text-lg font-bold text-slate-950">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">{summary}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function SystemMetricCard({
  detail,
  label,
  tone,
  value,
}: {
  detail: string;
  label: string;
  tone: "emerald" | "amber" | "rose" | "blue" | "slate";
  value: string;
}) {
  const toneClass = {
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    blue: "border-blue-200 bg-blue-50 text-blue-800",
    slate: "border-slate-200 bg-slate-50 text-slate-800",
  }[tone];

  return (
    <article className={`min-h-[104px] rounded-lg border p-4 ${toneClass}`}>
      <p className="text-xs font-bold uppercase tracking-[0.14em] opacity-70">{label}</p>
      <p className="mt-2 text-xl font-bold tabular-nums">{value}</p>
      <p className="mt-1 text-xs font-semibold opacity-75">{detail}</p>
    </article>
  );
}

function formatReadinessStatus(status: string) {
  if (status === "ready") return "Ready";
  if (status === "degraded") return "Degraded";
  if (status === "not_ready") return "Not ready";
  return "Unknown";
}

function formatJobKind(kind: string) {
  const labels: Record<string, string> = {
    chat_analysis: "Chat 分析",
    risk_assistant: "风险助手",
    news_update: "新闻更新",
    portfolio_refresh: "组合刷新",
    system_admin: "系统运维",
    account_security: "账号安全",
    account_export: "账号导出",
    account_delete: "账号删除",
  };
  return labels[kind] || kind;
}

function formatAuditStatus(status: string) {
  const labels: Record<string, string> = {
    success: "成功",
    error: "失败",
    queued: "排队",
    running: "运行中",
  };
  return labels[status] || status;
}

function formatAuditUser(userId: string) {
  const normalized = String(userId || "").trim();
  if (!normalized) return "--";
  return normalized.length > 14 ? `...${normalized.slice(-10)}` : normalized;
}

function formatAuditPayloadSummary(payload: Record<string, unknown>) {
  const newsUpdate = typeof payload.news_update === "object" && payload.news_update ? payload.news_update as Record<string, unknown> : null;
  const portfolioRefresh = typeof payload.portfolio_refresh === "object" && payload.portfolio_refresh ? payload.portfolio_refresh as Record<string, unknown> : null;
  const nestedParts = [
    newsUpdate ? `新闻任务 ${Number(newsUpdate.deleted_by_age || 0) + Number(newsUpdate.deleted_by_count || 0)}` : "",
    portfolioRefresh ? `组合任务 ${Number(portfolioRefresh.deleted_by_age || 0) + Number(portfolioRefresh.deleted_by_count || 0)}` : "",
  ].filter(Boolean);
  if (nestedParts.length) return nestedParts.join(" · ");

  const parts = [
    payload.deleted_by_age !== undefined ? `时间清理 ${payload.deleted_by_age}` : "",
    payload.deleted_by_count !== undefined ? `数量清理 ${payload.deleted_by_count}` : "",
    payload.deleted_accounts !== undefined ? `账户 ${payload.deleted_accounts}` : "",
    payload.deleted_sessions !== undefined ? `会话 ${payload.deleted_sessions}` : "",
    payload.remaining_events !== undefined ? `剩余事件 ${payload.remaining_events}` : "",
    payload.remaining_accounts !== undefined ? `剩余账户 ${payload.remaining_accounts}` : "",
    payload.remaining_sessions !== undefined ? `剩余会话 ${payload.remaining_sessions}` : "",
    payload.processed_count !== undefined ? `处理 ${payload.processed_count}` : "",
    payload.risk_score !== undefined ? `风险分 ${payload.risk_score}` : "",
  ].filter(Boolean);
  return parts.join(" · ") || "--";
}

function formatDuration(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0));
  const days = Math.floor(safeSeconds / 86400);
  const hours = Math.floor((safeSeconds % 86400) / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  if (days > 0) return `${days}天 ${hours}小时`;
  if (hours > 0) return `${hours}小时 ${minutes}分`;
  return `${minutes}分钟`;
}

function formatBytes(bytes: number) {
  const safeBytes = Math.max(0, Number(bytes) || 0);
  if (safeBytes < 1024) return `${safeBytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = safeBytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${units[unitIndex]}`;
}

function formatDatastoreName(name: string) {
  const labels: Record<string, string> = {
    auth: "账号与收藏",
    analysis_reports: "分析报告",
    portfolio: "资产 Watchlist",
    task_audit: "任务审计",
    daily_reports: "资产日报",
    invalid_json_backups: "损坏 JSON 备份",
    sim_accounts: "模拟账户状态",
  };
  return labels[name] || name;
}

function formatDatastoreScale(store: StorageInventory["datastores"][number]) {
  if (store.tables) {
    const totalRows = Object.values(store.tables).reduce((total, value) => total + Number(value || 0), 0);
    return `${totalRows} 行`;
  }
  if (typeof store.file_count === "number") return `${store.file_count} 文件`;
  if (typeof store.report_files === "number") return `${store.report_files} 报告`;
  return store.exists ? "已创建" : "--";
}

function formatDatastoreDetail(store: StorageInventory["datastores"][number]) {
  if (store.error) return store.error;
  if (store.tables) {
    const tableText = Object.entries(store.tables)
      .map(([table, count]) => `${table}:${count}`)
      .join(" · ");
    return tableText || "暂无表";
  }
  const details = [
    typeof store.user_dirs === "number" ? `用户目录:${store.user_dirs}` : "",
    typeof store.report_files === "number" ? `报告:${store.report_files}` : "",
    typeof store.index_files === "number" ? `索引:${store.index_files}` : "",
    typeof store.file_count === "number" ? `文件:${store.file_count}` : "",
  ].filter(Boolean);
  const fileNames = store.files?.slice(0, 3).map((item) => item.name).join(" · ");
  if (fileNames) details.push(fileNames);
  return details.join(" · ") || "暂无文件";
}

function formatBackupKind(kind: string) {
  const labels: Record<string, string> = {
    directory: "目录",
    directory_file: "目录文件",
    json: "JSON",
    runtime_json_invalid_backup: "损坏 JSON 备份",
    sqlite: "SQLite",
    sqlite_sidecar: "SQLite Sidecar",
    truncated: "截断提示",
  };
  return labels[kind] || kind;
}

function AgentStatusCard({ agent }: { agent: { name: string; detail: string; status: NewsUpdateProgress["status"] } }) {
  const palette = {
    pending: "border-slate-200 bg-slate-50 text-slate-600",
    running: "border-blue-200 bg-blue-50 text-blue-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warning: "border-amber-200 bg-amber-50 text-amber-700",
    error: "border-rose-200 bg-rose-50 text-rose-700",
  }[agent.status];
  const label = {
    pending: "待命",
    running: "运行中",
    success: "正常",
    warning: "降级",
    error: "异常",
  }[agent.status];

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition-colors duration-200 hover:border-blue-200 hover:bg-blue-50/40">
      <div className="flex items-start justify-between gap-3">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${palette}`}>
          <BotIcon />
        </span>
        <span className={`rounded-md border px-2 py-0.5 text-xs font-bold ${palette}`}>{label}</span>
      </div>
      <h4 className="mt-3 text-sm font-bold text-slate-950">{agent.name}</h4>
      <p className="mt-1 text-xs font-semibold text-slate-500">{agent.detail}</p>
    </article>
  );
}

function UpdateProgressRow({ progress }: { progress: NewsUpdateProgress }) {
  const statusStyle = {
    pending: "border-slate-200 bg-slate-50 text-slate-600",
    running: "border-blue-200 bg-blue-50 text-blue-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warning: "border-amber-200 bg-amber-50 text-amber-700",
    error: "border-rose-200 bg-rose-50 text-rose-700",
  }[progress.status];
  const barStyle = {
    pending: "bg-slate-300",
    running: "bg-blue-600",
    success: "bg-emerald-600",
    warning: "bg-amber-500",
    error: "bg-rose-600",
  }[progress.status];
  const percent = progress.total > 0 ? progress.percent : progress.status === "success" ? 100 : 0;
  const counter = progress.total > 0 ? `${progress.current}/${progress.total}` : progress.status === "running" ? "..." : "0/0";

  return (
    <div className="grid gap-3 py-4 first:pt-0 last:pb-0 md:grid-cols-[150px_minmax(0,1fr)_72px] md:items-center">
      <div className="flex items-center gap-3">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${statusStyle}`}>
          <span className="h-2 w-2 rounded-full bg-current" />
        </span>
        <div>
          <p className="text-sm font-bold text-slate-950">{progress.label}</p>
          <p className="mt-1 text-xs font-semibold text-slate-400">{counter}</p>
        </div>
      </div>
      <div className="min-w-0">
        <div className="flex items-center justify-between gap-3 text-xs font-bold text-slate-500">
          <span className="truncate">{progress.message}</span>
          <span className="font-mono">{percent}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barStyle}`}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 md:block md:text-right">
        <span className={`inline-flex rounded-lg border px-2.5 py-1 text-xs font-bold ${statusStyle}`}>
          {progress.status === "running" ? "运行中" : progress.status === "success" ? "完成" : progress.status === "warning" ? "警告" : progress.status === "error" ? "失败" : "待命"}
        </span>
        {typeof progress.fetched_count === "number" && (
          <p className="mt-0 text-xs font-semibold text-slate-400 md:mt-2">抓取 {progress.fetched_count}</p>
        )}
      </div>
    </div>
  );
}

function RankingCard({
  action,
  children,
  onAction,
  title,
}: {
  action?: string;
  children: ReactNode;
  onAction?: () => void;
  title: string;
}) {
  return (
    <section className="risk-card rounded-lg">
      <div className="flex items-center justify-between border-b border-blue-100 px-5 py-4">
        <PanelTitle icon={<ChartIcon />} title={title} />
        {action && (
          <button
            type="button"
            onClick={onAction}
            className="rounded-lg border border-blue-100 bg-white px-3 py-2 text-xs font-semibold text-blue-600 transition-colors duration-200 hover:bg-blue-50"
          >
            {action}
          </button>
        )}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function NewsTable({
  compact = false,
  favoriteActionLoadingId = "",
  favoriteNewsIds = new Set<string>(),
  items,
  maxRows,
  onAnalyzeNews,
  onToggleFavorite,
}: {
  compact?: boolean;
  favoriteActionLoadingId?: string;
  favoriteNewsIds?: Set<string>;
  items: NewsRankingItem[];
  maxRows?: number;
  onAnalyzeNews?: (item: NewsRankingItem) => void;
  onToggleFavorite?: (item: NewsRankingItem) => void;
}) {
  const router = useRouter();
  const rowLimit = maxRows ?? maxRankingTableRows;
  const renderedItems = compact ? items : items.slice(0, rowLimit);
  const headers = [
    { label: "", className: "w-12 px-3 py-3 text-center font-semibold" },
    { label: "#", className: "w-14 px-3 py-3 text-center font-semibold" },
    { label: "新闻标题", className: `${compact ? "min-w-[260px]" : "min-w-[340px]"} px-3 py-3 text-left font-semibold` },
    { label: "风险类别", className: "min-w-[140px] px-3 py-3 text-left font-semibold" },
    { label: "关联币种", className: "min-w-[120px] px-3 py-3 text-left font-semibold" },
    { label: "风险分", className: "w-24 px-3 py-3 text-center font-semibold" },
    { label: "风险等级", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: "操作", className: "w-36 px-3 py-3 text-center font-semibold" },
    { label: compact ? "" : "发布时间", className: "min-w-[160px] px-3 py-3 text-left font-semibold" },
  ];

  return (
    <div className="risk-scroll overflow-x-auto">
      <table className={`risk-table w-full text-left text-sm ${compact ? "min-w-[900px]" : "min-w-[1210px]"}`}>
        <thead className="border-y border-blue-100 bg-slate-50 text-xs text-slate-500">
          <tr>
            {headers.map((head, index) => (
              <th key={`${head.label || "blank"}-${index}`} className={head.className}>{head.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-blue-50">
          {renderedItems.length ? renderedItems.map((item, index) => (
            <tr
              key={item.news_id}
              data-ai-context={buildNewsTableAIContext(item)}
              onClick={() => {
                router.push(withReturnTo(`/news/${encodeURIComponent(item.news_id)}`));
              }}
              className="cursor-pointer text-slate-700 transition-colors duration-200 hover:bg-blue-50/70"
            >
              <td className="px-3 py-3 text-center">
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggleFavorite?.(item);
                  }}
                  disabled={!onToggleFavorite || favoriteActionLoadingId === `news:${item.news_id}`}
                  className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-50 ${
                    favoriteNewsIds.has(String(item.news_id))
                      ? "bg-amber-50 text-amber-600 hover:bg-amber-100"
                      : "text-slate-400 hover:bg-blue-50 hover:text-blue-700"
                  }`}
                  aria-label={favoriteNewsIds.has(String(item.news_id)) ? "取消收藏新闻" : "收藏新闻"}
                >
                  <StarIcon filled={favoriteNewsIds.has(String(item.news_id))} />
                </button>
              </td>
              <td className="px-3 py-3 text-center font-semibold text-slate-900">{index + 1}</td>
              <td className="px-3 py-3 font-semibold text-slate-800">
                <span className="line-clamp-1 text-blue-700">{item.title}</span>
              </td>
              <td className="px-3 py-3 text-slate-600">{formatScoreReasonText(item.risk_type || "综合风险")}</td>
              <td className="px-3 py-3 text-slate-600">{item.coins?.length ? item.coins.join(", ") : "--"}</td>
              <td className={`px-3 py-3 text-center font-bold tabular-nums ${riskScoreTextStyle(item.risk_score, item.risk_level)}`}>
                {clampScore(item.risk_score)}
              </td>
              <td className="px-3 py-3 text-center"><RiskBadge level={item.risk_level} /></td>
              <td className="px-3 py-3 text-center">
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onAnalyzeNews?.(item);
                  }}
                  disabled={!onAnalyzeNews}
                  className="inline-flex h-9 min-w-[104px] items-center justify-center gap-1.5 whitespace-nowrap rounded-lg bg-blue-600 px-3 text-xs font-bold text-white shadow-sm shadow-blue-100 transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <ShieldIcon />
                  深入分析
                </button>
              </td>
              <td className="whitespace-nowrap px-3 py-3 text-slate-500">{compact ? "" : item.published_at || "--"}</td>
            </tr>
          )) : (
            <tr>
              <td colSpan={headers.length} className="px-3 py-8 text-center text-sm font-semibold text-slate-400">
                暂无排行榜数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function CoinTable({ compact = false, items }: { compact?: boolean; items: CoinRankingItem[] }) {
  const router = useRouter();
  const renderedItems = compact ? items : items.slice(0, maxRankingTableRows);
  const headers = [
    { label: "#", className: "w-14 px-3 py-3 text-center font-semibold" },
    { label: "币种", className: "min-w-[150px] px-3 py-3 text-left font-semibold" },
    { label: "风险类别", className: "min-w-[260px] px-3 py-3 text-left font-semibold" },
    ...(!compact ? [
      { label: "主要风险来源", className: "min-w-[180px] px-3 py-3 text-left font-semibold" },
      { label: "最近关键事件", className: "min-w-[260px] px-3 py-3 text-left font-semibold" },
    ] : []),
    { label: "风险分", className: "w-24 px-3 py-3 text-center font-semibold" },
    { label: "风险等级", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: "相关新闻数", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: compact ? "" : "24H 趋势", className: "w-28 px-3 py-3 text-center font-semibold" },
  ];

  return (
    <div className="risk-scroll overflow-x-auto">
      <table className={`risk-table w-full text-left text-sm ${compact ? "min-w-[760px]" : "min-w-[1280px]"}`}>
        <thead className="border-y border-blue-100 bg-slate-50 text-xs text-slate-500">
          <tr>
            {headers.map((head, index) => (
              <th key={`${head.label || "blank"}-${index}`} className={head.className}>{head.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-blue-50">
          {renderedItems.length ? renderedItems.map((item) => (
            <tr
              key={item.symbol}
              data-ai-context={buildCoinTableAIContext(item)}
              onClick={() => {
                router.push(withReturnTo(`/coins/${encodeURIComponent(item.symbol)}`));
              }}
              className="cursor-pointer text-slate-700 transition-colors duration-200 hover:bg-blue-50/70"
            >
              <td className="px-3 py-3 text-center font-semibold text-slate-900">{item.rank}</td>
              <td className="px-3 py-3">
                <div className="flex items-center gap-2">
                  <CoinMark symbol={item.symbol} />
                  <span className="font-bold text-slate-900">{item.symbol}</span>
                </div>
              </td>
              <td className="px-3 py-3 text-slate-600">{formatScoreReasonText(item.main_risk_type || "综合风险")}</td>
              {!compact && (
                <>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {getCoinRiskSources(item).map((source) => (
                        <span key={source} className="rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">
                          {source}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-slate-600">
                    <span className="line-clamp-1">{getCoinKeyEvent(item)}</span>
                  </td>
                </>
              )}
              <td className={`px-3 py-3 text-center font-bold tabular-nums ${riskScoreTextStyle(item.final_score, item.risk_level)}`}>
                {clampScore(item.final_score)}
              </td>
              <td className="px-3 py-3 text-center"><RiskBadge level={item.risk_level} /></td>
              <td className="px-3 py-3 text-center tabular-nums">{item.news_count}</td>
              <td className="px-3 py-3 text-center">
                {compact ? "" : (
                  <span className="inline-flex">
                    <SparklineChart
                      ariaLabel={`${item.symbol} 24小时风险趋势`}
                      className="h-8 w-24"
                      series={buildCoinTrendSeries(item, "24h")}
                      tone={getRiskTone(item.final_score)}
                    />
                  </span>
                )}
              </td>
            </tr>
          )) : (
            <tr>
              <td colSpan={headers.length} className="px-3 py-8 text-center text-sm font-semibold text-slate-400">
                暂无排行榜数据
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2 text-sm leading-6 text-slate-700">
      {items.map((item, index) => (
        <li key={`${item}-${index}`} className="flex gap-2">
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-500" />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function ReportDocument({
  favoriteLoading,
  isFavorite,
  onChangeDisposition,
  onDeleteRecord,
  onReanalyze,
  onToggleFavorite,
  record,
}: {
  favoriteLoading: boolean;
  isFavorite: boolean;
  onChangeDisposition: (recordId: string, disposition: AnalysisDisposition, note?: string) => void;
  onDeleteRecord: (id: string) => void;
  onReanalyze: (input: string) => void;
  onToggleFavorite: (record: AnalysisRecord) => void;
  record: AnalysisRecord;
}) {
  const report = record.report;
  const score = clampScore(report.risk_score);
  const chatAgentResult = report.chat_agent_result || report.v6_result || {};
  const branchScoreMerge = (report.branch_score_merge || chatAgentResult.branch_score_merge || {}) as Record<string, unknown>;
  const mergedPrimaryCategory =
    typeof branchScoreMerge.primary_risk_name === "string" && branchScoreMerge.primary_risk_name.trim()
      ? branchScoreMerge.primary_risk_name
      : report.primary_category;
  const categories = report.risk_categories?.length ? report.risk_categories : ["综合风险"];
  const primaryCategory = mergedPrimaryCategory || categories[0];
  const secondaryCategories = (report.secondary_categories?.length ? report.secondary_categories : categories.filter((item) => item !== primaryCategory)).slice(0, 6);
  const evidenceItems = report.evidence?.length
    ? report.evidence
    : [{ risk_category: categories[0], evidence_text: "当前报告尚未抽取到结构化证据。", explanation: "建议补充官方公告、链上交易哈希、社群反馈截图或交易所通知。" }];
  const riskBranches = report.risk_type_branches || chatAgentResult.risk_type_branches || [];
  const evidenceGraph = report.evidence_graph || chatAgentResult.evidence_graph || [];
  const scenarioAssessments = report.scenario_assessments || chatAgentResult.scenario_assessments || [];
  const counterEvidence = report.counter_evidence || chatAgentResult.counter_evidence || [];
  const missingEvidenceByScenario = report.missing_evidence_by_scenario || chatAgentResult.missing_evidence_by_scenario || {};
  const decisionTrace = report.decision_trace || chatAgentResult.decision_trace || {};
  const impactAnalysis = report.impact_analysis || chatAgentResult.impact_analysis || {};
  const adviceGeneration = report.advice_generation || chatAgentResult.advice_generation || {};
  const finalContextMeta = report.final_context_agents || {};
  const isWeakRisk = detectWeakRisk(chatAgentResult, finalContextMeta, impactAnalysis, adviceGeneration);
  const summary = compactReportSummary(report.summary) || "事件已完成结构化风险研判。";
  const normalizedRecord = normalizeAnalysisRecord(record);

  function copySummary() {
    void copyTextToClipboard(buildReportSummaryText(record));
  }

  function copyEvidence() {
    void copyTextToClipboard(buildEvidenceText(evidenceItems));
  }

  function copyShareLink() {
    if (typeof window === "undefined") return;
    const url = `${window.location.origin}/reports?record=${encodeURIComponent(record.id)}`;
    void copyTextToClipboard(url);
  }

  function downloadMarkdown() {
    downloadTextFile(`${sanitizeFilename(record.title)}.md`, buildReportMarkdown(record));
  }

  function printPdf() {
    if (typeof window !== "undefined") window.print();
  }

  return (
    <article
      className="risk-scroll min-w-0 overflow-y-auto bg-white"
      data-ai-context={JSON.stringify({
        type: "risk_report",
        title: record.title,
        riskLevel: report.risk_level,
        riskScore: report.risk_score,
        riskCategories: report.risk_categories,
        createdAt: record.createdAt,
      })}
    >
      <div className="border-b border-blue-100 px-4 py-5 sm:px-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1" data-onboarding-id="page-title">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">CryptoRisk Report</p>
            <h2 className="mt-2 break-words text-xl font-bold text-slate-950 sm:text-2xl">{record.title}</h2>
            <p className="mt-2 text-sm text-slate-500">{record.createdAt}</p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <button
              type="button"
              onClick={() => onToggleFavorite(record)}
              disabled={favoriteLoading}
              className={`inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border px-4 text-sm font-bold transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto ${
                isFavorite
                  ? "border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100"
                  : "border-blue-100 bg-white text-slate-700 hover:bg-blue-50"
              }`}
            >
              <StarIcon filled={isFavorite} />
              {favoriteLoading ? "处理中..." : isFavorite ? "取消收藏" : "收藏报告"}
            </button>
            <button
              type="button"
              onClick={copySummary}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <CopyIcon />
              复制摘要
            </button>
            <button
              type="button"
              onClick={copyEvidence}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <ShieldIcon />
              复制证据
            </button>
            <button
              type="button"
              onClick={downloadMarkdown}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <DownloadIcon />
              导出 Markdown
            </button>
            <button
              type="button"
              onClick={printPdf}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <FileIcon />
              导出 PDF
            </button>
            <button
              type="button"
              onClick={copyShareLink}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <LinkIcon />
              复制分享链接
            </button>
            <button
              type="button"
              onClick={() => onDeleteRecord(record.id)}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-rose-200 bg-rose-50 px-4 text-sm font-bold text-rose-700 transition-colors duration-200 hover:bg-rose-100 sm:w-auto"
            >
              <TrashIcon />
              删除报告
            </button>
            <button
              type="button"
              onClick={() => onReanalyze(record.input)}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700 sm:w-auto"
            >
              <RefreshIcon />
              重新分析
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-5 p-4 sm:p-8">
        <ReportSection title="处置闭环" icon={<CheckIcon />}>
          <DispositionPanel
            disposition={normalizedRecord.disposition || "pending"}
            note={normalizedRecord.dispositionNote || ""}
            onChange={(disposition, note) => onChangeDisposition(record.id, disposition, note)}
          />
        </ReportSection>

        <ReportSection title="原始输入" icon={<ChatIcon />}>
          <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{formatReportOriginalInput(record.input)}</p>
        </ReportSection>

        <section className="grid gap-4 rounded-lg border border-blue-100 bg-slate-50 p-4 sm:gap-5 sm:p-5 lg:grid-cols-[180px_minmax(0,1fr)_220px]" data-onboarding-id="report-score">
          <div className="rounded-lg bg-white p-5 text-center shadow-sm">
            <p className="text-sm font-semibold text-slate-500">风险评分</p>
            <p className={`mt-3 text-5xl font-bold ${riskScoreTextStyle(score, report.risk_level || "")}`}>
              {score}<span className="text-xl text-slate-400">/100</span>
            </p>
            <div className="mt-4 flex justify-center"><RiskBadge level={report.risk_level} /></div>
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-bold text-white">主风险</span>
              <span className="rounded-md border border-blue-200 bg-white px-2.5 py-1 text-xs font-bold text-blue-700">{primaryCategory}</span>
              {secondaryCategories.map((item) => (
                <span key={item} className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
                  {item}
                </span>
              ))}
            </div>
            <p className="mt-4 text-base font-bold leading-8 text-slate-950">{summary}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {(report.risk_signals || []).map((item) => formatRiskSignalLabel(String(item))).filter(Boolean).slice(0, 4).map((item, index) => (
                <span key={`${item}-${index}`} className="rounded-md border border-blue-100 bg-white px-2.5 py-1 text-xs font-semibold text-slate-600">
                  {formatRiskSignalLabel(item)}
                </span>
              ))}
            </div>
          </div>
          <div className="grid content-start gap-3">
            <MetaTile label="置信度" value={`${clampScore(report.confidence_score ?? 0)}/100 · ${report.confidence_level || "待确认"}`} />
            <MetaTile label="风险状态" value={formatRiskStatus(report.risk_status)} />
            <MetaTile label="分析路径" value={formatEnginePath(chatAgentResult.orchestration_path)} />
          </div>
        </section>

        <div className="space-y-5" data-onboarding-id="report-actions">
          <ReportSection title="评分拆解" icon={<ChartIcon />} variant="main">
            <ScoreBreakdownPanel report={report} />
          </ReportSection>

          <ReportSection title="证据图谱与评分路径" icon={<ShieldIcon />} variant="main">
            <EvidenceGraphPanel
              atoms={evidenceGraph}
              counterEvidence={counterEvidence}
              decisionTrace={decisionTrace}
              missingByScenario={missingEvidenceByScenario}
              scenarioAssessments={scenarioAssessments}
            />
          </ReportSection>

          <ReportSection title="风险类别与证据" icon={<FileIcon />} variant="main">
            <RiskCategoryEvidence
              branches={riskBranches}
              categories={categories}
              evidenceItems={evidenceItems}
              stats={report.risk_type_stats || chatAgentResult.risk_type_stats || []}
            />
          </ReportSection>

          <ReportSection title="影响对象" icon={<UsersIcon />} variant="main">
            <ImpactObjectsPanel analysis={impactAnalysis} fallback={report.impact || []} isWeakRisk={isWeakRisk} />
          </ReportSection>

          <ReportSection title="处置建议" icon={<BulbIcon />} variant="main">
            <AdvicePanel advice={adviceGeneration} fallback={report.advice || []} isWeakRisk={isWeakRisk} />
          </ReportSection>
        </div>
      </div>
    </article>
  );
}

type ReportEvidenceItem = RiskReport["evidence"][number];

const dispositionOptions: Array<{ value: AnalysisDisposition; label: string; description: string }> = [
  { value: "pending", label: "待处理", description: "风险已识别，等待核验或处置" },
  { value: "verified", label: "已核验", description: "证据已确认，进入正式风险记录" },
  { value: "monitoring", label: "持续观察", description: "风险未完全落地，需要继续跟踪" },
  { value: "ignored", label: "已忽略", description: "误报、弱相关或无需继续处理" },
  { value: "reviewed", label: "已复盘", description: "事件已完成后续复盘归档" },
];

function DispositionPanel({
  disposition,
  note,
  onChange,
}: {
  disposition: AnalysisDisposition;
  note: string;
  onChange: (disposition: AnalysisDisposition, note?: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {dispositionOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value, note)}
            className={`min-h-[88px] rounded-lg border p-3 text-left transition-colors duration-200 ${
              disposition === option.value
                ? "border-blue-300 bg-blue-50 text-blue-800 shadow-sm"
                : "border-blue-100 bg-white text-slate-600 hover:bg-blue-50"
            }`}
          >
            <span className="text-sm font-bold">{option.label}</span>
            <span className="mt-1 block text-xs font-semibold leading-5">{option.description}</span>
          </button>
        ))}
      </div>
      <label className="block">
        <span className="text-xs font-bold text-slate-500">处置备注</span>
        <textarea
          value={note}
          onChange={(event) => onChange(disposition, event.target.value)}
          className="mt-2 min-h-20 w-full resize-y rounded-lg border border-blue-100 bg-white px-3 py-2 text-sm font-semibold leading-6 text-slate-700 outline-none transition-colors duration-200 focus:border-blue-300 focus:ring-4 focus:ring-blue-100"
          placeholder="记录核验来源、处理动作、后续观察点..."
        />
      </label>
    </div>
  );
}

function DispositionBadge({ disposition }: { disposition: AnalysisDisposition }) {
  const label = dispositionOptions.find((item) => item.value === disposition)?.label || "待处理";
  const style = {
    pending: "bg-slate-100 text-slate-600",
    verified: "bg-emerald-50 text-emerald-700",
    ignored: "bg-slate-100 text-slate-500",
    monitoring: "bg-amber-50 text-amber-700",
    reviewed: "bg-violet-50 text-violet-700",
  }[disposition];
  return <span className={`rounded-md px-2 py-1 text-xs font-bold ${style}`}>{label}</span>;
}

function ScoreBreakdownPanel({ report }: { report: RiskReport }) {
  const dimensions = [
    ["severity", "严重性", report.score_breakdown?.severity ?? report.severity_score ?? report.risk_score],
    ["evidence_strength", "证据强度", report.score_breakdown?.evidence_strength ?? report.confidence_score ?? 0],
    ["impact_scope", "影响范围", report.score_breakdown?.impact_scope ?? report.contagion_score ?? 0],
    ["urgency", "紧急度", report.score_breakdown?.urgency ?? report.urgency_score ?? 0],
    ["reversibility", "可逆性", report.score_breakdown?.reversibility ?? 0],
  ] as const;

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {dimensions.map(([, label, rawScore]) => {
        const score = clampScore(Number(rawScore) || 0);
        return (
          <div key={label} className="rounded-lg border border-blue-100 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-slate-500">{label}</span>
              <span className={`text-lg font-bold ${riskScoreTextStyle(score, "")}`}>{score}</span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-white">
              <div className="h-2 rounded-full bg-blue-600" style={{ width: `${score}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EvidenceGraphPanel({
  atoms,
  counterEvidence,
  decisionTrace,
  missingByScenario,
  scenarioAssessments,
}: {
  atoms: NonNullable<RiskReport["evidence_graph"]>;
  counterEvidence: NonNullable<RiskReport["counter_evidence"]>;
  decisionTrace: NonNullable<RiskReport["decision_trace"]>;
  missingByScenario: NonNullable<RiskReport["missing_evidence_by_scenario"]>;
  scenarioAssessments: NonNullable<RiskReport["scenario_assessments"]>;
}) {
  const supportAtoms = atoms.filter((item) => item.polarity === "support").slice(0, 5);
  const missingEntries = Object.entries(missingByScenario || {}).flatMap(([scenario, items]) =>
    asStringList(items).map((item) => ({ scenario, item })),
  ).slice(0, 6);
  const traceItems = [
    ["初始分", decisionTrace.pre_cap_score],
    ["最终分", decisionTrace.final_score],
    ["主分支", decisionTrace.primary_branch_score],
    ["次风险加权", decisionTrace.secondary_bonus],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  const caps = [
    ...asStringList(decisionTrace.hard_caps_applied),
    ...asStringList(decisionTrace.soft_caps_applied),
    ...asStringList(decisionTrace.score_caps_applied),
  ];
  const floors = asStringList(decisionTrace.score_floors_applied);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 lg:grid-cols-3">
        {(scenarioAssessments.length ? scenarioAssessments : []).slice(0, 6).map((item) => (
          <div key={`${item.scenario}-${item.risk_type}`} className="rounded-lg border border-blue-100 bg-slate-50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-white px-2 py-0.5 text-xs font-bold text-blue-700">{formatScenarioCode(item.scenario)}</span>
              <span className={`rounded-md px-2 py-0.5 text-xs font-bold ${item.status === "established" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                {formatScenarioStatus(item.status)}
              </span>
            </div>
            <p className="mt-2 text-sm font-bold leading-6 text-slate-900">{formatRiskTypeCode(item.risk_type) || item.risk_name || "综合风险"}</p>
            <div className="mt-3 grid grid-cols-3 gap-2 text-center">
              <MiniMetric label="规则" value={clampScore(item.rule_score)} />
              <MiniMetric label="分支" value={clampScore(item.branch_score)} />
              <MiniMetric label="置信" value={clampScore(Math.round((item.confidence || 0) * 100))} />
            </div>
          </div>
        ))}
        {!scenarioAssessments.length && (
          <div className="rounded-lg border border-blue-100 bg-slate-50 p-3 text-sm font-semibold text-slate-600">
            当前路径未进入多场景深度评估，按低风险或兜底路径生成报告。
          </div>
        )}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg border border-blue-100 bg-white p-3">
          <p className="text-xs font-bold text-slate-500">支持证据节点</p>
          <div className="mt-2 space-y-2">
            {(supportAtoms.length ? supportAtoms : atoms.slice(0, 3)).map((item) => (
              <EvidenceAtomRow key={item.id} atom={item} />
            ))}
            {!atoms.length && <p className="text-sm font-semibold leading-6 text-slate-600">暂无结构化证据节点。</p>}
          </div>
        </div>

        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-bold text-amber-800">反向证据 / 缺失证据</p>
          <div className="mt-2 space-y-2">
            {counterEvidence.slice(0, 4).map((item, index) => (
              <p key={`${item.text}-${index}`} className="rounded-md bg-white/80 px-3 py-2 text-sm font-semibold leading-6 text-amber-900">
                {formatScoreReasonText(item.meaning || item.text)}
              </p>
            ))}
            {missingEntries.map((entry) => (
              <p key={`${entry.scenario}-${entry.item}`} className="rounded-md bg-white/80 px-3 py-2 text-sm font-semibold leading-6 text-slate-700">
                {formatScenarioCode(entry.scenario)} 待核验：{formatScoreReasonText(entry.item)}
              </p>
            ))}
            {!counterEvidence.length && !missingEntries.length && (
              <p className="rounded-md bg-white/80 px-3 py-2 text-sm font-semibold text-slate-600">未发现明确反向证据，仍需继续跟踪来源更新。</p>
            )}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-slate-50 p-3">
        <div className="flex flex-wrap gap-2">
          {traceItems.map(([label, value]) => (
            <span key={String(label)} className="rounded-md border border-blue-100 bg-white px-2.5 py-1 text-xs font-bold text-slate-700">
              {String(label)}：{String(value)}
            </span>
          ))}
          {floors.map((item) => (
            <span key={`floor-${item}`} className="rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">
              保底：{formatRiskSignalLabel(item)}
            </span>
          ))}
          {caps.map((item) => (
            <span key={`cap-${item}`} className="rounded-md border border-rose-200 bg-rose-50 px-2.5 py-1 text-xs font-bold text-rose-700">
              压分：{formatRiskSignalLabel(item)}
            </span>
          ))}
        </div>
        {typeof decisionTrace.formula === "string" && decisionTrace.formula.trim() && (
          <p className="mt-3 text-xs font-semibold leading-5 text-slate-500">{formatScoreReasonText(decisionTrace.formula)}</p>
        )}
      </div>
    </div>
  );
}

function EvidenceAtomRow({ atom }: { atom: NonNullable<RiskReport["evidence_graph"]>[number] }) {
  return (
    <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-white px-2 py-0.5 text-xs font-bold text-slate-500">{atom.id}</span>
        <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-700">{formatEvidencePolarity(atom.polarity)}</span>
        <span className="rounded bg-white px-2 py-0.5 text-xs font-bold text-slate-600">{formatScenarioCode(atom.scenario)}</span>
      </div>
      <p className="mt-2 text-sm font-semibold leading-6 text-slate-800">{formatScoreReasonText(atom.text)}</p>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-white px-2 py-1">
      <p className="text-[11px] font-bold text-slate-400">{label}</p>
      <p className={`text-sm font-bold ${riskScoreTextStyle(value, "")}`}>{value}</p>
    </div>
  );
}

function RiskCategoryEvidence({
  branches,
  categories,
  evidenceItems,
  stats,
}: {
  branches: RiskTypeBranch[];
  categories: string[];
  evidenceItems: ReportEvidenceItem[];
  stats: NonNullable<RiskReport["risk_type_stats"]>;
}) {
  const groups = buildEvidenceGroups(categories, evidenceItems);

  return (
    <div className="space-y-4">
      {groups.map((group) => {
        const branch = branches.find((item) => item.risk_name === group.category);
        const stat = stats.find((item) => item.risk_name === group.category);
        const score = branch?.branch_score ?? stat?.score_100;
        const strength = branch?.evidence_strength;
        const missingEvidence = asStringList(branch?.missing_evidence).slice(0, 2);
        const established = branch?.established === true;
        const statusLabel = established ? "风险成立" : branch ? "证据不足" : "待核验";

        return (
          <div key={group.category} className="rounded-lg border border-blue-100 bg-blue-50/50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-white px-2.5 py-1 text-xs font-bold text-blue-700 shadow-sm">
                {formatEvidenceCategory(group.category)}
              </span>
              <span className={`rounded-md px-2.5 py-1 text-xs font-bold ${established ? "border border-emerald-200 bg-emerald-50 text-emerald-700" : "border border-amber-200 bg-amber-50 text-amber-700"}`}>
                {statusLabel}
              </span>
              {typeof score === "number" && (
                <span className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
                  分支 {clampScore(score)}/100
                </span>
              )}
              {typeof strength === "number" && (
                <span className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
                  证据 {clampScore(strength)}/100
                </span>
              )}
            </div>

            {branch?.reasoning && <p className="mt-3 text-sm font-semibold leading-6 text-slate-700">{formatScoreReasonText(branch.reasoning)}</p>}

            <div className="mt-3 grid gap-2">
              {group.items.map((item, index) => (
                <div key={`${group.category}-${item.evidence_text}-${index}`} className="rounded-lg border border-white bg-white/80 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-500">
                      证据 {String(index + 1).padStart(2, "0")}
                    </span>
                    {item.explanation && (
                      <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-bold text-emerald-700">
                        {formatRiskSignalLabel(item.explanation)}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm leading-7 text-slate-800">{formatScoreReasonText(item.evidence_text)}</p>
                </div>
              ))}
            </div>

            {missingEvidence.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {missingEvidence.map((item) => (
                  <span key={item} className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                    待核验：{formatScoreReasonText(item)}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ImpactObjectsPanel({ analysis, fallback, isWeakRisk }: { analysis: ImpactAnalysis; fallback: string[]; isWeakRisk?: boolean }) {
  const summary = compactReportSummary(analysis.impact_summary || fallback[0] || "影响对象尚不明确，需要补充更多上下文。");
  const sourceLabel = formatAgentSource(analysis.source);
  const emptyObjectLabel = isWeakRisk ? "弱风险未确认" : "未明确";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <span className="rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">
          {sourceLabel}
        </span>
        {isWeakRisk && (
          <span className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-800">
            弱风险保护：不推断影响对象
          </span>
        )}
      </div>
      <p className="rounded-lg border border-blue-100 bg-slate-50 p-4 text-sm font-semibold leading-7 text-slate-700">{summary}</p>
      <InfoPillGroup title="资产 / 交易对" items={asStringList(analysis.affected_assets)} empty={emptyObjectLabel} />
      <InfoPillGroup title="平台 / 协议" items={asStringList(analysis.affected_platforms)} empty={emptyObjectLabel} />
      <InfoPillGroup title="用户群体" items={asStringList(analysis.affected_users)} empty={emptyObjectLabel} />
      <InfoPillGroup title="传导路径" items={asStringList(analysis.impact_channels)} empty="持续监测" />
      {asStringList(analysis.uncertainty).length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-bold text-amber-800">不确定性</p>
          <BulletList items={asStringList(analysis.uncertainty)} />
        </div>
      )}
    </div>
  );
}

function AdvicePanel({ advice, fallback, isWeakRisk }: { advice: AdviceGeneration; fallback: string[]; isWeakRisk?: boolean }) {
  const actions = sanitizeAdvice(asStringList(advice.recommended_actions).length ? asStringList(advice.recommended_actions) : fallback);
  const monitoringItems = asStringList(advice.monitoring_items);
  const verificationNeeded = asStringList(advice.verification_needed);
  const doNotDo = sanitizeAdvice(asStringList(advice.do_not_do));
  const sourceLabel = formatAgentSource(advice.source);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-bold text-white">优先级</span>
        <span className="rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-bold text-blue-700">
          {formatAdvicePriority(advice.priority)}
        </span>
        <span className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
          {sourceLabel}
        </span>
        {isWeakRisk && (
          <span className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-800">
            弱风险建议：仅监测与核验
          </span>
        )}
      </div>
      {advice.reason && <p className="rounded-lg border border-blue-100 bg-slate-50 p-3 text-sm font-semibold leading-6 text-slate-700">{advice.reason}</p>}
      <BulletList items={actions.length ? actions : ["继续核验公告、链上资金流向和用户反馈。"]} />
      <InfoPillGroup title="监控项" items={monitoringItems} empty="官方公告、链上资金流向" />
      <InfoPillGroup title="补充核验" items={verificationNeeded} empty="事件时间线、影响范围" />
      {doNotDo.length > 0 && (
        <div className="rounded-lg border border-rose-100 bg-rose-50 p-3">
          <p className="text-xs font-bold text-rose-700">避免动作</p>
          <BulletList items={doNotDo} />
        </div>
      )}
    </div>
  );
}

function InfoPillGroup({ empty, items, title }: { empty: string; items: string[]; title: string }) {
  const values = items.filter(Boolean).slice(0, 8);

  return (
    <div>
      <p className="mb-2 text-xs font-bold text-slate-500">{title}</p>
      <div className="flex flex-wrap gap-2">
        {(values.length ? values : [empty]).map((item) => (
          <span key={item} className="rounded-md border border-blue-100 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function buildEvidenceGroups(categories: string[], evidenceItems: ReportEvidenceItem[]) {
  const orderedCategories = [...categories];
  for (const item of evidenceItems) {
    const category = item.risk_category || "综合风险";
    if (!orderedCategories.includes(category)) orderedCategories.push(category);
  }

  return orderedCategories
    .map((category) => ({
      category,
      items: evidenceItems.filter((item) => (item.risk_category || "综合风险") === category),
    }))
    .filter((group) => group.items.length > 0);
}

function asStringList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function formatAdvicePriority(value?: string) {
  const labels: Record<string, string> = {
    low: "低",
    medium: "中",
    high: "高",
    urgent: "紧急",
  };
  return labels[String(value || "")] || value || "中";
}

function MetaTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white p-4 shadow-sm">
      <p className="text-xs font-semibold text-slate-500">{label}</p>
      <p className="mt-2 text-sm font-bold leading-6 text-slate-900">{value}</p>
    </div>
  );
}

function formatEvidenceCategory(value: string) {
  const normalized = value.trim();
  const labels: Record<string, string> = {
    confirmed_risk: "支持已确认风险",
    potential_risk: "支持潜在风险",
    systemic_risk: "支持系统性风险",
    resolved_risk: "风险已缓解",
    no_risk: "暂未发现风险",
    uncertain: "信息仍待确认",
  };
  return labels[normalized] || normalized || "风险证据";
}

function formatEvidenceSignal(value: string) {
  const normalized = value.trim();
  const labels: Record<string, string> = {
    confirmed_attack: "已确认攻击",
    actual_loss: "资产损失",
    unauthorized_mint: "异常铸造",
    asset_exfiltration: "资金外流",
    withdrawal_pause: "提现暂停",
    user_impact: "用户影响",
    market_impact: "市场影响",
    operation_issue: "运营异常",
    potential_threat: "潜在威胁",
    regulatory_signal: "监管信号",
    discussion: "讨论信息",
    other: "其他证据",
    withdrawal_suspended: "提现暂停",
    planned_maintenance: "计划维护",
    recovery_time_confirmed: "恢复时间明确",
    fund_safety_statement: "资金安全声明",
    secondary_risk_bonus: "次要风险加权",
    validator_cap_score: "校验压分",
    validator_raise_floor: "校验抬分",
    insufficient_evidence: "关键证据不足",
    exploit_confirmed: "攻击已确认",
    loss_confirmed: "损失已确认",
    mitigation_status: "处置状态",
    recovery_time: "恢复时间",
    affected_assets: "受影响资产",
    affected_protocols: "受影响协议",
    attacker_address: "攻击者地址",
  };
  return labels[normalized] || normalized || "证据类型";
}

function formatScenarioCode(value: string) {
  const labels: Record<string, string> = {
    S0_GENERAL_UNKNOWN: "综合场景",
    S1_ATTACK_EXPLOIT: "链上攻击",
    S2_EXCHANGE_ABNORMALITY: "交易所异常",
    S3_STABLECOIN_RESERVE: "稳定币/储备",
    S4_INFRASTRUCTURE_FAILURE: "基础设施",
    S5_REGULATORY_ENFORCEMENT: "监管执法",
    S6_MARKET_LIQUIDATION: "清算波动",
    S7_FRAUD_GOVERNANCE: "诈骗治理",
    S8_WHALE_ONCHAIN_FLOW: "巨鲸流向",
    S9_TOKEN_ISSUANCE_ANOMALY: "异常增发",
    S10_BRIDGE_CROSS_CHAIN_RISK: "跨链桥",
  };
  return labels[value] || value || "场景";
}

function formatScenarioStatus(value: string) {
  const labels: Record<string, string> = {
    established: "风险成立",
    insufficient_evidence: "证据不足",
    not_established: "未成立",
    not_assessed: "未评估",
  };
  return labels[value] || value || "待评估";
}

function formatEvidencePolarity(value: string) {
  const labels: Record<string, string> = {
    support: "支持证据",
    counter: "反向证据",
    missing: "缺失证据",
  };
  return labels[value] || value || "证据";
}

function formatRiskTypeCode(value: string) {
  const labels: Record<string, string> = {
    score_hack: "链上漏洞 / 攻击风险",
    score_fraud: "诈骗 / 跑路 / Rug Pull 风险",
    score_regulatory: "监管与法律风险",
    score_outage: "交易所与系统运维风险",
    score_stablecoin: "稳定币异常风险",
    score_liquidation: "爆仓 / 清算风险",
    score_whale: "大额转账 / 巨鲸行为风险",
    score_volatility: "异常行情波动风险",
    score_team: "项目治理 / 团队异常风险",
    score_solvency: "偿付能力 / 储备 / 流动性风险",
    score_infra: "基础设施 / 协议层异常风险",
    score_token_issuance: "代币发行 / 异常增发风险",
    score_bridge: "跨链桥 / 跨链资金风险",
    score_macro: "宏观 / 政策冲击风险",
  };
  return labels[value] || value;
}

function formatRiskSignalLabel(value: string) {
  const normalized = value.trim();
  if (!normalized) return "风险信号";

  const branchScore = normalized.match(/^(score_[a-z_]+),branch_score=(\d+)$/);
  if (branchScore) {
    return `${formatRiskTypeCode(branchScore[1])}：分支评分 ${branchScore[2]}`;
  }

  const primaryRisk = normalized.match(/^primary_risk_type:(score_[a-z_]+)$/);
  if (primaryRisk) {
    return `主风险：${formatRiskTypeCode(primaryRisk[1])}`;
  }

  const highRiskFloor = normalized.match(/^high_risk_floor:(score_[a-z_]+):(\d+)$/);
  if (highRiskFloor) {
    return `${formatRiskTypeCode(highRiskFloor[1])}：强信号保底 ${highRiskFloor[2]}`;
  }

  const highRiskRoute = normalized.match(/^high_risk_route:(score_[a-z_]+)$/);
  if (highRiskRoute) {
    return `高风险路径：${formatRiskTypeCode(highRiskRoute[1])}`;
  }

  const lowRiskGateAdded = normalized.match(/^low_risk_gate_added:(score_[a-z_]+)$/);
  if (lowRiskGateAdded) {
    return `低风险复核补充：${formatRiskTypeCode(lowRiskGateAdded[1])}`;
  }

  const validatorScore = normalized.match(/^validator:(\d+)$/);
  if (validatorScore) {
    return `二次校验阈值 ${validatorScore[1]}`;
  }

  const labels: Record<string, string> = {
    risk_type_branch_merge: "风险类型分支合并",
    secondary_risk_bonus: "次要风险加权",
    primary_branch_evidence_weak: "主风险证据偏弱",
    no_established_risk_type_branch: "未形成明确风险分支",
    high_risk_floor_signal: "触发高风险保底",
    weak_rule_signal: "弱风险规则信号",
    fast_exit: "快速低风险路径",
    no_high_risk_scenario_detected: "未发现高风险场景",
    candidate_scenarios_detected: "发现候选风险场景",
    initial_high_risk_signal: "初筛发现高风险信号",
    initial_rule_evidence_conflict: "规则信号与证据存在冲突",
    low_risk_gate_escalated: "低风险门控已升级",
    validator_cap_score: "二次校验压低评分",
    validator_raise_floor: "二次校验抬高评分",
    discussion_only: "讨论或观点类信息",
    security_research_only: "安全研究或漏洞披露",
    planned_maintenance: "计划维护语境",
    resolved_or_repaired: "事件已修复或恢复",
    no_loss_or_no_impact: "暂未发现损失或影响",
    rumor_without_confirmation: "传闻或待确认信息",
    internal_transfer: "内部转账或钱包归集",
    normal_market_commentary: "普通行情评论",
    positive_regulatory_clarity: "监管利好或澄清",
    ordinary_team_change: "普通团队变动",
    cross_scenario_planned_or_resolved_ops: "跨场景仲裁：计划维护/已恢复",
    cross_scenario_security_research_only: "跨场景仲裁：安全研究",
    cross_scenario_discussion_or_clarity: "跨场景仲裁：讨论或监管澄清",
  };

  return labels[normalized] || formatScoreReasonText(formatEvidenceSignal(normalized)) || "风险信号";
}

function formatScoreReasonText(value?: string) {
  const raw = (value || "").trim();
  if (!raw) return "";
  const normalized = raw
    .replace(/high_risk_route:(score_[a-z_]+)/g, (_, riskType: string) => `高风险路径：${formatRiskTypeCode(riskType)}`)
    .replace(/low_risk_gate_added:(score_[a-z_]+)/g, (_, riskType: string) => `低风险复核补充：${formatRiskTypeCode(riskType)}`)
    .replace(/primary_risk_type:(score_[a-z_]+)/g, (_, riskType: string) => `主风险：${formatRiskTypeCode(riskType)}`)
    .replace(/high_risk_floor:(score_[a-z_]+):(\d+)/g, (_, riskType: string, score: string) => `${formatRiskTypeCode(riskType)}：强信号保底 ${score}`)
    .replace(/(score_[a-z_]+),branch_score=(\d+)/g, (_, riskType: string, score: string) => `${formatRiskTypeCode(riskType)}：分支评分 ${score}`)
    .replace(/validator:(\d+)/g, "二次校验阈值 $1")
    .replace(/no_established_risk_type_branch/g, "未形成明确风险分支")
    .replace(/risk_type_branch_merge/g, "风险类型分支合并")
    .replace(/secondary_risk_bonus/g, "次要风险加权")
    .replace(/primary_branch_evidence_weak/g, "主风险证据偏弱")
    .replace(/high_risk_floor_signal/g, "触发高风险保底")
    .replace(/weak_rule_signal/g, "弱风险规则信号")
    .replace(/fast_exit/g, "快速低风险路径")
    .replace(/no_high_risk_scenario_detected/g, "未发现高风险场景")
    .replace(/candidate_scenarios_detected/g, "发现候选风险场景")
    .replace(/initial_high_risk_signal/g, "初筛发现高风险信号")
    .replace(/initial_rule_evidence_conflict/g, "规则信号与证据存在冲突")
    .replace(/low_risk_gate_escalated/g, "低风险门控已升级")
    .replace(/validator_cap_score/g, "二次校验压低评分")
    .replace(/validator_raise_floor/g, "二次校验抬高评分")
    .replace(/branch_score/g, "分支评分")
    .replace(/rule_score/g, "规则评分")
    .replace(/risk_type/g, "风险类型")
    .replace(/risk_name/g, "风险名称")
    .replace(/score_reason/g, "评分原因")
    .replace(/score_hack/g, "链上漏洞/攻击风险")
    .replace(/score_fraud/g, "诈骗/Rug Pull 风险")
    .replace(/score_regulatory/g, "监管与法律风险")
    .replace(/score_outage/g, "交易所与系统运维风险")
    .replace(/score_stablecoin/g, "稳定币异常风险")
    .replace(/score_liquidation/g, "爆仓/清算风险")
    .replace(/score_whale/g, "大额转账/巨鲸行为风险")
    .replace(/score_volatility/g, "异常行情波动风险")
    .replace(/score_team/g, "项目治理/团队异常风险")
    .replace(/score_solvency/g, "偿付能力/储备/流动性风险")
    .replace(/score_infra/g, "基础设施/协议层异常风险")
    .replace(/score_token_issuance/g, "代币发行/异常增发风险")
    .replace(/score_bridge/g, "跨链桥/跨链资金风险")
    .replace(/score_macro/g, "宏观/政策冲击风险")
    .replace(/Request timed out\./gi, "请求超时。")
    .replace(/request timed out/gi, "请求超时")
    .replace(/timed out/gi, "请求超时")
    .replace(/_/g, " ");
  return normalized.replace(/\s+/g, " ").trim();
}

function formatReportOriginalInput(input: string) {
  const cleaned = extractNewsBodyFromAnalysisInput(input);
  return cleaned || input;
}

function extractNewsBodyFromAnalysisInput(input: string) {
  const raw = (input || "").trim();
  if (!raw) return "";
  const lines = raw.split(/\r?\n/);
  const newsLineIndex = lines.findIndex((line) => line.trim().startsWith("新闻正文："));
  if (newsLineIndex >= 0) {
    const firstLine = lines[newsLineIndex].replace(/^新闻正文：/, "").trim();
    const bodyLines = [firstLine];
    for (let index = newsLineIndex + 1; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^(用户选中片段|已有摘要|已有证据|用户补充要求|新闻标题|发布时间|原始风险类别|原始风险分|关联币种|引用内容)：/.test(line.trim())) {
        break;
      }
      bodyLines.push(line);
    }
    return bodyLines.join("\n").trim();
  }

  const quoteLineIndex = lines.findIndex((line) => line.trim().startsWith("引用内容："));
  if (quoteLineIndex >= 0) {
    return lines[quoteLineIndex].replace(/^引用内容：/, "").trim();
  }
  return raw;
}

function formatRiskStatus(value?: string) {
  const labels: Record<string, string> = {
    low_risk: "低风险",
    potential_risk: "潜在风险",
    confirmed_risk: "已确认风险",
    insufficient_evidence: "证据不足",
    resolved_or_mitigated: "已缓解或受限",
    false_positive_suppressed: "误报已抑制",
  };
  return labels[String(value || "")] || value || "待确认";
}

function formatEnginePath(value?: string) {
  const labels: Record<string, string> = {
    fast_exit: "快速低风险路径",
    deep_analysis: "完整案件分析",
  };
  return labels[String(value || "")] || value || "待确认";
}

function formatAgentSource(value?: string) {
  const labels: Record<string, string> = {
    llm: "LLM Agent",
    fallback: "规则兜底",
    weak_risk_guard: "弱风险保护",
    fallback_weak_risk_guard: "弱风险保护",
  };
  return labels[String(value || "")] || value || "待确认";
}

function detectWeakRisk(
  result: ChatAgentResult,
  meta: FinalContextMeta,
  impact: ImpactAnalysis,
  advice: AdviceGeneration,
) {
  const sources = [impact.source, advice.source].map((item) => String(item || ""));
  return Boolean(
    result.is_weak_risk
      || meta.is_weak_risk
      || sources.some((source) => source.includes("weak_risk"))
      || result.report_mode === "fast_exit",
  );
}

function ReportSection({
  children,
  icon,
  title,
  variant = "default",
}: {
  children: ReactNode;
  icon: ReactNode;
  title: string;
  variant?: "default" | "main" | "side";
}) {
  const sectionStyle = {
    default: "risk-panel rounded-lg p-5",
    main: "rounded-lg border border-blue-100 bg-white p-5 shadow-sm shadow-blue-100/50",
    side: "rounded-lg border border-blue-100 bg-white p-4 shadow-sm shadow-blue-100/50",
  }[variant];

  return (
    <section className={sectionStyle}>
      <div className={`${variant === "side" ? "mb-3" : "mb-4"} flex items-center gap-2`}>
        <span className="text-blue-600">{icon}</span>
        <h3 className="text-base font-bold text-slate-950">{title}</h3>
      </div>
      {children}
    </section>
  );
}

function DistributionCard({
  high,
  low,
  mid,
  midHigh,
  total,
}: {
  high: number;
  low: number;
  mid: number;
  midHigh: number;
  total: number;
}) {
  const safeTotal = Math.max(total, 1);
  const highEnd = (high / safeTotal) * 100;
  const midHighEnd = highEnd + (midHigh / safeTotal) * 100;
  const midEnd = midHighEnd + (mid / safeTotal) * 100;
  const chartStyle = {
    background: `conic-gradient(#ef4444 0 ${highEnd}%, #f97316 ${highEnd}% ${midHighEnd}%, #facc15 ${midHighEnd}% ${midEnd}%, #10b981 ${midEnd}% 100%)`,
  };

  return (
    <section className="risk-card rounded-lg p-5">
      <PanelTitle icon={<ChartIcon />} title="风险等级分布" />
      <div className="mt-5 grid gap-5 sm:grid-cols-[170px_minmax(0,1fr)]">
        <div className="relative h-40 w-40 rounded-full" style={chartStyle}>
          <div className="absolute inset-8 flex flex-col items-center justify-center rounded-full bg-white">
            <span className="text-3xl font-bold text-slate-700">{total.toLocaleString()}</span>
            <span className="text-sm text-slate-500">总数</span>
          </div>
        </div>
        <div className="space-y-3 text-sm">
          <Legend color="bg-red-500" label="高风险" value={high} />
          <Legend color="bg-orange-500" label="中高风险" value={midHigh} />
          <Legend color="bg-yellow-400" label="中风险" value={mid} />
          <Legend color="bg-emerald-500" label="低风险" value={low} />
        </div>
      </div>
    </section>
  );
}

function NewsRiskOverviewCard({ items }: { items: NewsRankingItem[] }) {
  const redAlerts = items.filter(isRedAlertNews).slice(0, 3);
  const categories = getNewsCategoryOptions(items).slice(0, 6).map((category) => ({
    category,
    count: items.filter((item) => normalizeRiskType(item.risk_type) === category).length,
  }));

  return (
    <section className="risk-card rounded-lg p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <PanelTitle icon={<ChartIcon />} title="新闻风险概览" />
          <p className="mt-1 text-xs font-semibold text-slate-500">新闻是离散事件，这里只展示类别和红色预警摘要</p>
        </div>
        <span className="rounded-lg border border-blue-100 px-2 py-1 text-xs font-semibold text-slate-500">{items.length} 条新闻</span>
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,0.45fr)_minmax(0,0.55fr)]">
        <div className="space-y-2">
          {categories.length ? categories.map((item) => (
            <div className="flex items-center justify-between rounded-lg border border-blue-100 bg-slate-50 px-3 py-2 text-sm" key={item.category}>
              <span className="font-semibold text-slate-700">{item.category}</span>
              <span className="font-bold text-blue-700">{item.count}</span>
            </div>
          )) : (
            <div className="rounded-lg border border-dashed border-blue-100 bg-slate-50 px-3 py-6 text-center text-sm font-semibold text-slate-500">暂无类别数据</div>
          )}
        </div>
        <div className="rounded-lg border border-red-100 bg-red-50/50 p-3">
          <p className="text-xs font-bold text-red-700">红色预警</p>
          <div className="mt-2 space-y-2">
            {redAlerts.length ? redAlerts.map((item) => (
              <div className="rounded-md bg-white px-3 py-2" key={item.news_id}>
                <p className="line-clamp-1 text-sm font-bold text-slate-950">{item.title}</p>
                <p className="mt-1 text-xs font-semibold text-red-600">风险分 {clampScore(item.risk_score)} · {formatScoreReasonText(item.risk_type || "综合风险")}</p>
              </div>
            )) : (
              <p className="rounded-md bg-white px-3 py-6 text-center text-sm font-semibold text-slate-500">当前没有红色预警新闻</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function CoinRiskTrendCard({ items, range }: { items: CoinRankingItem[]; range: RankingRange }) {
  const rankedSymbols = useMemo(() => items.slice(0, 6).map((item) => item.symbol), [items]);
  const [symbolToAdd, setSymbolToAdd] = useState("");
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([]);
  const effectiveSymbolToAdd = symbolToAdd || rankedSymbols[0] || "";
  const selectedActiveSymbols = selectedSymbols.filter((symbol) => rankedSymbols.includes(symbol)).slice(0, 3);
  const activeSymbols = selectedActiveSymbols.length ? selectedActiveSymbols : rankedSymbols.slice(0, 3);
  const palette = ["#2563eb", "#f97316", "#10b981", "#dc2626", "#7c3aed", "#0f766e"];
  const seriesSets = activeSymbols.map((symbol, index) => {
    const item = items.find((coin) => coin.symbol === symbol);
    return {
      color: palette[index % palette.length],
      label: symbol,
      points: item ? buildCoinTrendSeries(item, range) : [],
    };
  });

  function addSymbol() {
    if (!effectiveSymbolToAdd) return;
    setSelectedSymbols((current) => {
      if (current.includes(effectiveSymbolToAdd)) return current;
      return [...current, effectiveSymbolToAdd].slice(-3);
    });
  }

  function removeSymbol(symbol: string) {
    setSelectedSymbols((current) => {
      const next = current.filter((item) => item !== symbol);
      return next.length ? next : rankedSymbols.slice(0, 1);
    });
  }

  return (
    <section className="risk-card rounded-lg p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <PanelTitle icon={<ChartIcon />} title="热门币种风险趋势" />
          <p className="mt-1 text-xs font-semibold text-slate-500">点击币种对比，最多同时展示 3 条风险曲线</p>
        </div>
        <span className="rounded-lg border border-blue-100 px-2 py-1 text-xs font-semibold text-slate-500">
          {range === "24h" ? "近1天" : "近7天"}
        </span>
      </div>
      <MultiLineTrendChart className="mt-5 h-44" seriesSets={seriesSets} />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-600">
        <label className="font-bold text-slate-500" htmlFor="coin-trend-symbol">选择币种</label>
        <select
          id="coin-trend-symbol"
          value={effectiveSymbolToAdd}
          onChange={(event) => setSymbolToAdd(event.target.value)}
          className="h-9 rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-slate-700 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-blue-300"
        >
          {rankedSymbols.map((symbol) => (
            <option key={symbol} value={symbol}>{symbol}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={addSymbol}
          disabled={!effectiveSymbolToAdd || activeSymbols.includes(effectiveSymbolToAdd)}
          className="h-9 rounded-lg bg-blue-600 px-3 text-xs font-bold text-white transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          添加到图表
        </button>
        <div className="flex flex-wrap gap-2">
          {activeSymbols.map((symbol) => (
            <button
              key={symbol}
              type="button"
              onClick={() => removeSymbol(symbol)}
              className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-blue-700 transition-colors duration-200 hover:border-red-200 hover:bg-red-50 hover:text-red-600"
              aria-label={`移除 ${symbol}`}
            >
              {symbol} ×
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function RiskBadge({ level }: { level: string }) {
  const style = riskLevelStyle(level);
  return <span className={`inline-flex rounded-lg px-3 py-1 text-xs font-bold ${style}`}>{level || "低风险"}</span>;
}

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-blue-600">{icon}</span>
      <h2 className="font-bold text-slate-950">{title}</h2>
    </div>
  );
}

function DailyMetricCard({
  icon,
  label,
  tone,
  value,
}: {
  icon: ReactNode;
  label: string;
  tone: MetricTone;
  value: string;
}) {
  const toneClass = {
    blue: "border-blue-100 bg-blue-50 text-blue-700",
    red: "border-rose-100 bg-rose-50 text-rose-700",
    orange: "border-orange-100 bg-orange-50 text-orange-700",
    green: "border-emerald-100 bg-emerald-50 text-emerald-700",
    purple: "border-violet-100 bg-violet-50 text-violet-700",
  }[tone];

  return (
    <div className={`rounded-lg border p-4 ${toneClass}`}>
      <div className="flex items-center justify-between gap-3">
        <span>{icon}</span>
        <span className="text-2xl font-bold">{value}</span>
      </div>
      <p className="mt-2 text-xs font-bold uppercase tracking-[0.14em] opacity-80">{label}</p>
    </div>
  );
}

function RangeSegmentedControl({
  onChangeRange,
  range,
}: {
  onChangeRange: (range: RankingRange) => void;
  range: RankingRange;
}) {
  const options: Array<[RankingRange, string]> = [
    ["24h", "近1天"],
    ["7d", "近7天"],
  ];

  return (
    <div className="flex h-10 rounded-lg border border-blue-100 bg-slate-50 p-1">
      {options.map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => onChangeRange(value)}
          className={`h-8 rounded-md px-3 text-sm font-bold transition-colors duration-200 ${
            range === value
              ? "bg-blue-600 text-white shadow-sm shadow-blue-100"
              : "text-slate-500 hover:bg-white hover:text-blue-700"
          }`}
          aria-pressed={range === value}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function Notice({ text, tone }: { text: string; tone: "red" | "amber" }) {
  const style = tone === "red" ? "border-red-100 bg-red-50 text-red-700" : "border-amber-100 bg-amber-50 text-amber-700";
  return <div className={`rounded-lg border px-4 py-3 text-sm font-semibold ${style}`}>{text}</div>;
}

function TableFooter({ text }: { text: string }) {
  return <p className="mt-4 text-sm text-slate-500">{text}</p>;
}

function Legend({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="flex items-center gap-2 text-slate-600">
        <span className={`h-2 w-2 rounded-full ${color}`} />
        {label}
      </span>
      <span className="font-semibold text-slate-700">{value}</span>
    </div>
  );
}

function SparklineChart({
  ariaLabel,
  className,
  series,
  tone,
}: {
  ariaLabel: string;
  className?: string;
  series: TrendPoint[];
  tone: MetricTone;
}) {
  const color = getToneColor(tone);
  const width = 96;
  const height = 36;
  const points = getChartPoints(normalizeTrendSeries(series), width, height, 3);
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const latest = series[series.length - 1];
  const latestPoint = points[points.length - 1];
  const title = latest ? `${latest.label}: ${latest.value}` : ariaLabel;
  return (
    <svg className={className || "h-8 w-20"} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
      <title>{title}</title>
      <polyline points={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      {latestPoint && <circle cx={latestPoint.x} cy={latestPoint.y} r="2.5" fill={color} />}
    </svg>
  );
}

function MultiLineTrendChart({
  className,
  seriesSets,
}: {
  className?: string;
  seriesSets: Array<{ color: string; label: string; points: TrendPoint[] }>;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const width = 420;
  const height = 180;
  const padding = 18;
  const allValues = seriesSets.flatMap((set) => set.points.map((point) => point.value));
  const domain = getValueDomain(allValues, undefined);
  const lineSets = seriesSets.map((set) => {
    const normalized = normalizeTrendSeries(set.points);
    return {
      ...set,
      normalized,
      points: getChartPoints(normalized, width, height, padding, undefined, domain),
    };
  });
  const baseLength = Math.max(...lineSets.map((set) => set.normalized.length), 1);
  const activeIndex = Math.min(hoverIndex ?? baseLength - 1, baseLength - 1);
  const firstPoint = lineSets[0]?.points[activeIndex];

  function handleMouseMove(event: ReactMouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || baseLength <= 1) return;
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    setHoverIndex(Math.round(ratio * (baseLength - 1)));
  }

  return (
    <div className={`relative rounded-lg bg-slate-50 p-3 ${className || ""}`}>
      <svg
        ref={svgRef}
        className="h-full w-full"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="币种风险对比趋势图"
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={handleMouseMove}
      >
        {[0.25, 0.5, 0.75].map((ratio) => (
          <line key={ratio} x1={padding} x2={width - padding} y1={height * ratio} y2={height * ratio} stroke="#dbeafe" strokeDasharray="4 4" />
        ))}
        {lineSets.map((set) => (
          <path
            key={set.label}
            d={pointsToPath(set.points)}
            fill="none"
            stroke={set.color}
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="3"
          />
        ))}
        {firstPoint && <line x1={firstPoint.x} x2={firstPoint.x} y1={padding} y2={height - padding} stroke="#bfdbfe" strokeDasharray="3 4" />}
      </svg>
      {firstPoint && (
        <div
          className="pointer-events-none absolute top-4 rounded-lg border border-blue-100 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-lg"
          style={{ left: `${Math.min(78, Math.max(4, (firstPoint.x / width) * 100))}%` }}
        >
          <p className="font-bold text-slate-900">{lineSets[0]?.normalized[activeIndex]?.label || "趋势点"}</p>
          {lineSets.map((set) => (
            <p key={set.label} className="mt-1" style={{ color: set.color }}>
              {set.label}: {set.normalized[activeIndex]?.value ?? "--"}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function CoinMark({ large = false, symbol }: { large?: boolean; symbol: string }) {
  const colors = ["bg-slate-950", "bg-blue-600", "bg-orange-500", "bg-emerald-500", "bg-violet-600"];
  const color = colors[symbol.charCodeAt(0) % colors.length];
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-full ${color} font-bold text-white ${large ? "h-14 w-14 text-lg" : "h-7 w-7 text-xs"}`}>
      {symbol.slice(0, 1)}
    </span>
  );
}

function getPageMeta(view: ActiveView) {
  const map = {
    home: ["CryptoRisk Agent 风控看板", "多智能体加密风险监测平台"],
    chat: ["事件风险分析", "面向新闻 / 公告 / 链上事件的多智能体风险研判"],
    news: ["新闻风险榜", "基于新闻文本与风险规则的实时风险排行"],
    coin: ["币种风险榜", "基于新闻、公告与链上事件聚合的币种风险排行"],
    daily: ["资产日报", "自动聚合并分析与你关注资产相关的今日风险"],
    portfolio: ["我的风险资产", "Portfolio Risk Radar 个性化资产风险监控"],
    sim: ["模拟交易盘", "基于最近 7 天 15 分钟 K 线的现货模拟回放"],
    reports: ["分析报告", "查看、管理与导出风险分析结果报告"],
    favoriteNews: ["收藏新闻", "个人风险情报收藏库"],
    favoriteReports: ["收藏报告", "已收藏的 Agent 风控研判档案"],
    my: ["我的风控档案库", "关注资产与近期预警待处理事项"],
    settings: ["系统设置", "Agent 运行状态与新闻更新"],
  } satisfies Record<ActiveView, [string, string]>;

  return { title: map[view][0], subtitle: map[view][1] };
}

function favoriteString(favorite: FavoriteItem, key: string, fallback = "") {
  const value = favorite.payload[key];
  return typeof value === "string" && value.trim() ? value : fallback;
}

function favoriteNumber(favorite: FavoriteItem, key: string) {
  const value = favorite.payload[key];
  return typeof value === "number" ? clampScore(value) : 0;
}

function favoriteStringArray(favorite: FavoriteItem, key: string) {
  const value = favorite.payload[key];
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
    : [];
}

function favoriteRecord(favorite: FavoriteItem, key: string) {
  const value = favorite.payload[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function buildFavoriteNewsAnalysisInput(favorite: FavoriteItem) {
  const content = favoriteString(favorite, "content", favoriteString(favorite, "summary", favorite.title));
  return buildNewsAnalysisInput({
    title: favorite.title,
    content,
    published_at: favoriteString(favorite, "published_at", favorite.created_at),
    date: favorite.created_at,
    risk_type: favoriteString(favorite, "risk_type", "综合风险"),
    risk_level: favoriteString(favorite, "risk_level", "未标记"),
    risk_score: favoriteNumber(favorite, "risk_score"),
    coins: favoriteStringArray(favorite, "coins"),
    summary: favoriteString(favorite, "summary", ""),
    evidence: favoriteString(favorite, "evidence", ""),
    source_url: favoriteString(favorite, "source_url", ""),
  });
}

function buildReportTitle(input: string, report: RiskReport): string {
  const source = report.risk_categories?.[0] || input;
  const compact = input
    .replace(/[，。！？,.!?]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .join("");
  return `${compact || source || "事件"}风险分析报告`;
}

function buildHomePriorities(newsItems: NewsRankingItem[], coinItems: CoinRankingItem[]) {
  const topNews = newsItems[0];
  const topCoin = coinItems[0];
  const highRiskCount = newsItems.filter((item) => isHighRiskNews(item)).length;
  return [
    {
      title: topNews ? `先核验：${topNews.title}` : "先生成今日新闻风险榜",
      detail: topNews
        ? `${formatScoreReasonText(topNews.risk_type || "综合风险")} · 风险分 ${clampScore(topNews.risk_score)}`
        : "当前还没有真实排行榜数据，建议先在系统设置中更新新闻。",
      action: "查看新闻证据",
      view: "news" as ActiveView,
      tone: "red" as const,
    },
    {
      title: topCoin ? `关注 ${topCoin.symbol} 风险聚合` : "关注币种风险聚合",
      detail: topCoin
        ? `${formatScoreReasonText(topCoin.main_risk_type || "综合风险")} · 相关新闻 ${topCoin.news_count} 条`
        : "币种风险需要新闻标注后才能形成聚合分数。",
      action: "查看币种风险榜",
      view: "coin" as ActiveView,
      tone: "orange" as const,
    },
    {
      title: highRiskCount ? `处理 ${highRiskCount} 条高风险事件` : "建立个人资产监控",
      detail: highRiskCount
        ? "优先把红色预警与高风险新闻转为报告并记录处置状态。"
        : "添加关注资产后，日报和资产雷达会给出个性化命中。",
      action: highRiskCount ? "进入事件分析" : "进入我的风险资产",
      view: highRiskCount ? "chat" as ActiveView : "portfolio" as ActiveView,
      tone: "blue" as const,
    },
  ];
}

function formatTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatCompactDateTime(value: string): string {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value || "--";
  return formatTimestamp(date);
}

function formatSecurityEventType(value: string): string {
  const labels: Record<string, string> = {
    account_delete: "删除账号",
    account_export: "导出账号数据",
    login: "登录成功",
    logout: "退出登录",
    password_change: "修改密码",
    register: "注册账号",
    sessions_revoke_others: "撤销其他会话",
  };
  return labels[value] || value || "账号事件";
}

function formatSessionUserAgent(value?: string): string {
  const text = (value || "").trim();
  if (!text) return "--";
  if (/Edg\//i.test(text)) return "Microsoft Edge";
  if (/Chrome\//i.test(text) && !/Chromium/i.test(text)) return "Chrome";
  if (/Firefox\//i.test(text)) return "Firefox";
  if (/Safari\//i.test(text) && !/Chrome\//i.test(text)) return "Safari";
  return text.length > 48 ? `${text.slice(0, 48)}...` : text;
}

function formatSecurityEventContext(event: AccountSecurityEvent): string {
  const userAgent = typeof event.payload.user_agent === "string" ? formatSessionUserAgent(event.payload.user_agent) : "--";
  const ipHash = typeof event.payload.client_ip_hash === "string" && event.payload.client_ip_hash ? event.payload.client_ip_hash : "--";
  return `客户端 ${userAgent} · IP 摘要 ${ipHash}`;
}

function buildNewsTrendBuckets(items: NewsRankingItem[], range: RankingRange): NewsTrendBucket[] {
  const count = range === "24h" ? 12 : 7;
  const stepMs = range === "24h" ? 2 * 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  const timestamps = items.map(newsTimeValue).filter((value) => value > 0);
  const end = timestamps.length ? Math.max(...timestamps) : Date.now();
  const start = end - stepMs * (count - 1);
  const sums = Array.from({ length: count }, () => 0);
  const totals = Array.from({ length: count }, () => 0);
  const highCounts = Array.from({ length: count }, () => 0);
  const redCounts = Array.from({ length: count }, () => 0);

  items.forEach((item) => {
    const timestamp = newsTimeValue(item) || end;
    const index = Math.max(0, Math.min(count - 1, Math.floor((timestamp - start) / stepMs)));
    const score = clampScore(item.risk_score);
    sums[index] += score;
    totals[index] += 1;
    if (isHighRiskNews(item)) highCounts[index] += 1;
    if (isRedAlertNews(item)) redCounts[index] += 1;
  });

  let previousAverage = items.length ? getAverageRiskScore(items) : 0;
  return Array.from({ length: count }, (_, index) => {
    const timestamp = start + index * stepMs;
    const avgScore = totals[index] ? Math.round(sums[index] / totals[index]) : previousAverage;
    previousAverage = avgScore || previousAverage;
    return {
      avgScore,
      highCount: highCounts[index],
      label: formatTrendLabel(timestamp, range),
      newsCount: totals[index],
      redCount: redCounts[index],
      timestamp,
    };
  });
}

function buildCoinTrendSeries(item: CoinRankingItem, range: RankingRange): TrendPoint[] {
  const count = range === "24h" ? 12 : 7;
  const stepMs = range === "24h" ? 2 * 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  const related = item.related_news || [];
  const timestamps = related.map((news) => parseLooseTimestamp(news.published_at)).filter((value) => value > 0);
  const end = timestamps.length ? Math.max(...timestamps) : Date.now();
  const start = end - stepMs * (count - 1);
  const sums = Array.from({ length: count }, () => 0);
  const totals = Array.from({ length: count }, () => 0);

  related.forEach((news) => {
    const timestamp = parseLooseTimestamp(news.published_at) || end;
    const index = Math.max(0, Math.min(count - 1, Math.floor((timestamp - start) / stepMs)));
    sums[index] += clampScore(news.risk_score);
    totals[index] += 1;
  });

  if (!related.length || totals.every((value) => value === 0)) {
    return buildFallbackTrendSeries(clampScore(item.final_score), range);
  }

  let previous = clampScore(item.final_score);
  return Array.from({ length: count }, (_, index) => {
    const timestamp = start + index * stepMs;
    const value = totals[index] ? Math.round(sums[index] / totals[index]) : previous;
    previous = value;
    return {
      label: formatTrendLabel(timestamp, range),
      value,
      timestamp,
      meta: { 相关新闻: totals[index] },
    };
  });
}

function buildFallbackTrendSeries(score: number, range: RankingRange = "7d"): TrendPoint[] {
  const count = range === "24h" ? 12 : 7;
  const stepMs = range === "24h" ? 2 * 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  const end = Date.now();
  const safeScore = clampScore(score || 40);
  return Array.from({ length: count }, (_, index) => {
    const offset = Math.round(Math.sin((index + 1) * 1.4) * 5 + (index - count + 1) * 0.8);
    const timestamp = end - (count - index - 1) * stepMs;
    return {
      label: formatTrendLabel(timestamp, range),
      value: clampScore(safeScore + offset),
      timestamp,
    };
  });
}

function buildFlatTrendSeries(value: number, range: RankingRange = "7d"): TrendPoint[] {
  const count = range === "24h" ? 12 : 7;
  const stepMs = range === "24h" ? 2 * 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
  const end = Date.now();
  return Array.from({ length: count }, (_, index) => {
    const timestamp = end - (count - index - 1) * stepMs;
    return {
      label: formatTrendLabel(timestamp, range),
      value,
      timestamp,
    };
  });
}

function buildCoinAggregateTrendSeries(
  items: CoinRankingItem[],
  range: RankingRange,
  metric: "avg_score" | "high_count" | "news_count"
): TrendPoint[] {
  if (!items.length) return buildFlatTrendSeries(0, range);
  const perCoin = items.map((item) => buildCoinTrendSeries(item, range));
  const length = perCoin[0]?.length || (range === "24h" ? 12 : 7);
  return Array.from({ length }, (_, index) => {
    const points = perCoin.map((series) => series[index]).filter(Boolean);
    const timestamp = points[0]?.timestamp || Date.now();
    const value = (() => {
      if (metric === "avg_score") {
        return Math.round(points.reduce((sum, point) => sum + point.value, 0) / Math.max(points.length, 1));
      }
      if (metric === "high_count") {
        return points.filter((point) => point.value >= 80).length;
      }
      return points.reduce((sum, point) => sum + Number(point.meta?.相关新闻 || 0), 0);
    })();
    return {
      label: points[0]?.label || formatTrendLabel(timestamp, range),
      value,
      timestamp,
    };
  });
}

function getMetricDelta(series: TrendPoint[]) {
  const normalized = normalizeTrendSeries(series);
  const latest = normalized[normalized.length - 1]?.value || 0;
  const previous = normalized[normalized.length - 2]?.value || 0;
  const delta = latest - previous;
  const percent = previous ? (delta / previous) * 100 : 0;
  return {
    delta: `${delta >= 0 ? "+" : ""}${delta}`,
    deltaPercent: previous ? `${delta >= 0 ? "+" : ""}${percent.toFixed(1)}%` : "—",
    deltaTone: delta > 0 ? "up" as const : delta < 0 ? "down" as const : "neutral" as const,
  };
}

function deltaTextClass(tone: "up" | "down" | "neutral") {
  if (tone === "up") return "text-emerald-600";
  if (tone === "down") return "text-red-600";
  return "text-slate-500";
}

function getNewsCategoryOptions(items: NewsRankingItem[]) {
  return Array.from(new Set(items.map((item) => normalizeRiskType(item.risk_type)).filter(Boolean))).slice(0, 12);
}

function normalizeRiskType(value: string) {
  return formatScoreReasonText(value || "综合风险").replace(/\s+/g, "").replace(/[｜|]/g, "/") || "综合风险";
}

function getCoinRiskSources(item: CoinRankingItem) {
  const rawSources = [
    item.main_risk_type,
    ...(item.related_news || []).map((news) => news.risk_type),
  ]
    .join("/")
    .split(/[\/、,，|｜]/)
    .map((value) => mapRiskSource(value.trim()))
    .filter(Boolean);
  const unique = Array.from(new Set(rawSources));
  return unique.length ? unique.slice(0, 3) : ["综合风险"];
}

function mapRiskSource(value: string) {
  if (!value) return "";
  if (/监管|政策|制裁/.test(value)) return "监管";
  if (/漏洞|攻击|合约|安全|链上/.test(value)) return "合约安全";
  if (/交易所|提现|下架|平台/.test(value)) return "交易所";
  if (/清算|波动|价格|暴跌|行情/.test(value)) return "异常波动";
  if (/舆情|社区|传闻|社媒/.test(value)) return "社区舆情";
  if (/流动性|脱锚|挤兑|储备/.test(value)) return "流动性";
  if (/项目|跑路|团队|代币/.test(value)) return "项目方";
  return value.slice(0, 8);
}

function getCoinKeyEvent(item: CoinRankingItem) {
  const topRelated = [...(item.related_news || [])].sort((a, b) => clampScore(b.risk_score) - clampScore(a.risk_score))[0];
  return topRelated?.title || item.top_news_title || item.summary || "暂无关键事件";
}

function getToneColor(tone: MetricTone) {
  return {
    blue: "#2563eb",
    red: "#dc2626",
    orange: "#f97316",
    green: "#10b981",
    purple: "#7c3aed",
  }[tone];
}

function getRiskTone(score: number): MetricTone {
  const value = clampScore(score);
  if (value >= 80) return "red";
  if (value >= 60) return "orange";
  if (value < 35) return "green";
  return "blue";
}

function normalizeTrendSeries(series: TrendPoint[]) {
  if (series.length >= 2) return series;
  if (series.length === 1) {
    return [
      { ...series[0], label: `${series[0].label}-前` },
      series[0],
    ];
  }
  return buildFallbackTrendSeries(40);
}

function getChartPoints(
  series: TrendPoint[],
  width: number,
  height: number,
  padding: number,
  threshold?: number,
  domain?: { min: number; max: number }
) {
  const normalized = normalizeTrendSeries(series);
  const valueDomain = domain || getValueDomain(normalized.map((point) => point.value), threshold);
  const range = Math.max(1, valueDomain.max - valueDomain.min);
  return normalized.map((point, index) => {
    const x = padding + (index / Math.max(1, normalized.length - 1)) * (width - padding * 2);
    const y = height - padding - ((point.value - valueDomain.min) / range) * (height - padding * 2);
    return { x, y };
  });
}

function getValueDomain(values: number[], threshold?: number) {
  const allValues = threshold === undefined ? values : [...values, threshold];
  if (!allValues.length) return { min: 0, max: 100 };
  const minValue = Math.min(...allValues, 0);
  const maxValue = Math.max(...allValues, 10);
  if (minValue === maxValue) {
    return { min: Math.max(0, minValue - 10), max: maxValue + 10 };
  }
  const padding = Math.max(4, Math.round((maxValue - minValue) * 0.12));
  return {
    min: Math.max(0, minValue - padding),
    max: Math.min(100, maxValue + padding),
  };
}

function pointsToPath(points: Array<{ x: number; y: number }>) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x},${point.y}`).join(" ");
}

function formatTrendLabel(timestamp: number, range: RankingRange) {
  const date = new Date(timestamp);
  const pad = (value: number) => String(value).padStart(2, "0");
  if (range === "24h") return `${pad(date.getHours())}:00`;
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function parseLooseTimestamp(value: string) {
  if (!value) return 0;
  const normalized = value.includes("T") ? value : value.replace(/-/g, "/");
  const timestamp = Date.parse(normalized);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function getVisibleNewsItems(items: NewsRankingItem[], filter: NewsFilter, sort: NewsSort) {
  const filtered = items.filter((item) => {
    if (filter === "all" || filter === "top10") return true;
    if (filter === "high") return isHighRiskNews(item);
    if (filter === "medium") return isMediumRiskNews(item);
    if (filter === "red") return isRedAlertNews(item);
    return isLowRiskNews(item);
  });

  const scoped = filter === "top10"
    ? [...filtered].sort((a, b) => clampScore(b.risk_score) - clampScore(a.risk_score)).slice(0, 10)
    : filtered;

  return [...scoped].sort((a, b) => compareNews(a, b, sort));
}

function getNewsDistribution(items: NewsRankingItem[]) {
  const high = items.filter(isHighRiskNews).length;
  const midHigh = items.filter((item) => {
    const score = clampScore(item.risk_score);
    const level = item.risk_level || "";
    return !isHighRiskNews(item) && (level.includes("中高") || (score >= 70 && score < 80));
  }).length;
  const mid = items.filter((item) => {
    const score = clampScore(item.risk_score);
    return !isHighRiskNews(item) && score >= 40 && score < 70;
  }).length;
  const low = Math.max(0, items.length - high - midHigh - mid);

  return {
    total: items.length,
    high,
    midHigh,
    mid,
    low,
  };
}

function buildDailyRiskReport(range: RankingRange, agentReport: DailyRiskReport) {
  return {
    alertLevel: agentReport.alert_level,
    averageScore: clampScore(agentReport.average_score),
    personalScore: clampScore(agentReport.personal_risk_score),
    generatedAt: agentReport.generated_at || getDailyGeneratedAt([], range),
    createdAt: agentReport.created_at || agentReport.saved_at || "",
    generationDate: agentReport.generation_date || "",
    headline: agentReport.headline || "资产日报",
    highCount: agentReport.high_count || 0,
    personalHighCount: agentReport.personal_high_count || 0,
    riskThemes: mapAgentDailyThemes(agentReport.risk_themes || []),
    assetReports: mapAgentDailyAssetReports(agentReport.asset_reports || []),
    newsCount: agentReport.news_count || 0,
    redCount: agentReport.red_count || 0,
    personalRedCount: agentReport.personal_red_count || 0,
    userAssetsCount: agentReport.user_assets_count || 0,
    holdingAssetsCount: agentReport.holding_assets_count || 0,
    affectedAssets: agentReport.affected_assets || [],
    riskTypes: (agentReport.risk_types || []).map((item) => ({
      name: item.name,
      count: item.count,
      highCount: item.high_count,
      maxScore: item.max_score,
      weight: item.weight,
    })),
    summary: agentReport.summary,
    watchCoins: (agentReport.watch_coins || []).map((item) => ({
      symbol: item.symbol,
      name: item.name || item.symbol,
      score: clampScore(item.score),
      level: item.level,
      newsCount: item.news_count,
      riskType: item.risk_type,
      isHolding: item.is_holding,
      exposureMode: item.exposure_mode,
      exposureBucket: item.exposure_bucket,
      marketValue: item.market_value,
      priceChange24h: item.price_change_24h,
      alertThreshold: item.alert_threshold,
    })),
    actions: sanitizeAdvice(agentReport.actions || []),
    focusPoints: agentReport.focus_points || [],
    impactSummary: agentReport.impact_summary || "",
    source: agentReport.source,
  };
}

function mapAgentDailyThemes(themes: DailyRiskReport["risk_themes"]): DailyRiskTheme[] {
  return themes.map((item) => ({
    themeId: item.theme_id,
    title: item.title,
    riskType: item.risk_type,
    affectedAssets: item.affected_assets || [],
    eventCount: item.event_count,
    maxPersonalScore: clampScore(item.max_personal_score),
    riskLevel: item.risk_level,
    summary: item.summary,
    severityReason: item.severity_reason,
    evidenceSummary: item.evidence_summary || [],
    monitoringItems: item.monitoring_items || [],
  }));
}

function mapAgentDailyAssetReports(items: DailyRiskReport["asset_reports"]): DailyAssetReport[] {
  return items.map((item) => ({
    assetSymbol: item.asset_symbol,
    assetName: item.asset_name || item.asset_symbol,
    isHolding: Boolean(item.is_holding),
    exposureLabel: item.exposure_label || (item.is_holding ? "持仓资产" : "关注资产"),
    exposureMode: item.exposure_mode,
    exposureBucket: item.exposure_bucket,
    marketValue: item.market_value,
    priceChange24h: item.price_change_24h,
    alertThreshold: item.alert_threshold,
    personalRiskScore: clampScore(item.personal_risk_score),
    riskLevel: item.risk_level,
    summary: item.summary,
    riskTypes: item.risk_types || [],
    keyDrivers: item.key_drivers || [],
    evidenceSummary: item.evidence_summary || [],
    monitoringItems: item.monitoring_items || [],
    actions: sanitizeAdvice(item.actions || []),
    sourceEventCount: item.source_event_count || 0,
  }));
}

function getDailyGeneratedAt(items: NewsRankingItem[], range: RankingRange) {
  const latest = [...items]
    .map((item) => item.published_at || item.date)
    .filter(Boolean)
    .sort()
    .pop();
  return latest || (range === "24h" ? "近1天新闻窗口" : "近7天新闻窗口");
}

function getCoinDistribution(items: CoinRankingItem[]) {
  const high = items.filter(isHighRiskCoin).length;
  const midHigh = items.filter((item) => {
    const score = clampScore(item.final_score);
    const level = item.risk_level || "";
    return !isHighRiskCoin(item) && (level.includes("中高") || (score >= 70 && score < 80));
  }).length;
  const mid = items.filter((item) => {
    const score = clampScore(item.final_score);
    return !isHighRiskCoin(item) && score >= 40 && score < 70;
  }).length;
  const low = Math.max(0, items.length - high - midHigh - mid);

  return {
    total: items.length,
    high,
    midHigh,
    mid,
    low,
  };
}

function getAverageRiskScore(items: NewsRankingItem[]) {
  if (!items.length) return 0;
  const total = items.reduce((sum, item) => sum + clampScore(item.risk_score), 0);
  return Math.round(total / items.length);
}

function getAverageCoinRiskScore(items: CoinRankingItem[]) {
  if (!items.length) return 0;
  const total = items.reduce((sum, item) => sum + clampScore(item.final_score), 0);
  return Math.round(total / items.length);
}

function getRedAlertCount(items: NewsRankingItem[]) {
  return items.filter(isRedAlertNews).length;
}

function compareNews(a: NewsRankingItem, b: NewsRankingItem, sort: NewsSort) {
  if (sort === "score_desc") return clampScore(b.risk_score) - clampScore(a.risk_score);
  if (sort === "score_asc") return clampScore(a.risk_score) - clampScore(b.risk_score);
  if (sort === "time_desc") return newsTimeValue(b) - newsTimeValue(a);
  return newsTimeValue(a) - newsTimeValue(b);
}

function getVisibleCoinItems(items: CoinRankingItem[], filter: CoinFilter, sort: CoinSort) {
  const filtered = items.filter((item) => {
    if (filter === "all" || filter === "top10") return true;
    if (filter === "high") return isHighRiskCoin(item);
    if (filter === "medium") return isMediumRiskCoin(item);
    return isLowRiskCoin(item);
  });

  const scoped = filter === "top10"
    ? [...filtered].sort((a, b) => clampScore(b.final_score) - clampScore(a.final_score)).slice(0, 10)
    : filtered;

  return [...scoped].sort((a, b) => compareCoins(a, b, sort));
}

function readRankingFilter<T extends string>(
  scope: "news" | "coin",
  key: string,
  fallback: T,
  isValid: (value: string) => value is T
) {
  if (typeof window === "undefined") return fallback;
  const value = new URLSearchParams(window.location.search).get(key);
  if (value && isValid(value)) return value;

  const storedValue = window.sessionStorage.getItem(rankingStateKey(scope, key));
  return storedValue && isValid(storedValue) ? storedValue : fallback;
}

function readRankingRange(): RankingRange {
  if (typeof window === "undefined") return "24h";
  const value = new URLSearchParams(window.location.search).get("range");
  if (value && isRankingRange(value)) return value;

  const storedNewsRange = window.sessionStorage.getItem(rankingStateKey("news", "range"));
  if (storedNewsRange && isRankingRange(storedNewsRange)) return storedNewsRange;

  const storedCoinRange = window.sessionStorage.getItem(rankingStateKey("coin", "range"));
  return storedCoinRange && isRankingRange(storedCoinRange) ? storedCoinRange : "24h";
}

function syncRankingUrl(scope: "news" | "coin", params: Record<string, string>) {
  if (typeof window === "undefined") return;
  const searchParams = new URLSearchParams(window.location.search);
  Object.entries(params).forEach(([key, value]) => {
    searchParams.set(key, value);
    window.sessionStorage.setItem(rankingStateKey(scope, key), value);
  });
  const search = searchParams.toString();
  const nextUrl = `${window.location.pathname}${search ? `?${search}` : ""}`;
  window.history.replaceState(null, "", nextUrl);
}

function rankingStateKey(scope: "news" | "coin", key: string) {
  return `cryptorisk.ranking:${scope}:${key}`;
}

function withReturnTo(path: string) {
  if (typeof window === "undefined") return path;
  const returnTo = `${window.location.pathname}${window.location.search}`;
  window.sessionStorage.setItem(scrollStorageKey(returnTo), String(window.scrollY));
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}returnTo=${encodeURIComponent(returnTo)}`;
}

function restoreRankingScroll() {
  if (typeof window === "undefined") return;
  const key = scrollStorageKey(`${window.location.pathname}${window.location.search}`);
  const value = window.sessionStorage.getItem(key);
  if (!value) return;
  window.sessionStorage.removeItem(key);
  const top = Number(value);
  if (Number.isNaN(top)) return;
  window.setTimeout(() => {
    window.scrollTo({ top, behavior: "auto" });
  }, 0);
}

function scrollStorageKey(path: string) {
  return `cryptorisk.scroll:${path}`;
}

function isNewsFilter(value: string): value is NewsFilter {
  return ["all", "top10", "high", "medium", "low", "red"].includes(value);
}

function isNewsSort(value: string): value is NewsSort {
  return ["time_desc", "time_asc", "score_desc", "score_asc"].includes(value);
}

function isCoinFilter(value: string): value is CoinFilter {
  return ["all", "top10", "high", "medium", "low"].includes(value);
}

function isCoinSort(value: string): value is CoinSort {
  return ["score_desc", "score_asc", "news_desc", "news_asc"].includes(value);
}

function isRankingRange(value: string): value is RankingRange {
  return ["24h", "7d"].includes(value);
}

function compareCoins(a: CoinRankingItem, b: CoinRankingItem, sort: CoinSort) {
  if (sort === "score_desc") return clampScore(b.final_score) - clampScore(a.final_score);
  if (sort === "score_asc") return clampScore(a.final_score) - clampScore(b.final_score);
  if (sort === "news_desc") return b.news_count - a.news_count;
  return a.news_count - b.news_count;
}

function isHighRiskNews(item: NewsRankingItem) {
  const level = item.risk_level || "";
  if (level.includes("中高")) return false;
  return level.includes("高") || level.includes("红") || clampScore(item.risk_score) >= 80;
}

function isRedAlertNews(item: NewsRankingItem) {
  const level = item.risk_level || "";
  return level.includes("红") || clampScore(item.risk_score) >= 90;
}

function isMediumRiskNews(item: NewsRankingItem) {
  const level = item.risk_level || "";
  const score = clampScore(item.risk_score);
  return level.includes("中") || (score >= 40 && score < 80);
}

function isLowRiskNews(item: NewsRankingItem) {
  const level = item.risk_level || "";
  return level.includes("低") || clampScore(item.risk_score) < 40;
}

function isHighRiskCoin(item: CoinRankingItem) {
  const level = item.risk_level || "";
  if (level.includes("中高")) return false;
  return level.includes("高") || level.includes("红") || clampScore(item.final_score) >= 80;
}

function isMediumRiskCoin(item: CoinRankingItem) {
  const level = item.risk_level || "";
  const score = clampScore(item.final_score);
  return level.includes("中") || (score >= 40 && score < 80);
}

function isLowRiskCoin(item: CoinRankingItem) {
  const level = item.risk_level || "";
  return level.includes("低") || clampScore(item.final_score) < 40;
}

function newsTimeValue(item: NewsRankingItem) {
  const value = item.published_at || "";
  const timestamp = parseLooseTimestamp(value);
  if (timestamp) return timestamp;

  const timeMatch = value.match(/(\d{1,2}):(\d{2})/);
  if (!timeMatch) return 0;
  return Number(timeMatch[1]) * 60 + Number(timeMatch[2]);
}

function compactReportSummary(value: string) {
  const blockedPatterns = [
    /右侧已生成[^。]*。?/g,
    /可点击查看完整报告。?/g,
    /风险严重性和信息置信度[^。]*。?/g,
    /risk_score[^。；;]*[。；;]?/g,
    /confidence_score[^。；;]*[。；;]?/g,
    /严重性得分[^。；;]*[。；;]?/g,
    /置信度得分[^。；;]*[。；;]?/g,
    /紧急度得分[^。；;]*[。；;]?/g,
    /传染性得分[^。；;]*[。；;]?/g,
    /建议优先执行[:：]?/g,
    /简要分析[:：]?/g,
  ];
  let cleaned = (value || "").replace(/\s+/g, " ").trim();
  for (const pattern of blockedPatterns) {
    cleaned = cleaned.replace(pattern, "");
  }
  cleaned = cleaned.replace(/\s+/g, " ").replace(/^[，。；;、\s]+/, "").trim();
  const sentence = cleaned.split(/[。；;]/).map((item) => item.trim()).find(Boolean) || cleaned;
  if (sentence.length <= 88) return sentence;
  return `${sentence.slice(0, 86)}...`;
}

function buildBriefAnalysis(record: AnalysisRecord) {
  const report = record.report;
  const categories = report.risk_categories?.length ? report.risk_categories.join(" / ") : "综合风险";
  const summary = formatScoreReasonText(compactReportSummary(report.summary) || "事件已完成结构化风险研判");
  const isLowRiskPath = isLowRiskBriefReport(report);
  const signals = isLowRiskPath
    ? ""
    : report.risk_signals?.map((signal) => formatRiskSignalLabel(String(signal))).filter(Boolean).slice(0, 2).join("、");
  const lowRiskGate = (report.low_risk_gate || report.chat_agent_result?.low_risk_gate || {}) as Record<string, unknown>;
  const lowRiskGateText = formatLowRiskGateBrief(lowRiskGate);
  const advice = formatScoreReasonText(sanitizeAdvice(report.advice || []).slice(0, 2).join("；"));

  return [
    `${summary}。`,
    `风险 ${clampScore(report.risk_score)}/100（${report.risk_level || "待确认"}），置信度 ${clampScore(report.confidence_score ?? 0)}/100。`,
    lowRiskGateText,
    isLowRiskPath ? "" : (signals ? `关键信号：${signals}。` : `类别：${categories}。`),
    advice ? `建议：${advice}。` : "",
  ].filter(Boolean).join("\n");
}

function buildReportSummaryText(record: AnalysisRecord) {
  const report = record.report;
  return [
    record.title,
    `风险评分：${clampScore(report.risk_score)}/100（${report.risk_level || "待确认"}）`,
    `置信度：${clampScore(report.confidence_score ?? 0)}/100（${report.confidence_level || "待确认"}）`,
    `风险类别：${(report.risk_categories || []).join(" / ") || "综合风险"}`,
    `摘要：${formatScoreReasonText(compactReportSummary(report.summary) || "暂无摘要")}`,
    `处置状态：${dispositionOptions.find((item) => item.value === (record.disposition || "pending"))?.label || "待处理"}`,
  ].join("\n");
}

function buildEvidenceText(evidenceItems: ReportEvidenceItem[]) {
  return evidenceItems.length
    ? evidenceItems.map((item, index) => `${index + 1}. [${item.risk_category}] ${formatScoreReasonText(item.evidence_text)}\n   说明：${formatScoreReasonText(item.explanation || "暂无")}`).join("\n")
    : "暂无结构化证据。";
}

function buildReportMarkdown(record: AnalysisRecord) {
  const report = record.report;
  const advice = sanitizeAdvice(report.advice || []);
  return [
    `# ${record.title}`,
    "",
    `- 生成时间：${record.createdAt}`,
    `- 风险评分：${clampScore(report.risk_score)}/100`,
    `- 风险等级：${report.risk_level || "待确认"}`,
    `- 置信度：${clampScore(report.confidence_score ?? 0)}/100`,
    `- 处置状态：${dispositionOptions.find((item) => item.value === (record.disposition || "pending"))?.label || "待处理"}`,
    "",
    "## 原始输入",
    "",
    formatReportOriginalInput(record.input),
    "",
    "## 摘要",
    "",
    formatScoreReasonText(report.summary || "暂无摘要。"),
    "",
    "## 风险类别",
    "",
    (report.risk_categories || []).map((item) => `- ${item}`).join("\n") || "- 综合风险",
    "",
    "## 证据链",
    "",
    buildEvidenceText(report.evidence || []),
    "",
    "## 影响分析",
    "",
    (report.impact || []).map((item) => `- ${item}`).join("\n") || "- 暂无明确影响对象。",
    "",
    "## 处置建议",
    "",
    advice.map((item) => `- ${item}`).join("\n") || "- 暂无处置建议。",
  ].join("\n");
}

function sanitizeFilename(value: string) {
  return (value || "cryptorisk-report")
    .replace(/[\\/:*?"<>|]/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80);
}

function downloadTextFile(filename: string, content: string) {
  if (typeof window === "undefined") return;
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyTextToClipboard(text: string) {
  if (typeof navigator !== "undefined" && navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  }
}

function isLowRiskBriefReport(report: RiskReport) {
  const result = report.chat_agent_result || report.v6_result || {};
  return report.risk_status === "low_risk"
    || report.report_mode === "fast_exit"
    || result.report_mode === "fast_exit"
    || (clampScore(report.risk_score) <= 20 && report.risk_signals?.some((signal) => ["weak_rule_signal", "fast_exit"].includes(String(signal))));
}

function formatLowRiskGateBrief(gate: Record<string, unknown>) {
  if (!Object.keys(gate).length) return "";
  const escalated = Boolean(gate.escalate_to_high_risk);
  const confirmed = Boolean(gate.low_risk_confirmed);
  const reason = compactReportSummary(String(gate.reason || ""));
  const status = escalated
    ? "复核结果：已升级进入深度分析"
    : confirmed
      ? "复核结果：已复核，未升级"
      : "复核结果：已复核";
  return `${status}${reason ? `（${reason}）` : ""}。`;
}

function getMetrics(
  view: ActiveView,
  overview: RiskOverview | null,
  topNews: NewsRankingItem,
  topCoin: CoinRankingItem,
  loading: boolean,
  newsItems: NewsRankingItem[],
  coinItems: CoinRankingItem[]
) {
  const distribution = getNewsDistribution(newsItems);
  const averageRiskScore = getAverageRiskScore(newsItems);
  const redAlertCount = getRedAlertCount(newsItems);
  const newsTotal = newsItems.length || overview?.total_news || 0;
  const newsBuckets = buildNewsTrendBuckets(newsItems, "7d");
  const newsTotalSeries = newsBuckets.map((bucket) => ({ label: bucket.label, value: bucket.newsCount, timestamp: bucket.timestamp }));
  const highNewsSeries = newsBuckets.map((bucket) => ({ label: bucket.label, value: bucket.highCount, timestamp: bucket.timestamp }));
  const averageNewsSeries = newsBuckets.map((bucket) => ({ label: bucket.label, value: bucket.avgScore, timestamp: bucket.timestamp }));
  const redAlertSeries = newsBuckets.map((bucket) => ({ label: bucket.label, value: bucket.redCount, timestamp: bucket.timestamp }));
  const metricDelta = (series: TrendPoint[]) => getMetricDelta(series);

  if (view === "chat") {
    return [
      { label: "今日事件分析", value: "126", delta: "↑ 18.7%", tone: "purple" as const, icon: <ChatIcon /> },
      { label: "高风险事件", value: "28", delta: "↑ 21.2%", tone: "orange" as const, icon: <AlertIcon /> },
      { label: "平均分析时长", value: "2.4s", delta: "↓ 8.6%", tone: "blue" as const, icon: <ClockIcon /> },
      { label: "建议覆盖率", value: "96%", delta: "↑ 3.2%", tone: "green" as const, icon: <SmileIcon /> },
    ];
  }

  if (view === "reports") {
    return [
      { label: "累计报告数", value: "1,286", delta: "↑ 8.6%", tone: "blue" as const, icon: <FileIcon /> },
      { label: "今日新增报告", value: "36", delta: "↑ 16.2%", tone: "green" as const, icon: <PlusIcon /> },
      { label: "高风险报告", value: "12", delta: "↑ 9.1%", tone: "red" as const, icon: <AlertIcon /> },
      { label: "自动生成成功率", value: "98%", delta: "↑ 2.3%", tone: "purple" as const, icon: <CheckIcon /> },
    ];
  }

  if (view === "coin") {
    const coinDistribution = getCoinDistribution(coinItems);
    const averageCoinRiskScore = getAverageCoinRiskScore(coinItems);
    const coinNewsCount = coinItems.reduce((sum, item) => sum + (item.news_count || 0), 0);
    const coinTotalSeries = buildFlatTrendSeries(coinItems.length, "7d");
    const highCoinSeries = buildCoinAggregateTrendSeries(coinItems, "7d", "high_count");
    const averageCoinSeries = buildCoinAggregateTrendSeries(coinItems, "7d", "avg_score");
    const coinNewsSeries = buildCoinAggregateTrendSeries(coinItems, "7d", "news_count");
    return [
      { label: "监测币种总数", value: loading ? "--" : String(coinItems.length), tone: "blue" as const, icon: <CoinIcon />, series: coinTotalSeries, ...metricDelta(coinTotalSeries) },
      { label: "高风险币种", value: loading ? "--" : String(coinDistribution.high), tone: "red" as const, icon: <AlertIcon />, series: highCoinSeries, ...metricDelta(highCoinSeries) },
      { label: "平均币种风险分", value: loading ? "--" : String(averageCoinRiskScore), tone: "blue" as const, icon: <TrendIcon />, series: averageCoinSeries, ...metricDelta(averageCoinSeries) },
      { label: "关联新闻数", value: loading ? "--" : String(coinNewsCount), tone: "orange" as const, icon: <FileIcon />, series: coinNewsSeries, ...metricDelta(coinNewsSeries) },
    ];
  }

  if (view === "news") {
    return [
      { label: "监测新闻总数", value: loading ? "--" : String(newsTotal), tone: "blue" as const, icon: <FileIcon />, series: newsTotalSeries, ...metricDelta(newsTotalSeries) },
      { label: "高风险新闻", value: loading ? "--" : String(distribution.high), tone: "red" as const, icon: <AlertIcon />, series: highNewsSeries, ...metricDelta(highNewsSeries) },
      { label: "平均风险分", value: loading ? "--" : String(averageRiskScore), tone: "blue" as const, icon: <TrendIcon />, series: averageNewsSeries, ...metricDelta(averageNewsSeries) },
      { label: "红色预警事件", value: loading ? "--" : String(redAlertCount), tone: "orange" as const, icon: <ShieldIcon />, series: redAlertSeries, ...metricDelta(redAlertSeries) },
    ];
  }

  return [
    { label: "今日高风险新闻", value: loading ? "--" : String(distribution.high || overview?.high_risk_news || (topNews.risk_score > 80 ? 1 : 0)), tone: "red" as const, icon: <FileIcon />, series: highNewsSeries, ...metricDelta(highNewsSeries) },
    { label: "红色预警事件", value: loading ? "--" : String(redAlertCount), tone: "orange" as const, icon: <ShieldIcon />, series: redAlertSeries, ...metricDelta(redAlertSeries) },
    { label: "平均风险分", value: loading ? "--" : String(averageRiskScore), tone: "blue" as const, icon: <TrendIcon />, series: averageNewsSeries, ...metricDelta(averageNewsSeries) },
    { label: "实时监测状态", value: "运行中", delta: "所有 Agent 正常", tone: "green" as const, icon: <SmileIcon /> },
  ];
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value || 0)));
}

function extractEventAnalysisFollowUpQuestion(input: string) {
  const normalized = input.trim();
  const match = normalized.match(/(?:用户补充要求|补充要求|额外问题|补充问题|追问|问题)[:：]\s*([\s\S]+)$/i);
  return match?.[1]?.trim() || "";
}

function sanitizeAdvice(items: string[]) {
  return items.filter((item) => !forbiddenAdviceTerms.some((term) => item.includes(term)));
}

function riskLevelStyle(level: string) {
  if (level.includes("高") || level.includes("红")) return "border border-rose-200 bg-rose-50 text-rose-700";
  if (level.includes("中")) return "border border-orange-200 bg-orange-50 text-orange-700";
  return "border border-emerald-200 bg-emerald-50 text-emerald-700";
}

function riskScoreTextStyle(score: number, level: string) {
  const value = clampScore(score);
  if (level.includes("高") || level.includes("红") || value >= 80) return "text-rose-600";
  if (level.includes("中") || value >= 40) return "text-orange-600";
  return "text-emerald-600";
}

function IconSvg({ children }: { children: ReactNode }) {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

function HomeIcon() { return <IconSvg><path d="M3 10.5 12 3l9 7.5" /><path d="M5 10v10h14V10" /><path d="M9 20v-6h6v6" /></IconSvg>; }
function ChatIcon() { return <IconSvg><path d="M21 12a8 8 0 0 1-8 8H7l-4 3v-6a8 8 0 1 1 18-5Z" /></IconSvg>; }
function ChartIcon() { return <IconSvg><path d="M4 19V5" /><path d="M4 19h16" /><path d="m7 15 4-4 3 3 5-7" /></IconSvg>; }
function TradeIcon() { return <IconSvg><path d="M4 17h16" /><path d="M7 14l3-4 3 2 4-6" /><path d="M7 7h10" /><path d="M8 21l-2-4 2-4" /><path d="M16 21l2-4-2-4" /></IconSvg>; }
function PortfolioIcon() { return <IconSvg><path d="M4 19V5" /><path d="M4 19h16" /><path d="M7 15l3-3 3 2 5-7" /><circle cx="18" cy="7" r="2" /></IconSvg>; }
function CoinIcon() { return <IconSvg><circle cx="12" cy="12" r="8" /><path d="M9 10h6" /><path d="M9 14h6" /></IconSvg>; }
function FileIcon() { return <IconSvg><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /><path d="M9 13h6" /><path d="M9 17h6" /></IconSvg>; }
function UserIcon() { return <IconSvg><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></IconSvg>; }
function GearIcon() { return <IconSvg><circle cx="12" cy="12" r="3" /><path d="M19.4 15a8 8 0 0 0 .1-2l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L15 5.5h-4l-.4 2.6a8 8 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a8 8 0 0 0 .1 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.7 1l.4 2.6h4l.4-2.6a8 8 0 0 0 1.7-1l2.4 1 2-3.4z" /></IconSvg>; }
function KeyIcon() { return <IconSvg><circle cx="7.5" cy="14.5" r="3.5" /><path d="M10 12 21 1" /><path d="m16 6 2 2" /><path d="m13 9 2 2" /></IconSvg>; }
function ShieldIcon() { return <IconSvg><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" /><path d="m9 12 2 2 4-5" /></IconSvg>; }
function AlertIcon() { return <IconSvg><path d="m12 3 10 18H2z" /><path d="M12 9v5" /><path d="M12 18h.01" /></IconSvg>; }
function ClockIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></IconSvg>; }
function SmileIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="M8 14s1.5 2 4 2 4-2 4-2" /><path d="M9 9h.01" /><path d="M15 9h.01" /></IconSvg>; }
function TrendIcon() { return <IconSvg><path d="m4 16 5-5 4 4 7-8" /><path d="M14 7h6v6" /></IconSvg>; }
function SendIcon() { return <IconSvg><path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4z" /></IconSvg>; }
function BotIcon() { return <IconSvg><rect x="5" y="8" width="14" height="11" rx="4" /><path d="M12 4v4" /><path d="M9 13h.01" /><path d="M15 13h.01" /><path d="M10 17h4" /></IconSvg>; }
function UsersIcon() { return <IconSvg><path d="M16 21v-2a4 4 0 0 0-8 0v2" /><circle cx="12" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.8" /><path d="M16 3.1a4 4 0 0 1 0 7.8" /></IconSvg>; }
function BulbIcon() { return <IconSvg><path d="M9 18h6" /><path d="M10 22h4" /><path d="M8 14a6 6 0 1 1 8 0c-1 1-1 2-1 4H9c0-2 0-3-1-4Z" /></IconSvg>; }
function PlusIcon() { return <IconSvg><path d="M12 5v14" /><path d="M5 12h14" /></IconSvg>; }
function CheckIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></IconSvg>; }
function ChevronLeftIcon() { return <IconSvg><path d="m15 18-6-6 6-6" /></IconSvg>; }
function ChevronRightIcon() { return <IconSvg><path d="m9 18 6-6-6-6" /></IconSvg>; }
function ChevronDownIcon() { return <IconSvg><path d="m6 9 6 6 6-6" /></IconSvg>; }
function ChevronUpIcon() { return <IconSvg><path d="m18 15-6-6-6 6" /></IconSvg>; }
function CloseIcon() { return <IconSvg><path d="M18 6 6 18" /><path d="m6 6 12 12" /></IconSvg>; }
function StarIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill={filled ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z" />
    </svg>
  );
}
function TrashIcon() { return <IconSvg><path d="M4 7h16" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M6 7l1 14h10l1-14" /><path d="M9 7V4h6v3" /></IconSvg>; }
function PlayIcon() { return <IconSvg><path d="M8 5v14l11-7z" /></IconSvg>; }
function PauseIcon() { return <IconSvg><path d="M8 5v14" /><path d="M16 5v14" /></IconSvg>; }
function RefreshIcon() { return <IconSvg><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v6h-6" /></IconSvg>; }
function CopyIcon() { return <IconSvg><rect x="8" y="8" width="11" height="13" rx="2" /><path d="M5 16V5a2 2 0 0 1 2-2h8" /></IconSvg>; }
function DownloadIcon() { return <IconSvg><path d="M12 3v12" /><path d="m7 10 5 5 5-5" /><path d="M5 21h14" /></IconSvg>; }
function LinkIcon() { return <IconSvg><path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" /></IconSvg>; }
