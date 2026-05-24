"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { LoadingDots } from "@/components/ui/loading-states";
import { CoinRankingItem, fetchCoinDetail, readCachedCoinDetail } from "@/lib/api";

const coinDescriptions: Record<string, string> = {
  BTC: "Bitcoin 是最早的去中心化加密资产，常被视为加密市场的基准资产。其风险监测重点通常包括价格剧烈波动、杠杆清算、交易所资金流入流出和宏观流动性变化。",
  ETH: "Ethereum 是以智能合约和去中心化应用生态为核心的公链资产。其风险监测重点通常包括 DeFi 协议安全、质押与验证者变化、链上拥堵、合约漏洞和生态项目外溢风险。",
  SOL: "Solana 是高吞吐公链生态资产，常见风险来自链上活跃度异常、生态项目安全事件、网络稳定性、巨鲸转账和交易所流动性变化。",
  BNB: "BNB 是币安生态相关资产，风险监测重点包括交易所公告、平台合规事件、生态链安全事件、资金流动和市场信心变化。",
  XRP: "XRP 是 Ripple 生态相关资产，风险监测重点包括监管进展、市场流动性、机构合作消息和大额转账变化。",
  DOGE: "Dogecoin 是高社区驱动属性的加密资产，风险监测重点包括社交媒体情绪、名人言论、短时波动和投机交易拥挤度。",
  ADA: "Cardano 是权益证明公链生态资产，风险监测重点包括生态开发进度、治理动态、链上活跃度和市场波动。",
  TRX: "Tron 是高稳定币转账活跃度的公链生态资产，风险监测重点包括稳定币流动、链上异常转账、DeFi 安全和平台合规事件。",
  USDT: "USDT 是美元稳定币，风险监测重点包括脱锚、赎回压力、储备透明度、链上大额流动和交易所交易对异常价差。",
  USDC: "USDC 是美元稳定币，风险监测重点包括脱锚、发行与赎回、储备和银行通道变化，以及跨链流动性异常。",
  AAVE: "Aave 是 DeFi 借贷协议治理代币，风险监测重点包括资金池利用率、坏账、预言机价格、清算压力和协议安全事件。",
  UNI: "Uniswap 是去中心化交易协议治理代币，风险监测重点包括流动性池异常、治理提案、交易量波动和生态安全事件。",
  CRV: "Curve 是稳定币和同类资产交易协议相关代币，风险监测重点包括池子流动性、坏账传导、创始人仓位和 DeFi 连锁清算。",
};

