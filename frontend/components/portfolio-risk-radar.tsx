"use client";

import { Dispatch, FormEvent, MouseEvent as ReactMouseEvent, ReactNode, SetStateAction, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  CoinRankingItem,
  CoinRiskSnapshot,
  createPortfolioWatchlistItem,
  deletePortfolioWatchlistItem,
  fetchCoinRanking,
  fetchCurrentPortfolioRefreshJob,
  fetchPortfolioMarket,
  fetchPortfolioNews,
  fetchPortfolioRefreshJob,
  fetchPortfolioRisk,
  fetchPortfolioWatchlist,
  PortfolioMarketCandle,
  PortfolioNewsItem,
  PortfolioRefreshJob,
  PortfolioRiskLevel,
  PortfolioWatchlistItem,
  startPortfolioRefreshJob,
  updatePortfolioWatchlistItem,
} from "@/lib/api";

type AddFormState = {
  alertThreshold: string;
  amount: string;
  avgBuyPrice: string;
  isHolding: boolean;
  symbol: string;
};

type HoldingFormState = {
  alertThreshold: string;
  amount: string;
  avgBuyPrice: string;
  isHolding: boolean;
};

const portfolioZoomPresets = [
  { label: "1H", candles: 4 },
  { label: "4H", candles: 16 },
  { label: "1D", candles: 96 },
  { label: "3D", candles: 288 },
  { label: "全部", candles: 0 },
] as const;

type PortfolioZoomPreset = (typeof portfolioZoomPresets)[number];
type PortfolioChartRange = { start: number; end: number };
type PortfolioChartFollowMode =
  | { kind: "preset"; label: string; candles: number }
  | { kind: "manual" };
type PortfolioZoomDragMode = "start" | "end" | "window";
type PortfolioHoverPoint = {
  absoluteIndex: number;
  price: number;
  x: number;
  y: number;
};
type PortfolioTradeSide = "buy" | "sell";
type PortfolioTradeMarker = {
  candle_index: number;
  id: string;
  price: number;
  quantity: number;
  side: PortfolioTradeSide;
  symbol: string;
  time: string;
};
type PortfolioTradeDraft = {
  candle_index: number;
  price: number;
  quantity: string;
  side: PortfolioTradeSide;
  time: string;
};
type PortfolioRiskEvent = {
  ai_advice: string;
  ai_summary: string;
  candle_index: number;
  evidence: string;
  id: string;
  matched_reason: string;
  risk_level: string;
  risk_score: number;
  risk_type: string;
  source_url: string;
  summary: string;
  time: string;
  title: string;
};

type PortfolioCoinCandidate = {
  name: string;
  newsCount?: number;
  riskLevel?: string;
  score?: number;
  symbol: string;
};

type PortfolioRiskTone = {
  badge: string;
  bg: string;
  border: string;
  hover: string;
  marker: string;
  markerCluster: string;
  softText: string;
  text: string;
};

const defaultPortfolioZoomPreset = portfolioZoomPresets[portfolioZoomPresets.length - 1];
const defaultPortfolioChartFollowMode: PortfolioChartFollowMode = {
  candles: defaultPortfolioZoomPreset.candles,
  kind: "preset",
  label: defaultPortfolioZoomPreset.label,
};

const portfolioRiskTones: Record<"low" | "medium" | "high" | "critical", PortfolioRiskTone> = {
  low: {
    badge: "bg-emerald-600 text-white",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    hover: "hover:bg-emerald-100",
    marker: "#10b981",
    markerCluster: "#059669",
    softText: "text-emerald-700",
    text: "text-emerald-950",
  },
  medium: {
    badge: "bg-amber-600 text-white",
    bg: "bg-amber-50",
    border: "border-amber-200",
    hover: "hover:bg-amber-100",
    marker: "#d97706",
    markerCluster: "#b45309",
    softText: "text-amber-700",
    text: "text-amber-950",
  },
  high: {
    badge: "bg-red-600 text-white",
    bg: "bg-red-50",
    border: "border-red-200",
    hover: "hover:bg-red-100",
    marker: "#dc2626",
    markerCluster: "#991b1b",
    softText: "text-red-700",
    text: "text-red-950",
  },
  critical: {
    badge: "bg-red-900 text-white",
    bg: "bg-red-50",
    border: "border-red-300",
    hover: "hover:bg-red-100",
    marker: "#7f1d1d",
    markerCluster: "#450a0a",
    softText: "text-red-800",
    text: "text-red-950",
  },
};

const portfolioChartSpec = {
  height: 520,
  paddingX: 18,
  priceBottom: 420,
  priceTop: 68,
  volumeBottom: 506,
  volumeTop: 446,
  width: 640,
};

const portfolioMiniChartSpec = {
  bottom: 58,
  height: 80,
  paddingX: 6,
  top: 8,
  width: 640,
};
const portfolioCoinCandidateCacheKey = "cryptorisk.portfolio-coin-candidates:v1";
const portfolioRefreshJobStorageKey = "cryptorisk.portfolio-refresh-job-id";

const emptyAddForm: AddFormState = {
  alertThreshold: "70",
  amount: "",
  avgBuyPrice: "",
  isHolding: false,
  symbol: "",
};

function defaultHoldingForm(item: PortfolioWatchlistItem | null): HoldingFormState {
  return {
    alertThreshold: String(item?.alert_threshold ?? 70),
    amount: item?.amount ? String(item.amount) : "",
    avgBuyPrice: item?.avg_buy_price ? String(item.avg_buy_price) : "",
    isHolding: Boolean(item?.is_holding),
  };
}

