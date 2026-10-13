import { requestJson } from "@/lib/api";

export const marketIntervals = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
export type MarketInterval = typeof marketIntervals[number];
export type MarketSymbol = { symbol: string; base: string; quote: string; name: string };
export type Candle = { time: number; open: number; high: number; low: number; close: number; volume: number };
export type Ticker = { symbol: string; price: number; change_pct: number; high: number; low: number; volume: number; quote_volume: number; time: number };
export type Depth = { bids: Array<{ price: number; quantity: number }>; asks: Array<{ price: number; quantity: number }> };
export type Trade = { id: string; time: number; price: number; quantity: number; side: "buy" | "sell" };
export type Feed<T> = { data: T; source: string; as_of: number; stale: boolean };
export const maxCandles = 2000;

export function marketRequest<T>(path: string, signal: AbortSignal) {
  return requestJson<T>(`/api/market/${path}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(15_000)]) });
}
export function candlePath(symbol: string, interval: MarketInterval, limit = 500, endTime?: number) {
  const params = new URLSearchParams({ symbol, interval, limit: String(limit) });
  if (endTime !== undefined) params.set("end_time", String(endTime));
  return `candles?${params}`;
}
export function mergeCandles(previous: Candle[], incoming: Candle[], cap = maxCandles): Candle[] {
  const rows = new Map<number, Candle>();
  for (const candle of [...previous, ...incoming]) {
    if (![candle.time, candle.open, candle.high, candle.low, candle.close, candle.volume].every(Number.isFinite)) continue;
    if (candle.time <= 0 || candle.low <= 0 || candle.volume < 0 || candle.high < Math.max(candle.open, candle.close, candle.low) || candle.low > Math.min(candle.open, candle.close)) continue;
    rows.set(candle.time, candle);
  }
  return [...rows.values()].sort((a, b) => a.time - b.time).slice(-cap);
}
export function sma(candles: Candle[], period: number) {
  const result: Array<{ time: number; value: number }> = [];
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) result.push({ time: candles[i].time, value: sum / period });
  }
  return result;
}
export function ema(candles: Candle[], period: number) {
  if (candles.length < period) return [];
  let value = candles.slice(0, period).reduce((sum, candle) => sum + candle.close, 0) / period;
  const result = [{ time: candles[period - 1].time, value }];
  for (let i = period; i < candles.length; i++) {
    value += (candles[i].close - value) * 2 / (period + 1);
    result.push({ time: candles[i].time, value });
  }
  return result;
}
export function rsi(candles: Candle[], period = 14) {
  const result: Array<{ time: number; value: number }> = [];
  let gain = 0, loss = 0;
  for (let i = 1; i < candles.length; i++) {
    const delta = candles[i].close - candles[i - 1].close;
    if (i <= period) { gain += Math.max(0, delta) / period; loss += Math.max(0, -delta) / period; }
    else { gain = (gain * (period - 1) + Math.max(0, delta)) / period; loss = (loss * (period - 1) + Math.max(0, -delta)) / period; }
    if (i >= period) result.push({ time: candles[i].time, value: gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss) });
  }
  return result;
}
export function price(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: value >= 1 ? 2 : 4, maximumFractionDigits: value >= 100 ? 2 : value >= 1 ? 4 : 8 });
}
export function compact(value: number | undefined) {
  if (value === undefined || !Number.isFinite(value)) return "—";
  if (value !== 0 && Math.abs(value) < 0.00000001) return value.toExponential(2);
  if (Math.abs(value) < 1) return value.toLocaleString("en-US", { maximumSignificantDigits: 4 });
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}
export function downloadText(contents: string, filename: string, type = "text/csv;charset=utf-8") {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
