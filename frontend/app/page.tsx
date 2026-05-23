"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  CoinRankingItem,
  fetchCoinRanking,
  fetchNewsRanking,
  fetchRiskOverview,
  NewsRankingItem,
  RiskOverview,
  RiskReport,
  sendChatMessage,
} from "@/lib/api";

type ActiveView = "home" | "chat" | "ranking";
type RankingMode = "news" | "coin";
type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
};

type Example = {
  label: string;
  text: string;
};

const examples: Example[] = [
  {
    label: "DeFi 攻击事件",
    text: "某 DeFi 协议疑似遭遇 flash loan attack，攻击者从资金池转出约 1200 万美元资产，团队表示正在暂停合约并排查漏洞。",
  },
  {
    label: "交易所暂停提现",
    text: "某中心化交易所突然公告暂停 BTC、ETH 和 USDT 提现，理由是钱包系统维护，但社区反馈已经超过 8 小时无法提现。",
  },
  {
    label: "稳定币脱锚",
    text: "USDC 在多个交易所出现短时脱锚，价格跌至 0.92 美元附近，市场担心储备资产和赎回通道的透明度。",
  },
  {
    label: "巨鲸大额转账",
    text: "链上监测显示，一个沉睡 5 年的巨鲸地址向 Binance 转入 18,000 ETH，市场担心短期潜在抛压扩大。",
  },
];

const workflowSteps = [
  "Input",
  "Detect",
  "Classify",
  "Evidence",
  "Score",
  "Impact",
  "Advice",
  "Report",
];

const forbiddenAdviceTerms = ["买入", "卖出", "做空", "梭哈"];

export default function Home() {
  const [activeView, setActiveView] = useState<ActiveView>("home");
  const [rankingMode, setRankingMode] = useState<RankingMode>("news");
  const [overview, setOverview] = useState<RiskOverview | null>(null);
  const [newsRanking, setNewsRanking] = useState<NewsRankingItem[]>([]);
  const [coinRanking, setCoinRanking] = useState<CoinRankingItem[]>([]);
  const [rankingLoading, setRankingLoading] = useState(true);
  const [rankingError, setRankingError] = useState("");

  const [message, setMessage] = useState(examples[0].text);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "你好，我是 CryptoRisk Agent。输入加密货币新闻、链上事件或交易所公告，我会输出风险评分、证据和风控建议。",
    },
  ]);
  const [latestReport, setLatestReport] = useState<RiskReport | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");

  useEffect(() => {
    let ignore = false;

    async function loadRankings() {
      setRankingLoading(true);
      setRankingError("");
      try {
        const [overviewData, newsData, coinData] = await Promise.all([
          fetchRiskOverview(),
          fetchNewsRanking(10),
          fetchCoinRanking(10),
        ]);
        if (ignore) return;
        setOverview(overviewData);
        setNewsRanking(newsData.items);
        setCoinRanking(coinData.items);
      } catch (error) {
        console.error(error);
        if (!ignore) {
          setRankingError("排行榜数据加载失败，请确认 FastAPI 后端已启动。");
        }
      } finally {
        if (!ignore) setRankingLoading(false);
      }
    }

    loadRankings();
    return () => {
      ignore = true;
    };
  }, []);

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
    };

    setChatMessages((items) => [...items, userMessage]);
    setChatLoading(true);
    setChatError("");
    setMessage("");

    try {
      const response = await sendChatMessage(trimmed);
      setLatestReport(response.data);
      setChatMessages((items) => [
        ...items,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: response.data.summary,
        },
      ]);
    } catch (error) {
      console.error(error);
      setChatError("请求后端失败，请检查 FastAPI 是否启动，或查看后端终端报错。");
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <main className="min-h-screen overflow-x-hidden bg-gradient-to-br from-slate-50 via-white to-indigo-50 text-slate-900">
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute left-[-9rem] top-[-8rem] h-80 w-80 rounded-full bg-blue-200/50 blur-3xl" />
        <div className="absolute right-[-8rem] top-36 h-96 w-96 rounded-full bg-indigo-200/45 blur-3xl" />
        <div className="absolute bottom-[-10rem] left-1/3 h-96 w-96 rounded-full bg-orange-100/70 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-screen w-full max-w-7xl flex-col px-4 py-6 sm:px-6 lg:px-8">
        <Header activeView={activeView} onChangeView={setActiveView} />

        <section className="mt-5">
          <RiskOverviewCards
            loading={rankingLoading}
            overview={overview}
            onOpenRanking={() => setActiveView("ranking")}
          />
        </section>

        <section className="py-5">
          {activeView === "home" && (
            <DashboardHome
              coinRanking={coinRanking}
              error={rankingError}
              loading={rankingLoading}
              newsRanking={newsRanking}
              overview={overview}
              onOpenChat={() => setActiveView("chat")}
              onOpenRanking={() => setActiveView("ranking")}
            />
          )}

          {activeView === "chat" && (
            <ChatPanel
              chatError={chatError}
              chatLoading={chatLoading}
              chatMessages={chatMessages}
              latestReport={latestReport}
              message={message}
              onExampleClick={setMessage}
              onMessageChange={setMessage}
              onSubmit={handleChatSubmit}
            />
          )}

          {activeView === "ranking" && (
            <RiskRankingPanel
              coinItems={coinRanking}
              error={rankingError}
              loading={rankingLoading}
              mode={rankingMode}
              newsItems={newsRanking}
              onModeChange={setRankingMode}
            />
          )}
        </section>
      </div>
    </main>
  );
}