export default function PortfolioRiskRadar() {
  const mountedRef = useRef(true);
  const [watchlist, setWatchlist] = useState<PortfolioWatchlistItem[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [candles, setCandles] = useState<PortfolioMarketCandle[]>([]);
  const [newsItems, setNewsItems] = useState<PortfolioNewsItem[]>([]);
  const [riskSnapshot, setRiskSnapshot] = useState<CoinRiskSnapshot | null>(null);
  const [coinCandidates, setCoinCandidates] = useState<CoinRankingItem[]>(() => readCachedPortfolioCoinCandidates());
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshJob, setRefreshJob] = useState<PortfolioRefreshJob | null>(null);
  const [savingHolding, setSavingHolding] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<AddFormState>(emptyAddForm);
  const [chartRange, setChartRange] = useState<PortfolioChartRange>({ start: 0, end: 0 });
  const [chartFollowMode, setChartFollowMode] = useState<PortfolioChartFollowMode>(defaultPortfolioChartFollowMode);
  const [selectedRiskEvent, setSelectedRiskEvent] = useState<PortfolioRiskEvent | null>(null);
  const [analysisEvent, setAnalysisEvent] = useState<PortfolioRiskEvent | null>(null);
  const [tradeMarkers, setTradeMarkers] = useState<PortfolioTradeMarker[]>([]);
  const [tradeDraft, setTradeDraft] = useState<PortfolioTradeDraft | null>(null);
  const selectedItem = useMemo(
    () => watchlist.find((item) => item.symbol === selectedSymbol) || watchlist[0] || null,
    [selectedSymbol, watchlist]
  );
  const [holdingForm, setHoldingForm] = useState<HoldingFormState>(() => defaultHoldingForm(selectedItem));
  const portfolioEvents = useMemo(
    () => buildPortfolioRiskEvents(newsItems, candles, riskSnapshot),
    [candles, newsItems, riskSnapshot]
  );
  const addSymbolCandidates = useMemo(
    () => buildPortfolioCoinCandidates(coinCandidates, watchlist),
    [coinCandidates, watchlist]
  );

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadInitialWatchlist() {
      try {
        const items = await fetchPortfolioWatchlist();
        if (ignore) return;
        const nextSymbol = items[0]?.symbol || "";
        setWatchlist(items);
        setLastUpdated(formatNow());
        setSelectedSymbol(nextSymbol);
        setHoldingForm(defaultHoldingForm(items.find((item) => item.symbol === nextSymbol) || null));
      } catch (fetchError) {
        console.error(fetchError);
        if (!ignore) setError("自选资产列表暂时无法加载，请稍后重试。");
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    void loadInitialWatchlist();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadCoinCandidates() {
      try {
        const ranking = await fetchCoinRanking(0, "7d");
        if (!ignore) {
          setCoinCandidates(ranking.items);
          writeCachedPortfolioCoinCandidates(ranking.items);
        }
      } catch (fetchError) {
        console.error(fetchError);
      }
    }

    void loadCoinCandidates();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;

    async function resumeRefreshJob() {
      const storedJobId = readStoredPortfolioRefreshJobId();
      let job: PortfolioRefreshJob | null = null;
      try {
        if (storedJobId) {
          job = await fetchPortfolioRefreshJob(storedJobId);
        } else {
          job = await fetchCurrentPortfolioRefreshJob();
        }
      } catch {
        clearStoredPortfolioRefreshJobId();
      }
      if (ignore || !job) return;
      if (isActivePortfolioRefreshJob(job)) {
        await pollPortfolioRefreshJob(job);
        return;
      }
      setRefreshJob(job);
      if (job.status === "success" && job.result) {
        setLastUpdated(job.result.updated_at);
      }
      clearStoredPortfolioRefreshJobId();
    }

    void resumeRefreshJob();
    return () => {
      ignore = true;
    };
    // The refresh job id is stored in sessionStorage; this effect should only resume once on page entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedSymbol) {
      return;
    }
    void loadSymbolDetail(selectedSymbol);
  }, [selectedSymbol]);

  async function loadSymbolDetail(symbol: string) {
    setDetailLoading(true);
    setDetailError("");
    try {
      const [marketData, newsData, riskData] = await Promise.all([
        fetchPortfolioMarket(symbol, "15m", 200),
        fetchPortfolioNews(symbol),
        fetchPortfolioRisk(symbol),
      ]);
      setCandles(marketData);
      setNewsItems(newsData);
      setRiskSnapshot(riskData);
      setChartFollowMode(defaultPortfolioChartFollowMode);
      setChartRange(latestPortfolioRangeForMode(marketData, { start: 0, end: Math.max(0, marketData.length - 1) }, defaultPortfolioChartFollowMode));
      setSelectedRiskEvent(null);
      setTradeDraft(null);
      setTradeMarkers(readPortfolioTradeMarkers(symbol));
      setLastUpdated(riskData.generated_at || formatNow());
    } catch (fetchError) {
      console.error(fetchError);
      setDetailError("当前币种风险数据加载失败，已保留页面其它数据。");
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshAndReload(showLoading = true) {
    if (refreshing) return;
    if (showLoading) setRefreshing(true);
    setError("");
    try {
      const job = await startPortfolioRefreshJob();
      storePortfolioRefreshJobId(job.job_id);
      await pollPortfolioRefreshJob(job);
    } catch (refreshError) {
      console.error(refreshError);
      setError("刷新风险数据失败，已保留当前缓存视图。");
    } finally {
      if (showLoading && mountedRef.current) setRefreshing(false);
    }
  }

  async function pollPortfolioRefreshJob(initialJob: PortfolioRefreshJob) {
    let job = initialJob;
    setRefreshJob(job);
    setRefreshing(isActivePortfolioRefreshJob(job));
    storePortfolioRefreshJobId(job.job_id);

    while (mountedRef.current && isActivePortfolioRefreshJob(job)) {
      await sleep(1200);
      job = await fetchPortfolioRefreshJob(job.job_id);
      if (!mountedRef.current) return;
      setRefreshJob(job);
      storePortfolioRefreshJobId(job.job_id);
    }

    if (!mountedRef.current) return;
    setRefreshing(false);
    setRefreshJob(job);
    clearStoredPortfolioRefreshJobId();
    if (job.status === "success") {
      if (job.result) setLastUpdated(job.result.updated_at);
      await reloadPortfolioAfterRefresh();
      try {
        const ranking = await fetchCoinRanking(0, "7d");
        if (mountedRef.current) {
          setCoinCandidates(ranking.items);
          writeCachedPortfolioCoinCandidates(ranking.items);
        }
      } catch (candidateError) {
        console.error(candidateError);
      }
      return;
    }
    if (job.status === "error") {
      setError(job.error ? `刷新风险数据失败：${job.error}` : "刷新风险数据失败，已保留当前缓存视图。");
    }
  }

  async function reloadPortfolioAfterRefresh() {
    const items = await fetchPortfolioWatchlist();
    const nextSymbol = selectedSymbol || items[0]?.symbol || "";
    if (!mountedRef.current) return;
    setWatchlist(items);
    setHoldingForm(defaultHoldingForm(items.find((item) => item.symbol === nextSymbol) || null));
    if (nextSymbol) await loadSymbolDetail(nextSymbol);
  }

  async function handleAddSymbol(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const symbol = addForm.symbol.trim();
    if (!symbol) return;
    setError("");
    try {
      await createPortfolioWatchlistItem({
        symbol,
        is_holding: addForm.isHolding,
        amount: toNumber(addForm.amount),
        avg_buy_price: toNumber(addForm.avgBuyPrice),
        alert_threshold: Math.round(toNumber(addForm.alertThreshold, 70)),
      });
      setAddForm(emptyAddForm);
      setAddOpen(false);
      const items = await fetchPortfolioWatchlist();
      setWatchlist(items);
      const normalized = normalizeInputSymbol(symbol);
      const nextSymbol = items.find((item) => item.symbol === normalized)?.symbol || items[0]?.symbol || "";
      setSelectedSymbol(nextSymbol);
      setHoldingForm(defaultHoldingForm(items.find((item) => item.symbol === nextSymbol) || null));
    } catch (addError) {
      console.error(addError);
      setError("添加币种失败，请检查币种代码是否正确。");
    }
  }

  async function handleSaveHolding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedItem) return;
    setSavingHolding(true);
    setDetailError("");
    try {
      await updatePortfolioWatchlistItem(selectedItem.symbol, {
        is_holding: holdingForm.isHolding,
        amount: toNumber(holdingForm.amount),
        avg_buy_price: toNumber(holdingForm.avgBuyPrice),
        alert_threshold: Math.round(toNumber(holdingForm.alertThreshold, 70)),
      });
      const items = await fetchPortfolioWatchlist();
      setWatchlist(items);
      setHoldingForm(defaultHoldingForm(items.find((item) => item.symbol === selectedItem.symbol) || null));
      await loadSymbolDetail(selectedItem.symbol);
    } catch (saveError) {
      console.error(saveError);
      setDetailError("持仓设置保存失败，请稍后重试。");
    } finally {
      setSavingHolding(false);
    }
  }

  async function handleDeleteSymbol(symbol: string) {
    if (!window.confirm(`确定从风险资产列表移除 ${symbol} 吗？`)) return;
    setError("");
    try {
      await deletePortfolioWatchlistItem(symbol);
      const nextItems = await fetchPortfolioWatchlist();
      const nextSymbol = nextItems[0]?.symbol || "";
      setWatchlist(nextItems);
      setSelectedSymbol(nextSymbol);
      setHoldingForm(defaultHoldingForm(nextItems.find((item) => item.symbol === nextSymbol) || null));
      if (!nextSymbol) {
        setCandles([]);
        setNewsItems([]);
        setRiskSnapshot(null);
        setSelectedRiskEvent(null);
        setAnalysisEvent(null);
        setTradeDraft(null);
        setTradeMarkers([]);
      }
      clearPortfolioTradeMarkers(symbol);
    } catch (deleteError) {
      console.error(deleteError);
      setError("删除币种失败，请稍后重试。");
    }
  }

  const portfolioValue = watchlist.reduce((sum, item) => sum + (item.market_value || 0), 0);
  const averageRisk = watchlist.length
    ? Math.round(watchlist.reduce((sum, item) => sum + (item.risk_score || 0), 0) / watchlist.length)
    : 0;
  const highRiskCount = watchlist.filter((item) => ["high", "critical"].includes(item.risk_level)).length;

  function handlePortfolioPresetRange(preset: PortfolioZoomPreset) {
    setChartFollowMode({ candles: preset.candles, kind: "preset", label: preset.label });
    setChartRange(portfolioRangeForPreset(candles, Math.max(0, candles.length - 1), preset.candles));
  }

  function handlePortfolioManualRange() {
    setChartFollowMode({ kind: "manual" });
  }

  function inspectPortfolioRiskEvent(event: PortfolioRiskEvent) {
    setSelectedRiskEvent(event);
    const maxIndex = Math.max(0, candles.length - 1);
    const anchor = clampNumber(event.candle_index, 0, maxIndex);
    const currentSize = Math.max(32, chartRange.end - chartRange.start + 1);
    const size = Math.min(candles.length || 1, currentSize);
    const start = clampNumber(anchor - Math.floor(size * 0.45), 0, Math.max(0, maxIndex - size + 1));
    setChartFollowMode({ kind: "manual" });
    setChartRange({ start, end: Math.min(maxIndex, start + size - 1) });
  }

  function handlePickTradePoint(point: Omit<PortfolioTradeDraft, "quantity" | "side">) {
    if (!selectedItem) return;
    setTradeDraft({
      ...point,
      quantity: "",
      side: selectedItem.is_holding && selectedItem.amount > 0 ? "sell" : "buy",
    });
  }

  async function handleApplyChartTrade(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedItem || !tradeDraft) return;
    const quantity = toNumber(tradeDraft.quantity);
    if (quantity <= 0) {
      setDetailError("请输入大于 0 的数量。");
      return;
    }
    const currentAmount = toNumber(holdingForm.amount);
    const currentAvg = toNumber(holdingForm.avgBuyPrice);
    if (tradeDraft.side === "sell" && quantity > currentAmount) {
      setDetailError("卖出数量不能大于当前持有数量。");
      return;
    }

    const nextAmount = tradeDraft.side === "buy"
      ? currentAmount + quantity
      : Math.max(0, currentAmount - quantity);
    const nextAvg = tradeDraft.side === "buy"
      ? (nextAmount ? ((currentAmount * currentAvg) + (quantity * tradeDraft.price)) / nextAmount : 0)
      : (nextAmount ? currentAvg : 0);
    const nextForm: HoldingFormState = {
      alertThreshold: holdingForm.alertThreshold,
      amount: formatPlainNumber(nextAmount),
      avgBuyPrice: formatPlainNumber(nextAvg),
      isHolding: nextAmount > 0,
    };
    const marker: PortfolioTradeMarker = {
      candle_index: tradeDraft.candle_index,
      id: `${selectedItem.symbol}:${Date.now()}:${tradeDraft.side}`,
      price: tradeDraft.price,
      quantity,
      side: tradeDraft.side,
      symbol: selectedItem.symbol,
      time: tradeDraft.time,
    };

    setSavingHolding(true);
    setDetailError("");
    try {
      await updatePortfolioWatchlistItem(selectedItem.symbol, {
        is_holding: nextForm.isHolding,
        amount: toNumber(nextForm.amount),
        avg_buy_price: toNumber(nextForm.avgBuyPrice),
        alert_threshold: Math.round(toNumber(nextForm.alertThreshold, 70)),
      });
      const nextMarkers = [...tradeMarkers.filter((item) => item.symbol === selectedItem.symbol), marker].slice(-80);
      writePortfolioTradeMarkers(selectedItem.symbol, nextMarkers);
      setTradeMarkers(nextMarkers);
      setTradeDraft(null);
      const [items, riskData] = await Promise.all([
        fetchPortfolioWatchlist(),
        fetchPortfolioRisk(selectedItem.symbol),
      ]);
      setWatchlist(items);
      setRiskSnapshot(riskData);
      setHoldingForm(defaultHoldingForm(items.find((item) => item.symbol === selectedItem.symbol) || null));
    } catch (tradeError) {
      console.error(tradeError);
      setDetailError("图上持仓操作保存失败，请稍后重试。");
    } finally {
      setSavingHolding(false);
    }
  }

  return (
    <section className="space-y-5">
      <div className="risk-card rounded-lg p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-emerald-700">Portfolio Risk Radar</p>
            <h1 className="mt-2 text-2xl font-bold text-slate-950 sm:text-3xl">个人资产风险雷达</h1>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              上次更新时间：{lastUpdated || "等待刷新"} · demo_user 个性化风险监控
            </p>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-emerald-200 bg-white px-4 text-sm font-bold text-emerald-700 transition-colors duration-200 hover:bg-emerald-50 sm:w-auto"
            >
              <PlusIcon />
              添加币种
            </button>
            <button
              type="button"
              onClick={() => refreshAndReload(true)}
              disabled={refreshing}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white shadow-sm shadow-blue-200 transition-colors duration-200 hover:bg-blue-700 disabled:opacity-60 sm:w-auto"
            >
              <RefreshIcon />
              {refreshing ? "刷新中" : "刷新风险数据"}
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <PortfolioMetric label="监控币种" value={String(watchlist.length)} />
          <PortfolioMetric label="模拟持仓价值" value={formatUsdt(portfolioValue)} />
          <PortfolioMetric label="高风险资产" value={`${highRiskCount} / ${averageRisk}`} helper="数量 / 平均风险分" />
        </div>
      </div>

      {error ? <Notice tone="red" text={error} /> : null}
      {refreshing || isActivePortfolioRefreshJob(refreshJob) ? <PortfolioRefreshProgress job={refreshJob} /> : null}

      {loading ? (
        <LoadingPanel text="正在加载个人资产风险雷达" />
      ) : watchlist.length ? (
        <>
          <div className="grid min-w-0 gap-4 xl:grid-cols-[260px_minmax(0,1fr)_320px]">
            <WatchlistPanel
              items={watchlist}
              onDelete={handleDeleteSymbol}
              onSelect={(symbol) => {
                setSelectedSymbol(symbol);
                setHoldingForm(defaultHoldingForm(watchlist.find((item) => item.symbol === symbol) || null));
              }}
              selectedSymbol={selectedItem?.symbol || ""}
            />

            <section className="risk-panel min-w-0 rounded-lg bg-white p-3 sm:p-4">
              <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Market Candles</p>
                  <h2 className="mt-1 text-lg font-bold text-slate-950">{selectedItem?.symbol || "--"} 15m 实时行情</h2>
                </div>
                <span className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700">
                  {candles[0]?.source === "binance_public" ? "Binance public" : "Fallback mock"}
                </span>
              </div>
              {detailLoading ? (
                <LoadingPanel compact text="正在同步行情与风险数据" />
              ) : (
                <PortfolioInteractiveChart
                  activePresetLabel={chartFollowMode.kind === "preset" ? chartFollowMode.label : null}
                  candles={candles}
                  events={portfolioEvents}
                  onCloseBanner={() => setSelectedRiskEvent(null)}
                  onInspectEvent={inspectPortfolioRiskEvent}
                  onManualRange={handlePortfolioManualRange}
                  onPickTradePoint={handlePickTradePoint}
                  onPresetRange={handlePortfolioPresetRange}
                  onViewAnalysis={setAnalysisEvent}
                  range={chartRange}
                  selectedEvent={selectedRiskEvent}
                  setRange={setChartRange}
                  tradeMarkers={tradeMarkers}
                />
              )}
              {tradeDraft ? (
                <PortfolioTradeDraftPanel
                  draft={tradeDraft}
                  onChange={setTradeDraft}
                  onClose={() => setTradeDraft(null)}
                  onSubmit={handleApplyChartTrade}
                  saving={savingHolding}
                  watchItem={selectedItem}
                />
              ) : null}
              {detailError ? <div className="mt-3"><Notice tone="amber" text={detailError} /></div> : null}
            </section>

            <RiskSummaryPanel
              form={holdingForm}
              onChangeForm={setHoldingForm}
              onSubmit={handleSaveHolding}
              saving={savingHolding}
              snapshot={riskSnapshot}
              watchItem={selectedItem}
            />
          </div>

          <RelatedNewsSection items={newsItems} selectedSymbol={selectedItem?.symbol || ""} />
        </>
      ) : (
        <EmptyPortfolio onAdd={() => setAddOpen(true)} />
      )}

      {addOpen ? (
        <AddSymbolModal
          form={addForm}
          candidates={addSymbolCandidates}
          onChange={setAddForm}
          onClose={() => setAddOpen(false)}
          onSubmit={handleAddSymbol}
        />
      ) : null}
      {analysisEvent ? (
        <PortfolioEventAnalysisModal
          event={analysisEvent}
          onClose={() => setAnalysisEvent(null)}
          snapshot={riskSnapshot}
        />
      ) : null}
    </section>
  );
}

