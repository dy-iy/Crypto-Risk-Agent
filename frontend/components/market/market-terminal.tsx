"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, BarChart3, Camera, ChevronLeft, ChevronRight, Download, Expand, RefreshCw, Search, Star, TrendingUp, ZoomIn, ZoomOut } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { changeFollow, refreshFollows, useFollows } from "@/lib/follows";
import { normalizeMarketSymbol } from "@/lib/market-symbols";
import { GuestFollowImport } from "@/components/follows/follow-manager";
import { getAccountScope, localStore } from "@/lib/browser-storage";
import { requestJson, type PortfolioNewsItem } from "@/lib/api";
import { candlePath, compact, downloadText, marketIntervals, marketRequest, maxCandles, mergeCandles, price, type Candle, type Depth, type Feed, type MarketInterval, type MarketSymbol, type Ticker, type Trade } from "@/lib/market";
import MarketChart, { type ChartHandle } from "./market-chart";
import { useVisiblePoll } from "./use-visible-poll";
import "./market.css";

type ChartSettings = { mode: "candles" | "line"; showMA: boolean; showEMA: boolean; showRSI: boolean; logarithmic: boolean };
const defaultChart: ChartSettings = { mode: "candles", showMA: true, showEMA: false, showRSI: true, logarithmic: false };
type Preferences = { symbol: string; interval: MarketInterval; favorites: string[]; chart: ChartSettings };
const preferencesKey = () => `cryptorisk.market.preferences:${getAccountScope()}`;
function readPreferences(): Preferences {
  try {
    const value = JSON.parse(localStore.getItem(preferencesKey()) || "null");
    return { chart: { mode: value?.chart?.mode === "line" ? "line" : "candles", showMA: value?.chart?.showMA !== false, showEMA: value?.chart?.showEMA === true, showRSI: value?.chart?.showRSI !== false, logarithmic: value?.chart?.logarithmic === true }, symbol: typeof value?.symbol === "string" ? value.symbol : "BTCUSDT", interval: marketIntervals.includes(value?.interval) ? value.interval : "15m", favorites: Array.isArray(value?.favorites) ? value.favorites.filter((s: unknown): s is string => typeof s === "string").slice(0, 50) : ["BTCUSDT", "ETHUSDT", "SOLUSDT"] };
  } catch { return { chart: defaultChart, symbol: "BTCUSDT", interval: "15m", favorites: ["BTCUSDT", "ETHUSDT", "SOLUSDT"] }; }
}
function errorMessage(error: unknown) { return error instanceof Error && error.name === "TimeoutError" ? "行情请求超时，请重试" : "暂时无法获取行情，请检查网络后重试"; }
function stamp(value: number | undefined) { return value ? new Date(value).toLocaleTimeString("zh-CN", { hour12: false }) : "—"; }