function Header({
  activeView,
  onChangeView,
}: {
  activeView: ActiveView;
  onChangeView: (view: ActiveView) => void;
}) {
  return (
    <header className="rounded-3xl border border-white/70 bg-white/85 p-6 shadow-sm backdrop-blur">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Crypto Risk Control
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950 sm:text-4xl">
            CryptoRisk Agent
          </h1>
          <p className="mt-2 text-sm text-slate-500 sm:text-base">
            AI-powered Crypto Risk Control Dashboard
          </p>
        </div>

        <div className="flex flex-col gap-3 sm:items-end">
          <nav className="flex flex-wrap gap-2">
            <NavButton
              active={activeView === "home"}
              label="总览"
              onClick={() => onChangeView("home")}
            />
            <NavButton
              active={activeView === "chat"}
              label="风险聊天"
              onClick={() => onChangeView("chat")}
            />
            <NavButton
              active={activeView === "ranking"}
              label="今日排行榜"
              onClick={() => onChangeView("ranking")}
            />
          </nav>
          <div className="flex flex-wrap gap-2">
            {["Multi-Agent", "Crypto Risk", "Evidence-based", "Risk Scoring"].map(
              (tag) => (
                <span
                  key={tag}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 shadow-sm"
                >
                  {tag}
                </span>
              )
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

function NavButton({
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
      className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
        active
          ? "bg-gradient-to-r from-blue-500 to-indigo-500 text-white shadow-md shadow-blue-200"
          : "border border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
      }`}
    >
      {label}
    </button>
  );
}

function DashboardHome({
  coinRanking,
  error,
  loading,
  newsRanking,
  overview,
  onOpenChat,
  onOpenRanking,
}: {
  coinRanking: CoinRankingItem[];
  error: string;
  loading: boolean;
  newsRanking: NewsRankingItem[];
  overview: RiskOverview | null;
  onOpenChat: () => void;
  onOpenRanking: () => void;
}) {
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <FeatureEntryCard
          badge="AI 风控入口"
          buttonText="进入风险聊天"
          description="粘贴新闻、公告、链上告警或项目异常，实时生成风险评分、证据和处置建议。"
          gradient="from-blue-500 to-indigo-500"
          title="风险聊天"
          onClick={onOpenChat}
        />
        <FeatureEntryCard
          badge="300 条新闻分析"
          buttonText="查看今日排行榜"
          description="基于本地加密货币新闻数据，展示单条新闻风险榜和币种聚合风险榜。"
          gradient="from-orange-400 to-rose-500"
          title="今日风险排行榜"
          onClick={onOpenRanking}
        />
      </div>

      {error && <Notice tone="red" text={error} />}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <PreviewCard
          title="排行榜前十预览"
          subtitle="按单条新闻风险分数排序"
          actionLabel="查看完整榜单"
          onAction={onOpenRanking}
        >
          {loading ? (
            <SkeletonRows count={6} />
          ) : (
            <div className="space-y-3">
              {newsRanking.slice(0, 10).map((item) => (
                <CompactNewsRow key={item.news_id} item={item} />
              ))}
            </div>
          )}
        </PreviewCard>

        <PreviewCard
          title="高风险聚焦"
          subtitle="今日最高风险新闻与最高风险币种"
          actionLabel="打开排行榜"
          onAction={onOpenRanking}
        >
          <div className="space-y-4">
            <FocusBlock
              label="今日最高风险新闻"
              title={overview?.top_news?.title || "暂无数据"}
              meta={
                overview?.top_news
                  ? `${overview.top_news.risk_score} 分 · ${overview.top_news.risk_type}`
                  : "等待后端返回"
              }
              tone="red"
            />
            <FocusBlock
              label="当前最高风险币种"
              title={
                overview?.top_coin
                  ? `${overview.top_coin.symbol} · ${overview.top_coin.name}`
                  : "暂无数据"
              }
              meta={
                overview?.top_coin
                  ? `${overview.top_coin.final_score} 分 · ${overview.top_coin.news_count} 条相关新闻`
                  : "等待后端返回"
              }
              tone="blue"
            />
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-sm font-semibold text-slate-900">币种风险 Top 5</p>
              <div className="mt-3 space-y-2">
                {coinRanking.slice(0, 5).map((item) => (
                  <CompactCoinRow key={item.symbol} item={item} />
                ))}
              </div>
            </div>
          </div>
        </PreviewCard>
      </div>
    </div>
  );
}

function FeatureEntryCard({
  badge,
  buttonText,
  description,
  gradient,
  title,
  onClick,
}: {
  badge: string;
  buttonText: string;
  description: string;
  gradient: string;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group rounded-3xl border border-slate-200 bg-white p-6 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-4">
        <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
          {badge}
        </span>
        <span
          className={`h-12 w-12 rounded-2xl bg-gradient-to-br ${gradient} opacity-90 shadow-lg transition group-hover:scale-105`}
        />
      </div>
      <h2 className="mt-6 text-2xl font-semibold text-slate-950">{title}</h2>
      <p className="mt-3 max-w-xl text-sm leading-6 text-slate-500">{description}</p>
      <span className="mt-6 inline-flex rounded-full bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
        {buttonText}
      </span>
    </button>
  );
}

function RiskOverviewCards({
  loading,
  overview,
  onOpenRanking,
}: {
  loading: boolean;
  overview: RiskOverview | null;
  onOpenRanking: () => void;
}) {
  const cards = [
    {
      label: "今日新闻数",
      value: loading ? "--" : String(overview?.total_news ?? 0),
      hint: overview?.date || "Today",
      style: "border-t-blue-400 bg-blue-50 text-blue-700",
    },
    {
      label: "高风险新闻",
      value: loading ? "--" : String(overview?.high_risk_news ?? 0),
      hint: "High risk items",
      style: "border-t-red-400 bg-red-50 text-red-700",
    },
    {
      label: "最高风险新闻",
      value: overview?.top_news ? `${overview.top_news.risk_score}` : "--",
      hint: overview?.top_news?.risk_level || "Risk score",
      style: "border-t-orange-400 bg-orange-50 text-orange-700",
    },
    {
      label: "最高风险币种",
      value: overview?.top_coin?.symbol || "--",
      hint: overview?.top_coin ? `${overview.top_coin.final_score} 分` : "Coin ranking",
      style: "border-t-emerald-400 bg-emerald-50 text-emerald-700",
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((card) => (
        <button
          key={card.label}
          type="button"
          onClick={onOpenRanking}
          className="rounded-2xl border border-slate-200 border-t-4 bg-white p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
        >
          <div className={`rounded-2xl p-3 ${card.style}`}>
            <p className="text-xs font-semibold">{card.label}</p>
            <p className="mt-2 text-2xl font-semibold text-slate-950">{card.value}</p>
            <p className="mt-1 truncate text-xs text-slate-500">{card.hint}</p>
          </div>
        </button>
      ))}
    </div>
  );
}

function ChatPanel({
  chatError,
  chatLoading,
  chatMessages,
  latestReport,
  message,
  onExampleClick,
  onMessageChange,
  onSubmit,
}: {
  chatError: string;
  chatLoading: boolean;
  chatMessages: ChatMessage[];
  latestReport: RiskReport | null;
  message: string;
  onExampleClick: (value: string) => void;
  onMessageChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,0.38fr)_minmax(0,0.62fr)]">
      <form
        onSubmit={onSubmit}
        className="rounded-3xl border border-slate-200 bg-white p-5 shadow-md shadow-slate-200/70"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">
              Risk Analysis Console
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              输入加密货币新闻、链上事件、交易所公告或项目异常信息。
            </p>
          </div>
          <span className="rounded-2xl border border-purple-100 bg-purple-50 px-3 py-2 text-xs font-semibold text-purple-700">
            Chat
          </span>
        </div>

        <div className="mt-5 max-h-72 space-y-3 overflow-y-auto rounded-3xl border border-slate-200 bg-slate-50 p-3">
          {chatMessages.map((item) => (
            <div
              key={item.id}
              className={`rounded-2xl px-4 py-3 text-sm leading-6 ${
                item.role === "user"
                  ? "ml-6 bg-blue-600 text-white"
                  : "mr-6 border border-slate-200 bg-white text-slate-700"
              }`}
            >
              {item.content}
            </div>
          ))}
          {chatLoading && (
            <div className="mr-6 rounded-2xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">
              Multi-Agent 正在分析中...
            </div>
          )}
        </div>

        <textarea
          value={message}
          onChange={(event) => onMessageChange(event.target.value)}
          className="mt-4 min-h-44 w-full resize-none rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-200 focus:bg-white focus:shadow-sm"
          placeholder="粘贴新闻、公告、链上告警、稳定币异常或 Rug Pull 线索..."
        />

        <button
          type="submit"
          disabled={chatLoading}
          className="mt-4 w-full rounded-2xl bg-gradient-to-r from-blue-500 to-indigo-500 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-blue-200 transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-blue-200 disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {chatLoading ? "分析中..." : "发送分析"}
        </button>

        {chatError && <Notice tone="red" text={chatError} />}

        <div className="mt-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            示例输入
          </p>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {examples.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() => onExampleClick(example.text)}
                className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-left text-sm font-medium text-slate-700 shadow-sm transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
              >
                {example.label}
              </button>
            ))}
          </div>
        </div>
      </form>

      <ChatRiskDashboard report={latestReport} />
    </div>
  );
}

function ChatRiskDashboard({ report }: { report: RiskReport | null }) {
  if (!report) {
    return (
      <section className="relative flex min-h-[640px] items-center justify-center overflow-hidden rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="absolute h-72 w-72 rounded-full bg-gradient-to-br from-blue-100 via-indigo-100 to-purple-100" />
        <div className="relative max-w-md text-center">
          <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-3xl border border-blue-100 bg-white shadow-md shadow-blue-100">
            <span className="h-3 w-3 rounded-full bg-blue-500" />
          </div>
          <h2 className="text-2xl font-semibold text-slate-950">等待风险分析</h2>
          <p className="mt-3 text-sm leading-7 text-slate-500">
            发送事件文本后，Multi-Agent 工作流将生成风险评分、证据和处置建议。
          </p>
        </div>
      </section>
    );
  }

  const score = clampScore(report.risk_score);
  const impacts = splitImpact(report.impact);
  const advice = sanitizeAdvice(report.advice);

  return (
    <div className="space-y-5">
      <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)]">
          <div className="rounded-3xl border border-orange-100 bg-gradient-to-br from-orange-50 to-red-50 p-5">
            <p className="text-sm font-medium text-orange-700">Risk Score</p>
            <div className="mt-3 flex items-end gap-2">
              <p className="text-5xl font-semibold text-slate-950">{score}</p>
              <p className="pb-2 text-lg text-slate-500">/ 100</p>
            </div>
            <RiskBadge level={report.risk_level} />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-500">综合判断</p>
            <p className="mt-2 max-w-3xl text-base leading-7 text-slate-700">
              {report.summary}
            </p>
            <div className="mt-6 h-4 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-gradient-to-r from-orange-400 to-red-500"
                style={{ width: `${score}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      <WorkflowCard />

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="风险类别">
          <div className="flex flex-wrap gap-2">
            {report.risk_categories.length ? (
              report.risk_categories.map((category) => (
                <RiskTag key={category} category={category} />
              ))
            ) : (
              <EmptyLine text="暂无风险类别。" />
            )}
          </div>
        </Panel>
        <Panel title="评分拆解">
          <ScoreBreakdownBars breakdown={report.score_breakdown} />
        </Panel>
      </div>

      <Panel title="Evidence Timeline">
        <div className="space-y-3">
          {report.evidence.length ? (
            report.evidence.map((item, index) => (
              <EvidenceCard
                key={`${item.risk_category}-${index}`}
                evidence={item.evidence_text}
                label={item.risk_category}
                reason={item.explanation}
                rank={index + 1}
              />
            ))
          ) : (
            <EmptyLine text="暂无证据。" />
          )}
        </div>
      </Panel>

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="可能影响">
          <div className="grid gap-3 sm:grid-cols-2">
            <ImpactColumn
              bg="bg-blue-50"
              border="border-blue-100"
              items={impacts.objects}
              title="影响对象"
              titleColor="text-blue-700"
            />
            <ImpactColumn
              bg="bg-orange-50"
              border="border-orange-100"
              items={impacts.consequences}
              title="可能后果"
              titleColor="text-orange-700"
            />
          </div>
        </Panel>
        <Panel title="处置建议">
          <AdviceList items={advice} />
        </Panel>
      </div>
    </div>
  );
}

function RiskRankingPanel({
  coinItems,
  error,
  loading,
  mode,
  newsItems,
  onModeChange,
}: {
  coinItems: CoinRankingItem[];
  error: string;
  loading: boolean;
  mode: RankingMode;
  newsItems: NewsRankingItem[];
  onModeChange: (mode: RankingMode) => void;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-col gap-4 border-b border-slate-200 pb-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-semibold text-slate-950">今日风险排行榜</h2>
          <p className="mt-2 text-sm text-slate-500">
            基于本地 300 条加密货币新闻生成，不接爬虫，不请求外部新闻源。
          </p>
        </div>
        <div className="flex flex-wrap gap-2 rounded-2xl bg-slate-100 p-1">
          <TabButton
            active={mode === "news"}
            label="新闻风险分数排行榜"
            onClick={() => onModeChange("news")}
          />
          <TabButton
            active={mode === "coin"}
            label="币种风险排行榜"
            onClick={() => onModeChange("coin")}
          />
        </div>
      </div>

      {error && <Notice tone="red" text={error} />}

      <div className="mt-5">
        {loading ? (
          <SkeletonRows count={10} />
        ) : mode === "news" ? (
          <NewsRiskRankingTable items={newsItems} />
        ) : (
          <CoinRiskRankingTable items={coinItems} />
        )}
      </div>
    </section>
  );
}

function NewsRiskRankingTable({ items }: { items: NewsRankingItem[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!items.length) {
    return <EmptyLine text="暂无新闻排行榜数据。" />;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const expanded = expandedId === item.news_id;
        return (
          <article
            key={item.news_id}
            className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <button
              type="button"
              onClick={() => setExpandedId(expanded ? null : item.news_id)}
              className="grid w-full gap-3 text-left lg:grid-cols-[52px_minmax(0,1fr)_120px_110px]"
            >
              <RankNumber rank={item.rank} />
              <div className="min-w-0">
                <h3 className="line-clamp-2 text-base font-semibold text-slate-950">
                  {item.title}
                </h3>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span>{item.published_at || "暂无时间"}</span>
                  <span>·</span>
                  <RiskTag category={item.risk_type} />
                  {item.coins.map((coin) => (
                    <span
                      key={coin}
                      className="rounded-full border border-cyan-100 bg-cyan-50 px-2 py-1 font-semibold text-cyan-700"
                    >
                      {coin}
                    </span>
                  ))}
                </div>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-500">
                  {item.summary}
                </p>
              </div>
              <ScorePill score={item.risk_score} />
              <RiskBadge level={item.risk_level} />
            </button>

            {expanded && (
              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-semibold text-slate-900">风险理由 / Evidence</p>
                <p className="mt-2 text-sm leading-6 text-slate-600">{item.evidence}</p>
                <p className="mt-4 text-sm font-semibold text-slate-900">新闻正文 / 摘要</p>
                <p className="mt-2 text-sm leading-7 text-slate-600">{item.content}</p>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function CoinRiskRankingTable({ items }: { items: CoinRankingItem[] }) {
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  if (!items.length) {
    return <EmptyLine text="暂无币种排行榜数据。" />;
  }

  return (
    <div className="space-y-3">
      {items.map((item) => {
        const expanded = expandedSymbol === item.symbol;
        return (
          <article
            key={item.symbol}
            className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
          >
            <button
              type="button"
              onClick={() => setExpandedSymbol(expanded ? null : item.symbol)}
              className="grid w-full gap-3 text-left lg:grid-cols-[52px_120px_minmax(0,1fr)_130px_110px]"
            >
              <RankNumber rank={item.rank} />
              <div>
                <p className="text-lg font-semibold text-slate-950">{item.symbol}</p>
                <p className="text-xs text-slate-500">{item.name}</p>
              </div>
              <div className="min-w-0">
                <h3 className="line-clamp-2 font-semibold text-slate-900">
                  {item.top_news_title}
                </h3>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-500">
                  {item.summary}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <RiskTag category={item.main_risk_type} />
                  <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">
                    {item.news_count} 条相关新闻
                  </span>
                </div>
              </div>
              <ScorePill score={item.final_score} />
              <RiskBadge level={item.risk_level} />
            </button>

            {expanded && (
              <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-sm font-semibold text-slate-900">相关新闻</p>
                <div className="mt-3 space-y-2">
                  {item.related_news.map((news) => (
                    <div
                      key={news.news_id}
                      className="rounded-xl border border-slate-200 bg-white p-3"
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <p className="text-sm font-medium text-slate-800">{news.title}</p>
                        <span className="text-sm font-semibold text-orange-600">
                          {news.risk_score} 分
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {news.published_at || "暂无时间"} · {news.risk_type}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}

function TabButton({
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
      className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${
        active
          ? "bg-white text-blue-700 shadow-sm"
          : "text-slate-500 hover:text-slate-800"
      }`}
    >
      {label}
    </button>
  );
}

function WorkflowCard() {
  return (
    <Panel title="Multi-Agent Workflow">
      <div className="flex flex-wrap items-center gap-2">
        {workflowSteps.map((step, index) => (
          <div key={step} className="flex items-center gap-2">
            <span className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">
              <span className="mr-2 inline-block h-2 w-2 rounded-full bg-emerald-500" />
              {step}
            </span>
            {index < workflowSteps.length - 1 && (
              <span className="hidden h-px w-5 bg-slate-200 sm:block" />
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ScoreBreakdownBars({ breakdown }: { breakdown: RiskReport["score_breakdown"] }) {
  const rows = [
    ["事件严重性", breakdown?.severity ?? 0, "from-red-400 to-rose-500"],
    ["证据强度", breakdown?.evidence_strength ?? 0, "from-orange-400 to-amber-500"],
    ["影响范围", breakdown?.impact_scope ?? 0, "from-blue-400 to-indigo-500"],
    ["紧急程度", breakdown?.urgency ?? 0, "from-violet-400 to-purple-500"],
    ["可逆性", breakdown?.reversibility ?? 0, "from-emerald-400 to-teal-500"],
  ] as const;

  return (
    <div className="space-y-4">
      {rows.map(([label, rawValue, gradient]) => {
        const value = clampScore(rawValue);
        return (
          <div key={label}>
            <div className="mb-2 flex items-center justify-between text-sm">
              <span className="text-slate-700">{label}</span>
              <span className="font-semibold text-slate-900">{value}</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full bg-gradient-to-r ${gradient}`}
                style={{ width: `${value}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EvidenceCard({
  evidence,
  label,
  rank,
  reason,
}: {
  evidence: string;
  label: string;
  rank: number;
  reason: string;
}) {
  return (
    <div className="relative rounded-2xl border border-slate-200 bg-white p-4 pl-6 shadow-sm">
      <div className="absolute bottom-4 left-0 top-4 w-1 rounded-full bg-gradient-to-b from-blue-400 via-orange-400 to-red-400" />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <p className="font-semibold text-slate-900">{label}</p>
        <span className="w-fit rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          Evidence {String(rank).padStart(2, "0")}
        </span>
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-700">{evidence}</p>
      <p className="mt-2 text-sm leading-6 text-slate-500">{reason}</p>
    </div>
  );
}

function ImpactColumn({
  bg,
  border,
  items,
  title,
  titleColor,
}: {
  bg: string;
  border: string;
  items: string[];
  title: string;
  titleColor: string;
}) {
  return (
    <div className={`rounded-2xl border ${border} ${bg} p-4`}>
      <p className={`text-sm font-semibold ${titleColor}`}>{title}</p>
      <div className="mt-3 space-y-2">
        {items.length === 0 ? (
          <EmptyLine text="暂无。" />
        ) : (
          items.map((item, index) => (
            <p key={`${title}-${index}`} className="text-sm leading-6 text-slate-600">
              {item}
            </p>
          ))
        )}
      </div>
    </div>
  );
}

function AdviceList({ items }: { items: string[] }) {
  if (!items.length) {
    return <EmptyLine text="暂无处置建议。" />;
  }

  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <div
          key={`${item}-${index}`}
          className="flex gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700"
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 text-xs font-semibold text-white">
            {index + 1}
          </span>
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
}

function PreviewCard({
  actionLabel,
  children,
  subtitle,
  title,
  onAction,
}: {
  actionLabel: string;
  children: React.ReactNode;
  subtitle: string;
  title: string;
  onAction: () => void;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={onAction}
          className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100"
        >
          {actionLabel}
        </button>
      </div>
      {children}
    </section>
  );
}

function Panel({
  children,
  title,
}: {
  children: React.ReactNode;
  title: string;
}) {
  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="mb-4 text-base font-semibold text-slate-950">{title}</h3>
      {children}
    </section>
  );
}

function CompactNewsRow({ item }: { item: NewsRankingItem }) {
  return (
    <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 sm:grid-cols-[42px_minmax(0,1fr)_80px]">
      <RankNumber rank={item.rank} compact />
      <div className="min-w-0">
        <p className="line-clamp-1 text-sm font-semibold text-slate-900">{item.title}</p>
        <p className="mt-1 line-clamp-1 text-xs text-slate-500">{item.summary}</p>
      </div>
      <ScorePill score={item.risk_score} compact />
    </div>
  );
}

function CompactCoinRow({ item }: { item: CoinRankingItem }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl bg-white px-3 py-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-900">
          {item.symbol}
          <span className="ml-2 font-normal text-slate-500">{item.name}</span>
        </p>
        <p className="truncate text-xs text-slate-500">{item.main_risk_type}</p>
      </div>
      <span className="text-sm font-semibold text-orange-600">{item.final_score}</span>
    </div>
  );
}

function FocusBlock({
  label,
  meta,
  title,
  tone,
}: {
  label: string;
  meta: string;
  title: string;
  tone: "red" | "blue";
}) {
  const style =
    tone === "red"
      ? "border-red-100 bg-red-50 text-red-700"
      : "border-blue-100 bg-blue-50 text-blue-700";
  return (
    <div className={`rounded-2xl border p-4 ${style}`}>
      <p className="text-xs font-semibold">{label}</p>
      <p className="mt-2 line-clamp-2 text-base font-semibold text-slate-950">{title}</p>
      <p className="mt-2 text-sm text-slate-600">{meta}</p>
    </div>
  );
}

function RankNumber({ compact = false, rank }: { compact?: boolean; rank: number }) {
  return (
    <div
      className={`flex shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-500 font-semibold text-white ${
        compact ? "h-9 w-9 text-sm" : "h-11 w-11"
      }`}
    >
      {rank}
    </div>
  );
}

function ScorePill({ compact = false, score }: { compact?: boolean; score: number }) {
  const value = clampScore(score);
  return (
    <div
      className={`w-fit rounded-2xl border bg-white text-center shadow-sm ${
        score >= 80
          ? "border-red-100 text-red-700"
          : score >= 50
            ? "border-orange-100 text-orange-700"
            : "border-emerald-100 text-emerald-700"
      } ${compact ? "px-3 py-2" : "px-4 py-3"}`}
    >
      <p className={compact ? "text-sm font-semibold" : "text-xl font-semibold"}>
        {value}
      </p>
      {!compact && <p className="text-xs text-slate-400">risk score</p>}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const style = riskLevelStyle(level);
  return (
    <span
      className={`inline-flex w-fit rounded-full border px-3 py-1 text-xs font-semibold ${style}`}
    >
      {level || "低风险"}
    </span>
  );
}

function RiskTag({ category }: { category: string }) {
  return (
    <span
      className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${categoryStyle(
        category
      )}`}
    >
      {category}
    </span>
  );
}

function Notice({ text, tone }: { text: string; tone: "red" | "blue" }) {
  const style =
    tone === "red"
      ? "border-red-100 bg-red-50 text-red-700"
      : "border-blue-100 bg-blue-50 text-blue-700";
  return <div className={`mt-4 rounded-2xl border px-4 py-3 text-sm ${style}`}>{text}</div>;
}

function SkeletonRows({ count }: { count: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="h-20 animate-pulse rounded-2xl border border-slate-200 bg-slate-100"
        />
      ))}
    </div>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <p className="text-sm text-slate-400">{text}</p>;
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value || 0)));
}

function splitImpact(items: string[]) {
  const midpoint = Math.ceil(items.length / 2);
  return {
    objects: items.slice(0, midpoint),
    consequences: items.slice(midpoint),
  };
}

function sanitizeAdvice(items: string[]) {
  return items.filter(
    (item) => !forbiddenAdviceTerms.some((term) => item.includes(term))
  );
}

function riskLevelStyle(level: string) {
  if (level.includes("高") || level.includes("极高")) {
    return "border-red-100 bg-red-50 text-red-700";
  }
  if (level.includes("中") || level.includes("轻微")) {
    return "border-orange-100 bg-orange-50 text-orange-700";
  }
  return "border-emerald-100 bg-emerald-50 text-emerald-700";
}

function categoryStyle(category: string) {
  if (category.includes("链上漏洞") || category.includes("攻击")) {
    return "border-red-100 bg-red-50 text-red-700";
  }
  if (category.includes("诈骗") || category.includes("跑路") || category.includes("Rug")) {
    return "border-rose-100 bg-rose-50 text-rose-700";
  }
  if (category.includes("监管") || category.includes("法律")) {
    return "border-amber-100 bg-amber-50 text-amber-700";
  }
  if (category.includes("交易所") || category.includes("运维")) {
    return "border-blue-100 bg-blue-50 text-blue-700";
  }
  if (category.includes("稳定币")) {
    return "border-yellow-100 bg-yellow-50 text-yellow-700";
  }
  if (category.includes("爆仓") || category.includes("清算")) {
    return "border-orange-100 bg-orange-50 text-orange-700";
  }
  if (category.includes("大额转账") || category.includes("巨鲸")) {
    return "border-purple-100 bg-purple-50 text-purple-700";
  }
  if (category.includes("异常行情")) {
    return "border-pink-100 bg-pink-50 text-pink-700";
  }
  if (category.includes("治理") || category.includes("团队")) {
    return "border-indigo-100 bg-indigo-50 text-indigo-700";
  }
  if (category.includes("偿付能力") || category.includes("储备") || category.includes("流动性")) {
    return "border-cyan-100 bg-cyan-50 text-cyan-700";
  }
  if (category.includes("基础设施") || category.includes("协议层")) {
    return "border-emerald-100 bg-emerald-50 text-emerald-700";
  }
  if (category.includes("宏观") || category.includes("政策")) {
    return "border-slate-200 bg-slate-100 text-slate-700";
  }
  return "border-blue-100 bg-blue-50 text-blue-700";
}