function PortfolioRefreshProgress({ job }: { job: PortfolioRefreshJob | null }) {
  const activeStep = job?.stage === "done" ? 3 : job?.stage === "news" ? 1 : job?.stage === "error" ? 3 : 0;
  const steps = ["准备刷新", "同步新闻", "关联币种", "生成快照"];
  return (
    <section className="risk-card relative overflow-hidden rounded-lg border border-emerald-100 bg-white p-4">
      <div className="portfolio-refresh-sweep pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-emerald-100/70 to-transparent" />
      <div className="relative flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-700">Refreshing Risk Data</p>
          <h2 className="mt-1 text-base font-bold text-slate-950">{job?.message || "正在刷新新闻、行情和风险快照"}</h2>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-600" />
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400 [animation-delay:160ms]" />
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-200 [animation-delay:320ms]" />
        </div>
      </div>
      <div className="relative mt-4 grid gap-2 sm:grid-cols-4">
        {steps.map((step, index) => {
          const done = index < activeStep;
          const current = index === activeStep;
          return (
            <div
              className={`rounded-lg border px-3 py-2 text-xs font-bold transition-colors duration-200 ${
                done
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : current
                    ? "border-blue-200 bg-blue-50 text-blue-700"
                    : "border-blue-100 bg-white text-slate-400"
              }`}
              key={step}
            >
              {step}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function WatchlistPanel({
  items,
  onDelete,
  onSelect,
  selectedSymbol,
}: {
  items: PortfolioWatchlistItem[];
  onDelete: (symbol: string) => void;
  onSelect: (symbol: string) => void;
  selectedSymbol: string;
}) {
  const [deleteMode, setDeleteMode] = useState(false);

  return (
    <aside className="risk-panel min-w-0 rounded-lg p-3">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold uppercase tracking-[0.16em] text-slate-500">自选币种</h2>
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">{items.length}</span>
          <button
            aria-pressed={deleteMode}
            aria-label={deleteMode ? "关闭删除模式" : "管理自选币种"}
            className={`inline-flex h-8 w-8 items-center justify-center rounded-md border text-xs transition-colors duration-200 ${
              deleteMode
                ? "border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100"
                : "border-blue-100 bg-white text-slate-500 hover:bg-blue-50 hover:text-rose-600"
            }`}
            onClick={() => setDeleteMode((value) => !value)}
            type="button"
          >
            <TrashIcon />
          </button>
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
        {items.map((item) => {
          const selected = item.symbol === selectedSymbol;
          return (
            <article
              key={item.symbol}
              className={`group relative rounded-lg border p-3 transition-colors duration-200 ${deleteMode ? "pr-10" : ""} ${
                selected ? "border-emerald-400 bg-emerald-50" : "border-blue-100 bg-white hover:border-emerald-300 hover:bg-emerald-50/60"
              }`}
            >
              <button type="button" onClick={() => onSelect(item.symbol)} className="w-full text-left">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <CoinAvatar symbol={item.base_asset} />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-slate-950">{item.symbol}</p>
                        <p className="text-xs text-slate-500">{item.is_holding ? "已设置持仓" : "仅关注"}</p>
                      </div>
                    </div>
                  </div>
                  <RiskBadge level={item.risk_level} score={item.risk_score} />
                </div>
                <div className="mt-3 flex items-end justify-between gap-3">
                  <div>
                    <p className="text-sm font-bold text-slate-900">{formatUsdt(item.current_price)}</p>
                    <p className={`mt-1 text-xs font-bold ${item.price_change_24h >= 0 ? "text-emerald-600" : "text-red-600"}`}>
                      {formatPercent(item.price_change_24h)}
                    </p>
                  </div>
                </div>
              </button>
              {deleteMode ? (
                <button
                  type="button"
                  onClick={() => onDelete(item.symbol)}
                  aria-label={`从自选币种移除 ${item.symbol}`}
                  className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded-md border border-rose-100 bg-white text-rose-600 shadow-sm transition-colors duration-200 hover:bg-rose-50"
                >
                  <TrashIcon />
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </aside>
  );
}

function RiskSummaryPanel({
  form,
  onChangeForm,
  onSubmit,
  saving,
  snapshot,
  watchItem,
}: {
  form: HoldingFormState;
  onChangeForm: (value: HoldingFormState) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  snapshot: CoinRiskSnapshot | null;
  watchItem: PortfolioWatchlistItem | null;
}) {
  const threshold = Math.round(toNumber(form.alertThreshold, watchItem?.alert_threshold || 70));
  const riskScore = snapshot?.risk_score ?? watchItem?.risk_score ?? 0;
  const thresholdTriggered = riskScore >= threshold;

  return (
    <aside className="risk-panel min-w-0 rounded-lg bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Holding Impact</p>
          <h2 className="mt-1 text-lg font-bold text-slate-950">持仓与风险摘要</h2>
        </div>
        {snapshot ? <RiskBadge level={snapshot.risk_level} score={snapshot.risk_score} /> : null}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <InfoTile label="当前价值" value={formatUsdt(watchItem?.market_value || 0)} />
        <InfoTile label="浮动盈亏" value={formatUsdt(watchItem?.floating_pnl || 0)} tone={(watchItem?.floating_pnl || 0) >= 0 ? "up" : "down"} />
        <InfoTile label="24h 涨跌" value={formatPercent(snapshot?.price_change_24h ?? watchItem?.price_change_24h ?? 0)} tone={(snapshot?.price_change_24h ?? 0) >= 0 ? "up" : "down"} />
        <InfoTile label="相关新闻" value={`${snapshot?.related_news_count || 0} 条`} />
      </div>

      <form className="mt-4 space-y-3 rounded-lg border border-blue-100 bg-slate-50 p-3" onSubmit={onSubmit}>
        <label className="flex items-center justify-between gap-3 text-sm font-bold text-slate-700">
          标记为持仓
          <input
            checked={form.isHolding}
            onChange={(event) => onChangeForm({ ...form, isHolding: event.target.checked })}
            className="h-4 w-4 accent-emerald-700"
            type="checkbox"
          />
        </label>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          <PortfolioInput label="持有数量" value={form.amount} onChange={(value) => onChangeForm({ ...form, amount: value })} />
          <PortfolioInput label="买入均价" value={form.avgBuyPrice} onChange={(value) => onChangeForm({ ...form, avgBuyPrice: value })} />
          <PortfolioInput label="AI 风险分提醒线" value={form.alertThreshold} onChange={(value) => onChangeForm({ ...form, alertThreshold: value })} />
        </div>
        <div className={`rounded-lg border px-3 py-2 text-xs leading-5 ${thresholdTriggered ? "border-amber-200 bg-amber-50 text-amber-800" : "border-blue-100 bg-white text-slate-500"}`}>
          {thresholdTriggered ? "当前 AI 风险分已达到提醒线，建议检查相关新闻和持仓敞口。" : "提醒线按 AI 风险分触发，用来提示关注风险，不是价格止损或自动卖出。"}
        </div>
        <button
          type="submit"
          disabled={saving || !watchItem}
          className="h-10 w-full rounded-lg bg-blue-600 text-sm font-bold text-white transition-colors duration-200 hover:bg-blue-700 disabled:opacity-60"
        >
          {saving ? "保存中" : "保存持仓设置"}
        </button>
      </form>

      <div className="mt-4 space-y-3">
        <TextBlock title="AI 风险解释" text={snapshot?.ai_summary || "等待刷新后生成币种级风险解释。"} />
        <TextBlock title="持仓影响" text={snapshot?.holding_impact || "设置持仓后会计算当前价值、浮动盈亏和敞口影响。"} />
        <TextBlock title="AI 建议" text={snapshot?.ai_advice || "暂无建议。"} />
      </div>
    </aside>
  );
}

function PortfolioTradeDraftPanel({
  draft,
  onChange,
  onClose,
  onSubmit,
  saving,
  watchItem,
}: {
  draft: PortfolioTradeDraft;
  onChange: (draft: PortfolioTradeDraft) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  saving: boolean;
  watchItem: PortfolioWatchlistItem | null;
}) {
  return (
    <form className="mt-3 rounded-lg border border-emerald-100 bg-emerald-50/70 p-3" onSubmit={onSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-emerald-700">Position Marker</p>
          <h3 className="mt-1 text-sm font-bold text-slate-950">按图上点位记录持仓操作</h3>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {formatPortfolioTime(draft.time)} · 价格 {formatUsdt(draft.price)}
          </p>
        </div>
        <button className="rounded-md border border-emerald-200 bg-white px-2 py-1 text-xs font-bold text-emerald-700 hover:bg-emerald-100" onClick={onClose} type="button">
          取消
        </button>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)_120px]">
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-emerald-100 bg-white p-1">
          <button
            className={`h-9 rounded-md text-sm font-bold transition-colors duration-150 ${draft.side === "buy" ? "bg-emerald-700 text-white" : "text-emerald-700 hover:bg-emerald-50"}`}
            onClick={() => onChange({ ...draft, side: "buy" })}
            type="button"
          >
            加仓
          </button>
          <button
            className={`h-9 rounded-md text-sm font-bold transition-colors duration-150 ${draft.side === "sell" ? "bg-slate-950 text-white" : "text-slate-700 hover:bg-slate-50"}`}
            onClick={() => onChange({ ...draft, side: "sell" })}
            type="button"
          >
            卖出
          </button>
        </div>
        <PortfolioInput
          label={`数量${watchItem?.base_asset ? `（${watchItem.base_asset}）` : ""}`}
          value={draft.quantity}
          onChange={(value) => onChange({ ...draft, quantity: value })}
        />
        <button
          className="h-10 self-end rounded-lg bg-blue-600 px-4 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-60"
          disabled={saving || !watchItem}
          type="submit"
        >
          {saving ? "保存中" : "确认"}
        </button>
      </div>
    </form>
  );
}

function PortfolioInteractiveChart({
  activePresetLabel,
  candles,
  events,
  onCloseBanner,
  onInspectEvent,
  onManualRange,
  onPickTradePoint,
  onPresetRange,
  onViewAnalysis,
  range,
  selectedEvent,
  setRange,
  tradeMarkers,
}: {
  activePresetLabel: string | null;
  candles: PortfolioMarketCandle[];
  events: PortfolioRiskEvent[];
  onCloseBanner: () => void;
  onInspectEvent: (event: PortfolioRiskEvent) => void;
  onManualRange: () => void;
  onPickTradePoint: (point: Omit<PortfolioTradeDraft, "quantity" | "side">) => void;
  onPresetRange: (preset: PortfolioZoomPreset) => void;
  onViewAnalysis: (event: PortfolioRiskEvent) => void;
  range: PortfolioChartRange;
  selectedEvent: PortfolioRiskEvent | null;
  setRange: Dispatch<SetStateAction<PortfolioChartRange>>;
  tradeMarkers: PortfolioTradeMarker[];
}) {
  const dragRef = useRef<{ moved: boolean; range: PortfolioChartRange; x: number } | null>(null);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const zoomDragRef = useRef<{ mode: PortfolioZoomDragMode; range: PortfolioChartRange; trackWidth: number; x: number } | null>(null);
  const [hoverPoint, setHoverPoint] = useState<PortfolioHoverPoint | null>(null);
  const [openEventStack, setOpenEventStack] = useState<{ events: PortfolioRiskEvent[]; x: number } | null>(null);

  const maxIndex = Math.max(0, candles.length - 1);
  const safeRange = clampPortfolioRange(range, maxIndex);
  const visibleCandles = candles.slice(safeRange.start, safeRange.end + 1);
  const priceRange = getPortfolioPriceRange(visibleCandles);
  const ma10 = portfolioMovingAverage(candles, 10);
  const ma30 = portfolioMovingAverage(candles, 30);
  const ma10Path = buildPortfolioMovingAveragePath(ma10, safeRange, priceRange.min, priceRange.max);
  const ma30Path = buildPortfolioMovingAveragePath(ma30, safeRange, priceRange.min, priceRange.max);
  const clusters = createPortfolioClusters(events, safeRange);
  const latest = visibleCandles[visibleCandles.length - 1];
  const candleWidth = portfolioMainCandleWidth(visibleCandles.length);
  const maxVolume = Math.max(1, ...visibleCandles.map((item) => item.volume));
  const selectedAnchorIndex = selectedEvent?.candle_index;
  const selectedRelativeIndex = selectedAnchorIndex === undefined ? -1 : selectedAnchorIndex - safeRange.start;
  const selectedAnchorCandle = selectedAnchorIndex !== undefined && selectedRelativeIndex >= 0 && selectedRelativeIndex < visibleCandles.length
    ? candles[selectedAnchorIndex]
    : null;
  const selectedAnchorPoint: PortfolioHoverPoint | null = selectedAnchorCandle && selectedAnchorIndex !== undefined ? {
    absoluteIndex: selectedAnchorIndex,
    price: selectedAnchorCandle.close,
    x: portfolioCandleX(selectedRelativeIndex, visibleCandles.length),
    y: portfolioPriceY(selectedAnchorCandle.close, priceRange.min, priceRange.max),
  } : null;
  const activePointer = hoverPoint || selectedAnchorPoint;
  const readoutIndex = clampNumber(activePointer?.absoluteIndex ?? safeRange.end, 0, maxIndex);
  const readoutCandle = candles[readoutIndex] || latest;
  const readoutMa10 = ma10[readoutIndex];
  const readoutMa30 = ma30[readoutIndex];
  const readoutChange = readoutCandle?.open ? (readoutCandle.close - readoutCandle.open) / readoutCandle.open : 0;
  const visibleTradeMarkers = tradeMarkers.filter((marker) => marker.candle_index >= safeRange.start && marker.candle_index <= safeRange.end);
  const markerY = 48;
  const rangeSpan = Math.max(1, maxIndex);
  const startPercent = maxIndex ? (safeRange.start / rangeSpan) * 100 : 0;
  const endPercent = maxIndex ? (safeRange.end / rangeSpan) * 100 : 100;

  function updateRange(next: PortfolioChartRange, isManual = true) {
    if (isManual) onManualRange();
    setRange(clampPortfolioRange(next, maxIndex));
  }

  function zoomAround(anchor: number, anchorRatio: number, nextSize: number) {
    const size = Math.max(4, Math.min(maxIndex + 1, nextSize));
    let start = Math.round(anchor - anchorRatio * (size - 1));
    let end = start + size - 1;
    if (start < 0) {
      start = 0;
      end = size - 1;
    }
    if (end > maxIndex) {
      end = maxIndex;
      start = Math.max(0, end - size + 1);
    }
    updateRange({ start, end });
  }

  function applyWheelZoom(deltaY: number, anchorRatio = 0.5) {
    const size = safeRange.end - safeRange.start + 1;
    const ratio = clampNumber(anchorRatio, 0, 1);
    const anchor = safeRange.start + ratio * Math.max(0, size - 1);
    const nextSize = deltaY < 0 ? Math.floor(size * 0.8) : Math.ceil(size * 1.25);
    zoomAround(anchor, ratio, nextSize);
  }

  function wheelAnchorRatio(event: globalThis.WheelEvent, container: HTMLDivElement) {
    const rect = container.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * portfolioChartSpec.width;
    const plotX = (svgX - portfolioChartSpec.paddingX) / Math.max(1, portfolioChartSpec.width - portfolioChartSpec.paddingX * 2);
    return clampNumber(plotX, 0, 1);
  }

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container) return;
    const handleNativeWheel = (event: globalThis.WheelEvent) => {
      if (event.target instanceof Element && event.target.closest("[data-no-chart-wheel]")) {
        return;
      }
      event.preventDefault();
      applyWheelZoom(event.deltaY, wheelAnchorRatio(event, container));
    };
    container.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => container.removeEventListener("wheel", handleNativeWheel);
  });

  useEffect(() => {
    const handleMove = (event: MouseEvent) => {
      const drag = zoomDragRef.current;
      if (!drag) return;
      const delta = Math.round(((event.clientX - drag.x) / drag.trackWidth) * Math.max(1, maxIndex));
      if (delta === 0) return;
      if (drag.mode === "start") {
        updateRange({ end: drag.range.end, start: drag.range.start + delta });
        return;
      }
      if (drag.mode === "end") {
        updateRange({ end: drag.range.end + delta, start: drag.range.start });
        return;
      }
      updateRange({ end: drag.range.end + delta, start: drag.range.start + delta });
    };
    const handleUp = () => {
      zoomDragRef.current = null;
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  });

  useEffect(() => {
    if (!openEventStack) return;
    const close = () => setOpenEventStack(null);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [openEventStack]);

  function handleMouseDown(event: ReactMouseEvent<HTMLDivElement>) {
    dragRef.current = { moved: false, range: safeRange, x: event.clientX };
  }

  function handleMouseMove(event: ReactMouseEvent<HTMLDivElement>) {
    if (!dragRef.current) {
      updateHoverPoint(event);
      return;
    }
    const width = event.currentTarget.getBoundingClientRect().width || 1;
    const size = dragRef.current.range.end - dragRef.current.range.start + 1;
    const deltaCandles = Math.round(((dragRef.current.x - event.clientX) / width) * size);
    if (deltaCandles === 0) return;
    dragRef.current.moved = true;
    updateRange({
      end: dragRef.current.range.end + deltaCandles,
      start: dragRef.current.range.start + deltaCandles,
    });
  }

  function pointFromMouse(event: ReactMouseEvent<HTMLDivElement>): PortfolioHoverPoint | null {
    if (!visibleCandles.length) return null;
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * portfolioChartSpec.width;
    const svgY = ((event.clientY - rect.top) / Math.max(1, rect.height)) * portfolioChartSpec.height;
    const normalized = (svgX - portfolioChartSpec.paddingX) / Math.max(1, portfolioChartSpec.width - portfolioChartSpec.paddingX * 2);
    const relativeIndex = clampNumber(Math.round(normalized * Math.max(0, visibleCandles.length - 1)), 0, Math.max(0, visibleCandles.length - 1));
    const absoluteIndex = safeRange.start + relativeIndex;
    const x = portfolioCandleX(relativeIndex, visibleCandles.length);
    const y = clampNumber(svgY, portfolioChartSpec.priceTop, portfolioChartSpec.priceBottom);
    const priceRatio = (y - portfolioChartSpec.priceTop) / Math.max(1, portfolioChartSpec.priceBottom - portfolioChartSpec.priceTop);
    const price = priceRange.max - priceRatio * (priceRange.max - priceRange.min);
    return { absoluteIndex, price, x, y };
  }

  function updateHoverPoint(event: ReactMouseEvent<HTMLDivElement>) {
    const point = pointFromMouse(event);
    if (point) setHoverPoint(point);
  }

  function handleMouseUp(event: ReactMouseEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag && !drag.moved) {
      const point = pointFromMouse(event);
      const candle = point ? candles[point.absoluteIndex] : null;
      if (point && candle) {
        onPickTradePoint({
          candle_index: point.absoluteIndex,
          price: Number(point.price.toFixed(8)),
          time: String(candle.open_time),
        });
      }
    }
    stopDrag();
  }

  function stopDrag() {
    dragRef.current = null;
    setHoverPoint(null);
  }

  function startZoomDrag(mode: PortfolioZoomDragMode, event: ReactMouseEvent<HTMLButtonElement | HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    zoomDragRef.current = {
      mode,
      range: safeRange,
      trackWidth: event.currentTarget.parentElement?.getBoundingClientRect().width || 1,
      x: event.clientX,
    };
  }

  if (!candles.length) {
    return (
      <div className="flex h-[360px] items-center justify-center rounded-lg border border-dashed border-blue-100 bg-slate-50 text-sm font-bold text-slate-500">
        暂无行情数据，点击刷新风险数据后重试。
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-blue-100 bg-white p-2.5 shadow-sm sm:p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Market Candles</span>
          <span className="text-xs font-bold text-slate-600">K 线</span>
          {portfolioZoomPresets.map((preset) => (
            <button
              aria-pressed={activePresetLabel === preset.label}
              className={`h-8 rounded-md border px-3 text-xs font-bold transition-all duration-200 ${
                activePresetLabel === preset.label
                  ? "border-emerald-600 bg-emerald-600 text-white shadow-sm shadow-emerald-100"
                  : "border-blue-100 bg-white text-slate-700 hover:border-emerald-300 hover:bg-emerald-50"
              }`}
              key={preset.label}
              onClick={() => onPresetRange(preset)}
              type="button"
            >
              {preset.label}
            </button>
          ))}
          <span className="hidden text-xs text-slate-400 sm:inline">滚轮缩放 / 拖拽平移</span>
        </div>
        <div className="text-right text-xs font-semibold text-slate-500">
          <span>{visibleCandles.length} candles</span>
          <span className="mx-2 text-slate-300">/</span>
          <span>{formatPortfolioTime(latest?.open_time || 0)}</span>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-emerald-600" />绿色：上涨</span>
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-red-600" />红色：下跌</span>
        <span>MA10</span>
          <span>MA30</span>
          <span>成交量</span>
        <span>点击图中 K 线可按该时间和价格记录加仓 / 卖出。</span>
      </div>

      <PortfolioEventBanner event={selectedEvent} onClose={onCloseBanner} onViewAnalysis={onViewAnalysis} />

      {readoutCandle ? (
        <div className="mt-2 max-w-full rounded-lg border border-blue-100 bg-white px-3 py-2 font-sans text-[13px] font-semibold leading-5 tracking-normal text-slate-950 shadow-sm shadow-slate-900/5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
            <span>开: {formatNumber(readoutCandle.open, 2)}</span>
            <span>| 高: {formatNumber(readoutCandle.high, 2)}</span>
            <span>| 低: {formatNumber(readoutCandle.low, 2)}</span>
            <span>| 收: {formatNumber(readoutCandle.close, 2)}</span>
            <span>| 量: {formatNumber(readoutCandle.volume, 0)}</span>
            <span>| {readoutChange >= 0 ? "+" : ""}{formatPercent(readoutChange)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
            <span className="text-amber-600">MA10: {readoutMa10 ? formatNumber(readoutMa10, 2) : "--"}</span>
            <span className="text-blue-600">MA30: {readoutMa30 ? formatNumber(readoutMa30, 2) : "--"}</span>
          </div>
        </div>
      ) : null}

      <div
        ref={chartContainerRef}
        className="relative mt-2 cursor-grab select-none rounded-lg bg-gradient-to-b from-slate-50 to-white active:cursor-grabbing"
        onMouseDown={handleMouseDown}
        onMouseLeave={stopDrag}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        style={{ height: "clamp(340px, 58vh, 520px)" }}
      >
        <svg aria-label="portfolio market candlestick chart" className="h-full w-full" preserveAspectRatio="none" viewBox={`0 0 ${portfolioChartSpec.width} ${portfolioChartSpec.height}`}>
          <defs>
            <filter height="240%" id="portfolioRiskMarkerGlow" width="240%" x="-70%" y="-70%">
              <feGaussianBlur result="blur" stdDeviation="3" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {[104, 172, 240, 308, 376].map((y) => (
            <line key={y} stroke="#dbe4f0" strokeDasharray="4 8" strokeWidth="1" x1={portfolioChartSpec.paddingX} x2={portfolioChartSpec.width - portfolioChartSpec.paddingX} y1={y} y2={y} />
          ))}
          <rect fill="transparent" height={portfolioChartSpec.volumeBottom - portfolioChartSpec.volumeTop + 10} width={portfolioChartSpec.width - portfolioChartSpec.paddingX * 2} x={portfolioChartSpec.paddingX} y={portfolioChartSpec.volumeTop - 5} />
          <g>
            {clusters.map((cluster) => {
              const groupEvent = getDominantPortfolioEvent(cluster.events);
              const anchorIndex = groupEvent.candle_index;
              const candle = candles[anchorIndex];
              if (!candle) return null;
              const anchorY = portfolioPriceY(candle.high, priceRange.min, priceRange.max);
              const active = selectedAnchorIndex === anchorIndex;
              const tone = resolvePortfolioRiskTone(groupEvent);
              return (
                <line
                  key={`anchor-${groupEvent.id}`}
                  opacity={active ? 0.9 : 0.42}
                  stroke={active ? tone.marker : "#94a3b8"}
                  strokeDasharray="4 5"
                  strokeWidth={active ? 1.6 : 1}
                  x1={cluster.x}
                  x2={cluster.x}
                  y1={markerY + 13}
                  y2={anchorY}
                />
              );
            })}
          </g>
          {visibleCandles.map((candle, index) => {
            const x = portfolioCandleX(index, visibleCandles.length);
            const up = candle.close >= candle.open;
            const color = up ? "#16a34a" : "#dc2626";
            const yHigh = portfolioPriceY(candle.high, priceRange.min, priceRange.max);
            const yLow = portfolioPriceY(candle.low, priceRange.min, priceRange.max);
            const yOpen = portfolioPriceY(candle.open, priceRange.min, priceRange.max);
            const yClose = portfolioPriceY(candle.close, priceRange.min, priceRange.max);
            const bodyY = Math.min(yOpen, yClose);
            const bodyHeight = Math.max(1.2, Math.abs(yOpen - yClose));
            const volumeBarHeight = portfolioVolumeHeight(candle.volume, maxVolume);
            const absoluteIndex = safeRange.start + index;
            const highlighted = absoluteIndex === selectedAnchorIndex;
            return (
              <g key={`${candle.id || candle.open_time}-${index}`}>
                {highlighted ? (
                  <rect fill={color} height={Math.max(18, yLow - yHigh + 10)} opacity="0.12" rx="5" stroke={color} strokeDasharray="3 4" strokeWidth="1.5" width={candleWidth + 11} x={x - (candleWidth + 11) / 2} y={yHigh - 5} />
                ) : null}
                <line stroke={color} strokeWidth="1.4" x1={x} x2={x} y1={yHigh} y2={yLow} />
                <rect fill={color} height={bodyHeight} rx="1.2" width={candleWidth} x={x - candleWidth / 2} y={bodyY} />
                <rect fill={color} height={volumeBarHeight} opacity="0.34" rx="0.8" width={candleWidth} x={x - candleWidth / 2} y={portfolioChartSpec.volumeBottom - volumeBarHeight} />
              </g>
            );
          })}
          {ma10Path ? <path d={ma10Path} fill="none" stroke="#d97706" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" /> : null}
          {ma30Path ? <path d={ma30Path} fill="none" stroke="#2563eb" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" /> : null}
          {visibleTradeMarkers.map((marker, order) => {
            const relativeIndex = marker.candle_index - safeRange.start;
            const x = portfolioCandleX(relativeIndex, visibleCandles.length);
            const y = clampNumber(portfolioPriceY(marker.price, priceRange.min, priceRange.max), portfolioChartSpec.priceTop + 14, portfolioChartSpec.priceBottom - 14);
            const isBuy = marker.side === "buy";
            const fill = isBuy ? "#059669" : "#020617";
            const markerYPosition = isBuy ? y + (order % 2) * 8 : y - (order % 2) * 8;
            return (
              <g key={marker.id} pointerEvents="none">
                <title>{`${isBuy ? "加仓" : "卖出"} ${formatNumber(marker.quantity, 8)} @ ${formatUsdt(marker.price)} · ${formatPortfolioTime(marker.time)}`}</title>
                {isBuy ? (
                  <path d={`M ${x} ${markerYPosition - 11} L ${x - 8} ${markerYPosition + 5} L ${x + 8} ${markerYPosition + 5} Z`} fill={fill} opacity="0.96" stroke="#ffffff" strokeWidth="1.4" />
                ) : (
                  <path d={`M ${x} ${markerYPosition + 11} L ${x - 8} ${markerYPosition - 5} L ${x + 8} ${markerYPosition - 5} Z`} fill={fill} opacity="0.96" stroke="#ffffff" strokeWidth="1.4" />
                )}
                <text fill="#ffffff" fontSize="7.5" fontWeight="900" textAnchor="middle" x={x} y={isBuy ? markerYPosition + 2 : markerYPosition + 1}>
                  {isBuy ? "B" : "S"}
                </text>
              </g>
            );
          })}
          {activePointer ? (
            <g pointerEvents="none">
              <line opacity="0.75" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" x1={activePointer.x} x2={activePointer.x} y1={portfolioChartSpec.priceTop} y2={portfolioChartSpec.volumeBottom} />
              <line opacity="0.75" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" x1={portfolioChartSpec.paddingX} x2={portfolioChartSpec.width - portfolioChartSpec.paddingX} y1={activePointer.y} y2={activePointer.y} />
              <rect fill="#0f172a" height="18" rx="4" width="82" x={portfolioChartSpec.width - 104} y={clampNumber(activePointer.y - 9, portfolioChartSpec.priceTop, portfolioChartSpec.priceBottom - 18)} />
              <text fill="#ffffff" fontSize="10" fontWeight="700" textAnchor="middle" x={portfolioChartSpec.width - 63} y={clampNumber(activePointer.y + 4, portfolioChartSpec.priceTop + 13, portfolioChartSpec.priceBottom - 5)}>
                {formatNumber(activePointer.price, 2)}
              </text>
              <rect fill="#0f172a" height="18" rx="4" width="92" x={clampNumber(activePointer.x - 46, portfolioChartSpec.paddingX, portfolioChartSpec.width - portfolioChartSpec.paddingX - 92)} y={portfolioChartSpec.height - 22} />
              <text fill="#ffffff" fontSize="9.5" fontWeight="700" textAnchor="middle" x={clampNumber(activePointer.x, portfolioChartSpec.paddingX + 46, portfolioChartSpec.width - portfolioChartSpec.paddingX - 46)} y={portfolioChartSpec.height - 9}>
                {formatPortfolioTime(candles[activePointer.absoluteIndex]?.open_time || 0)}
              </text>
            </g>
          ) : null}
          {clusters.map((cluster) => {
            const groupEvent = getDominantPortfolioEvent(cluster.events);
            const count = cluster.events.length;
            const isCluster = count > 1;
            const tone = resolvePortfolioRiskTone(groupEvent);
            const flagWidth = isCluster ? Math.max(18, 12 + String(count).length * 7) : 8;
            const flagX = clampNumber(cluster.x, flagWidth / 2 + 3, portfolioChartSpec.width - flagWidth / 2 - 3);
            const active = cluster.events.some((event) => event.id === selectedEvent?.id);
            return (
              <g
                className="cursor-pointer transition-opacity"
                filter={active ? "url(#portfolioRiskMarkerGlow)" : undefined}
                key={`${groupEvent.id}-${count}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onInspectEvent(groupEvent);
                  if (isCluster) {
                    setOpenEventStack({
                      events: [...cluster.events].sort((a, b) => b.risk_score - a.risk_score),
                      x: cluster.x,
                    });
                  } else {
                    setOpenEventStack(null);
                  }
                }}
                onMouseDown={(event) => event.stopPropagation()}
              >
                {isCluster ? (
                  <>
                    <rect fill="transparent" height="31" rx="7" width={flagWidth + 18} x={flagX - flagWidth / 2 - 9} y={markerY - 16} />
                    <rect fill={tone.markerCluster} height="15" rx="4" stroke="#fff" strokeWidth="1.5" width={flagWidth} x={flagX - flagWidth / 2} y={markerY - 8} />
                    <text fill="#fff" fontSize="9.5" fontWeight="800" textAnchor="middle" x={flagX} y={markerY + 3}>
                      {count}
                    </text>
                  </>
                ) : (
                  <>
                    <rect fill="transparent" height="28" rx="7" width="28" x={flagX - 14} y={markerY - 14} />
                    <rect fill={tone.marker} height="8" rx="2" stroke="#fff" strokeWidth="1.5" width="8" x={flagX - 4} y={markerY - 4} />
                  </>
                )}
              </g>
            );
          })}
        </svg>
        {openEventStack ? (
          <PortfolioEventStackPopover
            events={openEventStack.events}
            leftPercent={(openEventStack.x / portfolioChartSpec.width) * 100}
            onInspect={(event) => {
              onInspectEvent(event);
              setOpenEventStack(null);
            }}
          />
        ) : null}
      </div>

      <PortfolioRiskHeatTimeline events={events} maxIndex={maxIndex} range={safeRange} />

      <div className="mt-2 rounded-lg border border-blue-100 bg-slate-50/70 px-3 py-2">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">DataZoom</span>
          <span className="text-xs text-slate-500">
            {safeRange.start} - {safeRange.end}
          </span>
        </div>
        <div className="relative h-16 rounded-md border border-blue-100 bg-white px-2 py-1">
          <svg className="absolute inset-x-2 top-2 h-10 w-[calc(100%-1rem)]" preserveAspectRatio="none" viewBox={`0 0 ${portfolioMiniChartSpec.width} ${portfolioMiniChartSpec.height}`}>
            {renderPortfolioMiniCandles(candles)}
          </svg>
          <div className="absolute bottom-2 left-4 right-4 h-5">
            <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-200" />
            <button
              aria-label="拖拽当前缩放窗口"
              className="absolute top-1/2 h-4 -translate-y-1/2 rounded-full bg-emerald-500/35"
              onMouseDown={(event) => startZoomDrag("window", event)}
              style={{ left: `${startPercent}%`, width: `${Math.max(2, endPercent - startPercent)}%` }}
              type="button"
            />
            <button
              aria-label="调整起点"
              className="absolute top-1/2 h-5 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm border border-emerald-700 bg-white shadow"
              onMouseDown={(event) => startZoomDrag("start", event)}
              style={{ left: `${startPercent}%` }}
              type="button"
            />
            <button
              aria-label="调整终点"
              className="absolute top-1/2 h-5 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm border border-emerald-700 bg-white shadow"
              onMouseDown={(event) => startZoomDrag("end", event)}
              style={{ left: `${endPercent}%` }}
              type="button"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function PortfolioRiskHeatTimeline({ events, maxIndex, range }: { events: PortfolioRiskEvent[]; maxIndex: number; range: PortfolioChartRange }) {
  const riskByIndex = useMemo(() => {
    const map = new Map<number, PortfolioRiskEvent>();
    events.forEach((event) => {
      const index = event.candle_index;
      if (index < 0) return;
      const current = map.get(index);
      if (!current || event.risk_score > current.risk_score) map.set(index, event);
    });
    return map;
  }, [events]);
  const start = Math.max(0, range.start);
  const end = Math.max(start, range.end);
  const count = end - start + 1;
  const cells = Array.from({ length: count }, (_, offset) => {
    const index = start + offset;
    const event = riskByIndex.get(index);
    const color = event ? resolvePortfolioRiskTone(event).marker : "#cbd5e1";
    return { color, event, index };
  });

  return (
    <div className="mt-2 rounded-lg border border-blue-100 bg-white px-3 py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">风险热力时间轴</span>
        <span className="text-xs text-slate-400">绿低 / 黄中 / 红高 / 深红严重 / 灰无事件</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
        {cells.map((cell) => (
          <div
            className="min-w-[2px] flex-1"
            key={cell.index}
            style={{ backgroundColor: cell.color, opacity: cell.event ? 0.92 : 0.32 }}
            title={cell.event ? `${formatPortfolioTime(cell.event.time)} ${cell.event.title} | 风险分 ${cell.event.risk_score}` : `K ${cell.index}: 无事件`}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>{range.start}</span>
        <span>{Math.min(range.end, maxIndex)}</span>
      </div>
    </div>
  );
}

function PortfolioEventStackPopover({
  events,
  leftPercent,
  onInspect,
}: {
  events: PortfolioRiskEvent[];
  leftPercent: number;
  onInspect: (event: PortfolioRiskEvent) => void;
}) {
  return (
    <div
      className="risk-scroll absolute z-50 max-h-56 w-[320px] max-w-[calc(100vw-2rem)] -translate-x-1/2 overflow-y-auto overscroll-contain rounded-lg border border-blue-100 bg-white p-2 font-sans text-[13px] leading-normal tracking-normal shadow-2xl"
      data-no-chart-wheel="true"
      onMouseDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
      style={{ left: `${clampNumber(leftPercent, 12, 88)}%`, top: "72px" }}
    >
      {events.map((event) => {
        const tone = resolvePortfolioRiskTone(event);
        return (
          <button
            className="group flex h-10 w-full min-w-0 cursor-pointer items-center gap-2 rounded-md px-3 text-left transition-colors duration-150 hover:bg-slate-50"
            key={event.id}
            onClick={() => onInspect(event)}
            type="button"
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: tone.marker }} />
            <span className="shrink-0 whitespace-nowrap text-xs font-medium text-slate-400">{formatPortfolioTime(event.time)}</span>
            <span className="min-w-0 flex-1 truncate whitespace-nowrap text-xs font-semibold text-slate-700 group-hover:text-slate-950">{cleanPortfolioText(event.title)}</span>
          </button>
        );
      })}
    </div>
  );
}

function PortfolioEventBanner({
  event,
  onClose,
  onViewAnalysis,
}: {
  event: PortfolioRiskEvent | null;
  onClose: () => void;
  onViewAnalysis: (event: PortfolioRiskEvent) => void;
}) {
  if (!event) return null;
  const tone = resolvePortfolioRiskTone(event);
  return (
    <div className={`mt-2 flex h-12 min-w-0 items-center gap-3 rounded-lg border px-3 shadow-sm ${tone.border} ${tone.bg} ${tone.text}`}>
      <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-bold ${tone.badge}`}>{formatPortfolioEventLevel(event)}</span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="min-w-0 flex-1 truncate text-sm font-bold">{cleanPortfolioText(event.title)}</h3>
          <span className="hidden shrink-0 text-xs font-semibold text-slate-600 md:inline">{event.risk_type || "综合风险"}</span>
          <span className="shrink-0 text-xs font-semibold">风险分: {event.risk_score}</span>
        </div>
      </div>
      <button
        className={`shrink-0 rounded-md border bg-white px-2.5 py-1.5 text-xs font-bold ${tone.border} ${tone.softText} ${tone.hover}`}
        onClick={() => onViewAnalysis(event)}
        type="button"
      >
        AI 分析
      </button>
      <button aria-label="关闭事件提示" className={`shrink-0 rounded-md px-2 text-lg leading-6 ${tone.softText} ${tone.hover}`} onClick={onClose} type="button">
        x
      </button>
    </div>
  );
}

function PortfolioEventAnalysisModal({
  event,
  onClose,
  snapshot,
}: {
  event: PortfolioRiskEvent;
  onClose: () => void;
  snapshot: CoinRiskSnapshot | null;
}) {
  const tone = resolvePortfolioRiskTone(event);
  const title = cleanPortfolioText(event.title || "未命名风险事件");
  const summary = cleanPortfolioText(event.summary || event.ai_summary || "暂无事件简析。");
  const evidence = cleanPortfolioText(event.evidence || "暂无结构化证据。");
  const evidenceRefs = snapshot?.evidence_refs?.map(formatPortfolioEvidenceRef).filter(Boolean).slice(0, 4) || [];
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/50 p-4" onMouseDown={onClose}>
      <section className="max-h-[88vh] w-full max-w-3xl overflow-hidden rounded-lg bg-white shadow-2xl shadow-slate-950/20" onMouseDown={(modalEvent) => modalEvent.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-blue-100 bg-white px-5 py-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-blue-600">AI Event Analysis</p>
            <h2 className="mt-1 text-xl font-bold text-slate-950">事件风险分析</h2>
          </div>
          <button className="rounded-md border border-blue-100 bg-white px-3 py-1 text-sm font-bold text-slate-500 hover:bg-blue-50" onClick={onClose} type="button">
            x
          </button>
        </header>
        <div className="risk-scroll max-h-[calc(88vh-84px)] overflow-y-auto overscroll-contain p-5">
          <div className={`rounded-lg border p-4 ${tone.border} ${tone.bg}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-md px-2 py-1 text-xs font-bold ${tone.badge}`}>{formatPortfolioEventLevel(event)}</span>
              <span className={`text-xs font-bold ${tone.softText}`}>风险分 {event.risk_score}/100</span>
              <span className="text-xs font-semibold text-slate-500">{formatPortfolioTime(event.time)}</span>
            </div>
            <h3 className="mt-3 text-lg font-bold leading-7 text-slate-950">{title}</h3>
            <p className="mt-2 text-sm leading-6 text-slate-700">{summary}</p>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <TextBlock title="风险类别" text={event.risk_type || "综合风险"} />
            <TextBlock title="匹配原因" text={cleanPortfolioText(event.matched_reason || "基于当前币种相关新闻关联。")} />
            <TextBlock title="AI 简析" text={cleanPortfolioText(event.ai_summary || snapshot?.ai_summary || "相关新闻不足，主要基于行情波动分析。")} />
            <TextBlock title="持仓建议" text={cleanPortfolioText(event.ai_advice || snapshot?.ai_advice || "建议保持观察，结合自身仓位设置预警阈值。")} />
          </div>
          <div className="mt-4 rounded-lg border border-blue-100 bg-slate-50 px-4 py-3">
            <p className="text-xs font-bold text-slate-500">证据句</p>
            <p className="mt-2 text-sm leading-6 text-slate-700">{evidence}</p>
          </div>
          {evidenceRefs.length ? (
            <div className="mt-4 rounded-lg border border-blue-100 bg-white p-4">
              <p className="text-xs font-bold text-slate-500">币种风险快照依据</p>
              <ul className="mt-3 space-y-2">
                {evidenceRefs.map((ref, index) => (
                  <li className="rounded-lg bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700" key={`${ref}-${index}`}>
                    <span className="mr-2 font-bold text-emerald-700">依据 {String(index + 1).padStart(2, "0")}</span>
                    {ref}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {event.source_url ? (
            <a className="mt-4 inline-flex h-9 items-center rounded-lg border border-blue-100 bg-white px-3 text-sm font-bold text-blue-700 hover:bg-blue-50" href={event.source_url} rel="noreferrer" target="_blank">
              查看新闻来源
            </a>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function RelatedNewsSection({ items, selectedSymbol }: { items: PortfolioNewsItem[]; selectedSymbol: string }) {
  return (
    <section className="risk-card rounded-lg">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-blue-100 px-4 py-4 sm:px-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-blue-600">Related News</p>
          <h2 className="mt-1 text-lg font-bold text-slate-950">{selectedSymbol || "--"} 相关新闻与证据</h2>
        </div>
        <span className="rounded-lg border border-blue-100 bg-white px-3 py-2 text-xs font-bold text-slate-600">
          {items.length} 条
        </span>
      </div>
      <div className="grid gap-3 p-4 sm:p-5 lg:grid-cols-2">
        {items.length ? items.slice(0, 8).map((item) => (
          <article key={item.news_id} className="rounded-lg border border-blue-100 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-blue-50 px-2 py-1 text-xs font-bold text-blue-700">{formatPortfolioRiskType(item.risk_type || "综合风险")}</span>
                  <span className="text-xs font-semibold text-slate-400">{item.published_at || "--"}</span>
                </div>
                <Link
                  href={`/news/${encodeURIComponent(item.news_id)}?returnTo=${encodeURIComponent("/portfolio")}`}
                  className="line-clamp-2 text-sm font-bold leading-6 text-slate-950 transition-colors duration-200 hover:text-blue-700"
                >
                  {item.title || "未命名新闻"}
                </Link>
              </div>
              <span className="text-2xl font-bold text-rose-600">{item.risk_score}</span>
            </div>
            <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-600">{item.summary || item.content || "暂无简析。"}</p>
            <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2">
              <p className="text-xs font-bold text-slate-500">证据句</p>
              <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-700">{item.evidence || item.matched_reason || "暂无结构化证据。"}</p>
            </div>
          </article>
        )) : (
          <div className="col-span-full rounded-lg border border-dashed border-blue-200 bg-blue-50/70 p-6 text-center text-sm font-semibold text-slate-600">
            当前币种相关新闻不足，AI 风险分析将主要基于行情波动和持仓敞口。
          </div>
        )}
      </div>
    </section>
  );
}

function AddSymbolModal({
  candidates,
  form,
  onChange,
  onClose,
  onSubmit,
}: {
  candidates: PortfolioCoinCandidate[];
  form: AddFormState;
  onChange: (value: AddFormState) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const normalizedFormSymbol = form.symbol.trim() ? normalizeInputSymbol(form.symbol) : "";
  const selectedCandidate = candidates.some((item) => item.symbol === normalizedFormSymbol) ? normalizedFormSymbol : "";

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-950/40 p-4" onMouseDown={onClose}>
      <form
        className="w-full max-w-md rounded-lg border border-blue-100 bg-white p-5 shadow-2xl shadow-slate-900/20"
        onMouseDown={(event) => event.stopPropagation()}
        onSubmit={onSubmit}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-700">Add Asset</p>
            <h2 className="mt-1 text-xl font-bold text-slate-950">添加风险资产</h2>
          </div>
          <button className="rounded-md border border-blue-100 bg-white px-2 py-1 text-sm font-bold text-slate-500 hover:bg-blue-50" type="button" onClick={onClose}>
            x
          </button>
        </div>
        <div className="mt-5 space-y-3">
          <label className="block">
            <span className="text-xs font-bold text-slate-500">币种风险榜</span>
            <select
              className="mt-1 h-10 w-full rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-emerald-300"
              onChange={(event) => onChange({ ...form, symbol: event.target.value })}
              value={selectedCandidate}
            >
              <option value="">从榜单选择币种</option>
              {candidates.map((candidate) => (
                <option key={candidate.symbol} value={candidate.symbol}>
                  {candidate.symbol} · {candidate.name}{candidate.score !== undefined ? ` · 风险分 ${Math.round(candidate.score)}` : ""}{candidate.newsCount !== undefined ? ` · ${candidate.newsCount} 条新闻` : ""}
                </option>
              ))}
            </select>
          </label>
          <PortfolioInput label="币种代码" placeholder="BTC / ETH / SOL / BTCUSDT" value={form.symbol} onChange={(value) => onChange({ ...form, symbol: value })} textMode />
          <label className="flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-slate-50 px-3 py-2 text-sm font-bold text-slate-700">
            是否模拟持有
            <input
              checked={form.isHolding}
              className="h-4 w-4 accent-emerald-700"
              onChange={(event) => onChange({ ...form, isHolding: event.target.checked })}
              type="checkbox"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <PortfolioInput label="持有数量" value={form.amount} onChange={(value) => onChange({ ...form, amount: value })} />
            <PortfolioInput label="买入均价" value={form.avgBuyPrice} onChange={(value) => onChange({ ...form, avgBuyPrice: value })} />
          </div>
          <PortfolioInput label="风险预警阈值" value={form.alertThreshold} onChange={(value) => onChange({ ...form, alertThreshold: value })} />
        </div>
        <button className="mt-5 h-11 w-full rounded-lg bg-blue-600 text-sm font-bold text-white hover:bg-blue-700" type="submit">
          添加到风险雷达
        </button>
      </form>
    </div>
  );
}

function PortfolioInput({
  label,
  onChange,
  placeholder,
  textMode = false,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  placeholder?: string;
  textMode?: boolean;
  value: string;
}) {
  return (
    <label className="block">
      <span className="text-xs font-bold text-slate-500">{label}</span>
      <input
        className="mt-1 h-10 w-full rounded-lg border border-blue-100 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition-colors duration-200 hover:bg-blue-50 focus:border-emerald-300"
        inputMode={textMode ? "text" : "decimal"}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        type={textMode ? "text" : "number"}
        value={value}
      />
    </label>
  );
}

function PortfolioMetric({ helper, label, value }: { helper?: string; label: string; value: string }) {
  return (
    <div className="rounded-lg border border-blue-100 bg-white px-4 py-3">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-bold text-slate-950">{value}</p>
      {helper ? <p className="mt-1 text-xs text-slate-400">{helper}</p> : null}
    </div>
  );
}

function InfoTile({ label, tone, value }: { label: string; tone?: "up" | "down"; value: string }) {
  const toneClass = tone === "up" ? "text-emerald-600" : tone === "down" ? "text-red-600" : "text-slate-950";
  return (
    <div className="rounded-lg border border-blue-100 bg-white px-3 py-3">
      <p className="text-xs font-bold text-slate-500">{label}</p>
      <p className={`mt-1 truncate text-sm font-bold ${toneClass}`}>{value}</p>
    </div>
  );
}

function TextBlock({ text, title }: { text: string; title: string }) {
  return (
    <div className="rounded-lg border border-blue-100 bg-slate-50 px-3 py-3">
      <p className="text-xs font-bold text-slate-500">{title}</p>
      <p className="mt-1 text-sm leading-6 text-slate-700">{text}</p>
    </div>
  );
}

function EmptyPortfolio({ onAdd }: { onAdd: () => void }) {
  return (
    <section className="risk-card flex min-h-[420px] items-center justify-center rounded-lg p-6">
      <div className="max-w-md text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
          <RadarIcon />
        </div>
        <h2 className="mt-4 text-xl font-bold text-slate-950">还没有自选风险资产</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">添加 BTC、ETH、SOL 等币种后，可以查看实时行情、相关新闻和持仓风险建议。</p>
        <button className="mt-5 h-10 rounded-lg bg-blue-600 px-4 text-sm font-bold text-white hover:bg-blue-700" type="button" onClick={onAdd}>
          添加币种
        </button>
      </div>
    </section>
  );
}

function LoadingPanel({ compact = false, text }: { compact?: boolean; text: string }) {
  return (
    <div className={`flex items-center justify-center rounded-lg border border-blue-100 bg-white text-sm font-bold text-slate-500 ${compact ? "h-[340px]" : "min-h-[360px]"}`}>
      <span className="mr-2 h-2 w-2 animate-pulse rounded-full bg-emerald-600" />
      {text}
    </div>
  );
}

function Notice({ text, tone }: { text: string; tone: "red" | "amber" }) {
  const style = tone === "red" ? "border-red-100 bg-red-50 text-red-700" : "border-amber-100 bg-amber-50 text-amber-700";
  return <div className={`rounded-lg border px-4 py-3 text-sm font-semibold ${style}`}>{text}</div>;
}

function RiskBadge({ level, score }: { level: PortfolioRiskLevel; score: number }) {
  const style = riskLevelStyle(level);
  return (
    <span className={`inline-flex shrink-0 items-center rounded-lg border px-2.5 py-1 text-xs font-bold ${style}`}>
      {formatRiskLevel(level)} {score ? `${score}` : "--"}
    </span>
  );
}

function CoinAvatar({ symbol }: { symbol: string }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-emerald-700 text-xs font-bold text-white">
      {symbol.slice(0, 1)}
    </span>
  );
}

function riskLevelStyle(level: PortfolioRiskLevel) {
  if (level === "critical") return "border-red-300 bg-red-900 text-white";
  if (level === "high") return "border-red-200 bg-red-50 text-red-700";
  if (level === "medium") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-emerald-200 bg-emerald-50 text-emerald-700";
}

function formatRiskLevel(level: PortfolioRiskLevel) {
  const labels: Record<PortfolioRiskLevel, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    critical: "严重",
  };
  return labels[level];
}

function buildPortfolioRiskEvents(
  newsItems: PortfolioNewsItem[],
  candles: PortfolioMarketCandle[],
  snapshot: CoinRiskSnapshot | null
): PortfolioRiskEvent[] {
  if (!candles.length) return [];
  return newsItems.slice(0, 24).map((item, index) => {
    const riskScore = clampNumber(Math.round(item.risk_score || snapshot?.risk_score || 0), 0, 100);
    const candleIndex = findNearestPortfolioCandleIndex(candles, item.published_at, index, newsItems.length);
    return {
      ai_advice: snapshot?.ai_advice || "建议结合持仓比例设置预警阈值，并持续关注后续官方进展。",
      ai_summary: item.summary || snapshot?.ai_summary || "相关新闻不足，主要基于行情波动分析。",
      candle_index: candleIndex,
      evidence: item.evidence || item.content || "",
      id: item.news_id || `${item.title}-${index}`,
      matched_reason: item.matched_reason || "新闻内容与当前币种存在关联。",
      risk_level: item.risk_level || snapshot?.risk_level || inferPortfolioRiskLevel(riskScore),
      risk_score: riskScore,
      risk_type: formatPortfolioRiskType(item.risk_type || snapshot?.main_risk_types?.[0] || "综合风险"),
      source_url: item.source_url || "",
      summary: item.summary || item.content || "",
      time: item.published_at || String(candles[candleIndex]?.open_time || ""),
      title: item.title || "未命名风险事件",
    };
  }).sort((a, b) => a.candle_index - b.candle_index || b.risk_score - a.risk_score);
}

function findNearestPortfolioCandleIndex(candles: PortfolioMarketCandle[], publishedAt: string, order: number, total: number) {
  if (!candles.length) return 0;
  const publishedTime = Date.parse(publishedAt || "");
  if (Number.isFinite(publishedTime)) {
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    candles.forEach((candle, index) => {
      const distance = Math.abs(candle.open_time - publishedTime);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });
    return nearestIndex;
  }
  const spacing = Math.max(3, Math.floor(candles.length / Math.max(2, total + 1)));
  return clampNumber(candles.length - 1 - order * spacing, 0, candles.length - 1);
}

function buildPortfolioCoinCandidates(rankingItems: CoinRankingItem[], watchlist: PortfolioWatchlistItem[]): PortfolioCoinCandidate[] {
  const currentSymbols = new Set(watchlist.map((item) => item.symbol));
  const defaults: PortfolioCoinCandidate[] = [
    { name: "Bitcoin", symbol: "BTCUSDT" },
    { name: "Ethereum", symbol: "ETHUSDT" },
    { name: "Solana", symbol: "SOLUSDT" },
    { name: "BNB", symbol: "BNBUSDT" },
    { name: "XRP", symbol: "XRPUSDT" },
    { name: "Dogecoin", symbol: "DOGEUSDT" },
    { name: "Cardano", symbol: "ADAUSDT" },
    { name: "Toncoin", symbol: "TONUSDT" },
    { name: "Chainlink", symbol: "LINKUSDT" },
    { name: "Avalanche", symbol: "AVAXUSDT" },
    { name: "TRON", symbol: "TRXUSDT" },
    { name: "Polkadot", symbol: "DOTUSDT" },
    { name: "Uniswap", symbol: "UNIUSDT" },
    { name: "Arbitrum", symbol: "ARBUSDT" },
    { name: "Optimism", symbol: "OPUSDT" },
    { name: "Aptos", symbol: "APTUSDT" },
  ];
  const bySymbol = new Map<string, PortfolioCoinCandidate & { order: number }>();
  defaults.forEach((item, index) => {
    bySymbol.set(item.symbol, { ...item, order: 10_000 + index });
  });
  rankingItems.forEach((item, index) => {
    const symbol = normalizeInputSymbol(item.symbol);
    bySymbol.set(symbol, {
      name: item.name || symbol.replace(/USDT$/, ""),
      newsCount: item.news_count,
      order: index,
      riskLevel: item.risk_level,
      score: item.final_score,
      symbol,
    });
  });
  watchlist.forEach((item, index) => {
    if (!bySymbol.has(item.symbol)) {
      bySymbol.set(item.symbol, {
        name: item.base_asset || item.symbol.replace(/USDT$/, ""),
        order: 20_000 + index,
        riskLevel: item.risk_level,
        score: item.risk_score,
        symbol: item.symbol,
      });
    }
  });
  return [...bySymbol.values()]
    .sort((a, b) => {
      const aAdded = currentSymbols.has(a.symbol) ? 1 : 0;
      const bAdded = currentSymbols.has(b.symbol) ? 1 : 0;
      return aAdded - bAdded || a.order - b.order || a.symbol.localeCompare(b.symbol);
    })
    .map((item) => ({
      name: item.name,
      newsCount: item.newsCount,
      riskLevel: item.riskLevel,
      score: item.score,
      symbol: item.symbol,
    }));
}

function resolvePortfolioRiskTone(event: PortfolioRiskEvent): PortfolioRiskTone {
  const level = `${event.risk_level || ""}`.toLowerCase();
  if (level.includes("critical") || level.includes("严重")) return portfolioRiskTones.critical;
  if (level.includes("high") || level.includes("高")) return portfolioRiskTones.high;
  if (level.includes("medium") || level.includes("mid") || level.includes("中")) return portfolioRiskTones.medium;
  if (level.includes("low") || level.includes("低")) return portfolioRiskTones.low;
  if (event.risk_score >= 85) return portfolioRiskTones.critical;
  if (event.risk_score >= 70) return portfolioRiskTones.high;
  if (event.risk_score >= 40) return portfolioRiskTones.medium;
  return portfolioRiskTones.low;
}

function inferPortfolioRiskLevel(score: number): PortfolioRiskLevel {
  if (score >= 85) return "critical";
  if (score >= 70) return "high";
  if (score >= 40) return "medium";
  return "low";
}

function formatPortfolioRiskType(value: string) {
  const raw = `${value || ""}`.trim();
  if (!raw) return "综合风险";
  const normalized = raw.toLowerCase();
  if (normalized.includes("hack") || normalized.includes("exploit") || normalized.includes("attack") || normalized.includes("漏洞")) return "链上漏洞 / 攻击风险";
  if (normalized.includes("fraud") || normalized.includes("scam") || normalized.includes("rug") || normalized.includes("诈骗")) return "诈骗 / Rug Pull 风险";
  if (normalized.includes("exchange") || normalized.includes("cex") || normalized.includes("交易所")) return "交易所与流动性风险";
  if (normalized.includes("stable") || normalized.includes("depeg") || normalized.includes("脱锚")) return "稳定币脱锚风险";
  if (normalized.includes("regulat") || normalized.includes("sec") || normalized.includes("监管")) return "监管合规风险";
  if (normalized.includes("market") || normalized.includes("price") || normalized.includes("whale") || normalized.includes("价格") || normalized.includes("巨鲸")) return "市场波动风险";
  if (raw.includes("_") || raw.includes(":")) return "综合风险";
  return raw;
}

function cleanPortfolioText(value: string) {
  return `${value || ""}`
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function formatPortfolioEvidenceRef(value: string) {
  const cleaned = cleanPortfolioText(value)
    .replace(/^[a-f0-9]{8,}:\s*/i, "")
    .replace(/^news[_-]?[a-z0-9-]+:\s*/i, "");
  return cleaned || "";
}

function formatPortfolioEventLevel(event: PortfolioRiskEvent) {
  const tone = resolvePortfolioRiskTone(event);
  if (tone === portfolioRiskTones.critical) return "严重风险";
  if (tone === portfolioRiskTones.high) return "高风险";
  if (tone === portfolioRiskTones.medium) return "中风险";
  return "低风险";
}

function clampPortfolioRange(range: PortfolioChartRange, maxIndex: number): PortfolioChartRange {
  const end = Math.max(0, Math.min(maxIndex, Math.max(range.start, range.end)));
  const start = Math.max(0, Math.min(end, Math.min(range.start, range.end)));
  return { end, start };
}

function portfolioRangeForPreset(candles: PortfolioMarketCandle[], anchor: number, size: number): PortfolioChartRange {
  const maxIndex = Math.max(0, candles.length - 1);
  if (!size || size >= candles.length) return { end: maxIndex, start: 0 };
  const end = clampNumber(anchor, 0, maxIndex);
  return { end, start: Math.max(0, end - size + 1) };
}

function latestPortfolioRangeForMode(
  candles: PortfolioMarketCandle[],
  previous: PortfolioChartRange,
  mode: PortfolioChartFollowMode
): PortfolioChartRange {
  const maxIndex = Math.max(0, candles.length - 1);
  if (mode.kind === "preset") return portfolioRangeForPreset(candles, maxIndex, mode.candles);
  return { end: maxIndex, start: Math.min(previous.start, maxIndex) };
}

function portfolioCandleX(index: number, count: number, width = portfolioChartSpec.width, paddingX = portfolioChartSpec.paddingX) {
  if (count <= 1) return width / 2;
  return paddingX + (index / (count - 1)) * (width - paddingX * 2);
}

function getPortfolioPriceRange(candles: PortfolioMarketCandle[]) {
  if (!candles.length) return { max: 1, min: 0 };
  const min = Math.min(...candles.map((item) => item.low));
  const max = Math.max(...candles.map((item) => item.high));
  const span = max - min || Math.max(max, 1) * 0.01;
  return { max: max + span * 0.04, min: min - span * 0.04 };
}

function portfolioPriceY(price: number, min: number, max: number, top = portfolioChartSpec.priceTop, bottom = portfolioChartSpec.priceBottom) {
  const span = max - min || Math.max(max, 1) * 0.01;
  return top + ((max - price) / span) * (bottom - top);
}

function portfolioMovingAverage(candles: PortfolioMarketCandle[], period: number) {
  return candles.map((_, index) => {
    if (index < period - 1) return null;
    const window = candles.slice(index - period + 1, index + 1);
    return window.reduce((sum, item) => sum + item.close, 0) / period;
  });
}

function buildPortfolioMovingAveragePath(values: Array<number | null>, range: PortfolioChartRange, min: number, max: number) {
  const commands: string[] = [];
  const count = range.end - range.start + 1;
  for (let index = range.start; index <= range.end; index += 1) {
    const value = values[index];
    if (value === null || value === undefined) continue;
    const x = portfolioCandleX(index - range.start, count);
    const y = portfolioPriceY(value, min, max);
    commands.push(`${commands.length ? "L" : "M"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return commands.join(" ");
}

function portfolioMainCandleWidth(count: number) {
  const drawable = portfolioChartSpec.width - portfolioChartSpec.paddingX * 2;
  const step = count <= 1 ? drawable : drawable / Math.max(1, count - 1);
  return Math.max(1.4, Math.min(11, step * 0.58));
}

function portfolioMiniCandleWidth(count: number) {
  const drawable = portfolioMiniChartSpec.width - portfolioMiniChartSpec.paddingX * 2;
  const step = count <= 1 ? drawable : drawable / Math.max(1, count - 1);
  return Math.max(0.8, Math.min(4, step * 0.56));
}

function portfolioMiniPriceY(price: number, min: number, max: number) {
  return portfolioPriceY(price, min, max, portfolioMiniChartSpec.top, portfolioMiniChartSpec.bottom);
}

function portfolioVolumeHeight(volume: number, maxVolume: number) {
  if (!maxVolume) return 0;
  return Math.max(1, (volume / maxVolume) * (portfolioChartSpec.volumeBottom - portfolioChartSpec.volumeTop));
}

function renderPortfolioMiniCandles(candles: PortfolioMarketCandle[]) {
  if (!candles.length) return null;
  const range = getPortfolioPriceRange(candles);
  const bodyWidth = portfolioMiniCandleWidth(candles.length);
  return candles.map((candle, index) => {
    const x = portfolioCandleX(index, candles.length, portfolioMiniChartSpec.width, portfolioMiniChartSpec.paddingX);
    const up = candle.close >= candle.open;
    const color = up ? "#16a34a" : "#dc2626";
    const yHigh = portfolioMiniPriceY(candle.high, range.min, range.max);
    const yLow = portfolioMiniPriceY(candle.low, range.min, range.max);
    const yOpen = portfolioMiniPriceY(candle.open, range.min, range.max);
    const yClose = portfolioMiniPriceY(candle.close, range.min, range.max);
    const bodyY = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(1, Math.abs(yOpen - yClose));
    return (
      <g key={`${candle.id || candle.open_time}-${index}`}>
        <line stroke={color} strokeWidth="1" x1={x} x2={x} y1={yHigh} y2={yLow} />
        <rect fill={color} height={bodyHeight} opacity="0.72" rx="0.6" width={bodyWidth} x={x - bodyWidth / 2} y={bodyY} />
      </g>
    );
  });
}

function createPortfolioClusters(events: PortfolioRiskEvent[], range: PortfolioChartRange) {
  const count = range.end - range.start + 1;
  const visible = events
    .filter((event) => event.candle_index >= range.start && event.candle_index <= range.end)
    .map((event) => ({
      event,
      x: portfolioCandleX(event.candle_index - range.start, count),
    }))
    .sort((a, b) => a.x - b.x);

  const groups: Array<{ events: PortfolioRiskEvent[]; x: number }> = [];
  visible.forEach((item) => {
    const last = groups[groups.length - 1];
    if (last && item.x - last.x < 22) {
      last.events.push(item.event);
      last.x = (last.x * (last.events.length - 1) + item.x) / last.events.length;
    } else {
      groups.push({ events: [item.event], x: item.x });
    }
  });
  return groups;
}

function getDominantPortfolioEvent(events: PortfolioRiskEvent[]) {
  return events.reduce((selected, event) => event.risk_score > selected.risk_score ? event : selected, events[0]);
}

function formatPortfolioTime(value: number | string) {
  if (!value) return "--";
  const normalizedValue = typeof value === "string" && /^\d+$/.test(value) ? Number(value) : value;
  const date = typeof normalizedValue === "number" ? new Date(normalizedValue) : new Date(normalizedValue);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
  });
}

function formatUsdt(value: number) {
  if (!Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 1000) {
    return `${value.toLocaleString("en-US", { maximumFractionDigits: 2 })} USDT`;
  }
  return `${value.toLocaleString("en-US", { maximumFractionDigits: value >= 1 ? 2 : 6 })} USDT`;
}

function portfolioTradeStorageKey(symbol: string) {
  return `cryptorisk.portfolio-trades:${normalizeInputSymbol(symbol)}`;
}

function readCachedPortfolioCoinCandidates(): CoinRankingItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.sessionStorage.getItem(portfolioCoinCandidateCacheKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { items?: CoinRankingItem[] };
    return Array.isArray(parsed.items) ? parsed.items : [];
  } catch {
    return [];
  }
}

function writeCachedPortfolioCoinCandidates(items: CoinRankingItem[]) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(portfolioCoinCandidateCacheKey, JSON.stringify({ items, updatedAt: Date.now() }));
  } catch {
    // Ignore session storage failures; the page can still fetch candidates.
  }
}

function isActivePortfolioRefreshJob(job: PortfolioRefreshJob | null) {
  return Boolean(job && (job.status === "queued" || job.status === "running"));
}

function readStoredPortfolioRefreshJobId() {
  if (typeof window === "undefined") return "";
  return window.sessionStorage.getItem(portfolioRefreshJobStorageKey) || "";
}

function storePortfolioRefreshJobId(jobId: string) {
  if (typeof window === "undefined" || !jobId) return;
  window.sessionStorage.setItem(portfolioRefreshJobStorageKey, jobId);
}

function clearStoredPortfolioRefreshJobId() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(portfolioRefreshJobStorageKey);
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function readPortfolioTradeMarkers(symbol: string): PortfolioTradeMarker[] {
  if (typeof window === "undefined" || !symbol) return [];
  try {
    const raw = window.localStorage.getItem(portfolioTradeStorageKey(symbol));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as PortfolioTradeMarker[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item) => item && item.symbol === normalizeInputSymbol(symbol) && ["buy", "sell"].includes(item.side))
      .map((item) => ({
        candle_index: Number(item.candle_index) || 0,
        id: String(item.id || `${item.symbol}:${item.time}:${item.side}`),
        price: Number(item.price) || 0,
        quantity: Number(item.quantity) || 0,
        side: item.side,
        symbol: normalizeInputSymbol(item.symbol),
        time: String(item.time || ""),
      }));
  } catch {
    return [];
  }
}

function writePortfolioTradeMarkers(symbol: string, markers: PortfolioTradeMarker[]) {
  if (typeof window === "undefined" || !symbol) return;
  try {
    window.localStorage.setItem(portfolioTradeStorageKey(symbol), JSON.stringify(markers));
  } catch {
    // Local marker persistence is best effort; holding state is still saved through the API.
  }
}

function clearPortfolioTradeMarkers(symbol: string) {
  if (typeof window === "undefined" || !symbol) return;
  try {
    window.localStorage.removeItem(portfolioTradeStorageKey(symbol));
  } catch {
    // Ignore storage failures.
  }
}

function formatNumber(value: number, digits = 6) {
  if (!Number.isFinite(value)) return "--";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatPlainNumber(value: number) {
  if (!Number.isFinite(value)) return "";
  return Number(value.toFixed(10)).toString();
}

function formatPercent(value: number) {
  if (!Number.isFinite(value)) return "--";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function toNumber(value: string, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function normalizeInputSymbol(symbol: string) {
  const compact = symbol.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  return compact.endsWith("USDT") ? compact : `${compact}USDT`;
}

function formatNow() {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function IconSvg({ children }: { children: ReactNode }) {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
}

function PlusIcon() { return <IconSvg><path d="M12 5v14" /><path d="M5 12h14" /></IconSvg>; }
function RefreshIcon() { return <IconSvg><path d="M20 12a8 8 0 1 1-2.3-5.7" /><path d="M20 4v6h-6" /></IconSvg>; }
function RadarIcon() { return <IconSvg><circle cx="12" cy="12" r="9" /><path d="M12 7v5l4 2" /><path d="M12 12 6 9" /></IconSvg>; }
function TrashIcon() { return <IconSvg><path d="M3 6h18" /><path d="M8 6V4h8v2" /><path d="M6 6l1 14h10l1-14" /><path d="M10 11v5" /><path d="M14 11v5" /></IconSvg>; }
