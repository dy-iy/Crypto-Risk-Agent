"use client";

import {
  Dispatch,
  FormEvent,
  MouseEvent as ReactMouseEvent,
  ReactNode,
  SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  buySim,
  fetchSimCandles,
  fetchSimEvents,
  fetchSimState,
  fetchSimSymbols,
  jumpSim,
  nextSimStep,
  resetSim,
  sellSim,
  SimCandle,
  SimPosition,
  SimRiskEvent,
  SimState,
  SimSymbol,
  SimTrade,
} from "@/lib/api";

const defaultSymbols: SimSymbol[] = [
  { symbol: "BTCUSDT", base_symbol: "BTC", name: "Bitcoin" },
  { symbol: "ETHUSDT", base_symbol: "ETH", name: "Ethereum" },
  { symbol: "BNBUSDT", base_symbol: "BNB", name: "BNB" },
  { symbol: "SOLUSDT", base_symbol: "SOL", name: "Solana" },
  { symbol: "XRPUSDT", base_symbol: "XRP", name: "XRP" },
  { symbol: "DOGEUSDT", base_symbol: "DOGE", name: "Dogecoin" },
  { symbol: "ADAUSDT", base_symbol: "ADA", name: "Cardano" },
  { symbol: "AVAXUSDT", base_symbol: "AVAX", name: "Avalanche" },
  { symbol: "LINKUSDT", base_symbol: "LINK", name: "Chainlink" },
  { symbol: "TRXUSDT", base_symbol: "TRX", name: "TRON" },
];

const playbackSpeeds = [
  { key: "one", label: "1x", intervalMs: 3000 },
  { key: "five", label: "5x", intervalMs: 1200 },
  { key: "ten", label: "10x", intervalMs: 600 },
] as const;

const zoomPresets = [
  { label: "1H", candles: 4 },
  { label: "4H", candles: 16 },
  { label: "1D", candles: 96 },
  { label: "3D", candles: 288 },
  { label: "\u5168\u90e8(7D)", candles: 0 },
];

const labels = {
  title: "CryptoRisk \u6a21\u62df\u4ea4\u6613\u76d8",
  simTime: "\u6a21\u62df\u65f6\u95f4",
  candleIndex: "K\u7ebf\u5e8f\u53f7",
  totalAsset: "\u603b\u8d44\u4ea7",
  returnRate: "\u6536\u76ca\u7387",
  next: "\u4e0b\u4e00\u6b65",
  autoplay: "\u81ea\u52a8\u64ad\u653e",
  pause: "\u6682\u505c",
  reset: "\u91cd\u7f6e",
  speed: "\u64ad\u653e\u901f\u5ea6",
  jumpTime: "\u8df3\u8f6c\u65f6\u95f4",
  jump: "\u8df3\u8f6c",
  currentPrice: "\u5f53\u524d\u4ef7\u683c",
  cash: "\u73b0\u91d1\u4f59\u989d",
  buyAmount: "\u4e70\u5165\u91d1\u989d USDT",
  buy: "\u4e70\u5165",
  sellQuantity: "\u5356\u51fa\u6570\u91cf",
  sell: "\u5356\u51fa",
  sellAll: "\u5168\u90e8\u5356\u51fa",
  currentPosition: "\u5f53\u524d\u6301\u4ed3",
  noNews: "\u5f53\u524d\u6a21\u62df\u65f6\u95f4\u524d\u6682\u65e0\u8be5\u5e01\u79cd\u76f8\u5173\u65b0\u95fb",
  hold: "\u7ee7\u7eed\u6301\u6709",
  sellHalf: "\u5356\u51fa 50%",
  viewAi: "\u67e5\u770b AI \u5206\u6790",
  positions: "\u6211\u7684\u6301\u4ed3",
  trades: "\u4ea4\u6613\u8bb0\u5f55",
  riskEvent: "\u98ce\u9669\u4e8b\u4ef6",
  riskScore: "\u98ce\u9669\u5206",
  affected: "\u5f71\u54cd\u5e01\u79cd",
  summary: "\u6458\u8981",
  analysis: "AI \u5206\u6790",
};

const simTourStorageKey = "cryptorisk_sim_tour_done";
const simTourWelcomeStorageKey = "cryptorisk_sim_tour_seen_welcome";

type TourAction =
  | "switch-symbol"
  | "inspect-event"
  | "view-ai"
  | "buy"
  | "next-candle"
  | "sell";

type TourStep = {
  title: string;
  body: string;
  task: string;
  targetId: string;
  requiredAction?: TourAction;
};

const beginnerTourSteps: TourStep[] = [
  {
    title: "欢迎来到 CryptoRisk 模拟交易盘",
    body: "这是一个历史行情回放实验，不是真实交易，也不是投资建议。你会用 10000 USDT 的模拟资金，观察新闻风险如何影响价格和自己的决策。",
    task: "先了解这次实验的目标，然后点击下一步。",
    targetId: "sim-shell",
  },
  {
    title: "先看账户状态",
    body: "这里显示模拟时间、K 线序号、总资产和收益率。总资产等于现金加持仓市值；收益率只是结果，不代表风险控制一定好。",
    task: "看一眼顶部资产区，确认初始资金和当前模拟时间。",
    targetId: "asset-metrics",
  },
  {
    title: "切换一个币种",
    body: "左侧是 10 个交易对。BTCUSDT 可以理解为用 USDT 计价的 BTC，USDT 在这里就是模拟盘里的美元计价单位。",
    task: "点击任意一个不同的币种，完成后会自动进入下一步。",
    targetId: "symbol-list",
    requiredAction: "switch-symbol",
  },
  {
    title: "认识 K 线主图",
    body: "每一根蜡烛代表 15 分钟。中间较粗的实体表示开盘价和收盘价之间的范围：绿色说明收盘价高于开盘价，红色说明收盘价低于开盘价。上下那根较细的影线表示这 15 分钟内价格曾经到过的最高价和最低价。",
    task: "观察一根蜡烛的粗实体和上下细影线：实体看开收盘，影线看最高和最低，然后点击下一步。",
    targetId: "kline-chart",
  },
  {
    title: "读懂 OHLCV",
    body: "OHLCV 分别是开盘价、最高价、最低价、收盘价和成交量。你买入或卖出的模拟成交价，用的就是当前 K 线的收盘价。",
    task: "把鼠标放到图上移动一下，观察左上角 OHLCV 数值变化。",
    targetId: "ohlcv-readout",
  },
  {
    title: "理解 MA10 / MA30",
    body: "MA 是移动平均线。MA10 是最近 10 根 K 线平均收盘价，MA30 是最近 30 根。它们帮助你判断价格是在短期均线之上还是之下。",
    task: "找到黄线 MA10 和蓝线 MA30，理解它们只是趋势参考。",
    targetId: "ma-readout",
  },
  {
    title: "观察成交量",
    body: "下方柱子是成交量，表示这 15 分钟市场交易是否活跃。新闻冲击出现时，如果成交量放大，说明市场反应更强。",
    task: "观察图表底部成交量柱，然后点击下一步。",
    targetId: "volume-area",
  },
  {
    title: "识别风险事件标记",
    body: "图上的小方块或数字代表新闻风险事件。绿色偏低风险，橙色中风险，红色高风险；数字表示附近聚集了多条新闻。",
    task: "点击一个风险事件标记，完成后会自动进入下一步；也可以跳过此步。",
    targetId: "risk-markers",
    requiredAction: "inspect-event",
  },
  {
    title: "读风险新闻提示条",
    body: "风险分不是涨跌预测，而是市场不确定性提示。分数越高，说明这条新闻更可能引发流动性、情绪或监管层面的波动。",
    task: "查看当前风险提示条，理解它只提醒风险，不保证价格方向。",
    targetId: "risk-banner",
  },
  {
    title: "查看 AI 分析",
    body: "AI 会解释新闻原因、影响币种、价格窗口和操作建议。它不是喊你买卖，而是帮你理解风险来源和可能的传导路径。",
    task: "点击“查看 AI 分析”，完成后会自动进入下一步；也可以跳过此步。",
    targetId: "ai-analysis-button",
    requiredAction: "view-ai",
  },
  {
    title: "完成第一次买入",
    body: "现在试着用少量资金做实验。输入 1000 USDT 并点击买入，系统会按当前 K 线收盘价模拟成交。",
    task: "在买入金额里输入 1000，然后点击买入。买入成功后自动进入下一步。",
    targetId: "buy-area",
    requiredAction: "buy",
  },
  {
    title: "查看现金和持仓变化",
    body: "买入后，现金会减少，当前持仓会增加。持仓市值会随着后续 K 线价格变化而上下波动。",
    task: "观察现金余额和当前持仓，然后点击下一步。",
    targetId: "position-area",
  },
  {
    title: "推进一根 K 线",
    body: "点击下一步会让模拟时间前进 15 分钟。你可以观察价格、总资产和收益率是否变化。",
    task: "点击工具栏里的“下一步”，完成后会自动进入下一步。",
    targetId: "next-button",
    requiredAction: "next-candle",
  },
  {
    title: "尝试卖出或继续持有",
    body: "卖出会按当前收盘价成交；全部卖出会清空当前币种持仓；继续持有意味着你愿意承担后续波动。",
    task: "输入数量卖出，或点击全部卖出。卖出成功后自动进入最后一步；也可以跳过此步。",
    targetId: "sell-area",
    requiredAction: "sell",
  },
  {
    title: "查看复盘报告",
    body: "复盘报告会评价本轮收益、回撤、风险响应和仓位控制。CryptoRisk 关注的不只是赚多少，更是风险决策是否合理。",
    task: "点击复盘报告查看表现，或结束教程后自由练习。",
    targetId: "report-button",
  },
];

/*
const legacyBeginnerTourSteps = [
  {
    title: "欢迎来到 CryptoRisk 模拟交易盘",
    body: "这是一个历史行情回放实验，不是真实交易，也不是投资建议。你会用 10000 USDT 的模拟资金，观察新闻风险如何影响价格和自己的决策。",
    task: "先了解这次实验的目标，然后点击下一步。",
    targetId: "sim-shell",
  },
  {
    title: "先看账户状态",
    body: "这里显示模拟时间、K 线序号、总资产和收益率。总资产等于现金加持仓市值；收益率只是结果，不代表风险控制一定好。",
    task: "看一眼顶部资产区，确认初始资金和当前模拟时间。",
    targetId: "asset-metrics",
  },
  {
    title: "切换一个币种",
    body: "左侧是 10 个交易对。BTCUSDT 可以理解为用 USDT 计价的 BTC，USDT 在这里就是模拟盘里的美元计价单位。",
    task: "点击任意一个不同的币种，完成后会自动进入下一步。",
    targetId: "symbol-list",
    requiredAction: "switch-symbol",
  },
  {
    title: "认识 K 线主图",
    body: "每一根蜡烛代表 15 分钟。绿色通常表示这 15 分钟收盘价高于开盘价，红色表示收盘价低于开盘价。",
    task: "观察红绿蜡烛和上下影线，然后点击下一步。",
    targetId: "kline-chart",
  },
  {
    title: "读懂 OHLCV",
    body: "OHLCV 分别是开盘价、最高价、最低价、收盘价和成交量。你买入或卖出的模拟成交价，用的就是当前 K 线的收盘价。",
    task: "把鼠标放到图上移动一下，观察左上角 OHLCV 数值变化。",
    targetId: "ohlcv-readout",
  },
  {
    title: "理解 MA10 / MA30",
    body: "MA 是移动平均线。MA10 是最近 10 根 K 线平均收盘价，MA30 是最近 30 根。它们帮助你判断价格是在短期均线之上还是之下。",
    task: "找到黄线 MA10 和蓝线 MA30，理解它们只是趋势参考。",
    targetId: "ma-readout",
  },
  {
    title: "观察成交量",
    body: "下方柱子是成交量，表示这 15 分钟市场交易是否活跃。新闻冲击出现时，如果成交量放大，说明市场反应更强。",
    task: "观察图表底部成交量柱，然后点击下一步。",
    targetId: "volume-area",
  },
  {
    title: "识别风险事件标记",
    body: "图上的小方块或数字代表新闻风险事件。绿色偏低风险，橙色中风险，红色高风险；数字表示附近聚集了多条新闻。",
    task: "点击一个风险事件标记，完成后会自动进入下一步；也可以跳过此步。",
    targetId: "risk-markers",
    requiredAction: "inspect-event",
  },
  {
    title: "读风险新闻提示条",
    body: "风险分不是涨跌预测，而是市场不确定性提示。分数越高，说明这条新闻更可能引发流动性、情绪或监管层面的波动。",
    task: "查看当前风险提示条，理解它只提醒风险，不保证价格方向。",
    targetId: "risk-banner",
  },
  {
    title: "查看 AI 分析",
    body: "AI 会解释新闻原因、影响币种、价格窗口和操作建议。它不是喊你买卖，而是帮你理解风险来源和可能的传导路径。",
    task: "点击“查看 AI 分析”，完成后会自动进入下一步；也可以跳过此步。",
    targetId: "ai-analysis-button",
    requiredAction: "view-ai",
  },
  {
    title: "完成第一次买入",
    body: "现在试着用少量资金做实验。输入 1000 USDT 并点击买入，系统会按当前 K 线收盘价模拟成交。",
    task: "在买入金额里输入 1000，然后点击买入。买入成功后自动进入下一步。",
    targetId: "buy-area",
    requiredAction: "buy",
  },
  {
    title: "查看现金和持仓变化",
    body: "买入后，现金会减少，当前持仓会增加。持仓市值会随着后续 K 线价格变化而上下波动。",
    task: "观察现金余额和当前持仓，然后点击下一步。",
    targetId: "position-area",
  },
  {
    title: "推进一根 K 线",
    body: "点击下一步会让模拟时间前进 15 分钟。你可以观察价格、总资产和收益率是否变化。",
    task: "点击工具栏里的“下一步”，完成后会自动进入下一步。",
    targetId: "next-button",
    requiredAction: "next-candle",
  },
  {
    title: "尝试卖出或继续持有",
    body: "卖出会按当前收盘价成交；全部卖出会清空当前币种持仓；继续持有意味着你愿意承担后续波动。",
    task: "输入数量卖出，或点击全部卖出。卖出成功后自动进入最后一步；也可以跳过此步。",
    targetId: "sell-area",
    requiredAction: "sell",
  },
  {
    title: "查看复盘报告",
    body: "复盘报告会评价本轮收益、回撤、风险响应和仓位控制。CryptoRisk 关注的不只是赚多少，更是风险决策是否合理。",
    task: "点击复盘报告查看表现，或结束教程后自由练习。",
    targetId: "report-button",
  },
];
*/

type PlaybackSpeed = (typeof playbackSpeeds)[number]["key"];
type ZoomPreset = (typeof zoomPresets)[number];
type ChartRange = { start: number; end: number };
type ChartFollowMode =
  | { kind: "preset"; label: string; candles: number }
  | { kind: "manual" };
type ZoomDragMode = "start" | "end" | "window";
type ChartHoverPoint = {
  absoluteIndex: number;
  x: number;
  y: number;
  price: number;
};
type AssetSnapshot = { index: number; time: string; totalAsset: number };
type TradeToast = {
  id: number;
  tone: "success" | "error" | "warning";
  title: string;
  body: string;
};
type EventImpact = {
  before1h: number | null;
  after1h: number | null;
  after4h: number | null;
  after24h: number | null;
};

const defaultZoomPreset = zoomPresets[zoomPresets.length - 1];
const defaultChartFollowMode: ChartFollowMode = {
  kind: "preset",
  label: defaultZoomPreset.label,
  candles: defaultZoomPreset.candles,
};