export default function MarketTerminal() {
  const follows = useFollows();
  const router = useRouter();
  const routeSymbol = normalizeMarketSymbol(useSearchParams().get("symbol"));
  const favorites = useMemo(() => follows.items.map(item => item.symbol), [follows.items]);
  const [preferences, setPreferences] = useState(readPreferences);
  const selectedSymbol = routeSymbol ?? normalizeMarketSymbol(preferences.symbol) ?? "BTCUSDT";
  const [symbols, setSymbols] = useState<MarketSymbol[]>([]);
  const [tickers, setTickers] = useState<Feed<Ticker[]> | null>(null);
  const [error, setError] = useState("");
  const [symbolError, setSymbolError] = useState("");
  const [query, setQuery] = useState("");
  const [watchOpen, setWatchOpen] = useState(false);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [sort, setSort] = useState<"default" | "gain" | "loss">("default");
  const [retry, setRetry] = useState(0);
  useEffect(() => { localStore.setItem(preferencesKey(), JSON.stringify({ ...preferences, symbol: selectedSymbol })); }, [preferences, selectedSymbol]);
  useEffect(() => {
    const controller = new AbortController();
    marketRequest<MarketSymbol[]>("symbols", controller.signal).then(data => {
      if (controller.signal.aborted) return;
      setSymbols(data); setSymbolError("");
      setPreferences(previous => data.some(s => s.symbol === previous.symbol) ? previous : { ...previous, symbol: data[0]?.symbol || "BTCUSDT" });
    }).catch(reason => { if (!controller.signal.aborted) setSymbolError(errorMessage(reason)); });
    return () => controller.abort();
  }, [retry]);
  const pollTickers = useCallback(async (signal: AbortSignal) => {
    try { const result = await marketRequest<Feed<Ticker[]>>("tickers", signal); if (!signal.aborted) { setTickers(result); setError(""); } }
    catch (reason) { if (!signal.aborted) setError(errorMessage(reason)); }
  }, []);
  useVisiblePoll(pollTickers, 10_000, retry);
  const quotes = useMemo(() => new Map(tickers?.data.map(row => [row.symbol, row]) || []), [tickers]);
  const visibleSymbols = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const result = symbols.filter(s => (!favoritesOnly || favorites.includes(s.symbol)) && `${s.symbol} ${s.name}`.toLowerCase().includes(needle));
    return sort === "default" ? result : result.sort((a, b) => ((quotes.get(b.symbol)?.change_pct || 0) - (quotes.get(a.symbol)?.change_pct || 0)) * (sort === "gain" ? 1 : -1));
  }, [symbols, query, favoritesOnly, favorites, quotes, sort]);
  const selected = symbols.find(s => s.symbol === selectedSymbol);
  const selectSymbol = (symbol: string) => { setPreferences(previous => ({ ...previous, symbol })); router.replace(`/market?symbol=${symbol}`, { scroll: false }); };
  function moveSymbol(delta: number) {
    if (!visibleSymbols.length) return;
    const index = visibleSymbols.findIndex(s => s.symbol === selectedSymbol);
    selectSymbol(visibleSymbols[(index + delta + visibleSymbols.length) % visibleSymbols.length].symbol);
  }
  const stale = Boolean(error || tickers?.stale);
  return <section className="market-terminal" aria-label="行情看盘工作台">
    <div className="market-heading"><div><p className="market-eyebrow">MARKET TERMINAL · SPOT</p><h1>行情看盘</h1></div><div className="market-source"><span className={`market-dot ${stale ? "is-stale" : ""}`} />{tickers ? stale ? "行情缓存 / 连接异常" : "Binance 现货 · 行情快照" : "连接行情源…"}<small>报价每 10 秒更新</small></div></div>
    {(error || symbolError) && <div className="market-notice" role="alert">{error || symbolError}。{tickers ? `当前显示 ${stamp(tickers.as_of)} 的最近有效报价。` : "暂无可用报价。"}<button onClick={() => { setRetry(v => v + 1);  }}>重试</button></div>}
    {follows.error && <div className="market-notice" role="alert">{follows.error}<button onClick={() => void refreshFollows(true)}>重试关注同步</button></div>}
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500"><span>{follows.scope === "guest" ? "游客自选 · 仅保存在当前浏览器" : "账号关注 · 与关注日报同步"}</span><Link href="/my?tab=assets" className="text-blue-700 underline">管理完整关注列表</Link><GuestFollowImport key={follows.scope}/></div>
    <div className="market-grid">
      <aside className={`market-watchlist market-panel ${watchOpen ? "is-open" : ""}`} aria-label="交易对列表">
        <div className="market-panel-title"><h2>市场 / 自选</h2><span>{symbols.length} 对</span><button className="market-list-toggle" aria-expanded={watchOpen} onClick={() => setWatchOpen(v => !v)}>{watchOpen ? "收起" : "选择交易对"}</button></div>
        <label className="market-search"><Search size={15}/><input aria-label="搜索交易对" placeholder="搜索币种" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <div className="market-watch-tools"><button aria-pressed={!favoritesOnly} onClick={() => setFavoritesOnly(false)}>全部</button><button aria-pressed={favoritesOnly} onClick={() => setFavoritesOnly(true)}>自选</button><select aria-label="交易对排序" value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="default">默认</option><option value="gain">涨幅</option><option value="loss">跌幅</option></select></div>
        <div className="market-symbol-list">{visibleSymbols.map(item => {
          const quote = quotes.get(item.symbol), favorite = favorites.includes(item.symbol);
          return <div className={`market-symbol-row ${item.symbol === selectedSymbol ? "is-selected" : ""}`} key={item.symbol}>
            <button className="market-star" aria-label={`${favorite ? "取消自选" : "添加自选"} ${item.base}`} aria-pressed={favorite} disabled={follows.loading || !follows.loaded || follows.pending.includes(item.symbol)} onClick={() => void changeFollow(item.symbol, favorite ? "remove" : "add")}><Star size={14} fill={favorite ? "currentColor" : "none"}/></button>
            <button className="market-symbol-choice" aria-current={item.symbol === selectedSymbol ? "true" : undefined} onClick={() => selectSymbol(item.symbol)}><span><strong>{item.base}</strong><small>/ USDT</small></span><span><b>{price(quote?.price)}</b><small className={quote && quote.change_pct >= 0 ? "market-up" : "market-down"}>{quote ? `${quote.change_pct >= 0 ? "+" : ""}${quote.change_pct.toFixed(2)}%` : "—"}</small></span></button>
          </div>;
        })}{!visibleSymbols.length && <div className="market-empty">{symbols.length ? favoritesOnly ? "暂无匹配自选，点击星标添加" : "没有匹配的交易对" : "交易对加载中；失败时请重试"}</div>}</div>
        <div className="market-watch-footer">USDT 计价 · 24h 涨跌幅<br/>报价时间 {stamp(tickers?.as_of)}</div>
      </aside>
      <div className="market-main">
        <div className="market-quote market-panel"><div className="market-pair"><span className="market-coin-mark">{selected?.base.slice(0, 1) || selectedSymbol.slice(0, 1)}</span><div><h2>{selected?.base || selectedSymbol.replace("USDT", "")}<small> / USDT</small></h2><span>{selected?.name || "现货市场"}</span></div><button className="market-icon" aria-label="上一个交易对" onClick={() => moveSymbol(-1)}><ChevronLeft size={16}/></button><button className="market-icon" aria-label="下一个交易对" onClick={() => moveSymbol(1)}><ChevronRight size={16}/></button></div>
          <QuoteMetrics quote={quotes.get(selectedSymbol)} stale={stale}/>
        </div>
        <MarketWorkspace key={`${selectedSymbol}:${preferences.interval}`} settings={preferences.chart} onSettings={update => setPreferences(previous => ({ ...previous, chart: update(previous.chart) }))} symbol={selectedSymbol} interval={preferences.interval} onInterval={interval => setPreferences(previous => ({ ...previous, interval }))}/>
      </div>
    </div>
    <footer className="market-attribution">行情为公开现货快照，非逐笔实时推送；盘口与成交明细每 5 秒更新，隐藏标签页暂停请求。 <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">TradingView Lightweight Charts™</a> · Copyright (с) 2025 TradingView, Inc.</footer>
  </section>;
}

