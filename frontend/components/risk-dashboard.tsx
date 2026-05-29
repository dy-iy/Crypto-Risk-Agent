"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import PortfolioRiskRadar from "@/components/portfolio-risk-radar";
import SimTradingPanel from "@/components/sim-trading-panel";
import { AgentProgress, LoadingDots } from "@/components/ui/loading-states";
import {
  clearApiCache,
  CoinRankingItem,
  fetchCoinRanking,
  fetchCurrentNewsUpdateJob,
  fetchNewsUpdateJob,
  fetchNewsRanking,
  fetchRiskOverview,
  FinalContextMeta,
  NewsUpdateJob,
  NewsUpdateProgress,
  NewsUpdateResponse,
  NewsRankingItem,
  readCachedCoinRanking,
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
} from "@/lib/api";

type ActiveView = "home" | "chat" | "news" | "coin" | "portfolio" | "sim" | "reports" | "settings";
type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
};

type NewsFilter = "all" | "top10" | "high" | "medium" | "low";
type NewsSort = "time_desc" | "time_asc" | "score_desc" | "score_asc";
type CoinFilter = "all" | "top10" | "high" | "medium" | "low";
type CoinSort = "score_desc" | "score_asc" | "news_desc" | "news_asc";
type RankingRange = "24h" | "7d";

type AnalysisRecord = {
  id: string;
  title: string;
  createdAt: string;
  input: string;
  report: RiskReport;
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
  chat: "/analysize",
  news: "/news",
  coin: "/coins",
  portfolio: "/portfolio",
  sim: "/sim",
  reports: "/reports",
  settings: "/settings",
};

const analysisRecordsStorageKey = "cryptorisk.analysisRecords";
const selectedRecordStorageKey = "cryptorisk.selectedRecordId";
const chatMessagesStorageKey = "cryptorisk.chatMessages";
const activeAnalysisTaskStorageKey = "cryptorisk.activeAnalysisTask";
const newsUpdateJobStorageKey = "cryptorisk.newsUpdateJobId";

const initialChatProgressStage: ChatProgressStage = "input_standardization";

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
    return raw ? (JSON.parse(raw) as AnalysisRecord[]) : [];
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
    return raw ? (JSON.parse(raw) as ChatMessage[]) : initialChatMessages;
  } catch {
    return initialChatMessages;
  }
}

function writeStoredChatMessages(messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(chatMessagesStorageKey, JSON.stringify(messages));
}

function writeStoredAnalysisRecords(records: AnalysisRecord[]) {
  if (typeof window === "undefined") return;
  if (records.length) {
    window.localStorage.setItem(analysisRecordsStorageKey, JSON.stringify(records));
  } else {
    window.localStorage.removeItem(analysisRecordsStorageKey);
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
      };
      const nextRecords = [record, ...readStoredAnalysisRecords()];
      writeStoredAnalysisRecords(nextRecords);
      window.localStorage.setItem(selectedRecordStorageKey, record.id);
      appendStoredChatMessages([
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: buildBriefAnalysis(record),
        },
      ]);
      activeAnalysisTask = {
        ...snapshot,
        status: "success",
        stage: "report_generation",
        recordId: record.id,
        updatedAt: new Date().toISOString(),
      };
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

function readCachedOverview() {
  return readCachedRiskOverview(readRankingRange());
}

function readCachedNewsItems() {
  return readCachedNewsRanking(10, readRankingRange())?.items || [];
}

function readCachedCoinItems() {
  return readCachedCoinRanking(10, readRankingRange())?.items || [];
}