type RiskTone = {
  bg: string;
  border: string;
  badge: string;
  text: string;
  softText: string;
  marker: string;
  markerCluster: string;
  hover: string;
};

const riskTones: Record<"low" | "medium" | "high", RiskTone> = {
  low: {
    bg: "bg-green-50",
    border: "border-green-200",
    badge: "bg-green-600 text-white",
    text: "text-green-950",
    softText: "text-green-700",
    marker: "#16a34a",
    markerCluster: "#15803d",
    hover: "hover:bg-green-100",
  },
  medium: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    badge: "bg-amber-600 text-white",
    text: "text-amber-950",
    softText: "text-amber-700",
    marker: "#d97706",
    markerCluster: "#b45309",
    hover: "hover:bg-amber-100",
  },
  high: {
    bg: "bg-red-50",
    border: "border-red-200",
    badge: "bg-red-600 text-white",
    text: "text-red-950",
    softText: "text-red-700",
    marker: "#dc2626",
    markerCluster: "#991b1b",
    hover: "hover:bg-red-100",
  },
};

function resolveRiskTone(event: SimRiskEvent): RiskTone {
  const rawLevel = `${event.risk_level || ""}`.toLowerCase();
  if (rawLevel.includes("\u4f4e") || rawLevel.includes("low")) return riskTones.low;
  if (rawLevel.includes("\u4e2d") || rawLevel.includes("medium") || rawLevel.includes("mid")) return riskTones.medium;
  if (rawLevel.includes("\u9ad8") || rawLevel.includes("high") || rawLevel.includes("critical")) return riskTones.high;
  if (event.risk_score >= 70) return riskTones.high;
  if (event.risk_score >= 40) return riskTones.medium;
  return getRiskTone({ ...event, risk_level: "" });
}

function getRiskTone(event: SimRiskEvent): RiskTone {
  const rawLevel = `${event.risk_level || ""}`.toLowerCase();
  if (rawLevel.includes("低") || rawLevel.includes("low")) return riskTones.low;
  if (rawLevel.includes("中") || rawLevel.includes("medium") || rawLevel.includes("mid")) return riskTones.medium;
  if (rawLevel.includes("高") || rawLevel.includes("high") || rawLevel.includes("critical")) return riskTones.high;
  if (event.risk_score >= 70) return riskTones.high;
  if (event.risk_score >= 40) return riskTones.medium;
  return riskTones.low;
}

function formatUsdt(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 100 ? 2 : 6,
  }).format(value);
}

function formatNumber(value: number, digits = 6) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function decodeEscapedUnicode(value: string) {
  return value
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)))
    .replace(/\\n/g, "\n");
}

function truncateText(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 3))}...`;
}

function simEventAiContext(event: SimRiskEvent, source: string) {
  return JSON.stringify({
    type: "sim_risk_event",
    page_type: "sim_trading",
    source,
    coin: event.affected_symbols || [],
    title: decodeEscapedUnicode(event.title),
    news_title: decodeEscapedUnicode(event.title),
    risk_level: decodeEscapedUnicode(event.risk_level || ""),
    risk_score: event.risk_score,
    risk_type: decodeEscapedUnicode(event.risk_type || ""),
    summary: decodeEscapedUnicode(event.summary || ""),
    evidence: decodeEscapedUnicode(event.evidence || ""),
    event_time: event.time,
    candle_index: event.candle_index,
  });
}

function upsertAssetSnapshot(history: AssetSnapshot[], state: SimState): AssetSnapshot[] {
  const snapshot = {
    index: state.current_index,
    time: state.sim_time,
    totalAsset: state.total_asset,
  };
  const withoutSameIndex = history.filter((item) => item.index !== snapshot.index);
  return [...withoutSameIndex, snapshot].sort((a, b) => a.index - b.index);
}

function mergeRiskEvents(previous: SimRiskEvent[], next: SimRiskEvent[]) {
  const byId = new Map(previous.map((event) => [event.id, event]));
  next.forEach((event) => byId.set(event.id, event));
  return [...byId.values()].sort((a, b) => (a.candle_index ?? 0) - (b.candle_index ?? 0));
}

function calculateMaxDrawdown(history: AssetSnapshot[]) {
  let peak = history[0]?.totalAsset || 10000;
  let maxDrawdown = 0;
  history.forEach((item) => {
    peak = Math.max(peak, item.totalAsset);
    if (peak > 0) maxDrawdown = Math.min(maxDrawdown, (item.totalAsset - peak) / peak);
  });
  return Math.abs(maxDrawdown);
}

function calculateWinRate(trades: SimState["trade_history"]) {
  const positions = new Map<string, { quantity: number; avgCost: number }>();
  let sellCount = 0;
  let winCount = 0;
  trades.forEach((trade) => {
    const current = positions.get(trade.symbol) || { quantity: 0, avgCost: 0 };
    if (trade.side === "BUY") {
      const nextQuantity = current.quantity + trade.quantity;
      const nextCost = current.quantity * current.avgCost + trade.quantity * trade.price;
      positions.set(trade.symbol, {
        quantity: nextQuantity,
        avgCost: nextQuantity ? nextCost / nextQuantity : 0,
      });
      return;
    }
    sellCount += 1;
    if (current.avgCost && trade.price > current.avgCost) winCount += 1;
    const nextQuantity = Math.max(0, current.quantity - trade.quantity);
    positions.set(trade.symbol, {
      quantity: nextQuantity,
      avgCost: nextQuantity ? current.avgCost : 0,
    });
  });
  return { sellCount, winCount, winRate: sellCount ? winCount / sellCount : 0 };
}

function calculateEventImpact(candles: SimCandle[], candleIndex?: number): EventImpact | null {
  if (candleIndex === undefined || !candles[candleIndex]) return null;
  const base = candles[candleIndex].close;
  const changeFrom = (targetIndex: number) => candles[targetIndex] && base
    ? (candles[targetIndex].close - base) / base
    : null;
  const before = candles[candleIndex - 4] && candles[candleIndex - 4].close
    ? (base - candles[candleIndex - 4].close) / candles[candleIndex - 4].close
    : null;
  return {
    before1h: before,
    after1h: changeFrom(candleIndex + 4),
    after4h: changeFrom(candleIndex + 16),
    after24h: changeFrom(candleIndex + 96),
  };
}

function formatTime(value: string) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toDatetimeLocalValue(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function localDatetimeToIso(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function clampRange(range: ChartRange, maxIndex: number): ChartRange {
  const end = Math.max(0, Math.min(maxIndex, Math.max(range.start, range.end)));
  const start = Math.max(0, Math.min(end, Math.min(range.start, range.end)));
  return { start, end };
}

const chartSpec = {
  width: 640,
  height: 520,
  paddingX: 18,
  priceTop: 68,
  priceBottom: 420,
  volumeTop: 446,
  volumeBottom: 506,
};

const miniChartSpec = {
  width: 640,
  height: 80,
  paddingX: 6,
  top: 8,
  bottom: 58,
};

function candleX(index: number, count: number, width = chartSpec.width, paddingX = chartSpec.paddingX) {
  if (count <= 1) return width / 2;
  return paddingX + (index / (count - 1)) * (width - paddingX * 2);
}

function clampNumber(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function getPriceRange(candles: SimCandle[]) {
  if (!candles.length) return { min: 0, max: 1 };
  const min = Math.min(...candles.map((item) => item.low));
  const max = Math.max(...candles.map((item) => item.high));
  const span = max - min || Math.max(max, 1) * 0.01;
  return { min: min - span * 0.04, max: max + span * 0.04 };
}

function priceY(price: number, min: number, max: number, top = chartSpec.priceTop, bottom = chartSpec.priceBottom) {
  const span = max - min || Math.max(max, 1) * 0.01;
  return top + ((max - price) / span) * (bottom - top);
}

function movingAverage(candles: SimCandle[], period: number) {
  return candles.map((_, index) => {
    if (index < period - 1) return null;
    const window = candles.slice(index - period + 1, index + 1);
    return window.reduce((sum, item) => sum + item.close, 0) / period;
  });
}

function buildMovingAveragePath(values: Array<number | null>, range: ChartRange, min: number, max: number) {
  const commands: string[] = [];
  const count = range.end - range.start + 1;
  for (let index = range.start; index <= range.end; index += 1) {
    const value = values[index];
    if (value === null || value === undefined) continue;
    const x = candleX(index - range.start, count);
    const y = priceY(value, min, max);
    commands.push(`${commands.length ? "L" : "M"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return commands.join(" ");
}

function getDominantEvent(events: SimRiskEvent[]) {
  return events.reduce((selected, event) => event.risk_score > selected.risk_score ? event : selected, events[0]);
}

function mainCandleWidth(count: number) {
  const drawable = chartSpec.width - chartSpec.paddingX * 2;
  const step = count <= 1 ? drawable : drawable / Math.max(1, count - 1);
  return Math.max(1.4, Math.min(11, step * 0.58));
}

function miniCandleWidth(count: number) {
  const drawable = miniChartSpec.width - miniChartSpec.paddingX * 2;
  const step = count <= 1 ? drawable : drawable / Math.max(1, count - 1);
  return Math.max(0.8, Math.min(4, step * 0.56));
}

function miniPriceY(price: number, min: number, max: number) {
  return priceY(price, min, max, miniChartSpec.top, miniChartSpec.bottom);
}

function volumeHeight(volume: number, maxVolume: number) {
  if (!maxVolume) return 0;
  return Math.max(1, (volume / maxVolume) * (chartSpec.volumeBottom - chartSpec.volumeTop));
}

function renderMiniCandles(candles: SimCandle[]) {
  if (!candles.length) return null;
  const range = getPriceRange(candles);
  const bodyWidth = miniCandleWidth(candles.length);
  return candles.map((candle, index) => {
    const x = candleX(index, candles.length, miniChartSpec.width, miniChartSpec.paddingX);
    const up = candle.close >= candle.open;
    const color = up ? "#16a34a" : "#dc2626";
    const yHigh = miniPriceY(candle.high, range.min, range.max);
    const yLow = miniPriceY(candle.low, range.min, range.max);
    const yOpen = miniPriceY(candle.open, range.min, range.max);
    const yClose = miniPriceY(candle.close, range.min, range.max);
    const bodyY = Math.min(yOpen, yClose);
    const bodyHeight = Math.max(1, Math.abs(yOpen - yClose));
    return (
      <g key={`${candle.openTime}-${index}`}>
        <line stroke={color} strokeWidth="1" x1={x} x2={x} y1={yHigh} y2={yLow} />
        <rect fill={color} height={bodyHeight} opacity="0.72" rx="0.6" width={bodyWidth} x={x - bodyWidth / 2} y={bodyY} />
      </g>
    );
  });
}

function rangeForPreset(candles: SimCandle[], anchor: number, size: number): ChartRange {
  const maxIndex = Math.max(0, candles.length - 1);
  if (!size || size >= candles.length) return { start: 0, end: maxIndex };
  const end = clampNumber(anchor, 0, maxIndex);
  return { start: Math.max(0, end - size + 1), end };
}

function latestRangeForMode(candles: SimCandle[], previous: ChartRange, mode: ChartFollowMode): ChartRange {
  const maxIndex = Math.max(0, candles.length - 1);
  if (mode.kind === "preset") return rangeForPreset(candles, maxIndex, mode.candles);
  return { start: Math.min(previous.start, maxIndex), end: maxIndex };
}

