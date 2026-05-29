"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { LoadingDots } from "@/components/ui/loading-states";
import { fetchNewsDetail, NewsRankingItem, readCachedNewsDetail } from "@/lib/api";

export default function NewsDetailPage({
  fromCoin = "",
  newsId,
  returnTo = "",
}: {
  fromCoin?: string;
  newsId: string;
  returnTo?: string;
}) {
  const safeReturnTo = safeInternalPath(returnTo);
  const detailRange = readRankingRangeFromPath(safeReturnTo, "news");
  const [item, setItem] = useState<NewsRankingItem | null>(() => readCachedNewsDetail(newsId, detailRange));
  const [loading, setLoading] = useState(() => !readCachedNewsDetail(newsId, detailRange));
  const [error, setError] = useState("");
  const coinSymbol = fromCoin.toUpperCase();
  const coinPath = coinSymbol ? `/coins/${encodeURIComponent(coinSymbol)}` : "";
  const coinReturnHref = coinSymbol
    ? (safeReturnTo.startsWith(coinPath) ? safeReturnTo : coinPath)
    : "";
  const newsBackHref = safeReturnTo.startsWith("/news") ? ensureRankingState(safeReturnTo, "news") : ensureRankingState("/news", "news");

  useEffect(() => {
    let ignore = false;

    async function loadNewsDetail() {
      if (!readCachedNewsDetail(newsId, detailRange)) setLoading(true);
      setError("");
      try {
        const data = await fetchNewsDetail(newsId, detailRange);
        if (!ignore) setItem(data);
      } catch (detailError) {
        console.error(detailError);
        if (!ignore) setError("新闻详情暂时无法加载，请稍后重试。");
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    loadNewsDetail();
    return () => {
      ignore = true;
    };
  }, [detailRange, newsId]);

  const sourceHref = useMemo(() => {
    if (!item) return "";
    return item.source_url || `https://www.google.com/search?q=${encodeURIComponent(item.title)}`;
  }, [item]);

  return (
    <main className="risk-shell min-h-screen bg-[#f4f7fb] text-slate-900">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <Link
              href={newsBackHref}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-slate-700 shadow-sm transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
            >
              <ChevronLeftIcon />
              返回新闻榜
            </Link>
            {coinReturnHref && (
              <Link
                href={coinReturnHref}
                className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-blue-100 bg-white px-4 text-sm font-bold text-blue-700 shadow-sm transition-colors duration-200 hover:bg-blue-50 sm:w-auto"
              >
                <CoinIcon />
                返回当前币种
              </Link>
            )}
          </div>
          {item && (
            <a
              href={sourceHref}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700 sm:w-auto"
            >
              <ExternalLinkIcon />
              {item.source_url ? "打开原文网页" : "检索原文网页"}
            </a>
          )}
        </div>

        {loading && (
          <section className="risk-card rounded-lg p-8">
            <LoadingDots label="正在加载新闻详情" />
          </section>
        )}

        {error && !loading && (
          <section className="rounded-lg border border-rose-100 bg-rose-50 p-5 text-sm font-semibold text-rose-700">
            {error}
          </section>
        )}

        {item && !loading && (
          <article
            className="space-y-5"
            data-ai-context={JSON.stringify({
              type: "news_detail",
              coin: item.coins,
              title: item.title,
              riskLevel: item.risk_level,
              riskScore: item.risk_score,
              riskType: item.risk_type,
              newsId: item.news_id,
              time: item.published_at || item.date,
            })}
          >
            <section className="risk-card rounded-lg p-5 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">CryptoRisk News Detail</p>
                  <h1 className="mt-3 break-words text-2xl font-bold leading-tight text-slate-950 sm:text-3xl">{item.title}</h1>
                  <p className="mt-3 text-sm text-slate-500">
                    发布时间：{item.published_at || item.date || "--"} · 新闻 ID：{item.news_id}
                  </p>
                </div>
                <div className="w-full rounded-lg border border-rose-100 bg-rose-50 px-5 py-4 text-center sm:w-auto">
                  <p className="text-xs font-bold text-rose-700">风险分</p>
                  <p className="mt-1 text-4xl font-bold text-rose-600">{clampScore(item.risk_score)}</p>
                </div>
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-3">
              <InfoCard label="风险等级" value={item.risk_level || "未标记"} />
              <InfoCard label="风险类别" value={item.risk_type || "综合风险"} />
              <InfoCard label="关联币种" value={formatCoins(item)} />
            </section>

            <DetailSection title="新闻摘要" icon={<FileIcon />}>
              <p>{item.summary || "暂无摘要。"}</p>
            </DetailSection>

            <DetailSection title="证据与判定依据" icon={<ShieldIcon />}>
              <p>{item.evidence || "暂无结构化证据。"}</p>
            </DetailSection>

            <DetailSection title="新闻正文" icon={<TextIcon />}>
              <p className="whitespace-pre-wrap">{item.content || "暂无正文。"}</p>
            </DetailSection>

            <DetailSection title="涉及币种" icon={<CoinIcon />}>
              {item.coin_details?.length ? (
                <div className="flex flex-wrap gap-2">
                  {item.coin_details.map((coin) => (
                    <span key={`${coin.symbol}-${coin.name}`} className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm font-bold text-blue-700">
                      {coin.symbol}{coin.name ? ` · ${coin.name}` : ""}
                    </span>
                  ))}
                </div>
              ) : (
                <p>{item.coins?.length ? item.coins.join("、") : "暂无明确关联币种。"}</p>
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

function formatCoins(item: NewsRankingItem) {
  const details = item.coin_details?.map((coin) => coin.symbol).filter(Boolean) || [];
  const coins = item.coins?.filter(Boolean) || [];
  const unique = Array.from(new Set([...details, ...coins]));
  return unique.length ? unique.join("、") : "--";
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
  const storedRange = window.sessionStorage.getItem(`cryptorisk.ranking:${scope}:range`);
  if (!searchParams.get("filter") && storedFilter) searchParams.set("filter", storedFilter);
  if (!searchParams.get("sort") && storedSort) searchParams.set("sort", storedSort);
  if (!searchParams.get("range") && storedRange && isRankingRange(storedRange)) searchParams.set("range", storedRange);
  const nextSearch = searchParams.toString();
  return `${pathname}${nextSearch ? `?${nextSearch}` : ""}`;
}

function readRankingRangeFromPath(path: string, scope: "news" | "coin") {
  if (typeof window === "undefined") return "24h";
  const [, search = ""] = path.split("?");
  const value = new URLSearchParams(search).get("range");
  if (value && isRankingRange(value)) return value;
  const storedRange = window.sessionStorage.getItem(`cryptorisk.ranking:${scope}:range`);
  return storedRange && isRankingRange(storedRange) ? storedRange : "24h";
}

function isRankingRange(value: string) {
  return value === "24h" || value === "7d";
}

function IconSvg({ children }: { children: ReactNode }) {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

function ChevronLeftIcon() { return <IconSvg><path d="m15 18-6-6 6-6" /></IconSvg>; }
function ExternalLinkIcon() { return <IconSvg><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></IconSvg>; }
function FileIcon() { return <IconSvg><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /><path d="M9 13h6" /><path d="M9 17h6" /></IconSvg>; }
function ShieldIcon() { return <IconSvg><path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" /><path d="m9 12 2 2 4-5" /></IconSvg>; }
function TextIcon() { return <IconSvg><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h10" /></IconSvg>; }
function CoinIcon() { return <IconSvg><circle cx="12" cy="12" r="8" /><path d="M9 10h6" /><path d="M9 14h6" /></IconSvg>; }