function QuoteMetrics({ quote, stale }: { quote?: Ticker; stale: boolean }) {
  return <div className="market-metrics"><div className="market-last"><strong className={quote && quote.change_pct < 0 ? "market-down" : "market-up"}>{price(quote?.price)}</strong><span className={quote && quote.change_pct < 0 ? "market-down" : "market-up"}>{quote && <>{quote.change_pct >= 0 ? <ArrowUp size={12}/> : <ArrowDown size={12}/>} {Math.abs(quote.change_pct).toFixed(2)}%</>}{stale && " · 缓存"}</span></div><Metric label="24h 最高" value={price(quote?.high)}/><Metric label="24h 最低" value={price(quote?.low)}/><Metric label="24h 成交额 (USDT)" value={compact(quote?.quote_volume)}/></div>;
}
function Metric({ label, value }: { label: string; value: string }) { return <div className="market-metric"><span>{label}</span><b>{value}</b></div>; }

function MarketWorkspace({ symbol, interval, onInterval, settings, onSettings }: { symbol: string; interval: MarketInterval; onInterval: (value: MarketInterval) => void; settings: ChartSettings; onSettings: (update: (previous: ChartSettings) => ChartSettings) => void }) {
  const { mode, showMA, showEMA, showRSI, logarithmic } = settings;
  const [candles, setCandles] = useState<Candle[]>([]);
  const [candleFeed, setCandleFeed] = useState<Feed<Candle[]> | null>(null);
  const [depth, setDepth] = useState<Feed<Depth> | null>(null);
  const [trades, setTrades] = useState<Feed<Trade[]> | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [noHistory, setNoHistory] = useState(false);
  const [sideTab, setSideTab] = useState<"depth" | "trades">("depth");
  const [expanded, setExpanded] = useState(false);
  const chart = useRef<ChartHandle>(null), shell = useRef<HTMLDivElement>(null);
  const loadedAt = useRef(0), historyController = useRef<AbortController | null>(null), historyPending = useRef(false);
  const [retry, setRetry] = useState(0);
  const poll = useCallback(async (signal: AbortSignal) => {
    const seconds = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400 }[interval];
    const full = !loadedAt.current || Date.now() - loadedAt.current > seconds * 2000;
    const requests = await Promise.allSettled([
      marketRequest<Feed<Candle[]>>(candlePath(symbol, interval, full ? 500 : 3), signal),
      marketRequest<Feed<Depth>>(`depth?symbol=${encodeURIComponent(symbol)}`, signal),
      marketRequest<Feed<Trade[]>>(`trades?symbol=${encodeURIComponent(symbol)}`, signal),
    ]);
    if (signal.aborted) return;
    const [bars, book, prints] = requests;
    const nextErrors: Record<string, string> = {};
    if (bars.status === "fulfilled") { setCandleFeed(bars.value); setCandles(previous => mergeCandles(previous, bars.value.data)); if (bars.value.data.length && !bars.value.stale) loadedAt.current = Date.now(); }
    else nextErrors.candles = errorMessage(bars.reason);
    if (book.status === "fulfilled") setDepth(book.value); else nextErrors.depth = errorMessage(book.reason);
    if (prints.status === "fulfilled") setTrades(prints.value); else nextErrors.trades = errorMessage(prints.reason);
    setErrors(nextErrors); setLoading(false);
  }, [symbol, interval]);
  useVisiblePoll(poll, 5000, retry);
  useEffect(() => () => { historyController.current?.abort(); }, []);
  useEffect(() => {
    if (!expanded) return;
    const previousFocus = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    shell.current?.querySelector<HTMLButtonElement>('[aria-label="退出图表全屏"]')?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setExpanded(false); }
      if (event.key !== "Tab") return;
      const buttons = [...(shell.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])];
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    window.addEventListener("keydown", keyboard);
    return () => {
      window.removeEventListener("keydown", keyboard);
      document.body.style.overflow = previousOverflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [expanded]);
  async function history() {
    if (historyPending.current || !candles.length || candles.length >= maxCandles) return;
    historyPending.current = true; setHistoryLoading(true);
    const controller = new AbortController(); historyController.current = controller;
    try {
      const result = await marketRequest<Feed<Candle[]>>(candlePath(symbol, interval, Math.max(2, Math.min(500, maxCandles - candles.length)), candles[0].time * 1000 - 1), controller.signal);
      if (controller.signal.aborted) return;
      setCandles(previous => mergeCandles(result.data, previous)); setNoHistory(result.data.length === 0);
      setErrors(previous => { const next = { ...previous }; delete next.history; return next; });
    } catch (error) { if (!controller.signal.aborted) setErrors(previous => ({ ...previous, history: errorMessage(error) })); }
    finally { historyPending.current = false; if (!controller.signal.aborted) setHistoryLoading(false); }
  }
  function exportCsv() {
    downloadText("time_utc,open,high,low,close,volume\n" + candles.map(c => [new Date(c.time * 1000).toISOString(), c.open, c.high, c.low, c.close, c.volume].join(",")).join("\n"), `${symbol}-${interval}.csv`);
  }
  return <div className="market-workspace">
    <div ref={shell} role={expanded ? "dialog" : undefined} aria-modal={expanded || undefined} aria-label={expanded ? "全屏行情图表" : undefined} className={`market-chart-panel market-panel ${expanded ? "is-expanded" : ""}`}>
      <div className="market-toolbar"><div className="market-intervals" aria-label="K 线周期">{marketIntervals.map(value => <button key={value} aria-pressed={interval === value} onClick={() => onInterval(value)}>{value}</button>)}</div><div className="market-chart-types"><button aria-label="蜡烛图" aria-pressed={mode === "candles"} onClick={() => onSettings(previous => ({ ...previous, mode: "candles" }))}><BarChart3 size={16}/></button><button aria-label="折线图" aria-pressed={mode === "line"} onClick={() => onSettings(previous => ({ ...previous, mode: "line" }))}><TrendingUp size={16}/></button><button aria-label={expanded ? "退出图表全屏" : "图表全屏"} aria-pressed={expanded} onClick={() => setExpanded(v => !v)}><Expand size={16}/></button></div></div>
      <div className="market-chart-options"><button aria-pressed={showMA} onClick={() => onSettings(previous => ({ ...previous, showMA: !previous.showMA }))}>MA 10/30</button><button aria-pressed={showEMA} onClick={() => onSettings(previous => ({ ...previous, showEMA: !previous.showEMA }))}>EMA 20</button><button aria-pressed={showRSI} onClick={() => onSettings(previous => ({ ...previous, showRSI: !previous.showRSI }))}>RSI 14</button><button aria-pressed={logarithmic} onClick={() => onSettings(previous => ({ ...previous, logarithmic: !previous.logarithmic }))}>对数</button><span className="market-feed-label">{loading ? "加载中…" : errors.candles || candleFeed?.stale ? "缓存 / 连接异常" : "5 秒快照"} · {stamp(candleFeed?.as_of)}</span></div>
      {(errors.candles || errors.history) && <div className="market-notice" role="alert">{errors.history || errors.candles}{candles.length > 0 && "，已保留最近有效 K 线。"}<button onClick={() => setRetry(v => v + 1)}>重试行情</button></div>}
      {loading && <div className="market-chart-loading" role="status">正在读取 {symbol} 的 {interval} 行情…</div>}
      {!loading && !candles.length && <div className="market-chart-loading">暂无可用 K 线，请切换周期或重试行情。</div>}
      <MarketChart ref={chart} candles={candles} mode={mode} showMA={showMA} showEMA={showEMA} showRSI={showRSI} logarithmic={logarithmic}/>
      <div className="market-chart-actions"><button onClick={() => chart.current?.zoom(0.8)} aria-label="放大图表"><ZoomIn size={15}/></button><button onClick={() => chart.current?.zoom(1.25)} aria-label="缩小图表"><ZoomOut size={15}/></button><button onClick={() => chart.current?.fit()}>适应窗口</button><button onClick={() => chart.current?.latest()}>回到最新</button><button disabled={historyLoading || noHistory || !candles.length || candles.length >= maxCandles} onClick={() => void history()}>{historyLoading ? "加载中…" : noHistory ? "无更早数据" : "更早 K 线"}</button><span className="market-action-spacer"/><button disabled={!candles.length} onClick={exportCsv} aria-label="导出 K 线 CSV"><Download size={15}/><span>CSV</span></button><button disabled={!candles.length} onClick={() => chart.current?.screenshot()} aria-label="保存图表图片"><Camera size={15}/></button><button onClick={() => setRetry(v => v + 1)} aria-label="刷新行情"><RefreshCw size={15}/></button></div>
    </div>
    <aside className="market-detail market-panel"><div className="market-detail-tabs"><button aria-pressed={sideTab === "depth"} onClick={() => setSideTab("depth")}>盘口深度</button><button aria-pressed={sideTab === "trades"} onClick={() => setSideTab("trades")}>最近成交</button></div>
      {sideTab === "depth" ? <OrderBook feed={depth} error={errors.depth}/> : <TradeTape feed={trades} error={errors.trades}/>}
      <div className="market-detail-note">{sideTab === "depth" ? "买卖盘为挂单快照，不代表成交。" : "颜色表示主动买入 / 主动卖出方向。"}</div>
    </aside>
    <MarketNews symbol={symbol}/>
  </div>;
}

