"use client";

import { useRef, useEffect, useCallback } from "react";
import { createChart, IChartApi, LineSeries, HistogramSeries } from "lightweight-charts";

interface IntradayBar {
  time: string;
  close: number;
  open: number;
  volume: number;
}

interface Props {
  bars: IntradayBar[];
  preClose: number | null;
  limitPct?: number;
  width?: number;
  height?: number;
}

/** Two-panel 分时图: top=price, bottom=volume. Crosshair synced. */
export default function IntradayChart({
  bars, preClose, limitPct = 10,
  width = 800, height = 500,
}: Props) {
  const topRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const tcRef = useRef<IChartApi | null>(null);
  const bcRef = useRef<IChartApi | null>(null);
  const volSeriesRef = useRef<any>(null);

  const toTime = useCallback((t: string) => {
    const [h, m] = t.split(":").map(Number);
    return (h * 3600 + m * 60) as any;
  }, []);

  useEffect(() => {
    if (!topRef.current || !bottomRef.current || bars.length < 2) return;

    // Cleanup
    tcRef.current?.remove(); tcRef.current = null;
    bcRef.current?.remove(); bcRef.current = null;

    const pc = preClose ?? bars[0]?.close ?? 0;
    const openPrice = bars[0]?.open ?? bars[0]?.close ?? pc;
    const limitUp = pc * (1 + limitPct / 100);
    const limitDown = pc * (1 - limitPct / 100);
    const topH = Math.floor(height * 0.7);
    const bottomH = height - topH;

    // Pre-compute data arrays
    const times = bars.map((b) => toTime(b.time));
    const prices = bars.map((b) => b.close);
    const volumes = bars.map((b) => ({
      time: toTime(b.time),
      value: b.volume,
      color: b.close >= pc ? "rgba(239,68,68,0.35)" : "rgba(34,197,94,0.35)",
    }));
    // VWAP
    let cv = 0, cm = 0;
    const vwapData = bars.map((b) => {
      cv += Math.max(b.volume, 1); cm += b.close * Math.max(b.volume, 1);
      return { time: toTime(b.time), value: cv > 0 ? cm / cv : b.close };
    });

    const commonGrid = { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } };
    const commonLayout = { background: { color: "#ffffff" }, textColor: "#999" };
    const tsOpts = { timeVisible: true, secondsVisible: false, borderColor: "#e5e7eb" };

    // ── Top chart (price) ──
    const tc = createChart(topRef.current, {
      width, height: topH,
      layout: commonLayout, grid: commonGrid,
      rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0.05, bottom: 0.05 } },
      timeScale: tsOpts,
    });
    tcRef.current = tc;

    // Price line
    tc.addSeries(LineSeries, { color: "#222", lineWidth: 2, priceLineVisible: false, lastValueVisible: false })
      .setData(prices.map((v, i) => ({ time: times[i], value: v })));

    // VWAP
    tc.addSeries(LineSeries, { color: "#f0a020", lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      .setData(vwapData);

    // Reference lines: open, preClose, limit-up, limit-down
    const addHLine = (value: number, color: string, style: 0 | 1 | 2 | 3 = 2) => {
      const refS = tc.addSeries(LineSeries, {
        color, lineWidth: 1, lineStyle: style,
        priceLineVisible: false, lastValueVisible: false,
      });
      refS.setData([{ time: times[0], value }, { time: times[times.length - 1], value }]);
    };
    if (preClose != null) addHLine(pc, "#bfbfbf", 2);          // preClose dashed gray
    addHLine(openPrice, "#7c3aed", 1);                          // open solid violet
    addHLine(limitUp, "#ef4444", 2);                            // limit-up dashed red
    addHLine(limitDown, "#22c55e", 2);                          // limit-down dashed green
    // ── Bottom chart (volume) ──
    const bc = createChart(bottomRef.current, {
      width, height: bottomH,
      layout: commonLayout, grid: commonGrid,
      rightPriceScale: { borderColor: "#e5e7eb", scaleMargins: { top: 0, bottom: 0 } },
      timeScale: tsOpts,
    });
    bcRef.current = bc;

    const volSeries = bc.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume" });
    volSeriesRef.current = volSeries;
    volSeries.setData(volumes);
    bc.priceScale("volume").applyOptions({ scaleMargins: { top: 0, bottom: 0 } });

    // ── Crosshair sync: highlight volume bar when price crosshair moves ──
    tc.subscribeCrosshairMove((param) => {
      if (!param.time || !bcRef.current || !volSeriesRef.current) return;
      const idx = volumes.findIndex((v) => v.time === (param.time as number));
      if (idx >= 0 && idx < volumes.length) {
        // Highlight the matching volume bar
        const updated = volumes.map((v, i) => ({
          ...v,
          color: i === idx
            ? (bars[i].close >= pc ? "rgba(239,68,68,0.85)" : "rgba(34,197,94,0.85)")
            : (bars[i].close >= pc ? "rgba(239,68,68,0.25)" : "rgba(34,197,94,0.25)"),
        }));
        volSeriesRef.current.setData(updated);
      }
    });
    // Restore normal volume colors when crosshair leaves
    tc.subscribeCrosshairMove(() => {}); // dummy — we need a better way
    // Instead, switch to tracking via time scale sync to know when crosshair leaves

    // ── Time scale sync ──
    const syncTime = (from: IChartApi, to: IChartApi) => {
      let busy = false;
      from.timeScale().subscribeVisibleTimeRangeChange(() => {
        if (busy) return;
        busy = true;
        const r = from.timeScale().getVisibleRange();
        if (r) to.timeScale().setVisibleRange(r);
        busy = false;
      });
    };
    syncTime(tc, bc);
    syncTime(bc, tc);

    tc.timeScale().fitContent();
    bc.timeScale().fitContent();

    return () => { tc.remove(); bc.remove(); tcRef.current = null; bcRef.current = null; };
  }, [bars, preClose, limitPct, width, height, toTime]);

  const pc = preClose ?? bars[0]?.close ?? 0;
  const openPrice = bars[0]?.open ?? bars[0]?.close ?? pc;
  const limitUp = pc * (1 + limitPct / 100);
  const limitDown = pc * (1 - limitPct / 100);
  const last = bars[bars.length - 1];
  const high = Math.max(...bars.map((b) => b.close));
  const low = Math.min(...bars.map((b) => b.close));
  const changePct = preClose ? ((last?.close ?? 0) - preClose) / preClose * 100 : 0;

  return (
    <div className="bg-white rounded-xl">
      <div ref={topRef} />
      <div ref={bottomRef} className="border-t border-gray-100" />
      <div className="flex justify-center gap-4 px-4 pb-3 pt-1 text-xs text-gray-500 flex-wrap">
        <span>涨停: <b className="text-red-500">{limitUp.toFixed(2)}</b></span>
        <span>昨收: <b>{pc.toFixed(2)}</b></span>
        <span>跌停: <b className="text-green-500">{limitDown.toFixed(2)}</b></span>
        <span>开盘: <b>{openPrice > 0 ? openPrice.toFixed(2) : "-"}</b></span>
        <span>最高: <b className="text-red-500">{high.toFixed(2)}</b></span>
        <span>最低: <b className="text-green-500">{low.toFixed(2)}</b></span>
        <span>收盘: <b>{last?.close.toFixed(2)}</b></span>
        <span>涨幅: <b className={changePct >= 0 ? "text-red-500" : "text-green-500"}>{changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%</b></span>
      </div>
    </div>
  );
}