function findTradeCandleIndex(trade: SimTrade, candles: SimCandle[]) {
  if (!candles.length) return -1;
  const tradeTime = Date.parse(trade.time);
  if (Number.isNaN(tradeTime)) return candles.length - 1;
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  candles.forEach((candle, index) => {
    const candleTime = Date.parse(candle.time);
    const openTime = Number.isFinite(candle.openTime) ? candle.openTime : candleTime;
    const closeTime = Number.isFinite(candle.closeTime) ? candle.closeTime : openTime + 15 * 60 * 1000;
    if (tradeTime >= openTime && tradeTime <= closeTime) {
      nearestIndex = index;
      nearestDistance = -1;
      return;
    }
    const anchor = Number.isNaN(candleTime) ? openTime : candleTime;
    const distance = Math.abs(tradeTime - anchor);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  return nearestIndex;
}

function latestTradeForSide(state: SimState, side: "BUY" | "SELL", symbol: string) {
  return [...state.trade_history].reverse().find((trade) => trade.side === side && trade.symbol === symbol) || null;
}

function buildTradeToast(trade: SimTrade, tone: TradeToast["tone"] = "success"): TradeToast {
  const sideText = trade.side === "BUY" ? "买入" : "卖出";
  const baseSymbol = trade.symbol.replace(/USDT$/, "");
  return {
    id: Date.now(),
    tone,
    title: `${sideText}成功`,
    body: `${sideText} ${formatNumber(trade.quantity, 8)} ${baseSymbol}，成交价 ${formatUsdt(trade.price)}，手续费 ${formatUsdt(trade.fee)}`,
  };
}

function isHighRiskConcentratedBuy(
  amount: number,
  state: SimState | null,
  selectedSymbol: string,
  currentRiskEvent: SimRiskEvent | null,
  selectedPosition: SimPosition | null
) {
  if (!state || !currentRiskEvent || currentRiskEvent.risk_score < 70) return false;
  if (!currentRiskEvent.affected_symbols.includes(selectedSymbol)) return false;
  const consumesMostCash = state.cash > 0 && amount >= state.cash * 0.8;
  const nextExposure = (selectedPosition?.market_value ?? 0) + amount;
  const highlyConcentrated = state.total_asset > 0 && nextExposure / state.total_asset >= 0.8;
  return consumesMostCash || highlyConcentrated;
}

function buildSymbolRiskRanking(symbols: SimSymbol[], events: SimRiskEvent[]) {
  return symbols.map((symbol) => {
    const relatedEvents = events.filter((event) => event.affected_symbols.includes(symbol.symbol));
    const maxRisk = relatedEvents.reduce((score, event) => Math.max(score, event.risk_score), 0);
    return {
      ...symbol,
      eventCount: relatedEvents.length,
      maxRisk,
      latestEventTime: relatedEvents.reduce((latest, event) => Math.max(latest, Date.parse(event.time) || 0), 0),
    };
  }).sort((a, b) => b.maxRisk - a.maxRisk || b.eventCount - a.eventCount || b.latestEventTime - a.latestEventTime);
}

function extractRiskEntities(event: SimRiskEvent) {
  const title = decodeEscapedUnicode(event.title || "");
  const evidence = decodeEscapedUnicode(event.evidence || "");
  const baseEntities = [
    ...(event.affected_assets || []),
    ...(event.affected_symbols || []).map((symbol) => symbol.replace(/USDT$/, "")),
    ...(event.related_symbol_details || []).flatMap((detail) => [detail.asset, detail.name, detail.matched_keywords]),
  ];
  const keywordEntities = ["Binance", "Coinbase", "SEC", "ETF", "DeFi", "USDT", "BTC", "ETH", "Solana", "Ripple", "Tron"]
    .filter((keyword) => `${title} ${evidence}`.toLowerCase().includes(keyword.toLowerCase()));
  return Array.from(new Set([...baseEntities, ...keywordEntities].filter(Boolean).map((item) => String(item).trim()))).slice(0, 5);
}

function createClusters(events: SimRiskEvent[], range: ChartRange) {
  const count = range.end - range.start + 1;
  const visible = events
    .filter((event) => {
      const index = event.candle_index ?? -1;
      return index >= range.start && index <= range.end;
    })
    .map((event) => ({
      event,
      x: candleX((event.candle_index ?? range.start) - range.start, count),
    }))
    .sort((a, b) => a.x - b.x);

  const groups: Array<{ events: SimRiskEvent[]; x: number }> = [];
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

export function SimTradingPanel({ embedded = false }: { embedded?: boolean }) {
  const [symbols, setSymbols] = useState<SimSymbol[]>(defaultSymbols);
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [state, setState] = useState<SimState | null>(null);
  const [candles, setCandles] = useState<SimCandle[]>([]);
  const [symbolEvents, setSymbolEvents] = useState<SimRiskEvent[]>([]);
  const [selectedEvent, setSelectedEvent] = useState<SimRiskEvent | null>(null);
  const [manualEventId, setManualEventId] = useState<string | null>(null);
  const [analysisEvent, setAnalysisEvent] = useState<SimRiskEvent | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [assetHistory, setAssetHistory] = useState<AssetSnapshot[]>([]);
  const [seenRiskEvents, setSeenRiskEvents] = useState<SimRiskEvent[]>([]);
  const [dismissedEventIds, setDismissedEventIds] = useState<string[]>([]);
  const [buyAmount, setBuyAmount] = useState("1000");
  const [sellQuantity, setSellQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<TradeToast | null>(null);
  const [pendingHighRiskBuy, setPendingHighRiskBuy] = useState<number | null>(null);
  const [tourWelcomeOpen, setTourWelcomeOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [tourStep, setTourStep] = useState(0);
  const [tourCongratsOpen, setTourCongratsOpen] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<PlaybackSpeed>("ten");
  const [jumpTime, setJumpTime] = useState("");
  const [chartRange, setChartRange] = useState<ChartRange>({ start: 0, end: 0 });
  const [chartFollowMode, setChartFollowMode] = useState<ChartFollowMode>(defaultChartFollowMode);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeSpeed = playbackSpeeds.find((speed) => speed.key === playbackSpeed) || playbackSpeeds[2];
  const selectedMeta = symbols.find((item) => item.symbol === selectedSymbol) || defaultSymbols[0];
  const selectedPrice = state?.prices[selectedSymbol] ?? candles[candles.length - 1]?.close ?? 0;
  const latestCandle = candles[candles.length - 1];
  const selectedChange = latestCandle?.open ? (latestCandle.close - latestCandle.open) / latestCandle.open : 0;
  const selectedPosition = state?.positions.find((position) => position.symbol === selectedSymbol) || null;
  const currentRiskEvent = useMemo(() => {
    const latest = state?.risk_events.find((event) => !dismissedEventIds.includes(event.id));
    return latest || null;
  }, [dismissedEventIds, state?.risk_events]);
  const symbolRiskRanking = useMemo(
    () => buildSymbolRiskRanking(symbols, seenRiskEvents),
    [seenRiskEvents, symbols]
  );

  function centerChartOnEvent(event: SimRiskEvent) {
    const index = event.candle_index ?? chartRange.end;
    const maxIndex = Math.max(0, candles.length - 1);
    const size = Math.max(16, chartRange.end - chartRange.start + 1);
    const start = index - Math.floor(size / 2);
    setChartRange(clampRange({ start, end: start + size - 1 }, maxIndex));
    setChartFollowMode({ kind: "manual" });
  }

  function handlePresetRange(preset: ZoomPreset) {
    setChartFollowMode({ kind: "preset", label: preset.label, candles: preset.candles });
    setChartRange(rangeForPreset(candles, Math.max(0, candles.length - 1), preset.candles));
  }

  function handleManualRange() {
    setChartFollowMode({ kind: "manual" });
  }

  const finishTour = useCallback((showCongrats = false) => {
    window.localStorage.setItem(simTourStorageKey, "true");
    window.localStorage.setItem(simTourWelcomeStorageKey, "true");
    setTourOpen(false);
    setTourWelcomeOpen(false);
    setTourCongratsOpen(showCongrats);
  }, []);

  function startTour() {
    setTourStep(0);
    setTourWelcomeOpen(false);
    setTourCongratsOpen(false);
    setTourOpen(true);
    setIsPlaying(false);
  }

  function skipTourStep() {
    setTourStep((step) => {
      if (step >= beginnerTourSteps.length - 1) {
        window.localStorage.setItem(simTourStorageKey, "true");
        window.setTimeout(() => finishTour(true), 0);
        return step;
      }
      return step + 1;
    });
  }

  const completeTourAction = useCallback((action: TourAction) => {
    if (!tourOpen) return;
    const currentStep = beginnerTourSteps[tourStep];
    if (currentStep?.requiredAction !== action) return;
    if (tourStep >= beginnerTourSteps.length - 1) {
      finishTour(true);
      return;
    }
    setTourStep((step) => Math.min(step + 1, beginnerTourSteps.length - 1));
  }, [finishTour, tourOpen, tourStep]);

  function handleSelectSymbol(symbol: string) {
    const changed = symbol !== selectedSymbol;
    setSelectedSymbol(symbol);
    if (changed) completeTourAction("switch-symbol");
  }

  function showToast(nextToast: Omit<TradeToast, "id"> | TradeToast) {
    setToast("id" in nextToast ? nextToast : { ...nextToast, id: Date.now() });
  }

  function inspectEvent(event: SimRiskEvent) {
    setIsPlaying(false);
    setManualEventId(event.id);
    setSelectedEvent(event);
    centerChartOnEvent(event);
    completeTourAction("inspect-event");
  }

  function openRiskAnalysis(event: SimRiskEvent) {
    setAnalysisEvent(event);
    completeTourAction("view-ai");
  }

  function closeBanner() {
    if (selectedEvent && currentRiskEvent?.id === selectedEvent.id) {
      setDismissedEventIds((ids) => ids.includes(selectedEvent.id) ? ids : [...ids, selectedEvent.id]);
    }
    setManualEventId(null);
    setSelectedEvent(null);
  }

  const refreshState = useCallback(async (nextState?: SimState, options?: { followLatest?: boolean }) => {
    const freshState = nextState || await fetchSimState();
    const [candleResponse, eventResponse] = await Promise.all([
      fetchSimCandles(selectedSymbol),
      fetchSimEvents(selectedSymbol),
    ]);
    setState(freshState);
    setAssetHistory((history) => upsertAssetSnapshot(history, freshState));
    setSeenRiskEvents((events) => mergeRiskEvents(events, freshState.risk_events || []));
    setCandles(candleResponse.items);
    setSymbolEvents(eventResponse.items);
    setJumpTime(toDatetimeLocalValue(freshState.sim_time));
    setChartRange((range) => {
      const maxIndex = Math.max(0, candleResponse.items.length - 1);
      if (options?.followLatest) {
        return latestRangeForMode(candleResponse.items, range, chartFollowMode);
      }
      if (range.end >= maxIndex - 2) {
        return { start: Math.min(range.start, maxIndex), end: maxIndex };
      }
      return clampRange(range, maxIndex);
    });
  }, [chartFollowMode, selectedSymbol]);

  const handleStep = useCallback(async () => {
    if (isBusy) return;
    setIsBusy(true);
    setError(null);
    try {
      const nextState = await nextSimStep();
      await refreshState(nextState, { followLatest: true });
      completeTourAction("next-candle");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to advance simulator");
      setIsPlaying(false);
    } finally {
      setIsBusy(false);
    }
  }, [completeTourAction, isBusy, refreshState]);

  const handleReset = useCallback(async () => {
    setIsBusy(true);
    setIsPlaying(false);
    setError(null);
    setDismissedEventIds([]);
    setSelectedEvent(null);
    setManualEventId(null);
    setReportOpen(false);
    setChartFollowMode(defaultChartFollowMode);
    try {
      const nextState = await resetSim();
      setAssetHistory([]);
      setSeenRiskEvents([]);
      await refreshState(nextState);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Failed to reset simulator");
    } finally {
      setIsBusy(false);
    }
  }, [refreshState]);

  async function executeBuy(amount: number) {
    setIsBusy(true);
    setError(null);
    try {
      const nextState = await buySim(selectedSymbol, amount);
      await refreshState(nextState);
      const trade = latestTradeForSide(nextState, "BUY", selectedSymbol);
      if (trade) showToast(buildTradeToast(trade));
      completeTourAction("buy");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Buy order failed";
      setError(message);
      showToast({ tone: "error", title: "买入失败", body: message });
    } finally {
      setIsBusy(false);
    }
  }

  async function handleBuy() {
    const amount = Number(buyAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      const message = "Buy amount must be greater than zero";
      setError(message);
      showToast({ tone: "error", title: "买入失败", body: message });
      return;
    }
    if (isHighRiskConcentratedBuy(amount, state, selectedSymbol, currentRiskEvent, selectedPosition)) {
      setPendingHighRiskBuy(amount);
      setIsPlaying(false);
      return;
    }
    await executeBuy(amount);
  }

  async function handleSell() {
    const quantity = Number(sellQuantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      const message = "Sell quantity must be greater than zero";
      setError(message);
      showToast({ tone: "error", title: "卖出失败", body: message });
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const nextState = await sellSim(selectedSymbol, quantity);
      await refreshState(nextState);
      const trade = latestTradeForSide(nextState, "SELL", selectedSymbol);
      if (trade) showToast(buildTradeToast(trade));
      completeTourAction("sell");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Sell order failed";
      setError(message);
      showToast({ tone: "error", title: "卖出失败", body: message });
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSellAll() {
    if (!selectedPosition || selectedPosition.quantity <= 0) return;
    setIsBusy(true);
    setError(null);
    try {
      const nextState = await sellSim(selectedSymbol, "ALL");
      await refreshState(nextState);
      const trade = latestTradeForSide(nextState, "SELL", selectedSymbol);
      if (trade) showToast(buildTradeToast(trade));
      completeTourAction("sell");
      setSellQuantity("");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Sell order failed";
      setError(message);
      showToast({ tone: "error", title: "卖出失败", body: message });
    } finally {
      setIsBusy(false);
    }
  }

  async function handleRiskEventSell(ratio: 0.5 | 1) {
    if (!currentRiskEvent || !state) return;
    const targetSymbol = currentRiskEvent.affected_symbols.find((symbol) => state.positions.some((position) => position.symbol === symbol));
    const targetPosition = state.positions.find((position) => position.symbol === targetSymbol);
    if (!targetSymbol || !targetPosition) {
      setDismissedEventIds((ids) => [...ids, currentRiskEvent.id]);
      return;
    }
    setIsBusy(true);
    setError(null);
    try {
      const quantity: number | "ALL" = ratio === 1 ? "ALL" : targetPosition.quantity * ratio;
      setSelectedSymbol(targetSymbol);
      const nextState = await sellSim(targetSymbol, quantity);
      await refreshState(nextState);
      const trade = latestTradeForSide(nextState, "SELL", targetSymbol);
      if (trade) showToast(buildTradeToast(trade));
      completeTourAction("sell");
      setDismissedEventIds((ids) => [...ids, currentRiskEvent.id]);
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : "Risk event sell order failed";
      setError(message);
      showToast({ tone: "error", title: "卖出失败", body: message });
    } finally {
      setIsBusy(false);
    }
  }

  async function handleJump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const targetTime = localDatetimeToIso(jumpTime);
    if (!targetTime) return;
    setIsBusy(true);
    setIsPlaying(false);
    setError(null);
    setDismissedEventIds([]);
    setSelectedEvent(null);
    setManualEventId(null);
    try {
      const nextState = await jumpSim({ target_time: targetTime });
      await refreshState(nextState);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Jump failed");
    } finally {
      setIsBusy(false);
    }
  }

  useEffect(() => {
    let ignore = false;
    Promise.all([fetchSimSymbols(), fetchSimState(), fetchSimCandles("BTCUSDT"), fetchSimEvents("BTCUSDT")])
      .then(([symbolResponse, simState, candleResponse, eventResponse]) => {
        if (ignore) return;
        setSymbols(symbolResponse.items);
        setState(simState);
        setAssetHistory([{
          index: simState.current_index,
          time: simState.sim_time,
          totalAsset: simState.total_asset,
        }]);
        setSeenRiskEvents(simState.risk_events || []);
        setCandles(candleResponse.items);
        setSymbolEvents(eventResponse.items);
        setJumpTime(toDatetimeLocalValue(simState.sim_time));
        setChartRange(latestRangeForMode(candleResponse.items, { start: 0, end: 0 }, defaultChartFollowMode));
      })
      .catch((exc) => {
        if (!ignore) setError(exc instanceof Error ? exc.message : "Failed to load simulator");
      });
    return () => {
      ignore = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    let ignore = false;
    Promise.all([fetchSimCandles(selectedSymbol), fetchSimEvents(selectedSymbol)])
      .then(([candleResponse, eventResponse]) => {
        if (ignore) return;
        setCandles(candleResponse.items);
        setSymbolEvents(eventResponse.items);
        setChartRange((range) => {
          const maxIndex = Math.max(0, candleResponse.items.length - 1);
          if (chartFollowMode.kind === "preset") {
            return latestRangeForMode(candleResponse.items, range, chartFollowMode);
          }
          if (range.end >= maxIndex - 2) {
            return { start: Math.min(range.start, maxIndex), end: maxIndex };
          }
          return clampRange(range, maxIndex);
        });
      })
      .catch((exc) => {
        if (!ignore) setError(exc instanceof Error ? exc.message : "Failed to load candles");
      });
    return () => {
      ignore = true;
    };
  }, [chartFollowMode, selectedSymbol, state?.current_index]);

  useEffect(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (!isPlaying) return;
    timerRef.current = setInterval(() => {
      handleStep();
    }, activeSpeed.intervalMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [activeSpeed.intervalMs, handleStep, isPlaying]);

  useEffect(() => {
    const resetTimer = window.setTimeout(() => {
      if (!manualEventId) setSelectedEvent(currentRiskEvent);
    }, 0);
    return () => window.clearTimeout(resetTimer);
  }, [currentRiskEvent, manualEventId, state?.current_index]);

  useEffect(() => {
    if (currentRiskEvent || manualEventId) return;
    const clearTimer = window.setTimeout(() => setSelectedEvent(null), 0);
    return () => window.clearTimeout(clearTimer);
  }, [currentRiskEvent, manualEventId, state?.current_index]);

  useEffect(() => {
    if (!manualEventId) return;
    const currentEventIds = new Set((state?.risk_events || []).map((event) => event.id));
    if (!currentEventIds.has(manualEventId)) return;
    const releaseTimer = window.setTimeout(() => setManualEventId(null), 0);
    return () => window.clearTimeout(releaseTimer);
  }, [manualEventId, state?.risk_events]);

  useEffect(() => {
    const resetDismissTimer = window.setTimeout(() => setDismissedEventIds([]), 0);
    return () => window.clearTimeout(resetDismissTimer);
  }, [state?.current_index]);

  useEffect(() => {
    if (!toast) return;
    const clearTimer = window.setTimeout(() => setToast(null), 2200);
    return () => window.clearTimeout(clearTimer);
  }, [toast]);

  useEffect(() => {
    if (window.localStorage.getItem(simTourStorageKey) || window.localStorage.getItem(simTourWelcomeStorageKey)) return;
    const tourTimer = window.setTimeout(() => {
      setTourWelcomeOpen(true);
      setIsPlaying(false);
    }, 0);
    return () => window.clearTimeout(tourTimer);
  }, []);

  const content = (
    <div className={embedded ? "flex min-w-0 flex-col gap-4" : "mx-auto flex w-full max-w-[1440px] flex-col gap-4"} data-tour-id="sim-shell">
      {toast ? <TradeToastView toast={toast} onClose={() => setToast(null)} /> : null}
      {tourWelcomeOpen ? <TourWelcomeModal onSkip={() => finishTour(false)} onStart={startTour} /> : null}
      {tourOpen ? (
        <GuidedTourOverlay
          onClose={() => finishTour(false)}
          onNext={() => {
            if (tourStep >= beginnerTourSteps.length - 1) finishTour(true);
            else setTourStep((step) => step + 1);
          }}
          onPrevious={() => setTourStep((step) => Math.max(0, step - 1))}
          onSkipStep={skipTourStep}
          step={tourStep}
          steps={beginnerTourSteps}
        />
      ) : null}
      {tourCongratsOpen ? <TourCompletionCard onClose={() => setTourCongratsOpen(false)} /> : null}
      {pendingHighRiskBuy !== null ? (
        <PreTradeWarningModal
          amount={pendingHighRiskBuy}
          event={currentRiskEvent}
          onCancel={() => setPendingHighRiskBuy(null)}
          onConfirm={() => {
            const amount = pendingHighRiskBuy;
            setPendingHighRiskBuy(null);
            void executeBuy(amount);
          }}
          selectedSymbol={selectedSymbol}
        />
      ) : null}
      <header className="risk-topbar rounded-lg border p-3">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-700">Risk Event Replay</p>
            <div className="mt-1 flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold text-slate-950 sm:text-3xl">{labels.title}</h1>
              <button
                className="h-8 rounded-lg border border-emerald-200 bg-white px-3 text-xs font-semibold text-emerald-700 transition-colors duration-200 hover:bg-emerald-50"
                onClick={startTour}
                type="button"
              >
                新手引导
              </button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-tour-id="asset-metrics">
            <Metric label={<WithTerm term="模拟时间">{labels.simTime}</WithTerm>} value={formatTime(state?.sim_time || "")} />
            <Metric label={labels.candleIndex} value={`${state?.current_index ?? 0}/${state?.max_index ?? 0}`} />
            <Metric label={<WithTerm term="总资产">{labels.totalAsset}</WithTerm>} value={formatUsdt(state?.total_asset ?? 10000)} />
            <Metric label={<WithTerm term="收益率">{labels.returnRate}</WithTerm>} value={formatPercent(state?.return_rate ?? 0)} tone={(state?.return_rate ?? 0) >= 0 ? "up" : "down"} />
          </div>
        </div>
      </header>
      <button
        className="fixed bottom-4 left-4 z-[70] rounded-full border border-emerald-200 bg-white px-4 py-2 text-sm font-semibold text-emerald-700 shadow-lg shadow-slate-900/10 transition-colors duration-200 hover:bg-emerald-50 sm:bottom-6 sm:left-auto sm:right-24"
        onClick={startTour}
        type="button"
      >
        新手引导
      </button>

      {analysisEvent ? <RiskAnalysisPanel event={analysisEvent} impact={calculateEventImpact(candles, analysisEvent.candle_index)} onClose={() => setAnalysisEvent(null)} /> : null}
      {reportOpen && state ? (
        <ReplayReportModal
          assetHistory={assetHistory}
          events={seenRiskEvents}
          onClose={() => setReportOpen(false)}
          state={state}
        />
      ) : null}
      {error ? <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{error}</div> : null}

      <section className="grid min-w-0 gap-3 xl:grid-cols-[190px_minmax(0,1fr)_270px]">
        <aside className="risk-panel min-w-0 rounded-lg p-2.5" data-tour-id="symbol-list">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-slate-500">Symbols</h2>
            <span className="text-xs text-slate-500">{symbols.length}</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-1">
            {symbols.map((item) => {
              const active = item.symbol === selectedSymbol;
              return (
                <button
                  key={item.symbol}
                  className={`rounded-lg border px-2.5 py-2 text-left transition-colors duration-200 ${active ? "border-emerald-500 bg-emerald-50 text-emerald-950" : "border-slate-200 bg-white/80 text-slate-700 hover:border-emerald-300 hover:bg-emerald-50/70"}`}
                  onClick={() => handleSelectSymbol(item.symbol)}
                  type="button"
                >
                  <span className="block text-sm font-semibold">{item.base_symbol}</span>
                  <span className="mt-1 block text-xs text-slate-500">{formatUsdt(state?.prices[item.symbol] ?? 0)}</span>
                </button>
              );
            })}
          </div>
          <SymbolRiskBoard
            items={symbolRiskRanking}
            onSelectSymbol={handleSelectSymbol}
            selectedSymbol={selectedSymbol}
          />
        </aside>

        <section className="flex min-w-0 flex-col gap-3">
          <div className="risk-panel rounded-lg p-2.5">
            <div className="mb-2">
              <ReplayControls
                activeSpeedKey={playbackSpeed}
                currentPrice={selectedPrice}
                currentReturn={selectedChange}
                isBusy={isBusy}
                isPlaying={isPlaying}
                jumpTime={jumpTime}
                onJump={handleJump}
                onJumpTimeChange={setJumpTime}
                onPause={() => setIsPlaying(false)}
                onReset={handleReset}
                onReport={() => setReportOpen(true)}
                onSpeedChange={(speed) => {
                  setPlaybackSpeed(speed);
                  setIsPlaying(true);
                }}
                onStep={handleStep}
                selectedMeta={selectedMeta}
                selectedSymbol={selectedSymbol}
                state={state}
              />
            </div>
            <PriceLineChart
              activePresetLabel={chartFollowMode.kind === "preset" ? chartFollowMode.label : null}
              candles={candles}
              events={symbolEvents}
              onInspectEvent={inspectEvent}
              onCloseBanner={closeBanner}
              onManualRange={handleManualRange}
              onPresetRange={handlePresetRange}
              onViewAnalysis={openRiskAnalysis}
              range={chartRange}
              selectedEvent={selectedEvent}
              setRange={setChartRange}
              trades={state?.trade_history ?? []}
              tradingSymbol={selectedSymbol}
            />
          </div>
          <SymbolNewsTimeline events={symbolEvents} selectedSymbol={selectedSymbol} simTime={state?.sim_time || ""} />
        </section>

        <TradePanel
          buyAmount={buyAmount}
          currentRiskEvent={currentRiskEvent}
          hasAffectedPosition={Boolean(currentRiskEvent?.affected_symbols.some((symbol) => state?.positions.some((position) => position.symbol === symbol)))}
          isBusy={isBusy}
          onBuy={handleBuy}
          onBuyAmountChange={setBuyAmount}
          onDismissRisk={() => currentRiskEvent && setDismissedEventIds((ids) => [...ids, currentRiskEvent.id])}
          onSell={handleSell}
          onSellAll={handleSellAll}
          onSellHalfRisk={() => handleRiskEventSell(0.5)}
          onSellQuantityChange={setSellQuantity}
          onSellRiskAll={() => handleRiskEventSell(1)}
          onViewAnalysis={() => currentRiskEvent && openRiskAnalysis(currentRiskEvent)}
          selectedPosition={selectedPosition}
          selectedPrice={selectedPrice}
          sellQuantity={sellQuantity}
          state={state}
        />
      </section>

      <section className="grid gap-3 lg:grid-cols-2">
        <PositionsTable state={state} />
        <TradesTable state={state} />
      </section>
    </div>
  );

  if (embedded) return content;
  return <main className="risk-shell min-h-screen px-4 py-5 text-slate-950 sm:px-6 lg:px-8">{content}</main>;
}

function SymbolRiskBoard({
  items,
  onSelectSymbol,
  selectedSymbol,
}: {
  items: Array<SimSymbol & { eventCount: number; maxRisk: number; latestEventTime: number }>;
  onSelectSymbol: (symbol: string) => void;
  selectedSymbol: string;
}) {
  const topItems = items.slice(0, 5);
  return (
    <section className="mt-3 rounded-lg border border-slate-200 bg-white/80 p-2">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">风险币种榜</p>
        <span className="text-[11px] font-semibold text-slate-400">past</span>
      </div>
      <div className="space-y-1">
        {topItems.map((item, index) => {
          const tone = item.maxRisk >= 70 ? riskTones.high : item.maxRisk >= 40 ? riskTones.medium : riskTones.low;
          const active = item.symbol === selectedSymbol;
          return (
            <button
              className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left transition-colors duration-200 ${
                active ? "border-emerald-400 bg-emerald-50" : "border-transparent hover:border-slate-200 hover:bg-slate-50"
              }`}
              key={item.symbol}
              onClick={() => onSelectSymbol(item.symbol)}
              type="button"
            >
              <span className="w-4 shrink-0 text-[11px] font-bold text-slate-400">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-semibold text-slate-900">{item.base_symbol}</span>
                <span className="block text-[11px] text-slate-500">{item.eventCount} news</span>
              </span>
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: tone.marker }} />
              <span className={`w-7 shrink-0 text-right text-xs font-bold ${item.maxRisk >= 70 ? "text-red-600" : item.maxRisk >= 40 ? "text-amber-600" : "text-emerald-600"}`}>
                {item.maxRisk || "--"}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

type TourFrame = {
  bubbleLeft: number;
  bubbleTop: number;
  highlightHeight: number;
  highlightLeft: number;
  highlightTop: number;
  highlightWidth: number;
};

const termExplanations: Record<string, string> = {
  AI分析: "AI 会解释新闻风险来源、影响币种和可能的操作思路，但不代表投资建议。",
  K线: "一根 K 线记录一段时间内的开盘价、最高价、最低价和收盘价。本模拟盘每根 K 线代表 15 分钟。",
  MA10: "最近 10 根 K 线收盘价的平均值，用来观察较短周期的价格趋势。",
  MA30: "最近 30 根 K 线收盘价的平均值，比 MA10 更平滑，适合观察稍长一点的趋势。",
  USDT: "可以简单理解为模拟盘里的美元计价单位，用来衡量买入金额、现金余额和资产价值。",
  成交量: "表示这段时间市场交易是否活跃。新闻冲击时成交量放大，通常说明市场反应更强。",
  收益率: "当前总资产相对初始资金 10000 USDT 的盈亏比例。收益高不等于风控一定好。",
  总资产: "现金余额加上所有持仓按当前价格计算的市值。",
  模拟时间: "历史回放中的当前时间点。系统只展示这个时间点之前已经发生的行情和新闻。",
  风险分: "风险分衡量新闻带来的不确定性，不是涨跌预测，也不是买卖指令。",
};

function TourWelcomeModal({ onSkip, onStart }: { onSkip: () => void; onStart: () => void }) {
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/35 p-4" onMouseDown={onSkip}>
      <section className="w-full max-w-md rounded-xl border border-emerald-100 bg-white p-5 shadow-2xl shadow-slate-900/20" onMouseDown={(event) => event.stopPropagation()}>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">CryptoRisk 新手实验</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950">跟着完成一次完整模拟交易</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          教程会带你看行情、理解 K 线、识别风险新闻、查看 AI 分析、买入、推进行情、卖出并查看复盘。这不是投资建议，只是一次风险决策练习。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50" onClick={onSkip} type="button">
            跳过
          </button>
          <button className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800" onClick={onStart} type="button">
            开始教程
          </button>
        </div>
      </section>
    </div>
  );
}

function TourCompletionCard({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/35 p-4" onMouseDown={onClose}>
      <section className="w-full max-w-md rounded-xl border border-emerald-100 bg-white p-5 shadow-2xl shadow-slate-900/20" onMouseDown={(event) => event.stopPropagation()}>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">教程完成</p>
        <h2 className="mt-2 text-xl font-semibold text-slate-950">你已经完成一次完整模拟交易</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          现在可以自由选择币种，观察风险新闻并尝试不同决策。记住，CryptoRisk 关注的不只是收益，而是你在新闻冲击下如何管理风险。
        </p>
        <div className="mt-5 flex justify-end">
          <button className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800" onClick={onClose} type="button">
            开始自由练习
          </button>
        </div>
      </section>
    </div>
  );
}

function GuidedTourOverlay({
  onClose,
  onNext,
  onPrevious,
  onSkipStep,
  step,
  steps,
}: {
  onClose: () => void;
  onNext: () => void;
  onPrevious: () => void;
  onSkipStep: () => void;
  step: number;
  steps: TourStep[];
}) {
  const currentStep = steps[step] || steps[0];
  const [frame, setFrame] = useState<TourFrame | null>(null);
  const isLast = step >= steps.length - 1;
  const requiresAction = Boolean(currentStep.requiredAction);

  useEffect(() => {
    let measureTimer = 0;

    const measure = () => {
      const target = findTourTarget(currentStep.targetId);
      const rect = target?.getBoundingClientRect();
      const usableRect = rect && rect.width > 8 && rect.height > 8 ? rect : fallbackTourRect();
      setFrame(calculateTourFrame(usableRect));
    };

    const scheduleMeasure = () => {
      window.clearTimeout(measureTimer);
      measureTimer = window.setTimeout(measure, 80);
    };

    const target = findTourTarget(currentStep.targetId);
    target?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
    scheduleMeasure();
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("scroll", scheduleMeasure, true);

    return () => {
      window.clearTimeout(measureTimer);
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("scroll", scheduleMeasure, true);
    };
  }, [currentStep.targetId]);

  if (!frame) return null;

  return (
    <>
      <div
        className="pointer-events-none fixed rounded-xl border-2 border-emerald-400 shadow-[0_0_0_9999px_rgba(15,23,42,0.46),0_0_28px_rgba(16,185,129,0.35)] transition-all duration-200"
        style={{
          height: frame.highlightHeight,
          left: frame.highlightLeft,
          top: frame.highlightTop,
          width: frame.highlightWidth,
          zIndex: 105,
        }}
      />
      <aside
        className="fixed z-[115] w-[min(420px,calc(100vw-32px))] rounded-xl border border-emerald-100 bg-white/95 p-4 shadow-2xl shadow-slate-900/20 backdrop-blur"
        style={{ left: frame.bubbleLeft, top: frame.bubbleTop }}
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
            {step + 1} / {steps.length}
          </span>
          <button className="rounded-md px-2 text-sm font-semibold text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} type="button">
            跳过教程
          </button>
        </div>
        <h3 className="text-base font-semibold text-slate-950">{currentStep.title}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-600">{currentStep.body}</p>
        <div className="mt-3 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-emerald-700">当前任务</p>
          <p className="mt-1 text-sm leading-5 text-emerald-950">{currentStep.task}</p>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <button
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50 disabled:opacity-40"
            disabled={step === 0}
            onClick={onPrevious}
            type="button"
          >
            上一步
          </button>
          <div className="flex gap-2">
            {requiresAction ? (
              <button className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-700 hover:bg-amber-100" onClick={onSkipStep} type="button">
                跳过此步
              </button>
            ) : null}
            <button
              className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              disabled={requiresAction}
              onClick={onNext}
              type="button"
            >
              {requiresAction ? "等待操作" : isLast ? "完成教程" : "下一步"}
            </button>
          </div>
        </div>
      </aside>
      <div className="fixed bottom-6 right-6 z-[115] w-[min(320px,calc(100vw-32px))] rounded-xl border border-slate-200 bg-white/95 p-3 shadow-xl shadow-slate-900/10 backdrop-blur">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">新手任务</p>
        <p className="mt-1 text-sm leading-5 text-slate-700">{currentStep.task}</p>
      </div>
    </>
  );
}

function WithTerm({ children, term }: { children: ReactNode; term: string }) {
  const explanation = termExplanations[term];
  if (!explanation) return <>{children}</>;

  return (
    <span className="group relative inline-flex items-center gap-1 align-middle">
      <span>{children}</span>
      <span
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 text-[10px] font-bold text-emerald-700"
        tabIndex={0}
      >
        ?
      </span>
      <span className="pointer-events-none absolute left-0 top-full z-[130] mt-2 hidden w-64 rounded-lg border border-emerald-100 bg-white p-3 text-xs font-medium leading-5 text-slate-600 shadow-xl shadow-slate-900/10 group-hover:block group-focus-within:block">
        {explanation}
      </span>
    </span>
  );
}

function findTourTarget(targetId: string) {
  const target = document.querySelector(`[data-tour-id="${targetId}"]`);
  if (!target || target.getBoundingClientRect().width < 8 || target.getBoundingClientRect().height < 8) {
    return document.querySelector('[data-tour-id="sim-shell"]');
  }
  return target;
}

function fallbackTourRect() {
  return {
    bottom: 180,
    height: 110,
    left: 24,
    right: Math.min(540, window.innerWidth - 24),
    top: 70,
    width: Math.min(516, window.innerWidth - 48),
    x: 24,
    y: 70,
    toJSON: () => undefined,
  } as DOMRect;
}

function calculateTourFrame(rect: DOMRect) {
  const padding = 10;
  const gap = 14;
  const bubbleWidth = Math.min(420, Math.max(320, window.innerWidth - 32));
  const bubbleHeight = 300;
  const highlightLeft = Math.max(12, rect.left - padding);
  const highlightTop = Math.max(12, rect.top - padding);
  const highlightWidth = Math.min(window.innerWidth - highlightLeft - 12, rect.width + padding * 2);
  const highlightHeight = Math.min(window.innerHeight - highlightTop - 12, rect.height + padding * 2);
  let bubbleLeft = highlightLeft + highlightWidth + gap;
  let bubbleTop = highlightTop;

  if (bubbleLeft + bubbleWidth > window.innerWidth - 16) {
    bubbleLeft = highlightLeft - bubbleWidth - gap;
  }
  if (bubbleLeft < 16) {
    bubbleLeft = Math.min(Math.max(16, highlightLeft), window.innerWidth - bubbleWidth - 16);
    bubbleTop = highlightTop + highlightHeight + gap;
  }
  if (bubbleTop + bubbleHeight > window.innerHeight - 16) {
    bubbleTop = highlightTop - bubbleHeight - gap;
  }
  if (bubbleTop < 16) bubbleTop = 16;

  return {
    bubbleLeft,
    bubbleTop,
    highlightHeight,
    highlightLeft,
    highlightTop,
    highlightWidth,
  };
}

function ReplayControls({
  activeSpeedKey,
  currentPrice,
  currentReturn,
  isBusy,
  isPlaying,
  jumpTime,
  onJump,
  onJumpTimeChange,
  onPause,
  onReset,
  onReport,
  onSpeedChange,
  onStep,
  selectedMeta,
  selectedSymbol,
  state,
}: {
  activeSpeedKey: PlaybackSpeed;
  currentPrice: number;
  currentReturn: number;
  isBusy: boolean;
  isPlaying: boolean;
  jumpTime: string;
  onJump: (event: FormEvent<HTMLFormElement>) => void;
  onJumpTimeChange: (value: string) => void;
  onPause: () => void;
  onReset: () => void;
  onReport: () => void;
  onSpeedChange: (value: PlaybackSpeed) => void;
  onStep: () => void;
  selectedMeta: SimSymbol;
  selectedSymbol: string;
  state: SimState | null;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex w-full min-w-0 items-center gap-3 sm:w-auto sm:min-w-[220px]">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-slate-500">{selectedMeta.name}</p>
          <h2 className="truncate text-lg font-semibold leading-5 text-slate-950">{selectedSymbol}</h2>
        </div>
        <div className="min-w-0 border-l border-slate-200 pl-3">
          <p className="truncate text-lg font-semibold leading-5 text-slate-950">{formatUsdt(currentPrice)}</p>
          <p className={`mt-0.5 text-xs font-semibold ${currentReturn >= 0 ? "text-emerald-600" : "text-red-600"}`}>
            {currentReturn >= 0 ? "+" : ""}{formatPercent(currentReturn)}
          </p>
        </div>
      </div>
      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
        <ControlButton disabled={!isPlaying} onClick={onPause}>{labels.pause}</ControlButton>
        <ControlButton onClick={onStep} tourId="next-button">{labels.next}</ControlButton>
        <ControlButton disabled={isBusy} tone="red" onClick={onReset}>{labels.reset}</ControlButton>
        <ControlButton onClick={onReport} tourId="report-button">复盘报告</ControlButton>
        <span className="ml-1 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{labels.speed}</span>
        <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {playbackSpeeds.map((speed) => (
            <button
              key={speed.key}
              className={`h-9 min-w-14 px-3 text-sm font-semibold transition-colors ${isPlaying && activeSpeedKey === speed.key ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}
              onClick={() => onSpeedChange(speed.key)}
              type="button"
            >
              {speed.label}
            </button>
          ))}
        </div>
      </div>
      <form className="flex w-full flex-wrap items-center gap-2 sm:w-auto" onSubmit={onJump}>
        <label className="flex w-full flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 sm:w-auto">
          <span>{labels.jumpTime}</span>
          <input
            className="h-9 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-2.5 text-xs font-medium normal-case tracking-normal text-slate-800 sm:w-[180px]"
            max={toDatetimeLocalValue(state?.end_time || "")}
            min={toDatetimeLocalValue(state?.start_time || "")}
            onChange={(event) => onJumpTimeChange(event.target.value)}
            type="datetime-local"
            value={jumpTime}
          />
        </label>
        <button className="h-9 w-full rounded-lg border border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 disabled:opacity-50 sm:w-auto" disabled={isBusy || !jumpTime} type="submit">
          {labels.jump}
        </button>
      </form>
    </div>
  );
}

function TradeToastView({ onClose, toast }: { onClose: () => void; toast: TradeToast }) {
  const toneClass = toast.tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : toast.tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : "border-red-200 bg-red-50 text-red-900";
  const accentClass = toast.tone === "success" ? "bg-emerald-600" : toast.tone === "warning" ? "bg-amber-600" : "bg-red-600";
  return (
    <div className="fixed left-1/2 top-5 z-[120] w-[min(92vw,520px)] -translate-x-1/2">
      <section className={`flex items-start gap-3 rounded-lg border px-4 py-3 shadow-2xl shadow-slate-900/15 ${toneClass}`}>
        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${accentClass}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{toast.title}</p>
          <p className="mt-1 whitespace-normal break-words text-xs leading-5">{toast.body}</p>
        </div>
        <button className="rounded-md px-2 text-lg leading-6 opacity-70 hover:bg-white/70 hover:opacity-100" onClick={onClose} type="button" aria-label="close trade notice">
          x
        </button>
      </section>
    </div>
  );
}

function PreTradeWarningModal({
  amount,
  event,
  onCancel,
  onConfirm,
  selectedSymbol,
}: {
  amount: number;
  event: SimRiskEvent | null;
  onCancel: () => void;
  onConfirm: () => void;
  selectedSymbol: string;
}) {
  return (
    <div className="fixed inset-0 z-[115] flex items-center justify-center bg-slate-950/45 p-4" onMouseDown={onCancel}>
      <section className="w-full max-w-md rounded-lg border border-red-200 bg-white shadow-2xl" onMouseDown={(mouseEvent) => mouseEvent.stopPropagation()}>
        <header className="border-b border-red-100 bg-red-50 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-red-700">Pre-trade Warning</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">高风险事件下的集中买入</h2>
        </header>
        <div className="space-y-3 p-5 text-sm leading-6 text-slate-700">
          <p>
            当前处于高风险事件影响期，且这笔 {formatUsdt(amount)} 的 {selectedSymbol} 买入会显著提高仓位集中度。
          </p>
          {event ? (
            <div className="rounded-lg border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-800">
              <p className="font-semibold">风险事件：{decodeEscapedUnicode(event.title)}</p>
              <p className="mt-1">风险分：{event.risk_score} | 影响币种：{event.affected_symbols.join(" / ")}</p>
            </div>
          ) : null}
          <p className="text-xs text-slate-500">这不是禁止交易，而是提醒你在新闻冲击期避免情绪化满仓。</p>
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50" onClick={onCancel} type="button">
            取消
          </button>
          <button className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700" onClick={onConfirm} type="button">
            确认执行
          </button>
        </footer>
      </section>
    </div>
  );
}

function PriceLineChart({
  activePresetLabel,
  candles,
  events,
  onCloseBanner,
  onInspectEvent,
  onManualRange,
  onPresetRange,
  onViewAnalysis,
  range,
  selectedEvent,
  setRange,
  trades,
  tradingSymbol,
}: {
  activePresetLabel: string | null;
  candles: SimCandle[];
  events: SimRiskEvent[];
  onCloseBanner: () => void;
  onInspectEvent: (event: SimRiskEvent) => void;
  onManualRange: () => void;
  onPresetRange: (preset: ZoomPreset) => void;
  onViewAnalysis: (event: SimRiskEvent) => void;
  range: ChartRange;
  selectedEvent: SimRiskEvent | null;
  setRange: Dispatch<SetStateAction<ChartRange>>;
  trades: SimTrade[];
  tradingSymbol: string;
}) {
  const dragRef = useRef<{ x: number; range: ChartRange; moved: boolean } | null>(null);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const zoomDragRef = useRef<{ mode: ZoomDragMode; x: number; range: ChartRange; trackWidth: number } | null>(null);
  const [hoverPoint, setHoverPoint] = useState<ChartHoverPoint | null>(null);
  const [openEventStack, setOpenEventStack] = useState<{ events: SimRiskEvent[]; x: number } | null>(null);
  const maxIndex = Math.max(0, candles.length - 1);
  const safeRange = clampRange(range, maxIndex);
  const visibleCandles = candles.slice(safeRange.start, safeRange.end + 1);
  const priceRange = getPriceRange(visibleCandles);
  const ma10 = movingAverage(candles, 10);
  const ma30 = movingAverage(candles, 30);
  const ma10Path = buildMovingAveragePath(ma10, safeRange, priceRange.min, priceRange.max);
  const ma30Path = buildMovingAveragePath(ma30, safeRange, priceRange.min, priceRange.max);
  const clusters = createClusters(events, safeRange);
  const latest = visibleCandles[visibleCandles.length - 1];
  const candleWidth = mainCandleWidth(visibleCandles.length);
  const maxVolume = Math.max(1, ...visibleCandles.map((item) => item.volume));
  const readoutIndex = clampNumber(hoverPoint?.absoluteIndex ?? safeRange.end, 0, maxIndex);
  const selectedAnchorIndex = selectedEvent?.candle_index;
  const selectedRelativeIndex = selectedAnchorIndex === undefined ? -1 : selectedAnchorIndex - safeRange.start;
  const selectedAnchorCandle = selectedAnchorIndex !== undefined && selectedRelativeIndex >= 0 && selectedRelativeIndex < visibleCandles.length ? candles[selectedAnchorIndex] : null;
  const selectedAnchorPoint = selectedAnchorCandle ? {
    absoluteIndex: selectedAnchorIndex ?? safeRange.start,
    x: candleX(selectedRelativeIndex, visibleCandles.length),
    y: priceY(selectedAnchorCandle.close, priceRange.min, priceRange.max),
    price: selectedAnchorCandle.close,
  } : null;
  const activePointer = hoverPoint || selectedAnchorPoint;
  const activeReadoutIndex = clampNumber(activePointer?.absoluteIndex ?? readoutIndex, 0, maxIndex);
  const readoutCandle = candles[activeReadoutIndex] || latest;
  const readoutMa10 = ma10[activeReadoutIndex];
  const readoutMa30 = ma30[activeReadoutIndex];
  const readoutChange = readoutCandle?.open ? (readoutCandle.close - readoutCandle.open) / readoutCandle.open : 0;
  const tradeMarkers = trades
    .filter((trade) => trade.symbol === tradingSymbol)
    .map((trade, order) => ({
      trade,
      order,
      absoluteIndex: findTradeCandleIndex(trade, candles),
    }))
    .filter((item) => item.absoluteIndex >= safeRange.start && item.absoluteIndex <= safeRange.end);

  const updateRange = (next: ChartRange, isManual = true) => {
    if (isManual) onManualRange();
    setRange(clampRange(next, maxIndex));
  };

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
    const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * chartSpec.width;
    const plotX = (svgX - chartSpec.paddingX) / Math.max(1, chartSpec.width - chartSpec.paddingX * 2);
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

  function handleMouseDown(event: ReactMouseEvent<HTMLDivElement>) {
    dragRef.current = { x: event.clientX, range: safeRange, moved: false };
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
      start: dragRef.current.range.start + deltaCandles,
      end: dragRef.current.range.end + deltaCandles,
    });
  }

  function updateHoverPoint(event: ReactMouseEvent<HTMLDivElement>) {
    if (!visibleCandles.length || dragRef.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / Math.max(1, rect.width)) * chartSpec.width;
    const svgY = ((event.clientY - rect.top) / Math.max(1, rect.height)) * chartSpec.height;
    const normalized = (svgX - chartSpec.paddingX) / Math.max(1, chartSpec.width - chartSpec.paddingX * 2);
    const relativeIndex = clampNumber(Math.round(normalized * Math.max(0, visibleCandles.length - 1)), 0, Math.max(0, visibleCandles.length - 1));
    const absoluteIndex = safeRange.start + relativeIndex;
    const x = candleX(relativeIndex, visibleCandles.length);
    const y = clampNumber(svgY, chartSpec.priceTop, chartSpec.priceBottom);
    const priceRatio = (y - chartSpec.priceTop) / Math.max(1, chartSpec.priceBottom - chartSpec.priceTop);
    const price = priceRange.max - priceRatio * (priceRange.max - priceRange.min);
    setHoverPoint({ absoluteIndex, x, y, price });
  }

  function stopDrag() {
    dragRef.current = null;
    setHoverPoint(null);
  }

  function startZoomDrag(mode: ZoomDragMode, event: ReactMouseEvent<HTMLButtonElement | HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    zoomDragRef.current = {
      mode,
      x: event.clientX,
      range: safeRange,
      trackWidth: event.currentTarget.parentElement?.getBoundingClientRect().width || 1,
    };
  }

  useEffect(() => {
    const handleMove = (event: MouseEvent) => {
      const drag = zoomDragRef.current;
      if (!drag) return;
      const delta = Math.round(((event.clientX - drag.x) / drag.trackWidth) * Math.max(1, maxIndex));
      if (delta === 0) return;
      if (drag.mode === "start") {
        updateRange({ start: drag.range.start + delta, end: drag.range.end });
        return;
      }
      if (drag.mode === "end") {
        updateRange({ start: drag.range.start, end: drag.range.end + delta });
        return;
      }
      updateRange({ start: drag.range.start + delta, end: drag.range.end + delta });
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

  const markerY = 48;
  const rangeSpan = Math.max(1, maxIndex);
  const startPercent = maxIndex ? (safeRange.start / rangeSpan) * 100 : 0;
  const endPercent = maxIndex ? (safeRange.end / rangeSpan) * 100 : 100;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm sm:p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="mr-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Price Replay</span>
          <span className="text-xs font-semibold text-slate-600"><WithTerm term="K线">K 线</WithTerm></span>
          {zoomPresets.map((preset) => (
            <button
              aria-pressed={activePresetLabel === preset.label}
              className={`h-7 rounded-md border px-2.5 text-xs font-semibold transition-all duration-200 ${
                activePresetLabel === preset.label
                  ? "border-emerald-600 bg-emerald-600 text-white shadow-sm shadow-emerald-100"
                  : "border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:bg-emerald-50"
              }`}
              key={preset.label}
              onClick={() => onPresetRange(preset)}
              type="button"
            >
              {preset.label}
            </button>
          ))}
          <span className="hidden text-xs text-slate-400 sm:inline">Wheel zoom / drag pan</span>
        </div>
        <div className="text-right text-xs font-semibold text-slate-500">
          <span>{visibleCandles.length} candles</span>
          <span className="mx-2 text-slate-300">/</span>
          <span>{formatTime(latest?.time || "")}</span>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-emerald-600" />绿色：上涨</span>
        <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-red-600" />红色：下跌</span>
        <span><WithTerm term="MA10">MA10</WithTerm></span>
        <span><WithTerm term="MA30">MA30</WithTerm></span>
        <span><WithTerm term="成交量">成交量</WithTerm></span>
        <span>历史回放只展示当前模拟时间之前的行情与新闻，避免未来信息泄露。</span>
      </div>

          <EventBanner event={selectedEvent} onClose={onCloseBanner} onViewAnalysis={onViewAnalysis} />

      {readoutCandle ? (
        <div
          className="mt-2 max-w-full rounded-lg border border-slate-100 bg-white px-3 py-2 font-sans text-[13px] font-semibold leading-5 tracking-normal text-slate-950 shadow-sm shadow-slate-900/5"
          data-tour-id="ohlcv-readout"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums">
            <span>开: {formatNumber(readoutCandle.open, 2)}</span>
            <span>| 高: {formatNumber(readoutCandle.high, 2)}</span>
            <span>| 低: {formatNumber(readoutCandle.low, 2)}</span>
            <span>| 收: {formatNumber(readoutCandle.close, 2)}</span>
            <span>| 量: {formatNumber(readoutCandle.volume, 0)}</span>
            <span>| {readoutChange >= 0 ? "+" : ""}{formatPercent(readoutChange)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 tabular-nums" data-tour-id="ma-readout">
            <span className="text-amber-600">MA10: {readoutMa10 ? formatNumber(readoutMa10, 2) : "--"}</span>
            <span className="text-blue-600">MA30: {readoutMa30 ? formatNumber(readoutMa30, 2) : "--"}</span>
          </div>
        </div>
      ) : null}

      <div
        ref={chartContainerRef}
        className="relative mt-2 cursor-grab select-none rounded-lg bg-gradient-to-b from-slate-50 to-white active:cursor-grabbing"
        data-tour-id="kline-chart"
        onMouseDown={handleMouseDown}
        onMouseLeave={stopDrag}
        onMouseMove={handleMouseMove}
        onMouseUp={stopDrag}
        style={{ height: "clamp(340px, 58vh, 520px)" }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-4 z-20 rounded-lg"
          data-tour-id="risk-markers"
          style={{
            height: `${(40 / chartSpec.height) * 100}%`,
            top: `${((markerY - 20) / chartSpec.height) * 100}%`,
          }}
        />
        <svg aria-label="simulation candlestick chart" className="h-full w-full" preserveAspectRatio="none" viewBox={`0 0 ${chartSpec.width} ${chartSpec.height}`}>
          <defs>
            <filter height="240%" id="riskMarkerGlow" width="240%" x="-70%" y="-70%">
              <feGaussianBlur result="blur" stdDeviation="3" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          {[104, 172, 240, 308, 376].map((y) => (
            <line key={y} stroke="#dbe4f0" strokeDasharray="4 8" strokeWidth="1" x1={chartSpec.paddingX} x2={chartSpec.width - chartSpec.paddingX} y1={y} y2={y} />
          ))}
          <rect data-tour-id="volume-area" fill="transparent" height={chartSpec.volumeBottom - chartSpec.volumeTop + 10} width={chartSpec.width - chartSpec.paddingX * 2} x={chartSpec.paddingX} y={chartSpec.volumeTop - 5} />
          <g>
          <g>
          {clusters.map((cluster) => {
            const groupEvent = getDominantEvent(cluster.events);
            const anchorIndex = groupEvent.candle_index ?? safeRange.start;
            const candle = candles[anchorIndex];
            if (!candle) return null;
            const anchorY = priceY(candle.high, priceRange.min, priceRange.max);
            const active = selectedAnchorIndex === anchorIndex;
            const tone = resolveRiskTone(groupEvent);
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
            const x = candleX(index, visibleCandles.length);
            const up = candle.close >= candle.open;
            const color = up ? "#16a34a" : "#dc2626";
            const yHigh = priceY(candle.high, priceRange.min, priceRange.max);
            const yLow = priceY(candle.low, priceRange.min, priceRange.max);
            const yOpen = priceY(candle.open, priceRange.min, priceRange.max);
            const yClose = priceY(candle.close, priceRange.min, priceRange.max);
            const bodyY = Math.min(yOpen, yClose);
            const bodyHeight = Math.max(1.2, Math.abs(yOpen - yClose));
            const volumeBarHeight = volumeHeight(candle.volume, maxVolume);
            const absoluteIndex = safeRange.start + index;
            const highlighted = absoluteIndex === selectedAnchorIndex;
            return (
              <g key={`${candle.openTime}-${index}`}>
                {highlighted ? (
                  <rect fill={color} height={Math.max(18, yLow - yHigh + 10)} opacity="0.12" rx="5" stroke={color} strokeDasharray="3 4" strokeWidth="1.5" width={candleWidth + 11} x={x - (candleWidth + 11) / 2} y={yHigh - 5} />
                ) : null}
                <line stroke={color} strokeWidth="1.4" x1={x} x2={x} y1={yHigh} y2={yLow} />
                <rect fill={color} height={bodyHeight} rx="1.2" width={candleWidth} x={x - candleWidth / 2} y={bodyY} />
                <rect fill={color} height={volumeBarHeight} opacity="0.34" rx="0.8" width={candleWidth} x={x - candleWidth / 2} y={chartSpec.volumeBottom - volumeBarHeight} />
              </g>
            );
          })}
          {ma10Path ? <path d={ma10Path} fill="none" stroke="#d97706" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" /> : null}
          {ma30Path ? <path d={ma30Path} fill="none" stroke="#2563eb" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" /> : null}
          {tradeMarkers.map(({ absoluteIndex, order, trade }) => {
            const candle = candles[absoluteIndex];
            if (!candle) return null;
            const relativeIndex = absoluteIndex - safeRange.start;
            const x = candleX(relativeIndex, visibleCandles.length);
            const isBuy = trade.side === "BUY";
            const yHigh = priceY(candle.high, priceRange.min, priceRange.max);
            const yLow = priceY(candle.low, priceRange.min, priceRange.max);
            const y = isBuy
              ? clampNumber(yLow + 22 + (order % 2) * 9, chartSpec.priceTop + 16, chartSpec.priceBottom - 8)
              : clampNumber(yHigh - 22 - (order % 2) * 9, chartSpec.priceTop + 16, chartSpec.priceBottom - 8);
            const fill = isBuy ? "#059669" : "#dc2626";
            const label = isBuy ? "B" : "S";
            return (
              <g key={`${trade.time}-${trade.symbol}-${trade.side}-${order}`} pointerEvents="none">
                <title>{`${isBuy ? "买入" : "卖出"} ${trade.symbol} | ${formatUsdt(trade.price)} | ${formatNumber(trade.quantity, 8)}`}</title>
                {isBuy ? (
                  <path d={`M ${x} ${y - 11} L ${x - 8} ${y + 5} L ${x + 8} ${y + 5} Z`} fill={fill} opacity="0.95" stroke="#ffffff" strokeWidth="1.4" />
                ) : (
                  <path d={`M ${x} ${y + 11} L ${x - 8} ${y - 5} L ${x + 8} ${y - 5} Z`} fill={fill} opacity="0.95" stroke="#ffffff" strokeWidth="1.4" />
                )}
                <text fill="#ffffff" fontSize="7.5" fontWeight="900" textAnchor="middle" x={x} y={isBuy ? y + 2 : y + 1}>
                  {label}
                </text>
              </g>
            );
          })}
          {activePointer ? (
            <g pointerEvents="none">
              <line opacity="0.75" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" x1={activePointer.x} x2={activePointer.x} y1={chartSpec.priceTop} y2={chartSpec.volumeBottom} />
              <line opacity="0.75" stroke="#334155" strokeDasharray="4 4" strokeWidth="1" x1={chartSpec.paddingX} x2={chartSpec.width - chartSpec.paddingX} y1={activePointer.y} y2={activePointer.y} />
              <rect fill="#0f172a" height="18" rx="4" width="82" x={chartSpec.width - 104} y={clampNumber(activePointer.y - 9, chartSpec.priceTop, chartSpec.priceBottom - 18)} />
              <text fill="#ffffff" fontSize="10" fontWeight="700" textAnchor="middle" x={chartSpec.width - 63} y={clampNumber(activePointer.y + 4, chartSpec.priceTop + 13, chartSpec.priceBottom - 5)}>
                {formatNumber(activePointer.price, 2)}
              </text>
              <rect fill="#0f172a" height="18" rx="4" width="92" x={clampNumber(activePointer.x - 46, chartSpec.paddingX, chartSpec.width - chartSpec.paddingX - 92)} y={chartSpec.height - 22} />
              <text fill="#ffffff" fontSize="9.5" fontWeight="700" textAnchor="middle" x={clampNumber(activePointer.x, chartSpec.paddingX + 46, chartSpec.width - chartSpec.paddingX - 46)} y={chartSpec.height - 9}>
                {formatTime(candles[activePointer.absoluteIndex]?.time || "")}
              </text>
            </g>
          ) : null}
          {clusters.map((cluster) => {
            const groupEvent = getDominantEvent(cluster.events);
            const count = cluster.events.length;
            const isCluster = count > 1;
            const tone = resolveRiskTone(groupEvent);
            const flagWidth = isCluster ? Math.max(18, 12 + String(count).length * 7) : 8;
            const flagX = clampNumber(cluster.x, flagWidth / 2 + 3, chartSpec.width - flagWidth / 2 - 3);
            const active = cluster.events.some((event) => event.id === selectedEvent?.id);
            return (
              <g
                className="cursor-pointer transition-opacity"
                filter={active ? "url(#riskMarkerGlow)" : undefined}
                key={`${groupEvent.id}-${count}`}
                onClick={(event) => {
                  event.stopPropagation();
                  onInspectEvent(groupEvent);
                  if (isCluster) {
                    setOpenEventStack({
                      events: [...cluster.events].sort((a, b) => b.risk_score - a.risk_score),
                      x: chartSpec.width / 2,
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
          </g>
        </svg>
        {openEventStack ? (
          <EventStackPopover
            events={openEventStack.events}
            leftPercent={(openEventStack.x / chartSpec.width) * 100}
            onInspect={(event) => {
              onInspectEvent(event);
              setOpenEventStack(null);
            }}
          />
        ) : null}
      </div>

      <RiskHeatTimeline events={events} maxIndex={maxIndex} range={safeRange} />

      <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">DataZoom</span>
          <span className="text-xs text-slate-500">
            {safeRange.start} - {safeRange.end}
          </span>
        </div>
        <div className="relative h-16 rounded-md border border-slate-200 bg-white px-2 py-1">
          <svg className="absolute inset-x-2 top-2 h-10 w-[calc(100%-1rem)]" preserveAspectRatio="none" viewBox={`0 0 ${miniChartSpec.width} ${miniChartSpec.height}`}>
            {renderMiniCandles(candles)}
          </svg>
          <div className="absolute bottom-2 left-4 right-4 h-5">
            <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-200" />
            <button
              aria-label="drag selected zoom window"
              className="absolute top-1/2 h-4 -translate-y-1/2 rounded-full bg-emerald-500/35"
              onMouseDown={(event) => startZoomDrag("window", event)}
              style={{ left: `${startPercent}%`, width: `${Math.max(2, endPercent - startPercent)}%` }}
              type="button"
            />
            <button
              aria-label="zoom start"
              className="absolute top-1/2 h-5 w-3 -translate-x-1/2 -translate-y-1/2 rounded-sm border border-emerald-700 bg-white shadow"
              onMouseDown={(event) => startZoomDrag("start", event)}
              style={{ left: `${startPercent}%` }}
              type="button"
            />
            <button
              aria-label="zoom end"
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

function RiskHeatTimeline({ events, maxIndex, range }: { events: SimRiskEvent[]; maxIndex: number; range: ChartRange }) {
  const riskByIndex = useMemo(() => {
    const map = new Map<number, SimRiskEvent>();
    events.forEach((event) => {
      const index = event.candle_index;
      if (index === undefined || index < 0) return;
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
    const color = event ? resolveRiskTone(event).marker : "#cbd5e1";
    return { color, event, index };
  });
  return (
    <div className="mt-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">风险热力时间轴</span>
        <span className="text-xs text-slate-400">绿低 / 黄中 / 红高 / 灰无事件</span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
        {cells.map((cell) => (
          <div
            className="min-w-[2px] flex-1"
            key={cell.index}
            style={{ backgroundColor: cell.color, opacity: cell.event ? 0.92 : 0.32 }}
            title={cell.event ? `${formatTime(cell.event.time)} ${decodeEscapedUnicode(cell.event.title)} | ${cell.event.risk_score}` : `K ${cell.index}: no event`}
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

function EventStackPopover({
  events,
  leftPercent,
  onInspect,
}: {
  events: SimRiskEvent[];
  leftPercent: number;
  onInspect: (event: SimRiskEvent) => void;
}) {
  return (
    <div
      data-no-chart-wheel="true"
      className="risk-scroll absolute z-50 max-h-56 w-[320px] max-w-[calc(100vw-2rem)] -translate-x-1/2 overflow-y-auto overscroll-contain rounded-lg border border-slate-200 bg-white p-2 font-sans text-[13px] leading-normal tracking-normal shadow-2xl"
      onMouseDown={(event) => event.stopPropagation()}
      onWheel={(event) => event.stopPropagation()}
      style={{ left: `${clampNumber(leftPercent, 12, 88)}%`, top: "72px" }}
    >
      {events.map((event) => {
        const tone = resolveRiskTone(event);
        return (
          <button
            className="group flex h-10 w-full min-w-0 cursor-pointer items-center gap-2 rounded-md px-3 text-left transition-colors duration-150 hover:bg-slate-50"
            data-ai-context={simEventAiContext(event, "event_stack_popover")}
            key={event.id}
            onClick={() => onInspect(event)}
            type="button"
          >
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: tone.marker }} />
            <span className="shrink-0 whitespace-nowrap text-xs font-medium text-slate-400">{formatTime(event.time)}</span>
            <span className="min-w-0 flex-1 truncate whitespace-nowrap text-xs font-semibold text-slate-700 group-hover:text-slate-950">{event.title}</span>
          </button>
        );
      })}
    </div>
  );
}

function EventBanner({
  event,
  onClose,
  onViewAnalysis,
}: {
  event: SimRiskEvent | null;
  onClose: () => void;
  onViewAnalysis: (event: SimRiskEvent) => void;
}) {
  if (!event) return null;
  const tone = resolveRiskTone(event);
  const affected = (event.affected_assets?.length ? event.affected_assets : event.affected_symbols).slice(0, 3).join(" / ") || "--";
  return (
    <div
      className={`mt-2 flex h-12 min-w-0 items-center gap-3 rounded-lg border px-3 shadow-sm ${tone.border} ${tone.bg} ${tone.text}`}
      data-ai-context={simEventAiContext(event, "event_banner")}
      data-tour-id="risk-banner"
    >
      <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${tone.badge}`}>{event.risk_level || labels.riskEvent}</span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">{event.title}</h3>
          <span className="hidden shrink-0 text-xs font-semibold text-slate-600 md:inline">{affected}</span>
          <span className="shrink-0 text-xs font-semibold"><WithTerm term="风险分">{labels.riskScore}</WithTerm>: {event.risk_score}</span>
        </div>
      </div>
      <button
        className={`shrink-0 rounded-md border bg-white px-2.5 py-1.5 text-xs font-semibold ${tone.border} ${tone.softText} ${tone.hover}`}
        data-tour-id="ai-analysis-button"
        onClick={() => onViewAnalysis(event)}
        type="button"
      >
        <WithTerm term="AI分析">{labels.viewAi}</WithTerm>
      </button>
      <button className={`shrink-0 rounded-md px-2 text-lg leading-6 ${tone.softText} ${tone.hover}`} onClick={onClose} type="button" aria-label="close event banner">
        x
      </button>
    </div>
  );
}

function EventImpactReadout({ compact = false, impact }: { compact?: boolean; impact: EventImpact | null }) {
  const itemClass = compact ? "text-xs" : "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm";
  const labelClass = compact ? "text-slate-500" : "block text-xs font-semibold uppercase tracking-[0.12em] text-slate-500";
  const valueClass = compact ? "font-semibold text-slate-950" : "mt-1 block font-semibold text-slate-950";
  const formatImpact = (value: number | null) => value === null ? "--" : `${value >= 0 ? "+" : ""}${formatPercent(value)}`;
  const items = [
    ["前1小时", impact?.before1h ?? null],
    ["后1小时", impact?.after1h ?? null],
    ["后4小时", impact?.after4h ?? null],
    ["后24小时", impact?.after24h ?? null],
  ] as const;
  return (
    <div className={compact ? "grid grid-cols-2 gap-x-4 gap-y-1" : "grid gap-3 sm:grid-cols-4"}>
      {items.map(([label, value]) => (
        <div className={itemClass} key={label}>
          <span className={labelClass}>{label}</span>
          <span className={`${value !== null && value < 0 ? "text-red-600" : value !== null && value > 0 ? "text-emerald-600" : valueClass} ${compact ? "ml-1 font-semibold" : valueClass}`}>
            {formatImpact(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

function TradePanel({
  buyAmount,
  currentRiskEvent,
  hasAffectedPosition,
  isBusy,
  onBuy,
  onBuyAmountChange,
  onDismissRisk,
  onSell,
  onSellAll,
  onSellHalfRisk,
  onSellQuantityChange,
  onSellRiskAll,
  onViewAnalysis,
  selectedPosition,
  selectedPrice,
  sellQuantity,
  state,
}: {
  buyAmount: string;
  currentRiskEvent: SimRiskEvent | null;
  hasAffectedPosition: boolean;
  isBusy: boolean;
  onBuy: () => void;
  onBuyAmountChange: (value: string) => void;
  onDismissRisk: () => void;
  onSell: () => void;
  onSellAll: () => void;
  onSellHalfRisk: () => void;
  onSellQuantityChange: (value: string) => void;
  onSellRiskAll: () => void;
  onViewAnalysis: () => void;
  selectedPosition: SimPosition | null;
  selectedPrice: number;
  sellQuantity: string;
  state: SimState | null;
}) {
  return (
    <aside className="risk-panel min-w-0 rounded-lg p-3">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Trade</h2>
      {currentRiskEvent ? (
        <RiskEventInTradePanel
          event={currentRiskEvent}
          hasAffectedPosition={hasAffectedPosition}
          isBusy={isBusy}
          onDismiss={onDismissRisk}
          onSellAll={onSellRiskAll}
          onSellHalf={onSellHalfRisk}
          onViewAnalysis={onViewAnalysis}
        />
      ) : null}
      <div className="space-y-3">
        <InfoBlock label={labels.currentPrice} value={formatUsdt(selectedPrice)} />
        <InfoBlock label={<WithTerm term="USDT">{labels.cash}</WithTerm>} value={formatUsdt(state?.cash ?? 10000)} />

        <label className="block" data-tour-id="buy-area">
          <span className="text-sm font-semibold text-slate-700"><WithTerm term="USDT">{labels.buyAmount}</WithTerm></span>
          <input
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-base text-slate-900"
            onChange={(event) => onBuyAmountChange(event.target.value)}
            type="number"
            value={buyAmount}
          />
        </label>
        <button className="h-10 w-full rounded-lg bg-emerald-700 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50" disabled={isBusy} onClick={onBuy} type="button">
          {labels.buy}
        </button>

        <label className="block" data-tour-id="sell-area">
          <span className="text-sm font-semibold text-slate-700">{labels.sellQuantity}</span>
          <input
            className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-base text-slate-900"
            onChange={(event) => onSellQuantityChange(event.target.value)}
            type="number"
            value={sellQuantity}
          />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <button className="h-10 rounded-lg bg-slate-950 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50" disabled={isBusy} onClick={onSell} type="button">
            {labels.sell}
          </button>
          <button className="h-10 rounded-lg border border-slate-200 bg-white text-sm font-semibold text-slate-500 hover:bg-slate-50 disabled:opacity-50" disabled={isBusy || !selectedPosition} onClick={onSellAll} type="button">
            {labels.sellAll}
          </button>
        </div>
        <InfoBlock
          label={labels.currentPosition}
          value={selectedPosition ? formatNumber(selectedPosition.quantity, 8) : "0"}
          subValue={selectedPosition ? formatUsdt(selectedPosition.market_value) : "$0.00"}
          tourId="position-area"
        />
      </div>
    </aside>
  );
}

function RiskEventInTradePanel({
  event,
  hasAffectedPosition,
  isBusy,
  onDismiss,
  onSellAll,
  onSellHalf,
  onViewAnalysis,
}: {
  event: SimRiskEvent;
  hasAffectedPosition: boolean;
  isBusy: boolean;
  onDismiss: () => void;
  onSellAll: () => void;
  onSellHalf: () => void;
  onViewAnalysis: () => void;
}) {
  const tone = resolveRiskTone(event);
  return (
    <section
      className={`mb-4 min-w-0 rounded-lg border p-3 shadow-sm ${tone.border} ${tone.bg} ${tone.text}`}
      data-ai-context={simEventAiContext(event, "trade_panel_event")}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-semibold ${tone.badge}`}>{event.risk_level || labels.riskEvent}</span>
          <span className="shrink-0 text-xs font-semibold"><WithTerm term="风险分">{labels.riskScore}</WithTerm>: {event.risk_score}</span>
        </div>
        <button className={`shrink-0 rounded-md px-2 text-lg leading-6 ${tone.softText} ${tone.hover}`} onClick={onDismiss} type="button" aria-label="close risk event">
          x
        </button>
      </div>
      <h3 className="mt-2 min-w-0 max-w-full whitespace-normal break-words text-sm font-semibold leading-5">{event.title}</h3>
      <p className={`mt-1 whitespace-normal break-words text-xs leading-5 ${tone.softText}`}>{event.summary || event.risk_type}</p>
      <p className={`mt-2 text-xs font-medium ${tone.softText}`}>
        {labels.affected}: {(event.affected_assets?.length ? event.affected_assets : event.affected_symbols).join(" / ")}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button className={`rounded-md border bg-white px-2 py-2 text-xs font-semibold ${tone.border} ${tone.softText} ${tone.hover}`} onClick={onDismiss} type="button">
          {labels.hold}
        </button>
        <button className={`rounded-md px-2 py-2 text-xs font-semibold disabled:opacity-50 ${tone.badge}`} disabled={isBusy || !hasAffectedPosition} onClick={onSellHalf} type="button">
          {labels.sellHalf}
        </button>
        <button className="rounded-md bg-slate-950 px-2 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50" disabled={isBusy || !hasAffectedPosition} onClick={onSellAll} type="button">
          {labels.sellAll}
        </button>
        <button className="rounded-md border border-slate-200 bg-white px-2 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={onViewAnalysis} type="button">
          <WithTerm term="AI分析">{labels.viewAi}</WithTerm>
        </button>
      </div>
    </section>
  );
}

function SymbolNewsTimeline({ events, selectedSymbol, simTime }: { events: SimRiskEvent[]; selectedSymbol: string; simTime: string }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const sortedEvents = useMemo(() => [...events].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()), [events]);
  const latestId = sortedEvents[0]?.id;

  useEffect(() => {
    if (!latestId) return;
    const highlightTimer = window.setTimeout(() => {
      setHighlightedId(latestId);
      scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }, 0);
    const clearTimer = window.setTimeout(() => setHighlightedId(null), 2200);
    return () => {
      window.clearTimeout(highlightTimer);
      window.clearTimeout(clearTimer);
    };
  }, [latestId]);

  return (
    <section className="risk-panel rounded-lg p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Related News Timeline</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-950">{selectedSymbol}</h2>
        </div>
        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-500">{formatTime(simTime)}</span>
      </div>
      <div className="risk-scroll max-h-72 space-y-3 overflow-y-auto pr-1" ref={scrollRef}>
        {sortedEvents.length ? sortedEvents.map((event) => {
          const tone = resolveRiskTone(event);
          return (
            <article
              className={`rounded-lg border p-3 transition-colors duration-700 ${highlightedId === event.id ? `${tone.border} ${tone.bg}` : "border-slate-200 bg-white"}`}
              data-ai-context={simEventAiContext(event, "symbol_news_timeline")}
              key={event.id}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded-md px-2 py-1 text-xs font-semibold ${tone.badge}`}>{event.risk_level || labels.riskEvent}</span>
                <span className={`text-xs font-semibold ${tone.softText}`}>{labels.riskScore}: {event.risk_score}</span>
                <span className="text-xs text-slate-400">{formatTime(event.time)}</span>
              </div>
              <h3 className="mt-2 whitespace-normal break-words text-sm font-semibold text-slate-950">{event.title}</h3>
              <p className="mt-1 line-clamp-2 whitespace-normal break-words text-xs leading-5 text-slate-600">{event.summary || event.risk_type}</p>
            </article>
          );
        }) : (
          <div className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">{labels.noNews}</div>
        )}
      </div>
    </section>
  );
}

function ReplayReportModal({
  assetHistory,
  events,
  onClose,
  state,
}: {
  assetHistory: AssetSnapshot[];
  events: SimRiskEvent[];
  onClose: () => void;
  state: SimState;
}) {
  const maxDrawdown = calculateMaxDrawdown(assetHistory);
  const winStats = calculateWinRate(state.trade_history);
  const returnRate = state.return_rate;
  const highRiskEvents = events.filter((event) => event.risk_score >= 70);
  const responseSummary = highRiskEvents.reduce(
    (summary, event) => {
      const eventTime = new Date(event.time).getTime();
      const affected = new Set(event.affected_symbols || []);
      const followupTrades = state.trade_history.filter((trade) => {
        const tradeTime = new Date(trade.time).getTime();
        return tradeTime >= eventTime && tradeTime <= eventTime + 60 * 60 * 1000 && affected.has(trade.symbol);
      });
      if (followupTrades.some((trade) => trade.side === "SELL")) summary.reduce += 1;
      else if (followupTrades.some((trade) => trade.side === "BUY")) summary.add += 1;
      else summary.hold += 1;
      return summary;
    },
    { add: 0, hold: 0, reduce: 0 },
  );
  const maxConcentration = state.total_asset
    ? Math.max(0, ...state.positions.map((position) => position.market_value / state.total_asset))
    : 0;
  const returnScore = clampNumber(50 + returnRate * 300, 0, 100);
  const drawdownScore = clampNumber(100 - maxDrawdown * 400, 0, 100);
  const newsScore = highRiskEvents.length ? (responseSummary.reduce / highRiskEvents.length) * 100 : 80;
  const overtradePenalty = Math.max(0, state.trade_history.length - 16) * 2;
  const concentrationPenalty = Math.max(0, maxConcentration - 0.6) * 80;
  const concentrationScore = clampNumber(100 - maxConcentration * 100, 0, 100);
  const diversityScore = state.positions.length <= 1
    ? (state.positions.length ? 45 : 75)
    : clampNumber(50 + Math.min(state.positions.length, 5) * 10 - maxConcentration * 30, 0, 100);
  const totalScore = clampNumber(returnScore * 0.35 + drawdownScore * 0.3 + newsScore * 0.25 - overtradePenalty - concentrationPenalty, 0, 100);
  const radarMetrics = [
    { label: "收益率", value: returnScore },
    { label: "回撤控制", value: drawdownScore },
    { label: "风险响应", value: newsScore },
    { label: "仓位控制", value: concentrationScore },
    { label: "资产分散", value: diversityScore },
  ];
  const traderType = totalScore >= 78 && newsScore >= 60
    ? "风控型交易者"
    : state.trade_history.length > 24
      ? "情绪型交易者"
      : returnRate > 0.04 && maxDrawdown > 0.12
        ? "激进型交易者"
        : "稳健型交易者";
  const mainHoldings = state.positions.length
    ? state.positions
      .slice()
      .sort((a, b) => b.market_value - a.market_value)
      .slice(0, 3)
      .map((position) => position.symbol)
      .join(" / ")
    : "现金为主";
  const aiComment = totalScore >= 78
    ? "你在收益和回撤之间保持了较好平衡，高风险事件后的仓位处理较主动。"
    : newsScore < 35
      ? "高风险新闻出现后减仓动作不足，建议将新闻响应纳入交易纪律。"
      : state.trade_history.length > 24
        ? "交易频率偏高，容易被短线波动牵引，建议减少无计划交易。"
        : "整体交易节奏较稳，可以进一步优化事件发生后的止损与减仓规则。";

  return (
    <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/50 p-4" onMouseDown={onClose}>
      <section className="max-h-[88vh] w-full max-w-5xl overflow-hidden rounded-lg bg-white shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flex items-start justify-between gap-4 border-b border-emerald-100 bg-emerald-50 px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">Replay Report</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">本次模拟交易复盘报告</h2>
          </div>
          <button className="rounded-md border border-emerald-200 bg-white px-3 py-1 text-sm font-semibold text-emerald-700 hover:bg-emerald-100" onClick={onClose} type="button">
            x
          </button>
        </header>
        <div className="risk-scroll max-h-[calc(88vh-84px)] overflow-y-auto overscroll-contain p-5">
          <div className="grid gap-3 md:grid-cols-4">
            <InfoBlock label="初始资金" value={formatUsdt(10000)} />
            <InfoBlock label="最终资产" value={formatUsdt(state.total_asset)} />
            <InfoBlock label="总收益率" value={formatPercent(returnRate)} />
            <InfoBlock label="风控评分" value={`${Math.round(totalScore)}/100`} />
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <InfoBlock label="最大回撤" value={formatPercent(maxDrawdown)} />
            <InfoBlock label="交易次数" value={`${state.trade_history.length} 次`} />
            <InfoBlock label="胜率" value={winStats.sellCount ? `${winStats.winCount}/${winStats.sellCount} (${formatPercent(winStats.winRate)})` : "--"} />
            <InfoBlock label="主要持仓" value={mainHoldings} />
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_1fr]">
            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-950">风控评分构成</h3>
              <div className="mt-3 space-y-2 text-sm text-slate-700">
                <ScoreRow label="收益得分" value={returnScore} />
                <ScoreRow label="风险控制得分" value={drawdownScore} />
                <ScoreRow label="新闻响应得分" value={newsScore} />
                <ScoreRow label="仓位控制得分" value={concentrationScore} />
                <p className="pt-2 text-xs text-slate-500">过度交易惩罚：-{overtradePenalty.toFixed(0)} | 仓位集中惩罚：-{concentrationPenalty.toFixed(0)}</p>
              </div>
            </section>

            <section className="rounded-lg border border-slate-200 bg-white p-4">
              <h3 className="text-sm font-semibold text-slate-950">高风险新闻响应</h3>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                <InfoBlock label="减仓" value={`${responseSummary.reduce}`} />
                <InfoBlock label="观望" value={`${responseSummary.hold}`} />
                <InfoBlock label="加仓" value={`${responseSummary.add}`} />
              </div>
              <p className="mt-3 text-sm leading-6 text-slate-600">统计口径：高风险事件发生后 1 小时内，若对受影响币种发生卖出视为减仓，买入视为加仓，否则视为观望。</p>
            </section>
          </div>

          <section className="mt-5 rounded-lg border border-slate-200 bg-white p-4">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="max-w-xl">
                <h3 className="text-sm font-semibold text-slate-950">风控能力雷达图</h3>
                <p className="mt-2 text-sm leading-6 text-slate-600">收益高不等于风控好。这里同时衡量收益、回撤、新闻响应、仓位集中和资产分散，让复盘更贴近 CryptoRisk 的风控目标。</p>
              </div>
              <RiskRadarChart metrics={radarMetrics} />
            </div>
          </section>

          <section className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
            <h3 className="text-sm font-semibold text-emerald-900">AI 对用户操作的评价</h3>
            <p className="mt-2 text-sm leading-7 text-emerald-800">{aiComment}</p>
            <p className="mt-3 text-lg font-semibold text-slate-950">一句话总结：{traderType}</p>
          </section>
        </div>
      </section>
    </div>
  );
}

function ScoreRow({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span>{label}</span>
        <span className="font-semibold text-slate-950">{Math.round(value)}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div className="h-2 rounded-full bg-emerald-600" style={{ width: `${clampNumber(value, 0, 100)}%` }} />
      </div>
    </div>
  );
}

function RiskRadarChart({ metrics }: { metrics: Array<{ label: string; value: number }> }) {
  const center = 96;
  const radius = 70;
  const angleStep = (Math.PI * 2) / metrics.length;
  const pointFor = (index: number, value: number) => {
    const angle = -Math.PI / 2 + index * angleStep;
    const scaled = radius * clampNumber(value, 0, 100) / 100;
    return {
      x: center + Math.cos(angle) * scaled,
      y: center + Math.sin(angle) * scaled,
    };
  };
  const ringPoints = (value: number) =>
    metrics.map((_, index) => {
      const point = pointFor(index, value);
      return `${point.x},${point.y}`;
    }).join(" ");
  const areaPoints = metrics.map((metric, index) => {
    const point = pointFor(index, metric.value);
    return `${point.x},${point.y}`;
  }).join(" ");
  return (
    <div className="mx-auto shrink-0 md:mx-0">
      <svg className="h-48 w-48 sm:h-56 sm:w-56" viewBox="0 0 192 192" role="img" aria-label="risk control radar chart">
        {[25, 50, 75, 100].map((ring) => (
          <polygon key={ring} points={ringPoints(ring)} fill="none" stroke="#dbe4f0" strokeWidth="1" />
        ))}
        {metrics.map((metric, index) => {
          const outer = pointFor(index, 100);
          const label = pointFor(index, 118);
          return (
            <g key={metric.label}>
              <line x1={center} y1={center} x2={outer.x} y2={outer.y} stroke="#e2e8f0" strokeWidth="1" />
              <text fill="#475569" fontSize="9" fontWeight="700" textAnchor="middle" x={label.x} y={label.y}>
                {metric.label}
              </text>
            </g>
          );
        })}
        <polygon points={areaPoints} fill="#10b981" fillOpacity="0.22" stroke="#059669" strokeLinejoin="round" strokeWidth="2.5" />
        {metrics.map((metric, index) => {
          const point = pointFor(index, metric.value);
          return <circle cx={point.x} cy={point.y} fill="#059669" key={metric.label} r="3.2" stroke="#fff" strokeWidth="1.5" />;
        })}
      </svg>
    </div>
  );
}

function RiskAnalysisPanel({ event, impact, onClose }: { event: SimRiskEvent; impact: EventImpact | null; onClose: () => void }) {
  const tone = resolveRiskTone(event);
  const affected = (event.affected_assets?.length ? event.affected_assets : event.affected_symbols).join(" / ") || "--";
  const displayTitle = decodeEscapedUnicode(event.title);
  const displayRiskType = decodeEscapedUnicode(event.risk_type || "--");
  const riskAction = event.risk_score >= 70
    ? "\u5efa\u8bae\u7acb\u5373\u964d\u4f4e\u66b4\u9732\u4ed3\u4f4d\uff0c\u5c06\u98ce\u9669\u5e01\u79cd\u51cf\u4ed3 30%-50%\uff0c\u4fdd\u7559\u73b0\u91d1\u5e94\u5bf9\u4e8c\u6b21\u6ce2\u52a8\u3002"
    : event.risk_score >= 40
      ? "\u5efa\u8bae\u6682\u505c\u8ffd\u9ad8\uff0c\u89c2\u5bdf 1-2 \u6839 15m K \u7ebf\u662f\u5426\u6536\u590d\u5173\u952e\u4ef7\u4f4d\uff0c\u5fc5\u8981\u65f6\u8f7b\u4ed3\u9632\u5b88\u3002"
      : "\u6682\u65f6\u4e0d\u9700\u8fc7\u5ea6\u907f\u9669\uff0c\u4fdd\u6301\u539f\u6709\u4ed3\u4f4d\u8282\u594f\uff0c\u6301\u7eed\u8ddf\u8e2a\u540e\u7eed\u65b0\u95fb\u662f\u5426\u5347\u7ea7\u3002";
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4" onMouseDown={onClose}>
      <section
        className="max-h-[86vh] w-full max-w-4xl overflow-hidden rounded-lg bg-white shadow-2xl"
        data-ai-context={simEventAiContext(event, "ai_analysis_modal")}
        onMouseDown={(mouseEvent) => mouseEvent.stopPropagation()}
      >
        <header className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${tone.border} ${tone.bg}`}>
          <div className="min-w-0">
            <p className={`text-xs font-semibold uppercase tracking-[0.16em] ${tone.softText}`}>{labels.analysis}</p>
            <h2 className="mt-1 whitespace-normal break-words text-lg font-semibold text-slate-950">{displayTitle}</h2>
          </div>
          <button className={`shrink-0 rounded-md border bg-white px-3 py-1 text-sm font-semibold ${tone.border} ${tone.softText} ${tone.hover}`} onClick={onClose} type="button">
            x
          </button>
        </header>
        <div className="risk-scroll max-h-[calc(86vh-84px)] overflow-y-auto overscroll-contain p-5">
          <div className="grid gap-3 md:grid-cols-3">
            <InfoBlock label={<WithTerm term="风险分">{labels.riskScore}</WithTerm>} value={String(event.risk_score)} />
            <InfoBlock label={labels.riskEvent} value={displayRiskType} />
            <InfoBlock label={labels.affected} value={affected} />
          </div>
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-semibold text-slate-950">事件窗口价格影响</h3>
            <EventImpactReadout impact={impact} />
          </div>
          <RiskExplanationChain event={event} riskAction={riskAction} />
          <div className="mt-5 grid gap-4">
            <AnalysisSection
              accentClass={tone.softText}
              body={event.summary || event.evidence || "\u8be5\u65b0\u95fb\u663e\u793a\u5e02\u573a\u51fa\u73b0\u9700\u8981\u5173\u6ce8\u7684\u98ce\u9669\u4fe1\u53f7\u3002"}
              kicker="01"
              title="\u4e8b\u4ef6\u6838\u5fc3\u6458\u8981"
            />
            <AnalysisSection
              accentClass="text-red-700"
              body={`\u8be5\u4e8b\u4ef6\u5f52\u5c5e\u4e8e\u300c${event.risk_type || "\u5e02\u573a\u98ce\u9669"}\u300d\u3002\u5f53\u98ce\u9669\u4fe1\u53f7\u4e0e ${affected} \u76f8\u5173\u65f6\uff0c\u77ed\u7ebf\u4ea4\u6613\u8005\u5f80\u5f80\u4f1a\u4f18\u5148\u964d\u4f4e\u66b4\u9732\uff0c\u9020\u6210\u4e70\u76d8\u72b9\u8c6b\u3001\u5356\u76d8\u524d\u7f6e\uff0c\u5e76\u653e\u5927 15m \u7ea7\u522b\u7684\u6ce2\u52a8\u3002`}
              kicker="02"
              title="\u76d8\u9762\u4f20\u5bfc\u903b\u8f91"
            />
            <AnalysisSection
              accentClass="text-amber-700"
              body="\u5386\u53f2\u4e0a\uff0c\u4ea4\u6613\u6240\u5f02\u5e38\u3001\u76d1\u7ba1\u6d88\u606f\u3001\u94fe\u4e0a\u653b\u51fb\u548c\u5927\u989d\u8d44\u91d1\u8fc1\u79fb\u5e38\u5728 24 \u5c0f\u65f6\u5185\u5f15\u53d1\u4e8c\u6b21\u6ce2\u52a8\u3002\u7c7b\u4f3c\u573a\u666f\u4e2d\uff0c\u5e02\u573a\u5f80\u5f80\u5148\u51fa\u73b0\u60c5\u7eea\u6027\u629b\u538b\uff0c\u968f\u540e\u624d\u4f1a\u6839\u636e\u5b98\u65b9\u6f84\u6e05\u6216\u8d44\u91d1\u9762\u7a33\u5b9a\u9010\u6b65\u4fee\u590d\u3002"
              kicker="03"
              title="\u5386\u53f2\u76f8\u4f3c\u590d\u76d8"
            />
            <AnalysisSection
              accentClass="text-emerald-700"
              body={riskAction}
              kicker="04"
              title="AI \u98ce\u63a7\u64cd\u4f5c\u5efa\u8bae"
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function RiskExplanationChain({ event, riskAction }: { event: SimRiskEvent; riskAction: string }) {
  const entities = extractRiskEntities(event);
  const affected = (event.affected_assets?.length ? event.affected_assets : event.affected_symbols).join(" / ") || "--";
  const steps = [
    { label: "新闻文本", value: truncateText(decodeEscapedUnicode(event.title), 52) },
    { label: "实体识别", value: entities.length ? entities.join(" / ") : "暂无明确实体" },
    { label: "风险类型", value: decodeEscapedUnicode(event.risk_type || "综合市场风险") },
    { label: "影响币种", value: affected },
    { label: "风险等级", value: `${decodeEscapedUnicode(event.risk_level || labels.riskEvent)} ${event.risk_score}/100` },
    { label: "交易建议", value: decodeEscapedUnicode(riskAction) },
  ];
  return (
    <section className="mt-4 rounded-lg border border-slate-200 bg-slate-50/80 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-950">风险解释链</h3>
        <span className="text-xs font-semibold text-slate-400">Explainable AI Risk Path</span>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-6">
        {steps.map((step, index) => (
          <div className="relative rounded-lg border border-slate-200 bg-white px-3 py-2" key={step.label}>
            <span className="text-[11px] font-bold text-emerald-600">{String(index + 1).padStart(2, "0")}</span>
            <p className="mt-1 text-xs font-semibold text-slate-500">{step.label}</p>
            <p className="mt-1 line-clamp-3 text-xs leading-5 text-slate-800">{step.value}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function AnalysisSection({ accentClass, body, kicker, title }: { accentClass: string; body: string; kicker: string; title: string }) {
  const displayTitle = decodeEscapedUnicode(title);
  const displayBody = decodeEscapedUnicode(body);
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className={`text-xs font-bold ${accentClass}`}>{kicker}</span>
        <h3 className="text-sm font-semibold text-slate-950">{displayTitle}</h3>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{displayBody}</p>
    </section>
  );
}

function PositionsTable({ state }: { state: SimState | null }) {
  const positions = state?.positions || [];
  return (
    <DataPanel title={labels.positions}>
      <div className="risk-scroll overflow-x-auto">
        <table className="risk-table min-w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-[0.12em] text-slate-500">
            <tr>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Qty</th>
              <th className="px-3 py-2">Avg</th>
              <th className="px-3 py-2">Value</th>
              <th className="px-3 py-2">PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {positions.length ? positions.map((position) => (
              <tr key={position.symbol}>
                <td className="px-3 py-2 font-semibold text-slate-900">{position.symbol}</td>
                <td className="px-3 py-2 text-slate-600">{formatNumber(position.quantity, 8)}</td>
                <td className="px-3 py-2 text-slate-600">{formatUsdt(position.avg_cost)}</td>
                <td className="px-3 py-2 text-slate-600">{formatUsdt(position.market_value)}</td>
                <td className={`px-3 py-2 font-semibold ${position.pnl >= 0 ? "text-emerald-600" : "text-red-600"}`}>{formatUsdt(position.pnl)} / {formatPercent(position.pnl_rate)}</td>
              </tr>
            )) : (
              <tr><td className="px-3 py-6 text-center text-slate-500" colSpan={5}>No positions</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </DataPanel>
  );
}

function TradesTable({ state }: { state: SimState | null }) {
  const trades = [...(state?.trade_history || [])].reverse();
  return (
    <DataPanel title={labels.trades}>
      <div className="risk-scroll max-h-80 overflow-auto">
        <table className="risk-table min-w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-[0.12em] text-slate-500">
            <tr>
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Side</th>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {trades.length ? trades.map((trade, index) => (
              <tr key={`${trade.time}-${trade.symbol}-${index}`}>
                <td className="px-3 py-2 text-slate-500">{formatTime(trade.time)}</td>
                <td className={`px-3 py-2 font-semibold ${trade.side === "BUY" ? "text-emerald-600" : "text-red-600"}`}>{trade.side}</td>
                <td className="px-3 py-2 font-semibold text-slate-900">{trade.symbol}</td>
                <td className="px-3 py-2 text-slate-600">{formatUsdt(trade.amount_usdt)}</td>
              </tr>
            )) : (
              <tr><td className="px-3 py-6 text-center text-slate-500" colSpan={4}>No trades</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </DataPanel>
  );
}

function InfoBlock({ label, subValue, tourId, value }: { label: ReactNode; subValue?: string; tourId?: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2.5" data-tour-id={tourId}>
      <p className="text-xs font-semibold text-slate-600">{label}</p>
      <p className="mt-1 whitespace-normal break-words text-xl font-semibold text-slate-950">{value}</p>
      {subValue ? <p className="mt-1 text-sm text-slate-500">{subValue}</p> : null}
    </div>
  );
}

function Metric({ label, tone, value }: { label: ReactNode; tone?: "up" | "down"; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${tone === "up" ? "text-emerald-600" : tone === "down" ? "text-red-600" : "text-slate-950"}`}>{value}</p>
    </div>
  );
}

function ControlButton({ children, disabled, onClick, tone, tourId }: { children: ReactNode; disabled?: boolean; onClick: () => void; tone?: "green" | "red"; tourId?: string }) {
  const color = tone === "green"
    ? "bg-emerald-700 text-white hover:bg-emerald-800"
    : tone === "red"
      ? "border border-red-200 bg-red-50 text-red-600 hover:bg-red-100"
      : "bg-slate-950 text-white hover:bg-slate-800";
  return (
    <button className={`h-9 rounded-lg px-3 text-xs font-semibold disabled:opacity-50 ${color}`} data-tour-id={tourId} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  );
}

function DataPanel({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="risk-panel rounded-lg p-4">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</h2>
      {children}
    </section>
  );
}

export default SimTradingPanel;
