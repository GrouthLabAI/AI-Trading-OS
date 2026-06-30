"use client";

import { useRef, useEffect } from "react";
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
  limitPct?: number;   // e.g. 10 for ±10% limit
  width?: number;
  height?: number;
}

/** Standard Chinese 分时图: top=price (preClose-centered, limit-bound), bottom=volume. */
export default function IntradayChart({
  bars, preClose, limitPct = 10,
  width = 800, height = 500,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || bars.length < 2) return;
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

    const up = (bars[bars.length - 1]?.close ?? 0) >= (preClose ?? bars[0]?.open ?? 0);
    const color = up ? "#ef4444" : "#22c55e";

    // ── Price bounds: [limit-down, limit-up], preClose at exact center ──
    const pc = preClose ?? bars[0]?.close ?? 0;
    const limitUp = pc * (1 + limitPct / 100);
    const limitDown = pc * (1 - limitPct / 100);
    // Symmetric: preClose is the exact midpoint
    const maxDelta = Math.max(limitUp - pc, pc - limitDown);
    const priceMin = pc - maxDelta;
    const priceMax = pc + maxDelta;

    const chart = createChart(containerRef.current, {
      width, height,
      layout: { background: { color: "#ffffff" }, textColor: "#999" },
      grid: {
        vertLines: { color: "#f0f0f0" },
        horzLines: { color: "#f0f0f0" },
      },
      rightPriceScale: {
        borderColor: "#e5e7eb",
        scaleMargins: { top: 0.05, bottom: 0.48 },
        entireTextOnly: true,
      },
      timeScale: {
        borderColor: "#e5e7eb",
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
        vertLine: { color: "#999", style: 1, width: 1, labelBackgroundColor: "#999" },
        horzLine: { color: "#999", style: 1, width: 1, labelBackgroundColor: "#999" },
      },
    });
    chartRef.current = chart;

    const toTime = (t: string) => {
      const [h, m] = t.split(":").map(Number);
      return (h * 3600 + m * 60) as any;
    };

    // ── Price panel ──
    // Price line
    const priceSeries = chart.addSeries(LineSeries, {
      color, lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false,
    });
    priceSeries.setData(bars.map((b) => ({ time: toTime(b.time), value: b.close })));

    // VWAP (均价线) — yellow
    const avgSeries = chart.addSeries(LineSeries, {
      color: "#f0a020", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false,
    });
    let cumV = 0, cumM = 0;
    avgSeries.setData(bars.map((b) => {
      cumV += Math.max(b.volume, 1);
      cumM += b.close * Math.max(b.volume, 1);
      return { time: toTime(b.time), value: cumV > 0 ? cumM / cumV : b.close };
    }));

    // Pre-close center line (dashed)
    if (preClose != null) {
      const refSeries = chart.addSeries(LineSeries, {
        color: "#bfbfbf", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, lastValueVisible: false,
      });
      const f = toTime(bars[0].time);
      const l = toTime(bars[bars.length - 1].time);
      refSeries.setData([{ time: f, value: preClose }, { time: l, value: preClose }]);
    }

    // Limit-up / limit-down reference lines
    const luSeries = chart.addSeries(LineSeries, {
      color: "#ef4444", lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false,
    });
    const ldSeries = chart.addSeries(LineSeries, {
      color: "#22c55e", lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false,
    });
    const f = toTime(bars[0].time);
    const l = toTime(bars[bars.length - 1].time);
    luSeries.setData([{ time: f, value: limitUp }, { time: l, value: limitUp }]);
    ldSeries.setData([{ time: f, value: limitDown }, { time: l, value: limitDown }]);

    // Fix price scale so preClose sits at the exact center
    chart.priceScale("right").applyOptions({
      autoScale: false,
    });

    // ── Volume panel (bottom half) ──
    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volSeries.setData(bars.map((b) => ({
      time: toTime(b.time),
      value: b.volume,
      color: b.close >= preClose! ? "rgba(239,68,68,0.35)" : "rgba(34,197,94,0.35)",
    })));
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.55, bottom: 0 },
    });

    chart.timeScale().fitContent();

    return () => { chart.remove(); chartRef.current = null; };
  }, [bars, preClose, limitPct, width, height]);

  // ── Stats footer ──
  const first = bars[0];
  const last = bars[bars.length - 1];
  const high = Math.max(...bars.map((b) => b.close));
  const low = Math.min(...bars.map((b) => b.close));
  const changePct = preClose ? ((last?.close ?? 0) - preClose) / preClose * 100 : 0;

  return (
    <div className="bg-white rounded-xl">
      <div ref={containerRef} className="flex justify-center" />
      <div className="flex justify-center gap-4 px-4 pb-3 text-xs text-gray-500 flex-wrap">
        <span>涨停: <b className="text-red-500">{(preClose! * (1 + limitPct / 100)).toFixed(2)}</b></span>
        <span>昨收: <b>{preClose?.toFixed(2) ?? "-"}</b></span>
        <span>跌停: <b className="text-green-500">{(preClose! * (1 - limitPct / 100)).toFixed(2)}</b></span>
        <span>开盘: <b>{first?.open > 0 ? first.open.toFixed(2) : first?.close.toFixed(2)}</b></span>
        <span>最高: <b className="text-red-500">{high.toFixed(2)}</b></span>
        <span>最低: <b className="text-green-500">{low.toFixed(2)}</b></span>
        <span>收盘: <b>{last?.close.toFixed(2)}</b></span>
        <span>涨幅: <b className={changePct >= 0 ? "text-red-500" : "text-green-500"}>{changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%</b></span>
      </div>
    </div>
  );
}