export default function CoinDetailPage({ returnTo = "", symbol }: { returnTo?: string; symbol: string }) {
  const normalizedSymbol = symbol.toUpperCase();
  const [item, setItem] = useState<CoinRankingItem | null>(() => readCachedCoinDetail(normalizedSymbol));
  const [loading, setLoading] = useState(() => !readCachedCoinDetail(normalizedSymbol));
  const [error, setError] = useState("");
  const backHref = ensureRankingState(safeInternalPath(returnTo) || "/coins", "coin");

  useEffect(() => {
    let ignore = false;

    async function loadCoinDetail() {
      if (!readCachedCoinDetail(normalizedSymbol)) setLoading(true);
      setError("");
      try {
        const data = await fetchCoinDetail(normalizedSymbol);
        if (!ignore) setItem(data);
      } catch (detailError) {
        console.error(detailError);
        if (!ignore) setError("币种详情暂时无法加载，请稍后重试。");
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    loadCoinDetail();
    return () => {
      ignore = true;
    };
  }, [normalizedSymbol]);

  const description = useMemo(() => {
    if (!item) return "";
    return coinDescriptions[item.symbol] || `${item.name || item.symbol} 是当前风险榜中识别到的关联币种。系统基于相关新闻数量、最高风险分、平均风险分和主要风险类型进行聚合评分，建议重点核验相关新闻证据与官方公告。`;
  }, [item]);

  return (
    <main className="risk-shell min-h-screen bg-[#f4f7fb] text-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <Link
            href={backHref}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 shadow-sm transition-colors duration-200 hover:bg-blue-50"
          >
            <ChevronLeftIcon />
            返回币种榜
          </Link>
        </div>

        {loading && (
          <section className="risk-card rounded-lg p-8">
            <LoadingDots label="正在加载币种详情" />
          </section>
        )}

        {error && !loading && (
          <section className="rounded-lg border border-rose-100 bg-rose-50 p-5 text-sm font-semibold text-rose-700">
            {error}
          </section>
        )}

        {item && !loading && (
          <article className="space-y-5">
            <section className="risk-card rounded-lg p-5 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">CryptoRisk Coin Detail</p>
                  <div className="mt-4 flex items-center gap-4">
                    <CoinMark symbol={item.symbol} />
                    <div>
                      <h1 className="text-3xl font-bold leading-tight text-slate-950">{item.symbol}</h1>
                      <p className="mt-1 text-sm font-semibold text-slate-500">{item.name || item.symbol}</p>
                    </div>
                  </div>
                  <p className="mt-5 max-w-4xl text-sm leading-7 text-slate-700">{description}</p>
                </div>
                <div className="rounded-lg border border-rose-100 bg-rose-50 px-5 py-4 text-center">
                  <p className="text-xs font-bold text-rose-700">综合风险分</p>
                  <p className="mt-1 text-4xl font-bold text-rose-600">{clampScore(item.final_score)}</p>
                </div>
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-4">
              <InfoCard label="风险等级" value={item.risk_level || "未标记"} />
              <InfoCard label="主要风险类别" value={item.main_risk_type || "综合风险"} />
              <InfoCard label="相关新闻数" value={`${item.news_count || 0}`} />
              <InfoCard label="当前排名" value={`#${item.rank || "--"}`} />
            </section>

            <DetailSection title="风险摘要" icon={<ShieldIcon />}>
              <p>{item.summary || "暂无摘要。"}</p>
            </DetailSection>

            <DetailSection title="相关风险新闻" icon={<FileIcon />}>
              {item.related_news?.length ? (
                <div className="risk-scroll flex gap-4 overflow-x-auto pb-2">
                  {item.related_news.map((news) => (
                    <Link
                      key={news.news_id}
                      href={`/news/${encodeURIComponent(news.news_id)}?fromCoin=${encodeURIComponent(item.symbol)}&returnTo=${encodeURIComponent(`/coins/${encodeURIComponent(item.symbol)}?returnTo=${encodeURIComponent(backHref)}`)}`}
                      className="min-w-[280px] max-w-[340px] rounded-lg border border-blue-100 bg-white p-4 shadow-sm transition-colors duration-200 hover:border-blue-300 hover:bg-blue-50"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <RiskBadge level={news.risk_level} />
                        <span className="text-xl font-bold text-rose-600">{clampScore(news.risk_score)}</span>
                      </div>
                      <p className="mt-3 line-clamp-3 text-sm font-bold leading-6 text-blue-700">{news.title}</p>
                      <p className="mt-3 text-xs leading-5 text-slate-500">{news.risk_type || "综合风险"}</p>
                      <p className="mt-2 text-xs font-semibold text-slate-500">{news.published_at || "--"}</p>
                    </Link>
                  ))}
                </div>
              ) : (
                <p>暂无关联新闻。</p>
              )}
            </DetailSection>
          </article>
        )}
      </div>
    </main>
  );
}

function DetailSection({ children, icon, title }: { children: ReactNode; icon: ReactNode; title: string }) {
  return (
    <section className="risk-panel rounded-lg p-5">
      <div className="mb-4 flex items-center gap-2 text-blue-600">
        {icon}
        <h2 className="text-base font-bold text-slate-950">{title}</h2>
      </div>
      <div className="text-sm leading-7 text-slate-700">{children}</div>
    </section>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="risk-card rounded-lg p-5">
      <p className="text-xs font-bold text-blue-600">{label}</p>
      <p className="mt-2 text-base font-bold leading-7 text-slate-950">{value}</p>
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  const style = level.includes("高") || level.includes("红")
    ? "border border-rose-200 bg-rose-50 text-rose-700"
    : level.includes("中")
      ? "border border-orange-200 bg-orange-50 text-orange-700"
      : "border border-emerald-200 bg-emerald-50 text-emerald-700";
  return <span className={`inline-flex rounded-lg px-3 py-1 text-xs font-bold ${style}`}>{level || "低风险"}</span>;
}

function CoinMark({ symbol }: { symbol: string }) {
  const colors = ["bg-slate-950", "bg-blue-600", "bg-orange-500", "bg-emerald-500", "bg-violet-600"];
  const color = colors[symbol.charCodeAt(0) % colors.length];
  return (
    <span className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full ${color} text-lg font-bold text-white`}>
      {symbol.slice(0, 1)}
    </span>
  );
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, Math.round(value || 0)));
}

function safeInternalPath(value: string) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return "";
  return value;
}

function ensureRankingState(path: string, scope: "news" | "coin") {
  if (typeof window === "undefined") return path;
  const [pathname, search = ""] = path.split("?");
  const searchParams = new URLSearchParams(search);
  const storedFilter = window.sessionStorage.getItem(`cryptorisk.ranking:${scope}:filter`);
  const storedSort = window.sessionStorage.getItem(`cryptorisk.ranking:${scope}:sort`);
  if (!searchParams.get("filter") && storedFilter) searchParams.set("filter", storedFilter);
  if (!searchParams.get("sort") && storedSort) searchParams.set("sort", storedSort);
  const nextSearch = searchParams.toString();
  return `${pathname}${nextSearch ? `?${nextSearch}` : ""}`;
}

function IconSvg({ children }: { children: ReactNode }) {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

function ChevronLeftIcon() { return <IconSvg><path d="m15 18-6-6 6-6" /></IconSvg>; }
function FileIcon() { return <IconSvg><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /><path d="M9 13h6" /><path d="M9 17h6" /></IconSvg>; }
function ShieldIcon() { return <IconSvg><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" /><path d="m9 12 2 2 4-5" /></IconSvg>; }
