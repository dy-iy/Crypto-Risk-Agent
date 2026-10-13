"use client";

import { memo, forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { CandlestickSeries, LineSeries, HistogramSeries, createChart, ColorType, CrosshairMode, LineStyle, type IChartApi, type ISeriesApi, type UTCTimestamp, type Time } from "lightweight-charts";
import { type Candle, sma, ema, rsi, price, compact } from "@/lib/market";

export type ChartHandle = { fit: () => void; latest: () => void; zoom: (factor: number) => void; screenshot: () => void };
type Props = { candles: Candle[]; mode: "candles" | "line"; showMA: boolean; showEMA: boolean; showRSI: boolean; logarithmic: boolean };
const MarketChart = memo(forwardRef<ChartHandle, Props>(function MarketChart({ candles, mode, showMA, showEMA, showRSI, logarithmic }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<{ candle: ISeriesApi<"Candlestick">; line: ISeriesApi<"Line">; volume: ISeriesApi<"Histogram">; ma10: ISeriesApi<"Line">; ma30: ISeriesApi<"Line">; ema20: ISeriesApi<"Line">; rsi14: ISeriesApi<"Line"> } | null>(null);
  const previousRef = useRef<Candle[]>([]);
  const candleMap = useRef(new Map<number, Candle>());
  const [hover, setHover] = useState<Candle | null>(null);
  const hoverFrame = useRef<number | null>(null);
  useImperativeHandle(ref, () => ({
    fit: () => chartRef.current?.timeScale().fitContent(),
    latest: () => chartRef.current?.timeScale().scrollToRealTime(),
    zoom: factor => {
      const chart = chartRef.current, range = chart?.timeScale().getVisibleLogicalRange();
      if (chart && range) { const width = Math.max(12, Math.min(2000, (range.to - range.from) * factor)); chart.timeScale().setVisibleLogicalRange({ from: range.to - width, to: range.to }); }
    },
    screenshot: () => { const chart = chartRef.current; if (!chart) return; const link = document.createElement("a"); link.href = chart.takeScreenshot().toDataURL("image/png"); link.download = "cryptorisk-chart.png"; link.click(); },
  }), []);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true, layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#64748b", fontFamily: "Arial, sans-serif", fontSize: 11, attributionLogo: true },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      rightPriceScale: { borderColor: "#e2e8f0", scaleMargins: { top: 0.1, bottom: 0.23 } },
      timeScale: { borderColor: "#e2e8f0", timeVisible: true, secondsVisible: false, rightOffset: 5, barSpacing: 7 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: "zh-CN", timeFormatter: (time: Time) => typeof time === "number" ? new Date(time * 1000).toLocaleString("zh-CN", { timeZone: "UTC", hour12: false }) : String(time) },
      handleScroll: { vertTouchDrag: false },
    });
    const candle = chart.addSeries(CandlestickSeries, { upColor: "#059669", downColor: "#e11d48", borderVisible: false, wickUpColor: "#059669", wickDownColor: "#e11d48" });
    const line = chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2, visible: false });
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", priceLineVisible: false, lastValueVisible: false });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const ma10 = chart.addSeries(LineSeries, { color: "#d97706", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ma30 = chart.addSeries(LineSeries, { color: "#7c3aed", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ema20 = chart.addSeries(LineSeries, { color: "#0284c7", lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const rsi14 = chart.addSeries(LineSeries, { color: "#7c3aed", lineWidth: 1, title: "RSI 14", priceLineVisible: false, priceFormat: { type: "price", precision: 1, minMove: 0.1 }, autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, 1);
    rsi14.createPriceLine({ price: 70, color: "#e2e8f0", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    rsi14.createPriceLine({ price: 30, color: "#e2e8f0", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false });
    chart.panes()[1]?.setHeight(100);
    chart.subscribeCrosshairMove(event => {
      if (hoverFrame.current !== null) cancelAnimationFrame(hoverFrame.current);
      const selected = typeof event.time === "number" ? candleMap.current.get(event.time) ?? null : null;
      hoverFrame.current = requestAnimationFrame(() => { setHover(selected); hoverFrame.current = null; });
    });
    chartRef.current = chart; seriesRef.current = { candle, line, volume, ma10, ma30, ema20, rsi14 };
    return () => { if (hoverFrame.current !== null) cancelAnimationFrame(hoverFrame.current); chart.remove(); chartRef.current = null; seriesRef.current = null; previousRef.current = []; };
  }, []);

  useEffect(() => {
    const s = seriesRef.current, chart = chartRef.current;
    if (!s || !chart) return;
    const previous = previousRef.current;
    // Incremental updates preserve zoom and avoid rebuilding every candle on each quote refresh.
    const historicalRevision = previous.slice(0, -1).some((row, index) => {
      const next = candles[index];
      return !next || row.time !== next.time || row.open !== next.open || row.high !== next.high || row.low !== next.low || row.close !== next.close || row.volume !== next.volume;
    });
    const incremental = previous.length > 0 && candles.length >= previous.length && !historicalRevision;
    const visibleRange = previous.length ? chart.timeScale().getVisibleRange() : null;
    const tailTime = previous.at(-1)?.time ?? 0;
    const typed = (row: Candle) => ({ ...row, time: row.time as UTCTimestamp });
    if (incremental) {
      for (const row of candles) if (row.time >= tailTime) {
        s.candle.update(typed(row)); s.line.update({ time: row.time as UTCTimestamp, value: row.close });
        s.volume.update({ time: row.time as UTCTimestamp, value: row.volume, color: row.close >= row.open ? "#a7f3d0" : "#fecdd3" });
      }
    } else {
      s.candle.setData(candles.map(typed)); s.line.setData(candles.map(row => ({ time: row.time as UTCTimestamp, value: row.close })));
      s.volume.setData(candles.map(row => ({ time: row.time as UTCTimestamp, value: row.volume, color: row.close >= row.open ? "#a7f3d0" : "#fecdd3" })));
    }
    for (const [series, data] of [[s.ma10, sma(candles, 10)], [s.ma30, sma(candles, 30)], [s.ema20, ema(candles, 20)], [s.rsi14, rsi(candles)]] as const) {
      if (incremental) { for (const row of data) if (row.time >= tailTime) series.update({ ...row, time: row.time as UTCTimestamp }); }
      else series.setData(data.map(row => ({ ...row, time: row.time as UTCTimestamp })));
    }
    const minPrice = candles.at(-1)?.close ?? 1;
    const precision = minPrice >= 100 ? 2 : minPrice >= 1 ? 4 : 8;
    for (const series of [s.candle, s.line]) series.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
    candleMap.current = new Map(candles.map(row => [row.time, row]));
    if (!previous.length && candles.length) chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, candles.length - 100), to: candles.length + 3 });
    if (!incremental && visibleRange && candles.length) chart.timeScale().setVisibleRange(visibleRange);
    previousRef.current = candles;
  }, [candles]);

  useEffect(() => {
    const s = seriesRef.current;
    if (!s) return;
    s.candle.applyOptions({ visible: mode === "candles" }); s.line.applyOptions({ visible: mode === "line" });
    s.ma10.applyOptions({ visible: showMA }); s.ma30.applyOptions({ visible: showMA }); s.ema20.applyOptions({ visible: showEMA });
    s.rsi14.applyOptions({ visible: showRSI });
    chartRef.current?.panes()[1]?.setHeight(showRSI ? 100 : 1);
    chartRef.current?.priceScale("right", 0).applyOptions({ mode: logarithmic ? 1 : 0 });
  }, [mode, showMA, showEMA, showRSI, logarithmic]);
  const selected = hover ?? candles.at(-1);
  return <div className="market-chart-wrap">
    <div className="market-ohlc" aria-label="十字线行情数据"><span>{selected ? new Date(selected.time * 1000).toISOString().slice(5, 16).replace("T", " ") : "—"} UTC</span>{selected && <><span>开 <b>{price(selected.open)}</b></span><span>高 <b>{price(selected.high)}</b></span><span>低 <b>{price(selected.low)}</b></span><span>收 <b>{price(selected.close)}</b></span><span>量 <b>{compact(selected.volume)}</b></span></>}</div>
    <div ref={host} className="market-canvas" role="img" aria-label="价格 K 线与成交量图，可拖动和缩放；键盘操作请使用图表工具栏" />
    <div className="market-chart-caption">{showMA && <><span style={{ color: "#d97706" }}>MA 10</span><span style={{ color: "#7c3aed" }}>MA 30</span></>}{showEMA && <span style={{ color: "#0284c7" }}>EMA 20</span>}<span>成交量 · UTC 时间</span></div>
  </div>;
}));
export default MarketChart;