export default function RiskDashboard({ initialView = "home" }: { initialView?: ActiveView }) {
  const router = useRouter();
  const [activeView, setActiveView] = useState<ActiveView>(initialView);
  const [rankingRange, setRankingRange] = useState<RankingRange>(() => readRankingRange());
  const [overview, setOverview] = useState<RiskOverview | null>(() => readCachedOverview());
  const [newsRanking, setNewsRanking] = useState<NewsRankingItem[]>(() => readCachedNewsItems());
  const [coinRanking, setCoinRanking] = useState<CoinRankingItem[]>(() => readCachedCoinItems());
  const [rankingLoading, setRankingLoading] = useState(() => !readCachedOverview() && !readCachedNewsItems().length && !readCachedCoinItems().length);
  const [rankingError, setRankingError] = useState("");
  const [newsUpdateLoading, setNewsUpdateLoading] = useState(false);
  const [newsUpdateError, setNewsUpdateError] = useState("");
  const [newsUpdateResult, setNewsUpdateResult] = useState<NewsUpdateResponse | null>(null);
  const [newsUpdateJob, setNewsUpdateJob] = useState<NewsUpdateJob | null>(null);
  const updatePollGenerationRef = useRef(0);

  const [message, setMessage] = useState(examplePrompts[0]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>(() => readStoredChatMessages());
  const [latestReport, setLatestReport] = useState<RiskReport | null>(null);
  const [analysisRecords, setAnalysisRecords] = useState<AnalysisRecord[]>(() => readStoredAnalysisRecords());
  const [selectedRecordId, setSelectedRecordId] = useState(() => readStoredSelectedRecordId());
  const [reportSidebarCollapsed, setReportSidebarCollapsed] = useState(false);
  const [chatLoading, setChatLoading] = useState(() => getActiveAnalysisTaskSnapshot()?.status === "running");
  const [chatError, setChatError] = useState(() => {
    const task = getActiveAnalysisTaskSnapshot();
    return task?.status === "error" ? `分析失败：${task.error || "请求后端失败"}` : "";
  });
  const [chatProgressStage, setChatProgressStage] = useState<ChatProgressStage>(() => getActiveAnalysisTaskSnapshot()?.stage || initialChatProgressStage);

  useEffect(() => {
    let ignore = false;

    async function loadRankings() {
      const hasCachedData = Boolean(readCachedRiskOverview(rankingRange) || newsRanking.length || coinRanking.length);
      if (!hasCachedData) setRankingLoading(true);
      setRankingError("");
      try {
        const [overviewData, newsData, coinData] = await Promise.all([
          fetchRiskOverview(rankingRange),
          fetchNewsRanking(0, rankingRange),
          fetchCoinRanking(0, rankingRange),
        ]);
        if (ignore) return;
        setOverview(overviewData);
        setNewsRanking(newsData.items);
        setCoinRanking(coinData.items);
      } catch (error) {
        console.error(error);
        if (!ignore) {
          setRankingError("排行数据暂未连接，当前展示本地演示数据。请确认 FastAPI 后端已启动。");
          setNewsRanking(fallbackNews);
          setCoinRanking(fallbackCoins);
        }
      } finally {
        if (!ignore) setRankingLoading(false);
      }
    }

    loadRankings();

    return () => {
      ignore = true;
    };
  }, [rankingRange]);

  useEffect(() => {
    if (!analysisRecords.length) return;
    window.localStorage.setItem(analysisRecordsStorageKey, JSON.stringify(analysisRecords));
  }, [analysisRecords]);

  useEffect(() => {
    if (!selectedRecordId) return;
    window.localStorage.setItem(selectedRecordStorageKey, selectedRecordId);
  }, [selectedRecordId]);

  useEffect(() => {
    window.localStorage.setItem(chatMessagesStorageKey, JSON.stringify(chatMessages));
  }, [chatMessages]);

  useEffect(() => {
    return subscribeAnalysisTask((task) => {
      const records = readStoredAnalysisRecords();
      setChatLoading(task?.status === "running");
      setChatProgressStage(task?.stage || initialChatProgressStage);
      setChatError(task?.status === "error" ? `分析失败：${task.error || "请求后端失败"}` : "");
      setChatMessages(readStoredChatMessages());
      setAnalysisRecords(records);

      if (task?.recordId) {
        setSelectedRecordId(task.recordId);
        setLatestReport(records.find((record) => record.id === task.recordId)?.report || null);
        return;
      }

      setLatestReport(records[0]?.report || null);
    });
  }, []);

  const displayNews = newsRanking;
  const displayCoins = coinRanking;
  const topNews = displayNews[0] || emptyNewsItem;
  const topCoin = displayCoins[0] || emptyCoinItem;
  const reportRecords = analysisRecords;
  const selectedRecord = reportRecords.find((record) => record.id === selectedRecordId) || reportRecords[0] || null;

  const pageMeta = getPageMeta(activeView);

  function handleChangeView(view: ActiveView) {
    setActiveView(view);
    router.push(viewRoutes[view]);
  }

  function handleChangeRankingRange(range: RankingRange) {
    setRankingRange(range);
    syncRankingUrl(activeView === "coin" ? "coin" : "news", { range });
  }

  async function refreshRankingsAfterUpdate(silent = false) {
    if (!silent) setRankingLoading(true);
    setRankingError("");
    try {
      clearApiCache();
      const [overviewData, newsData, coinData] = await Promise.all([
        fetchRiskOverview(rankingRange),
        fetchNewsRanking(0, rankingRange),
        fetchCoinRanking(0, rankingRange),
      ]);
      setOverview(overviewData);
      setNewsRanking(newsData.items);
      setCoinRanking(coinData.items);
    } catch (error) {
      console.error(error);
      setRankingError("新闻已更新，但排行榜刷新失败，请稍后重新打开排行榜。");
    } finally {
      if (!silent) setRankingLoading(false);
    }
  }

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

  async function pollNewsUpdateJob(initialJob: NewsUpdateJob) {
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
  }

  useEffect(() => {
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
  }, []);

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
    setActiveView("chat");
    window.history.pushState(null, "", viewRoutes.chat);
    runAnalysis(input);
  }

  function handleClearChatHistory() {
    setChatMessages(initialChatMessages);
    window.localStorage.setItem(chatMessagesStorageKey, JSON.stringify(initialChatMessages));
  }

  function handleDeleteRecord(id: string) {
    setAnalysisRecords((items) => {
      const nextRecords = items.filter((item) => item.id !== id);
      if (nextRecords.length) {
        window.localStorage.setItem(analysisRecordsStorageKey, JSON.stringify(nextRecords));
        const nextSelected = nextRecords[0].id;
        window.localStorage.setItem(selectedRecordStorageKey, nextSelected);
        setSelectedRecordId(nextSelected);
      } else {
        window.localStorage.removeItem(analysisRecordsStorageKey);
        window.localStorage.removeItem(selectedRecordStorageKey);
        setSelectedRecordId("");
      }
      return nextRecords;
    });
  }

  function handleDeleteAllRecords() {
    setAnalysisRecords([]);
    setSelectedRecordId("");
    setLatestReport(null);
    window.localStorage.removeItem(analysisRecordsStorageKey);
    window.localStorage.removeItem(selectedRecordStorageKey);
  }

  return (
    <main className="risk-shell min-h-screen bg-[#f4f7fb] text-slate-900">
      <div className="flex min-h-screen">
        <Sidebar activeView={activeView} onChangeView={handleChangeView} />

        <div className="min-w-0 flex-1 lg:pl-[248px]">
          <TopBar title={pageMeta.title} subtitle={pageMeta.subtitle} />
          <MobileNav activeView={activeView} onChangeView={handleChangeView} />

          <div className="px-3 py-4 sm:px-6 sm:py-5 2xl:px-8">
            <div className="min-w-0 space-y-5">
              {rankingError && <Notice tone="amber" text={rankingError} />}

              {activeView !== "chat" && activeView !== "portfolio" && activeView !== "sim" && activeView !== "reports" && activeView !== "settings" && (
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
                  newsItems={displayNews}
                  onChangeView={handleChangeView}
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
                  onSelectRecord={setSelectedRecordId}
                  onSubmit={handleChatSubmit}
                  records={analysisRecords}
                />
              )}

              {activeView === "news" && (
                <NewsView
                  items={displayNews}
                  range={rankingRange}
                  onChangeRange={handleChangeRankingRange}
                />
              )}
              {activeView === "coin" && (
                <CoinView
                  items={displayCoins}
                  range={rankingRange}
                  onChangeRange={handleChangeRankingRange}
                />
              )}
              {activeView === "portfolio" && (
                <PortfolioRiskRadar />
              )}
              {activeView === "sim" && (
                <SimTradingPanel embedded />
              )}
              {activeView === "reports" && (
                <ReportsView
                  collapsed={reportSidebarCollapsed}
                  onDeleteAllRecords={handleDeleteAllRecords}
                  onDeleteRecord={handleDeleteRecord}
                  onChangeView={handleChangeView}
                  onSelectRecord={setSelectedRecordId}
                  onToggleCollapsed={() => setReportSidebarCollapsed((value) => !value)}
                  onReanalyze={handleReanalyze}
                  records={reportRecords}
                  selectedRecord={selectedRecord}
                />
              )}
              {activeView === "settings" && (
                <SettingsView
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
    { key: "portfolio", label: "我的风险资产", icon: <PortfolioIcon /> },
    { key: "sim", label: "模拟交易盘", icon: <TradeIcon /> },
    { key: "reports", label: "分析报告", icon: <FileIcon /> },
    { key: "settings", label: "系统设置", icon: <GearIcon /> },
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
        {navItems.slice(0, 4).map((item) => (
          <SidebarButton
            key={item.key}
            active={activeView === item.key}
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

        {navItems.slice(4).map((item) => (
          <SidebarButton
            key={item.key}
            active={activeView === item.key}
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

function TopBar({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <header className="risk-topbar sticky top-0 z-20 border-b border-blue-100 backdrop-blur-xl">
      <div className="flex min-h-[76px] items-center gap-4 px-4 sm:min-h-[92px] sm:px-6 2xl:px-8">
        <div className="min-w-0 flex-1">
          <p className="truncate text-xl font-bold tracking-tight text-slate-950 sm:text-2xl">{title}</p>
          <p className="mt-1 line-clamp-2 text-sm text-slate-500">{subtitle}</p>
        </div>
      </div>
    </header>
  );
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
    ["news", "新闻榜"],
    ["coin", "币种榜"],
    ["portfolio", "资产"],
    ["sim", "模拟盘"],
    ["reports", "报告"],
    ["settings", "设置"],
  ];

  return (
    <nav className="risk-scroll sticky top-[76px] z-10 flex gap-2 overflow-x-auto border-b border-blue-100 bg-white px-3 py-2.5 sm:top-[92px] sm:px-4 sm:py-3 lg:hidden">
      {items.map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => onChangeView(key)}
          className={`shrink-0 rounded-lg px-3 py-2 text-sm font-semibold transition-colors duration-200 sm:px-4 ${
            activeView === key
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
  const metrics = getMetrics(activeView, overview, topNews, topCoin, loading, newsItems, coinItems);

  return (
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {metrics.map((metric) => (
        <MetricCard key={metric.label} {...metric} />
      ))}
    </section>
  );
}

function MetricCard({
  icon,
  label,
  value,
  delta,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  delta: string;
  tone: "blue" | "red" | "orange" | "green" | "purple";
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
        <Sparkline tone={tone} />
      </div>
      <div className="mt-3">
        <p className="text-sm font-semibold text-slate-600">{label}</p>
        <p className={`mt-1 text-3xl font-bold ${toneStyle.split(" ")[1]}`}>{value}</p>
        <p className="mt-2 text-xs text-slate-500">较昨日 <span className="font-semibold text-emerald-600">{delta}</span></p>
      </div>
    </article>
  );
}

function DashboardHome({
  coinItems,
  newsItems,
  onChangeView,
}: {
  coinItems: CoinRankingItem[];
  newsItems: NewsRankingItem[];
  onChangeView: (view: ActiveView) => void;
}) {
  const topCoin = coinItems[0] || emptyCoinItem;
  const topNews = newsItems[0] || emptyNewsItem;

  return (
    <>
      <CommandHero topCoin={topCoin} topNews={topNews} onStart={() => onChangeView("chat")} />
      <div className="grid gap-5 xl:grid-cols-2">
        <RankingCard title="新闻风险排行榜 Top 10" action="查看全部" onAction={() => onChangeView("news")}>
          <NewsTable items={newsItems.slice(0, 10)} compact />
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
    <section className="risk-card grid gap-5 rounded-lg p-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.55fr)]">
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
        <HeroSignal label="最高风险币种" value={`${topCoin.symbol} / ${topCoin.main_risk_type}`} score={topCoin.final_score} tone="orange" />
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

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, chatLoading]);

  return (
    <section className="grid min-h-[calc(100vh-168px)] gap-4 sm:gap-5 xl:h-[calc(100vh-170px)] xl:grid-cols-[minmax(0,4fr)_minmax(230px,1fr)]">
      <div className="risk-card flex min-h-[calc(100vh-168px)] flex-col rounded-lg xl:h-full xl:min-h-0">
        <div className="risk-scroll min-h-0 flex-1 overflow-y-auto px-3 py-5 sm:px-8 sm:py-6 lg:px-10">
          <div className="mx-auto max-w-5xl space-y-5">
            {chatMessages.map((item) => (
              <div key={item.id} className={`flex ${item.role === "user" ? "justify-end" : "justify-start"}`}>
                {item.role === "assistant" && (
                  <div className="mr-3 mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
                    <ShieldIcon />
                  </div>
                )}
                <div
                  className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm leading-7 shadow-sm sm:max-w-[78%] sm:px-5 sm:py-4 ${
                    item.role === "user"
                      ? "bg-blue-600 text-white"
                      : "border border-blue-100 bg-slate-50 text-slate-700"
                  }`}
                >
                  {item.role === "assistant" && !item.content ? <LoadingDots label="正在生成简要分析" /> : item.content}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="w-full max-w-[640px]">
                  <AgentProgress
                    icon={<ShieldIcon />}
                    title="Chat Agent 正在研判"
                    activeStage={chatProgressStage}
                    steps={["输入标准化", "风险信号扫描", "提取证据", "生成报告"]}
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
                    className="shrink-0 rounded-full border border-blue-100 bg-white px-4 py-2 text-xs font-semibold text-blue-700 shadow-sm transition-colors duration-200 hover:bg-blue-50"
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

            <form onSubmit={onSubmit} className="flex min-h-14 items-end gap-2 rounded-xl border border-blue-100 bg-white px-3 py-3 shadow-xl shadow-blue-100/70 sm:gap-3 sm:rounded-2xl sm:px-4">
              <textarea
                value={message}
                onChange={(event) => onMessageChange(event.target.value)}
                className="max-h-32 min-h-8 flex-1 resize-none bg-transparent text-sm leading-7 text-slate-700 outline-none placeholder:text-slate-400"
                placeholder="输入新闻、公告、链上事件或交易所异常..."
                rows={1}
              />
              <button
                type="submit"
                disabled={chatLoading || !message.trim()}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                aria-label="发送分析事件"
              >
                <SendIcon />
              </button>
            </form>
            {chatError && <div className="mt-3"><Notice tone="red" text={chatError} /></div>}
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
              <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-600">{record.report.summary || record.input}</p>
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
  items,
  onChangeRange,
  range,
}: {
  items: NewsRankingItem[];
  onChangeRange: (range: RankingRange) => void;
  range: RankingRange;
}) {
  const [filter, setFilter] = useState<NewsFilter>(() => readRankingFilter("news", "filter", "top10", isNewsFilter));
  const [sort, setSort] = useState<NewsSort>(() => readRankingFilter("news", "sort", "score_desc", isNewsSort));
  const visibleItems = useMemo(() => getVisibleNewsItems(items, filter, sort), [filter, items, sort]);
  const distribution = useMemo(() => getNewsDistribution(items), [items]);

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
        <TrendCard title="今日风险趋势（按平均风险分）" />
      </div>
      <NewsRankingPanel
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
  const visibleItems = useMemo(() => getVisibleCoinItems(items, filter, sort), [filter, items, sort]);
  const distribution = useMemo(() => getCoinDistribution(items), [items]);

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
        <TrendCard title="热门币种风险趋势" withLegend />
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
        <TableFooter text={`当前显示 ${items.length} 个 / 全部 ${total} 个币种`} />
      </div>
    </section>
  );
}

function NewsRankingPanel({
  filter,
  items,
  onChangeFilter,
  onChangeRange,
  onChangeSort,
  range,
  sort,
  total,
}: {
  filter: NewsFilter;
  items: NewsRankingItem[];
  onChangeFilter: (filter: NewsFilter) => void;
  onChangeRange: (range: RankingRange) => void;
  onChangeSort: (sort: NewsSort) => void;
  range: RankingRange;
  sort: NewsSort;
  total: number;
}) {
  const filters: Array<[NewsFilter, string]> = [
    ["all", "全部新闻"],
    ["top10", "Top10 风险新闻"],
    ["high", "高风险"],
    ["medium", "中风险"],
    ["low", "低风险"],
  ];
  const sortOptions: Array<[NewsSort, string]> = [
    ["time_desc", "发布时间：晚 → 早"],
    ["time_asc", "发布时间：早 → 晚"],
    ["score_desc", "风险分：高 → 低"],
    ["score_asc", "风险分：低 → 高"],
  ];

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
          <NewsTable items={items} />
        </div>
        <TableFooter text={`当前显示 ${items.length} 条 / 全部 ${total} 条`} />
      </div>
    </section>
  );
}

function ReportsView({
  collapsed,
  onDeleteAllRecords,
  onDeleteRecord,
  onChangeView,
  onReanalyze,
  onSelectRecord,
  onToggleCollapsed,
  records,
  selectedRecord,
}: {
  collapsed: boolean;
  onDeleteAllRecords: () => void;
  onDeleteRecord: (id: string) => void;
  onChangeView: (view: ActiveView) => void;
  onReanalyze: (input: string) => void;
  onSelectRecord: (id: string) => void;
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
                          <RiskBadge level={record.report.risk_level} />
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
        <ReportDocument onDeleteRecord={onDeleteRecord} onReanalyze={onReanalyze} record={selectedRecord} />
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

function SettingsView({
  onUpdateTodayNews,
  updateError,
  updateJob,
  updateLoading,
  updateResult,
}: {
  onUpdateTodayNews: () => void;
  updateError: string;
  updateJob: NewsUpdateJob | null;
  updateLoading: boolean;
  updateResult: NewsUpdateResponse | null;
}) {
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
      </div>
    </section>
  );
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

function AssistantPanel({
  activeView,
  latestReport,
  topCoin,
  topNews,
}: {
  activeView: ActiveView;
  chatLoading: boolean;
  latestReport: RiskReport | null;
  topCoin: CoinRankingItem;
  topNews: NewsRankingItem;
}) {
  const topic = activeView === "coin" ? topCoin.symbol : topNews.coins[0] || topCoin.symbol;
  const score = latestReport?.risk_score ?? (activeView === "coin" ? topCoin.final_score : topNews.risk_score);
  const [question, setQuestion] = useState("");
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantError, setAssistantError] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const assistantEndRef = useRef<HTMLDivElement | null>(null);
  const [assistantMessages, setAssistantMessages] = useState<ChatMessage[]>([
    {
      id: "assistant-welcome",
      role: "assistant",
      content: "可以问我金融市场、加密资产、DeFi 风险、交易所事件、项目基本面、宏观影响和当前页面里的风险线索。",
    },
  ]);

  useEffect(() => {
    assistantEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [assistantMessages, assistantLoading]);

  const askAssistant = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || assistantLoading) return;

    const shouldUsePageContext = shouldAttachAssistantPageContext(trimmed, {
      activeView,
      latestReport,
      topCoin,
      topNews,
    });
    const context = shouldUsePageContext ? {
      active_view: activeView,
      topic,
      risk_score: score,
      latest_report: latestReport,
      top_coin: topCoin,
      top_news: topNews,
    } : {
      active_view: activeView,
      page_context_available: true,
      page_context_omitted: "用户问题未明确指向当前页面，避免用页面数据污染回答。",
    };

    setAssistantMessages((items) => [
      ...items,
      { id: `assistant-user-${Date.now()}`, role: "user", content: trimmed },
    ]);
    setQuestion("");
    setAssistantError("");
    setAssistantLoading(true);
    const replyId = `assistant-reply-${Date.now()}`;
    setAssistantMessages((items) => [
      ...items,
      { id: replyId, role: "assistant", content: "" },
    ]);

    try {
      await streamRiskAssistant(trimmed, context, (chunk) => {
        setAssistantMessages((items) =>
          items.map((item) =>
            item.id === replyId ? { ...item, content: item.content + chunk } : item
          )
        );
      });
    } catch (error) {
      console.error(error);
      setAssistantMessages((items) => items.filter((item) => item.id !== replyId));
      setAssistantError("助手暂时无法回答，请稍后重试。");
    } finally {
      setAssistantLoading(false);
    }
  };

  const handleAssistantSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    askAssistant(question);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setAssistantOpen(true)}
        className={`fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-blue-600 text-white shadow-2xl shadow-blue-200 transition-all duration-200 hover:-translate-y-0.5 hover:bg-blue-700 ${
          assistantOpen ? "pointer-events-none scale-95 opacity-0" : "opacity-100"
        }`}
        aria-label="打开 AI 风控助手"
        aria-expanded={assistantOpen}
      >
        <BotIcon />
      </button>

      {assistantOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-slate-950/20 backdrop-blur-[1px] xl:hidden"
          onClick={() => setAssistantOpen(false)}
          aria-label="关闭 AI 风控助手遮罩"
        />
      )}

      <aside
        className={`fixed inset-y-0 right-0 z-50 w-full max-w-[420px] transform border-l border-blue-100 bg-white shadow-2xl shadow-slate-900/20 transition-transform duration-300 sm:right-4 sm:top-[108px] sm:bottom-6 sm:h-[calc(100vh-132px)] sm:rounded-lg sm:border ${
          assistantOpen ? "translate-x-0" : "translate-x-full sm:translate-x-[calc(100%+2rem)]"
        }`}
        aria-hidden={!assistantOpen}
      >
      <section className="flex h-full flex-col">
        <div className="flex items-center justify-between border-b border-blue-100 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-full bg-blue-50 text-blue-600">
              <BotIcon />
            </div>
            <div>
              <p className="font-bold text-slate-950">AI风控助手</p>
              <p className="text-xs text-slate-500">金融与加密风险问答</p>
            </div>
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
          </div>
          <button
            className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-400 transition-colors duration-200 hover:bg-blue-50 hover:text-slate-900"
            type="button"
            onClick={() => setAssistantOpen(false)}
            aria-label="关闭 AI 风控助手"
          >
            ×
          </button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-5 p-5">
          <div className="risk-scroll min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
            {assistantMessages.map((message) => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[88%] whitespace-pre-wrap rounded-lg px-4 py-3 text-sm leading-7 ${
                    message.role === "user"
                      ? "bg-blue-600 font-semibold text-white"
                      : "border border-blue-100 bg-slate-50 text-slate-700"
                  }`}
                >
                  {message.role === "assistant" ? (
                    message.content ? <MarkdownMessage content={message.content} /> : <LoadingDots label="正在整理回答" />
                  ) : (
                    message.content
                  )}
                </div>
              </div>
            ))}
            <div ref={assistantEndRef} />
          </div>

          {assistantError && <Notice tone="red" text={assistantError} />}

          <div className="flex gap-3 text-slate-500">
            <ThumbIcon />
            <ThumbIcon down />
          </div>

          <form onSubmit={handleAssistantSubmit} className="flex h-12 items-center gap-3 rounded-lg border border-blue-100 bg-slate-50 px-3 text-sm">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              className="min-w-0 flex-1 bg-transparent text-slate-700 outline-none placeholder:text-slate-400"
              placeholder="问金融、币种、风险或当前页面..."
            />
            <button
              type="submit"
              disabled={assistantLoading || !question.trim()}
              className="ml-auto flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 text-white transition-colors duration-200 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="发送问题"
            >
              <SendIcon />
            </button>
          </form>
          <p className="text-xs text-slate-400">内容由 AI 生成，仅供参考</p>
        </div>
      </section>
    </aside>
    </>
  );
}

function MarkdownMessage({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const elements: ReactNode[] = [];
  let listItems: string[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const text = paragraph.join(" ");
    elements.push(
      <p key={`p-${elements.length}`} className="my-2 first:mt-0 last:mb-0">
        {renderInlineMarkdown(text)}
      </p>
    );
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length) return;
    elements.push(
      <ul key={`ul-${elements.length}`} className="my-2 list-disc space-y-1 pl-5">
        {listItems.map((item, index) => (
          <li key={`${index}-${item}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const className = level === 1 ? "mt-1 text-base font-bold" : "mt-2 text-sm font-bold";
      elements.push(
        <p key={`h-${elements.length}`} className={className}>
          {renderInlineMarkdown(heading[2])}
        </p>
      );
      return;
    }

    const unordered = line.match(/^[-*]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      listItems.push(unordered[1]);
      return;
    }

    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      listItems.push(ordered[1]);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();

  return <div className="break-words">{elements}</div>;
}

function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    const token = match[0];
    if (token.startsWith("`")) {
      nodes.push(
        <code key={`code-${match.index}`} className="rounded bg-blue-50 px-1 py-0.5 text-[0.92em] text-blue-700">
          {token.slice(1, -1)}
        </code>
      );
    } else {
      nodes.push(
        <strong key={`strong-${match.index}`} className="font-bold text-slate-900">
          {token.slice(2, -2)}
        </strong>
      );
    }

    lastIndex = match.index + token.length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
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

function NewsTable({ compact = false, items }: { compact?: boolean; items: NewsRankingItem[] }) {
  const router = useRouter();
  const headers = [
    { label: "#", className: "w-14 px-3 py-3 text-center font-semibold" },
    { label: "新闻标题", className: `${compact ? "min-w-[260px]" : "min-w-[340px]"} px-3 py-3 text-left font-semibold` },
    { label: "风险类别", className: "min-w-[140px] px-3 py-3 text-left font-semibold" },
    { label: "关联币种", className: "min-w-[120px] px-3 py-3 text-left font-semibold" },
    { label: "风险分", className: "w-24 px-3 py-3 text-center font-semibold" },
    { label: "风险等级", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: compact ? "" : "发布时间", className: "min-w-[160px] px-3 py-3 text-left font-semibold" },
  ];

  return (
    <div className="risk-scroll overflow-x-auto">
      <table className={`risk-table w-full text-left text-sm ${compact ? "min-w-[760px]" : "min-w-[1080px]"}`}>
        <thead className="border-y border-blue-100 bg-slate-50 text-xs text-slate-500">
          <tr>
            {headers.map((head) => (
              <th key={head.label || "blank"} className={head.className}>{head.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-blue-50">
          {items.length ? items.map((item, index) => (
            <tr
              key={item.news_id}
              data-ai-context={JSON.stringify({
                type: "news",
                coin: item.coins,
                title: item.title,
                riskLevel: item.risk_level,
                riskScore: item.risk_score,
                riskType: item.risk_type,
                time: item.published_at,
              })}
              onClick={() => {
                router.push(withReturnTo(`/news/${encodeURIComponent(item.news_id)}`));
              }}
              className="cursor-pointer text-slate-700 transition-colors duration-200 hover:bg-blue-50/70"
            >
              <td className="px-3 py-3 text-center font-semibold text-slate-900">{index + 1}</td>
              <td className="px-3 py-3 font-semibold text-slate-800">
                <span className="line-clamp-1 text-blue-700">{item.title}</span>
              </td>
              <td className="px-3 py-3 text-slate-600">{item.risk_type || "综合风险"}</td>
              <td className="px-3 py-3 text-slate-600">{item.coins?.length ? item.coins.join(", ") : "--"}</td>
              <td className={`px-3 py-3 text-center font-bold tabular-nums ${riskScoreTextStyle(item.risk_score, item.risk_level)}`}>
                {clampScore(item.risk_score)}
              </td>
              <td className="px-3 py-3 text-center"><RiskBadge level={item.risk_level} /></td>
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
  const headers = [
    { label: "#", className: "w-14 px-3 py-3 text-center font-semibold" },
    { label: "币种", className: "min-w-[150px] px-3 py-3 text-left font-semibold" },
    { label: "风险类别", className: "min-w-[260px] px-3 py-3 text-left font-semibold" },
    { label: "风险分", className: "w-24 px-3 py-3 text-center font-semibold" },
    { label: "风险等级", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: "相关新闻数", className: "w-28 px-3 py-3 text-center font-semibold" },
    { label: compact ? "" : "24H 趋势", className: "w-28 px-3 py-3 text-center font-semibold" },
  ];

  return (
    <div className="risk-scroll overflow-x-auto">
      <table className={`risk-table w-full text-left text-sm ${compact ? "min-w-[760px]" : "min-w-[900px]"}`}>
        <thead className="border-y border-blue-100 bg-slate-50 text-xs text-slate-500">
          <tr>
            {headers.map((head) => (
              <th key={head.label || "blank"} className={head.className}>{head.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-blue-50">
          {items.length ? items.map((item) => (
            <tr
              key={item.symbol}
              data-ai-context={JSON.stringify({
                type: "coin",
                coin: item.symbol,
                title: item.top_news_title,
                riskLevel: item.risk_level,
                riskScore: item.final_score,
                riskType: item.main_risk_type,
              })}
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
              <td className="px-3 py-3 text-slate-600">{item.main_risk_type || "综合风险"}</td>
              <td className={`px-3 py-3 text-center font-bold tabular-nums ${riskScoreTextStyle(item.final_score, item.risk_level)}`}>
                {clampScore(item.final_score)}
              </td>
              <td className="px-3 py-3 text-center"><RiskBadge level={item.risk_level} /></td>
              <td className="px-3 py-3 text-center tabular-nums">{item.news_count}</td>
              <td className="px-3 py-3 text-center">{compact ? "" : <span className="inline-flex"><MiniTrend /></span>}</td>
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
  onDeleteRecord,
  onReanalyze,
  record,
}: {
  onDeleteRecord: (id: string) => void;
  onReanalyze: (input: string) => void;
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
  const impactAnalysis = report.impact_analysis || chatAgentResult.impact_analysis || {};
  const adviceGeneration = report.advice_generation || chatAgentResult.advice_generation || {};
  const finalContextMeta = report.final_context_agents || {};
  const isWeakRisk = detectWeakRisk(chatAgentResult, finalContextMeta, impactAnalysis, adviceGeneration);
  const summary = compactReportSummary(report.summary) || "事件已完成结构化风险研判。";

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
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">CryptoRisk Report</p>
            <h2 className="mt-2 break-words text-xl font-bold text-slate-950 sm:text-2xl">{record.title}</h2>
            <p className="mt-2 text-sm text-slate-500">{record.createdAt}</p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
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
        <section className="grid gap-4 rounded-lg border border-blue-100 bg-slate-50 p-4 sm:gap-5 sm:p-5 lg:grid-cols-[180px_minmax(0,1fr)_220px]">
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
              {(report.risk_signals || []).map(compactReportSummary).filter(Boolean).slice(0, 4).map((item, index) => (
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

        <ReportSection title="风险类别与证据" icon={<FileIcon />}>
          <RiskCategoryEvidence
            branches={riskBranches}
            categories={categories}
            evidenceItems={evidenceItems}
            stats={report.risk_type_stats || chatAgentResult.risk_type_stats || []}
          />
        </ReportSection>

        <div className="grid gap-5 xl:grid-cols-2">
          <ReportSection title="影响对象" icon={<UsersIcon />}>
            <ImpactObjectsPanel analysis={impactAnalysis} fallback={report.impact || []} isWeakRisk={isWeakRisk} />
          </ReportSection>

          <ReportSection title="处置建议" icon={<BulbIcon />}>
            <AdvicePanel advice={adviceGeneration} fallback={report.advice || []} isWeakRisk={isWeakRisk} />
          </ReportSection>
        </div>

        <ReportSection title="原始输入" icon={<ChatIcon />}>
          <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{record.input}</p>
        </ReportSection>
      </div>
    </article>
  );
}

type ReportEvidenceItem = RiskReport["evidence"][number];

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

        return (
          <div key={group.category} className="rounded-lg border border-blue-100 bg-blue-50/50 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-white px-2.5 py-1 text-xs font-bold text-blue-700 shadow-sm">
                {formatEvidenceCategory(group.category)}
              </span>
              <span className={`rounded-md px-2.5 py-1 text-xs font-bold ${branch?.established === false ? "border border-amber-200 bg-amber-50 text-amber-700" : "border border-emerald-200 bg-emerald-50 text-emerald-700"}`}>
                {branch?.established === false ? "证据不足" : "风险成立"}
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

            {branch?.reasoning && <p className="mt-3 text-sm font-semibold leading-6 text-slate-700">{branch.reasoning}</p>}

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
                  <p className="mt-2 text-sm leading-7 text-slate-800">{item.evidence_text}</p>
                </div>
              ))}
            </div>

            {missingEvidence.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {missingEvidence.map((item) => (
                  <span key={item} className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
                    待核验：{item}
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

function EngineTrace({
  report,
  result,
  validation,
}: {
  report: RiskReport;
  result: ChatAgentResult;
  validation: ChatAgentResult["validation"];
}) {
  const primaryBranch = String((result.branch_score_merge?.primary_risk_name as string | undefined) || report.primary_category || formatScenario(String(result.primary_scenario || "")) || "");
  const extractionMode = formatExtractionMode(result.extraction_mode);
  const llmCalls = result.llm_call_count ?? 0;
  const fallbackCount = result.fallback_count ?? 0;
  const validationAnswers = Object.entries(validation?.answered_questions || {}).slice(0, 6);
  const impactAnalysis = report.impact_analysis || result.impact_analysis || {};
  const adviceGeneration = report.advice_generation || result.advice_generation || {};
  const finalContextMeta = report.final_context_agents || {};
  const isWeakRisk = detectWeakRisk(result, finalContextMeta, impactAnalysis, adviceGeneration);
  const finalContextSources = [impactAnalysis.source, adviceGeneration.source]
    .map(formatAgentSource)
    .filter((item, index, values) => item && item !== "待确认" && values.indexOf(item) === index);
  const traceItems = [
    {
      title: "快速规则扫描",
      value: `${report.risk_signals?.length || 0} 个信号`,
      detail: "完成风险方向粗筛与缓和语义识别",
    },
    {
      title: "风险类型分支审核",
      value: primaryBranch || "综合风险",
      detail: "按命中 risk_type 独立审核证据强度、严重性与成立状态",
    },
    {
      title: "分支评分合并",
      value: `${extractionMode} · ${llmCalls} 次调用`,
      detail: fallbackCount ? `分支兜底 ${fallbackCount} 次` : "最强成立分支决定主分，次要成立分支补充加权",
    },
    {
      title: "二次校验",
      value: `${clampScore(result.pre_cap_score ?? report.risk_score)} → ${clampScore(report.final_risk_score ?? report.risk_score)}`,
      detail: validation ? formatValidationAction(validation.action) : "未触发二次校验调整",
    },
    {
      title: "影响与建议 Agent",
      value: finalContextSources.length ? finalContextSources.join(" / ") : "待确认",
      detail: isWeakRisk ? "弱风险保护：只输出监测建议，不推断具体影响对象" : "影响对象 Agent 与处置建议 Agent 分别生成上下文结论",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {traceItems.map((item, index) => (
          <div key={item.title} className="rounded-lg border border-blue-100 bg-slate-50 p-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-blue-600 text-xs font-bold text-white">
                {index + 1}
              </span>
              <p className="min-w-0 truncate text-xs font-bold text-slate-600">{item.title}</p>
            </div>
            <p className="mt-3 text-sm font-bold leading-6 text-slate-950">{item.value}</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">{item.detail}</p>
          </div>
        ))}
      </div>

      {validation && (
        <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md bg-amber-600 px-2.5 py-1 text-xs font-bold text-white">Validation</span>
            <span className="rounded-md border border-amber-200 bg-white px-2.5 py-1 text-xs font-bold text-amber-800">
              {formatValidationAction(validation.action)}
            </span>
          </div>
          {validation.reason && <p className="mt-3 text-sm font-semibold leading-6 text-amber-950">{validation.reason}</p>}
          {validationAnswers.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {validationAnswers.map(([key, value]) => (
                <span key={key} className="rounded-md border border-amber-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700">
                  {formatRiskSignalLabel(key)}：{formatUnknownValue(value)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceSignalList({
  empty,
  items,
}: {
  empty: string;
  items: Array<{ label: string; value: string; tone: "blue" | "green" | "amber" | "slate" }>;
}) {
  if (!items.length) {
    return <p className="rounded-lg border border-dashed border-blue-200 bg-slate-50 p-4 text-sm font-semibold text-slate-500">{empty}</p>;
  }

  const toneStyle = {
    blue: "border-blue-100 bg-blue-50 text-blue-800",
    green: "border-emerald-100 bg-emerald-50 text-emerald-800",
    amber: "border-amber-100 bg-amber-50 text-amber-800",
    slate: "border-slate-200 bg-slate-50 text-slate-700",
  };

  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <div key={`${item.label}-${item.value}-${index}`} className={`rounded-lg border px-3 py-2 ${toneStyle[item.tone]}`}>
          <span className="text-xs font-bold">{item.label}</span>
          <p className="mt-1 text-sm font-semibold leading-6">{item.value}</p>
        </div>
      ))}
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

  const labels: Record<string, string> = {
    risk_type_branch_merge: "风险类型分支合并",
    secondary_risk_bonus: "次要风险加权",
    primary_branch_evidence_weak: "主风险证据偏弱",
    no_established_risk_type_branch: "未形成明确风险分支",
    high_risk_floor_signal: "触发高风险保底",
    weak_rule_signal: "弱风险规则信号",
    fast_exit: "快速低风险路径",
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
  };

  return labels[normalized] || formatEvidenceSignal(normalized);
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

function formatExtractionMode(value?: string) {
  const labels: Record<string, string> = {
    llm: "分支 LLM 审核",
    heuristic_fallback: "分支规则兜底",
    fast_exit: "快速低风险",
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

function formatReportMode(value?: string) {
  const labels: Record<string, string> = {
    full_case: "完整报告",
    fast_exit: "快速低风险报告",
  };
  return labels[String(value || "")] || value || "待确认";
}

function formatScenario(value: string) {
  const labels: Record<string, string> = {
    S0_GENERAL_UNKNOWN: "综合风险",
    S1_ATTACK_EXPLOIT: "链上漏洞 / 攻击风险",
    S2_EXCHANGE_ABNORMALITY: "交易所与系统运维风险",
    S3_STABLECOIN_RESERVE: "稳定币异常风险",
    S4_INFRASTRUCTURE_FAILURE: "基础设施 / 协议层异常风险",
    S5_REGULATORY_ENFORCEMENT: "监管与法律风险",
    S6_MARKET_LIQUIDATION: "爆仓 / 清算风险",
    S7_FRAUD_GOVERNANCE: "诈骗 / 跑路 / Rug Pull 风险",
    S8_WHALE_ONCHAIN_FLOW: "大额转账 / 巨鲸行为风险",
  };
  return labels[value] || value;
}

function formatCalibrationRule(value: string) {
  const [scope, score] = value.split(":");
  const scopeLabel = formatScenario(scope) || formatEvidenceSignal(scope);
  return score ? `${scopeLabel} 校准阈值 ${score}` : formatEvidenceSignal(value);
}

function formatValidationAction(value?: string) {
  const labels: Record<string, string> = {
    cap_score: "二次校验：压低最高分",
    raise_floor: "二次校验：抬高最低分",
    no_change: "二次校验：无需调整",
  };
  return labels[String(value || "")] || value || "未触发校验";
}

function formatUnknownValue(value: unknown) {
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (value === null || value === undefined || value === "") return "无";
  if (Array.isArray(value)) return value.join("、");
  return String(value);
}

function EventConclusion({ categories, report }: { categories: string[]; report: RiskReport }) {
  const summary = compactReportSummary(report.summary);
  const signals = (report.risk_signals || []).map(compactReportSummary).filter(Boolean).slice(0, 3);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-blue-100 bg-gradient-to-br from-blue-50 to-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-blue-600 px-2.5 py-1 text-xs font-bold text-white">{report.risk_level || "待确认"}</span>
          <span className="rounded-md border border-blue-200 bg-white px-2.5 py-1 text-xs font-bold text-blue-700">
            风险 {clampScore(report.risk_score)}/100
          </span>
          <span className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-bold text-slate-600">
            置信度 {clampScore(report.confidence_score ?? 0)}/100
          </span>
        </div>
        <p className="mt-3 text-base font-bold leading-7 text-slate-950">{summary || "暂无事件结论。"}</p>
        <p className="mt-2 text-sm font-semibold text-slate-500">{categories.join(" / ")}</p>
      </div>
      {signals.length > 0 && (
        <div className="grid gap-2 md:grid-cols-3">
          {signals.map((signal, index) => (
            <div key={`${signal}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold leading-6 text-slate-700">
              {signal}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReportSection({ children, icon, title }: { children: ReactNode; icon: ReactNode; title: string }) {
  return (
    <section className="risk-panel rounded-lg p-5">
      <div className="mb-4 flex items-center gap-2">
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

function TrendCard({ title, withLegend = false }: { title: string; withLegend?: boolean }) {
  return (
    <section className="risk-card rounded-lg p-5">
      <div className="flex items-center justify-between">
        <PanelTitle icon={<ChartIcon />} title={title} />
        <span className="rounded-lg border border-blue-100 px-2 py-1 text-xs font-semibold text-slate-500">24小时</span>
      </div>
      <div className="mt-5 h-40 rounded-lg bg-slate-50 p-3">
        <svg className="h-full w-full" viewBox="0 0 340 130" role="img" aria-label="风险趋势">
          {[20, 50, 80, 110].map((y) => (
            <line key={y} x1="0" x2="340" y1={y} y2={y} stroke="#dbeafe" strokeDasharray="4 4" />
          ))}
          <polyline
            points="0,86 26,91 52,78 78,88 104,67 130,72 156,62 182,47 208,70 234,49 260,43 286,55 312,50 340,42"
            fill="none"
            stroke="#2563eb"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="130" cy="72" r="5" fill="#2563eb" />
        </svg>
      </div>
      {withLegend && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
          {["SOL", "FTT", "LUNC", "XRP", "BNB"].map((item) => (
            <span key={item} className="rounded-full border border-blue-100 px-3 py-1">{item}</span>
          ))}
        </div>
      )}
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

function Sparkline({ tone }: { tone: "blue" | "red" | "orange" | "green" | "purple" }) {
  const color = {
    blue: "#2563eb",
    red: "#ef4444",
    orange: "#f97316",
    green: "#10b981",
    purple: "#7c3aed",
  }[tone];

  return (
    <svg className="mt-8 h-8 w-20" viewBox="0 0 88 32" aria-hidden="true">
      <polyline
        points="0,24 10,20 18,23 28,12 38,18 48,8 58,25 68,16 78,20 88,12"
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MiniTrend() {
  return (
    <svg className="h-8 w-20" viewBox="0 0 80 28" aria-hidden="true">
      <polyline
        points="0,22 8,21 16,9 24,18 32,5 40,22 48,16 56,20 64,8 72,17 80,14"
        fill="none"
        stroke="#ef4444"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
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
    portfolio: ["我的风险资产", "Portfolio Risk Radar 个性化资产风险监控"],
    sim: ["模拟交易盘", "基于最近 7 天 15 分钟 K 线的现货模拟回放"],
    reports: ["分析报告", "查看、管理与导出风险分析结果报告"],
    settings: ["系统设置", "Agent 运行状态与新闻更新"],
  } satisfies Record<ActiveView, [string, string]>;

  return { title: map[view][0], subtitle: map[view][1] };
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

function formatTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function getVisibleNewsItems(items: NewsRankingItem[], filter: NewsFilter, sort: NewsSort) {
  const filtered = items.filter((item) => {
    if (filter === "all" || filter === "top10") return true;
    if (filter === "high") return isHighRiskNews(item);
    if (filter === "medium") return isMediumRiskNews(item);
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
  return items.filter((item) => {
    const level = item.risk_level || "";
    return level.includes("红") || clampScore(item.risk_score) >= 90;
  }).length;
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
  return ["all", "top10", "high", "medium", "low"].includes(value);
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
  const timestamp = Date.parse(value);
  if (!Number.isNaN(timestamp)) return timestamp;

  const timeMatch = value.match(/(\d{1,2}):(\d{2})/);
  if (!timeMatch) return 0;
  return Number(timeMatch[1]) * 60 + Number(timeMatch[2]);
}

function shouldAttachAssistantPageContext(
  question: string,
  context: {
    activeView: ActiveView;
    latestReport: RiskReport | null;
    topCoin: CoinRankingItem;
    topNews: NewsRankingItem;
  }
) {
  const normalized = question.toLowerCase();
  const directPageTerms = [
    "当前页面",
    "这个页面",
    "页面",
    "这里",
    "这个",
    "这条",
    "这篇",
    "当前",
    "上面",
    "右侧",
    "左侧",
  ];
  const pageDataTerms = [
    "风险分",
    "风险评分",
    "排行榜",
    "榜单",
    "证据",
    "报告",
  ];
  if (directPageTerms.some((term) => normalized.includes(term.toLowerCase()))) return true;

  const symbols = [
    context.topCoin.symbol,
    context.topCoin.name,
    ...(context.topNews.coins || []),
  ]
    .filter(Boolean)
    .map((item) => String(item).toLowerCase());
  const matchesCurrentAsset = symbols.some((symbol) => symbol && normalized.includes(symbol));
  return matchesCurrentAsset && pageDataTerms.some((term) => normalized.includes(term.toLowerCase()));
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
  const summary = compactReportSummary(report.summary) || "事件已完成结构化风险研判";
  const signals = report.risk_signals?.map(compactReportSummary).filter(Boolean).slice(0, 2).join("、");
  const lowRiskGate = (report.low_risk_gate || report.chat_agent_result?.low_risk_gate || {}) as Record<string, unknown>;
  const lowRiskGateText = formatLowRiskGateBrief(lowRiskGate);
  const advice = sanitizeAdvice(report.advice || []).slice(0, 2).join("；");

  return [
    `${summary}。`,
    `风险 ${clampScore(report.risk_score)}/100（${report.risk_level || "待确认"}），置信度 ${clampScore(report.confidence_score ?? 0)}/100。`,
    lowRiskGateText,
    signals ? `关键信号：${signals}。` : `类别：${categories}。`,
    advice ? `建议：${advice}。` : "",
  ].filter(Boolean).join("\n");
}

function formatLowRiskGateBrief(gate: Record<string, unknown>) {
  if (!Object.keys(gate).length) return "";
  const escalated = Boolean(gate.escalate_to_high_risk);
  const confirmed = Boolean(gate.low_risk_confirmed);
  const reason = compactReportSummary(String(gate.reason || ""));
  const status = escalated
    ? "低风险门控：已升级进入深度分析"
    : confirmed
      ? "低风险门控：已复核，未升级"
      : "低风险门控：已复核";
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
    return [
      { label: "监测币种总数", value: loading ? "--" : String(coinItems.length), delta: "实时数据", tone: "blue" as const, icon: <CoinIcon /> },
      { label: "高风险币种", value: loading ? "--" : String(coinDistribution.high), delta: "实时数据", tone: "red" as const, icon: <AlertIcon /> },
      { label: "平均币种风险分", value: loading ? "--" : String(averageCoinRiskScore), delta: "实时数据", tone: "blue" as const, icon: <TrendIcon /> },
      { label: "关联新闻数", value: loading ? "--" : String(coinNewsCount), delta: "实时聚合", tone: "orange" as const, icon: <FileIcon /> },
    ];
  }

  if (view === "news") {
    return [
      { label: "监测新闻总数", value: loading ? "--" : String(newsTotal), delta: "实时数据", tone: "blue" as const, icon: <FileIcon /> },
      { label: "高风险新闻", value: loading ? "--" : String(distribution.high), delta: "实时数据", tone: "red" as const, icon: <AlertIcon /> },
      { label: "平均风险分", value: loading ? "--" : String(averageRiskScore), delta: "实时数据", tone: "blue" as const, icon: <TrendIcon /> },
      { label: "红色预警事件", value: loading ? "--" : String(redAlertCount), delta: "实时数据", tone: "orange" as const, icon: <ShieldIcon /> },
    ];
  }

  return [
    { label: "今日高风险新闻", value: loading ? "--" : String(distribution.high || overview?.high_risk_news || (topNews.risk_score > 80 ? 1 : 0)), delta: "实时数据", tone: "red" as const, icon: <FileIcon /> },
    { label: "红色预警事件", value: loading ? "--" : String(redAlertCount), delta: "实时数据", tone: "orange" as const, icon: <ShieldIcon /> },
    { label: "平均风险分", value: loading ? "--" : String(averageRiskScore), delta: "实时数据", tone: "blue" as const, icon: <TrendIcon /> },
    { label: "实时监测状态", value: "运行中", delta: "所有 Agent 正常", tone: "green" as const, icon: <SmileIcon /> },
  ];
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value || 0)));
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
function GearIcon() { return <IconSvg><circle cx="12" cy="12" r="3" /><path d="M19.4 15a8 8 0 0 0 .1-2l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L15 5.5h-4l-.4 2.6a8 8 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a8 8 0 0 0 .1 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.7 1l.4 2.6h4l.4-2.6a8 8 0 0 0 1.7-1l2.4 1 2-3.4z" /></IconSvg>; }
function ShieldIcon() { return <IconSvg><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" /><path d="m9 12 2 2 4-5" /></IconSvg>; }
function AlertIcon() { return <IconSvg><path d="m12 3 10 18H2z" /><path d="M12 9v5" /><path d="M12 18h.01" /></IconSvg>; }
function ClockIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></IconSvg>; }
function SmileIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="M8 14s1.5 2 4 2 4-2 4-2" /><path d="M9 9h.01" /><path d="M15 9h.01" /></IconSvg>; }
function TrendIcon() { return <IconSvg><path d="m4 16 5-5 4 4 7-8" /><path d="M14 7h6v6" /></IconSvg>; }
function SendIcon() { return <IconSvg><path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4z" /></IconSvg>; }
function BotIcon() { return <IconSvg><rect x="5" y="8" width="14" height="11" rx="4" /><path d="M12 4v4" /><path d="M9 13h.01" /><path d="M15 13h.01" /><path d="M10 17h4" /></IconSvg>; }
function ThumbIcon({ down = false }: { down?: boolean }) { return <IconSvg><path d={down ? "M7 10v10H4V10z" : "M7 14V4H4v10z"} /><path d={down ? "M7 18h9l-1 4 5-6V7a2 2 0 0 0-2-2H9z" : "M7 6h9l-1-4 5 6v9a2 2 0 0 1-2 2H9z"} /></IconSvg>; }
function UsersIcon() { return <IconSvg><path d="M16 21v-2a4 4 0 0 0-8 0v2" /><circle cx="12" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.8" /><path d="M16 3.1a4 4 0 0 1 0 7.8" /></IconSvg>; }
function BulbIcon() { return <IconSvg><path d="M9 18h6" /><path d="M10 22h4" /><path d="M8 14a6 6 0 1 1 8 0c-1 1-1 2-1 4H9c0-2 0-3-1-4Z" /></IconSvg>; }
function PlusIcon() { return <IconSvg><path d="M12 5v14" /><path d="M5 12h14" /></IconSvg>; }
function CheckIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></IconSvg>; }
function ChevronLeftIcon() { return <IconSvg><path d="m15 18-6-6 6-6" /></IconSvg>; }
function ChevronRightIcon() { return <IconSvg><path d="m9 18 6-6-6-6" /></IconSvg>; }
function ChevronDownIcon() { return <IconSvg><path d="m6 9 6 6 6-6" /></IconSvg>; }
function ChevronUpIcon() { return <IconSvg><path d="m18 15-6-6-6 6" /></IconSvg>; }
function TrashIcon() { return <IconSvg><path d="M4 7h16" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M6 7l1 14h10l1-14" /><path d="M9 7V4h6v3" /></IconSvg>; }
function RefreshIcon() { return <IconSvg><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v6h-6" /></IconSvg>; }