function FeedNote({ feed, error }: { feed: { as_of: number; stale: boolean } | null; error?: string }) {
  return <p className={`market-detail-time ${error || feed?.stale ? "market-down" : ""}`}>{error ? `${error}；${feed ? "当前为旧快照" : "暂无数据"}` : feed ? `${feed.stale ? "缓存快照 · " : "更新于 "}${stamp(feed.as_of)}` : "正在加载…"}</p>;
}
function OrderBook({ feed, error }: { feed: Feed<Depth> | null; error?: string }) {
  const bids = feed?.data.bids.slice(0, 10) || [], asks = feed?.data.asks.slice(0, 10) || [];
  const max = Math.max(1, ...[...bids, ...asks].map(row => row.quantity));
  const spread = bids.length && asks.length ? asks[0].price - bids[0].price : undefined;
  const row = (item: { price: number; quantity: number }, side: "bid" | "ask") => <div className={`market-book-row ${side}`} key={item.price} style={{ backgroundSize: `${item.quantity / max * 100}% 100%` }}><b>{price(item.price)}</b><span>{compact(item.quantity)}</span><span>{compact(item.price * item.quantity)}</span></div>;
  return <><FeedNote feed={feed} error={error}/><div className="market-book-head"><span>价格 (USDT)</span><span>数量</span><span>金额</span></div><div className="market-book-side asks" aria-label="卖盘">{[...asks].reverse().map(item => row(item, "ask"))}</div><div className="market-spread">买卖价差 <b>{price(spread)}</b><small>{spread !== undefined && bids[0] ? `${(spread / bids[0].price * 100).toFixed(4)}%` : ""}</small></div><div className="market-book-side bids" aria-label="买盘">{bids.map(item => row(item, "bid"))}</div>{feed && !bids.length && !asks.length && <div className="market-empty">暂无盘口数据</div>}</>;
}
function TradeTape({ feed, error }: { feed: Feed<Trade[]> | null; error?: string }) {
  return <><FeedNote feed={feed} error={error}/><div className="market-book-head"><span>价格 (USDT)</span><span>数量</span><span>时间</span></div><div className="market-tape">{feed?.data.map(row => <div className="market-book-row" key={row.id}><b className={row.side === "buy" ? "market-up" : "market-down"}>{price(row.price)}</b><span>{compact(row.quantity)}</span><time>{stamp(row.time)}</time></div>)}</div>{feed && !feed.data.length && <div className="market-empty">暂无成交数据</div>}</>;
}
function MarketNews({ symbol }: { symbol: string }) {
  const [news, setNews] = useState<PortfolioNewsItem[]>([]), [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    requestJson<PortfolioNewsItem[]>(`/api/portfolio/news/${encodeURIComponent(symbol)}?limit=5`, { signal: controller.signal }).then(rows => { if (!controller.signal.aborted) setNews(rows); }).catch(() => { if (!controller.signal.aborted) setError("相关新闻暂时不可用"); });
    return () => controller.abort();
  }, [symbol]);
  return <section className="market-news market-panel"><div className="market-panel-title"><h2>相关新闻</h2><span>已收录的风险事件 · 非实时资讯流</span></div>{error || !news.length ? <p className="market-empty">{error || "暂无关联新闻"}</p> : <div className="market-news-grid">{news.map(item => <Link key={item.news_id} href={`/news/${encodeURIComponent(item.news_id)}?fromCoin=${symbol.replace("USDT", "")}&returnTo=${encodeURIComponent("/market")}`}><span className="market-news-risk">风险 {Math.round(item.risk_score)}</span><h3>{item.title}</h3><time>{item.published_at}</time></Link>)}</div>}</section>;
}
