"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2, Search, TrendingUp, TrendingDown, BarChart3, Target, Shield, Zap, ExternalLink, ChevronRight, AlertTriangle, Maximize2, Minimize2, Settings, X } from "lucide-react";
import IntradayChartFull from "@/components/IntradayChart";
import AIChatPanel from "./AIChatPanel";
import { createChart, IChartApi, ISeriesApi, CandlestickData, HistogramData, Time, CrosshairMode, LineData, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from "lightweight-charts";

// ── Types ─────────────────────────────────────────────────────────

interface OHLVCBar {
  date: string;
  open: number; high: number; low: number; close: number;
  volume: number; turnover_rate: number;
  is_limit_up: boolean;
  is_limit_down: boolean;
  is_one_word: boolean;
}

interface IndicatorSnapshot {
  rsi: number | null;
  macd_dif: number | null;
  macd_dea: number | null;
  macd_hist: number | null;
  vol_ratio: number | null;
}

interface OHLCVData {
  code: string;
  name: string;
  period: string;
  limit_pct: number;
  bars: OHLVCBar[];
  indicators: IndicatorSnapshot & { per_bar: IndicatorSnapshot[] };
}

interface StockInfo {
  code: string; name: string;
  close: number; change_pct: number; change_amount: number;
  open: number; high: number; low: number; pre_close: number;
  volume: number; amount: number; turnover_rate: number;
  total_market_cap: number; float_market_cap: number;
}

interface SearchResult {
  code: string; name: string; close: number; change_pct: number;
}

interface PriceLevel { price: number; label: string; }
interface PhaseRange { phase: string; start_date: string; end_date: string; label: string; }
interface SignalMarker { date: string; signal: string; price: number; }

interface AIAnalysis {
  phase: string; rating: string; confidence: number;
  phases: PhaseRange[];
  signal_markers: SignalMarker[];
  support_levels: PriceLevel[];
  resistance_levels: PriceLevel[];
  signals: string[];
  analysis: string; advice: string;
}

const PHASE_COLORS_MAP: Record<string, string> = {
  accumulation: "rgba(59,130,246,0.10)",   // blue
  markup:       "rgba(34,197,94,0.10)",    // green
  distribution: "rgba(249,115,22,0.10)",   // orange
  markdown:     "rgba(239,68,68,0.10)",    // red
};
const PHASE_LABELS: Record<string, string> = {
  accumulation: "吸筹", markup: "上涨", distribution: "派发", markdown: "下跌",
};

const RATING_CONFIG: Record<string, { label: string; color: string; pct: number }> = {
  strong_sell: { label: "强烈卖出", color: "#dc2626", pct: 5 },
  sell:       { label: "卖出",     color: "#f97316", pct: 25 },
  neutral:    { label: "中立",     color: "#9ca3af", pct: 50 },
  buy:        { label: "买入",     color: "#22c55e", pct: 75 },
  strong_buy: { label: "强烈买入", color: "#16a34a", pct: 95 },
};

// ── Format helpers ─────────────────────────────────────────────────

function fmt(n: number | undefined | null, decimals = 2): string {
  if (n === undefined || n === null) return "-";
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtPct(n: number): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
const pctStyle = (v: number) => ({ color: v >= 0 ? UP_COLOR : DOWN_COLOR });
const upCls = (v: number) => v >= 0 ? "text-[#FF381A]" : "text-[#009B67]";
function fmtCap(n: number): string {
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
  return fmt(n, 0);
}
/** Mini intraday chart (SVG line) with call auction zone */
function MiniIntradayChart({ bars, preClose, width, height }: {
  bars: { time: string; close: number; open: number; volume: number }[];
  preClose: number | null;
  width: number; height: number;
}) {
  if (bars.length < 2) return null;
  const pad = { top: 6, right: 4, bottom: 14, left: 32 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  // Include preClose in range for call auction visualization
  const allValues = [...bars.map((b) => b.close), ...(preClose != null ? [preClose] : [])];
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = max - min || 1;

  // X-axis mapping: 9:15 → 15:00, total 345 min
  const totalMins = 345; // 9:15 to 15:00
  const startMin = 9 * 60 + 15; // 555
  const toX = (timeStr: string) => {
    const parts = timeStr.split(":");
    const mins = parseInt(parts[0]) * 60 + parseInt(parts[1]);
    return pad.left + ((mins - startMin) / totalMins) * w;
  };
  const toY = (v: number) => pad.top + h - ((v - min) / range) * h;

  const preCloseY = preClose != null ? toY(preClose) : null;
  const firstClose = bars[0]?.close;
  const firstOpen = bars[0]?.open;

  // VWAP (均价线) — cumulative volume-weighted average
  const avgLineParts: string[] = [];
  let cumVol = 0, cumVal = 0;
  bars.forEach((b, i) => {
    cumVol += b.volume;
    cumVal += b.close * Math.max(b.volume, 1);
    const avg = cumVol > 0 ? cumVal / cumVol : b.close;
    avgLineParts.push(`${i === 0 ? "M" : "L"}${toX(b.time)},${toY(avg)}`);
  });
  const avgPath = avgLineParts.join(" ");

  // Price line path
  const linePath = bars.map((b, i) => `${i === 0 ? "M" : "L"}${toX(b.time)},${toY(b.close)}`).join(" ");
  const fillPath = `${linePath} L${toX(bars[bars.length - 1].time)},${pad.top + h} L${toX(bars[0].time)},${pad.top + h} Z`;

  // Call auction zone: 9:15-9:30
  const auctionX1 = toX("09:15");
  const auctionX2 = toX("09:30");
  const lunchX1 = toX("11:30");
  const lunchX2 = toX("13:00");

  const up = (firstClose ?? 0) >= (preClose ?? firstClose ?? 0);
  const color = up ? "#ef4444" : "#22c55e";

  // Time labels
  const timeLabels = [
    { x: toX("09:15"), label: "9:15" },
    { x: toX("09:30"), label: "9:30" },
    { x: toX("10:30"), label: "10:30" },
    { x: toX("11:30"), label: "11:30" },
    { x: toX("13:00"), label: "13:00" },
    { x: toX("14:00"), label: "14:00" },
    { x: toX("15:00"), label: "15:00" },
  ];

  return (
    <svg width={width} height={height} className="block">
      {/* Call auction zone (9:15-9:30) shaded gray */}
      <rect x={auctionX1} y={pad.top} width={auctionX2 - auctionX1} height={h}
        fill="#6b7280" fillOpacity={0.12} />
      {/* Lunch break zone (11:30-13:00) */}
      <rect x={lunchX1} y={pad.top} width={lunchX2 - lunchX1} height={h}
        fill="#6b7280" fillOpacity={0.06} />
      {/* Call auction label */}
      <text x={(auctionX1 + auctionX2) / 2} y={pad.top + 8} textAnchor="middle"
        fill="#9ca3af" fontSize={7}>竞价</text>
      {/* Pre-close dashed line + jump to open */}
      {preCloseY != null && (
        <>
          <line x1={auctionX1} y1={preCloseY} x2={auctionX2} y2={preCloseY}
            stroke="#666" strokeDasharray="2,2" strokeWidth={0.5} />
          {firstOpen != null && (
            <line x1={auctionX2} y1={preCloseY} x2={auctionX2} y2={toY(firstOpen)}
              stroke="#888" strokeWidth={1} strokeDasharray="1,1" />
          )}
        </>
      )}
      {/* Fill area */}
      <path d={fillPath} fill={color} fillOpacity={0.12} />
      {/* 均价线 (yellow solid) */}
      <path d={avgPath} fill="none" stroke="#f0a020" strokeWidth={0.8} />
      {/* Price line */}
      <path d={linePath} fill="none" stroke={color} strokeWidth={1.2} />
      {/* Time labels */}
      {timeLabels.map((t) => (
        <text key={t.label} x={t.x} y={height - 2} textAnchor="middle"
          fill="#999" fontSize={8}>{t.label}</text>
      ))}
      {/* Price labels */}
      <text x={pad.left - 2} y={pad.top + 8} textAnchor="end" fill="#ef4444" fontSize={8}>
        {max.toFixed(2)}
      </text>
      <text x={pad.left - 2} y={pad.top + h} textAnchor="end" fill="#22c55e" fontSize={8}>
        {min.toFixed(2)}
      </text>
    </svg>
  );
}

/** 5-segment rating gauge — strong sell → strong buy */
function RatingGauge({ rating, confidence }: { rating: string; confidence: number }) {
  const cfg = RATING_CONFIG[rating] || RATING_CONFIG.neutral;
  const segments = [
    { key: "strong_sell", color: "#dc2626", label: "" },
    { key: "sell",       color: "#f97316", label: "" },
    { key: "neutral",    color: "#9ca3af", label: "" },
    { key: "buy",        color: "#22c55e", label: "" },
    { key: "strong_buy", color: "#16a34a", label: "" },
  ];
  const activeIdx = segments.findIndex((s) => s.key === rating);
  return (
    <div className="flex flex-col items-center shrink-0">
      {/* Gauge track */}
      <div className="flex gap-0.5 rounded-full overflow-hidden" style={{ width: 140 }}>
        {segments.map((seg, i) => (
          <div key={seg.key} className="h-2 flex-1 transition-colors"
            style={{ backgroundColor: i <= activeIdx ? seg.color : "#e5e7eb" }}
          />
        ))}
      </div>
      {/* Needle */}
      <div className="relative h-3 w-full" style={{ width: 140 }}>
        <div className="absolute transition-all" style={{ left: `${cfg.pct}%`, transform: "translateX(-50%)" }}>
          <div className="w-0 h-0 border-l-[4px] border-r-[4px] border-t-[6px] border-l-transparent border-r-transparent"
            style={{ borderTopColor: cfg.color }}
          />
        </div>
      </div>
      {/* Label */}
      <span className="text-xs font-semibold mt-0.5" style={{ color: cfg.color }}>
        {cfg.label} ({(confidence * 100).toFixed(0)}%)
      </span>
    </div>
  );
}

function fmtVol(n: number): string {
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿手`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万手`;
  return fmt(n, 0);
}

// ── Constants ──────────────────────────────────────────────────────

const PERIODS = [
  { label: "日线", value: "daily" },
  { label: "周线", value: "weekly" },
] as const;

const DAY_RANGES = [
  { label: "1月", value: 30 },
  { label: "3月", value: 90 },
  { label: "6月", value: 180 },
  { label: "1年", value: 250 },
  { label: "2年", value: 500 },
] as const;

const UP_COLOR = "#FF381A";
const DOWN_COLOR = "#009B67";

const COLORS = {
  bg: "#ffffff",
  grid: "#f0f0f0",
  text: "#999999",
  red: UP_COLOR,
  green: DOWN_COLOR,
  ma5: "#f2a603",
  ma10: "#d44de8",
  ma20: "#2b7ee8",
  ma60: "#e84e2b",
  volUp: UP_COLOR + "80",   // ~50% opacity hex
  volDown: DOWN_COLOR + "80",
};

// ── Main Component ─────────────────────────────────────────────────

// A-share stock code: 6 digits (主板 00/60, 创业板 30, 科创板 688)
const STOCK_CODE_RE = /^[0-9]{6}$/;

export default function StockPage() {
  const params = useParams();
  const router = useRouter();
  const rawCode = (params?.code as string) || "";
  const validCode = STOCK_CODE_RE.test(rawCode);
  const code = validCode ? rawCode : "";

  const [info, setInfo] = useState<StockInfo | null>(null);
  const [bars, setBars] = useState<OHLVCBar[]>([]);
  const [indicators, setIndicators] = useState<(IndicatorSnapshot & { per_bar?: IndicatorSnapshot[] }) | null>(null);
  const [period, setPeriod] = useState<"daily" | "weekly">("daily");
  const [dayRange, setDayRange] = useState(250);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [aiResult, setAiResult] = useState<AIAnalysis | null>(null);
  const [chartFullscreen, setChartFullscreen] = useState(false);
  const [showCrosshair, setShowCrosshair] = useState(false);
  const [showSR, setShowSR] = useState(false); // support/resistance toggle
  const [showTechSignals, setShowTechSignals] = useState(false); // technical signal markers
  const [intradayModal, setIntradayModal] = useState<{ date: string; label: string; x: number; y: number } | null>(null);
  const [pinnedPhases, setPinnedPhases] = useState<Set<string>>(new Set());
  const [phaseBands, setPhaseBands] = useState<{ x1: number; x2: number; color: string }[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!settingsOpen) return;
    const onClick = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) {
        setSettingsOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [settingsOpen]);
  const [hoveredBar, setHoveredBar] = useState<OHLVCBar | null>(null); // follows crosshair

  // Update page title
  useEffect(() => {
    const stockLabel = info?.name && !/^\d{6}$/.test(info.name)
      ? `${info.name} ${info.code}` : code;
    document.title = stockLabel ? `${stockLabel} · AI Trading OS` : "AI Trading OS";
  }, [info, code]);

  // Search
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);

  // Chart refs
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);

  // Crosshair tooltip state
  const [crosshair, setCrosshair] = useState<{
    visible: boolean; x: number; y: number;
    date: string; open: number; high: number; low: number; close: number;
    volume: number; changePct: number;
    turnoverRate: number; volRatio: number | null;
    isLimitUp: boolean; limitUpTime: string | null;
  } | null>(null);

  // Intraday data cache: date → { bars, preClose }
  const intradayCache = useRef<Map<string, { bars: { time: string; close: number; open: number; volume: number }[]; preClose: number | null }>>(new Map());
  const [intradayBars, setIntradayBars] = useState<{ time: string; close: number; open: number; volume: number }[] | null>(null);
  const [intradayPreClose, setIntradayPreClose] = useState<number | null>(null);

  // ── Search ──────────────────────────────────────────────────────

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 1) { setSearchResults([]); setSearchOpen(false); return; }
    try {
      const res = await fetch(`/api/stock/search?q=${encodeURIComponent(q)}`);
      const json = await safeJson(res);
      if (json.status === "ok") {
        setSearchResults(json.data.slice(0, 8));
        setSearchOpen(true);
      }
    } catch { /* */ }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => doSearch(searchQ), 300);
    return () => clearTimeout(timer);
  }, [searchQ, doSearch]);

  // ── Data fetching ───────────────────────────────────────────────

  const safeJson = async (res: Response) => {
    const text = await res.text();
    try { return JSON.parse(text); }
    catch {
      console.error(`[StockPage] Invalid JSON from ${res.url}:`, text.slice(0, 200));
      return { status: "error", message: "服务器返回了非JSON响应，请确认后端是否已重启" };
    }
  };

  const fetchData = useCallback(async () => {
    if (!code) return;
    setLoading(true);
    try {
      const [infoRes, ohlcvRes] = await Promise.all([
        fetch(`/api/stock/${code}/info`),
        fetch(`/api/stock/${code}/ohlcv?days=${dayRange}&period=${period}`),
      ]);
      const infoJson = await safeJson(infoRes);
      const ohlcvJson = await safeJson(ohlcvRes);

      if (infoJson.status === "ok") setInfo(infoJson.data);
      if (ohlcvJson.status === "ok") {
        setBars(ohlcvJson.data.bars || []);
        const ind = ohlcvJson.data.indicators;
        setIndicators(ind || null);
      }
    } catch (e) {
      console.error("Failed to fetch stock data:", e);
    } finally {
      setLoading(false);
    }
  }, [code, period, dayRange]);

  useEffect(() => {
    if (validCode) fetchData();
    else setLoading(false);
  }, [fetchData, validCode]);

  // Phase band coordinates (DOM overlay, no primitive — no height change)
  const updatePhaseBands = useCallback(() => {
    if (!chartApiRef.current || !aiResult?.phases || pinnedPhases.size === 0) {
      setPhaseBands([]);
      return;
    }
    const ts = chartApiRef.current.timeScale();
    const bands: { x1: number; x2: number; color: string }[] = [];
    aiResult.phases.forEach((p) => {
      if (!pinnedPhases.has(p.phase)) return;
      const x1 = ts.timeToCoordinate(p.start_date as Time);
      const x2 = ts.timeToCoordinate(p.end_date as Time);
      if (x1 != null && x2 != null) {
        bands.push({
          x1,
          x2,
          color: (PHASE_COLORS_MAP[p.phase] || "rgba(156,163,175,0.10)").replace("0.10", "0.15"),
        });
      }
    });
    setPhaseBands(bands);
  }, [aiResult, pinnedPhases]);

  useEffect(() => { updatePhaseBands(); }, [updatePhaseBands]);

  // Subscribe to timeScale changes for live band updates
  useEffect(() => {
    if (!chartApiRef.current) return;
    const ts = chartApiRef.current.timeScale();
    const handler = () => updatePhaseBands();
    ts.subscribeVisibleLogicalRangeChange(handler);
    return () => { try { ts.unsubscribeVisibleLogicalRangeChange(handler); } catch {} };
  }, [updatePhaseBands]);

  // Dedicated redraw for phase toggle (pinnedPhases change)
  useEffect(() => {
    if (chartApiRef.current && aiResult && bars.length > 0) {
      drawWyckoffOverlays(chartApiRef.current, bars, aiResult, candleSeriesRef.current, showSR, pinnedPhases);
      // addSeries/removeSeries triggers async re-layout — restore height after
      if (!chartFullscreen) {
        setTimeout(() => chartApiRef.current?.applyOptions({ height: 560 }), 100);
      }
    }
  }, [pinnedPhases]); // eslint-disable-line

  // ── Fullscreen: Escape key + resize ─────────────────────────────

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (chartFullscreen) { setChartFullscreen(false); return; }
        if (pinnedPhases.size > 0) { setPinnedPhases(new Set()); return; }
      }
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    // Resize chart after CSS transition — poll until container has height
    const applyFS2 = () => {
      const h = chartRef.current?.clientHeight;
      if (h && h > 300) {
        chartApiRef.current?.applyOptions({
          width: chartRef.current?.clientWidth || window.innerWidth,
          height: h,
        });
      } else {
        requestAnimationFrame(applyFS2);
      }
    };
    const timer = setTimeout(() => requestAnimationFrame(applyFS2), 100);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearTimeout(timer);
      document.body.style.overflow = "";
    };
  }, [chartFullscreen, pinnedPhases]);

  const toggleFullscreen = useCallback(() => {
    setChartFullscreen((prev) => {
      if (!prev) {
        // Entering fullscreen — wait for flex layout then apply
        const applyFS = () => {
          const h = chartRef.current?.clientHeight;
          if (h && h > 300) {
            chartApiRef.current?.applyOptions({
              width: chartRef.current?.clientWidth || window.innerWidth,
              height: h,
            });
          } else {
            requestAnimationFrame(applyFS);
          }
        };
        setTimeout(() => requestAnimationFrame(applyFS), 100);
      } else {
        // Exiting — restore size
        setTimeout(() => {
          chartApiRef.current?.applyOptions({
            width: chartRef.current?.clientWidth || 800,
            height: 560,
          });
        }, 200);
      }
      return !prev;
    });
  }, []);

  // ── AI Analysis ─────────────────────────────────────────────────

  const runAnalysis = useCallback(async () => {
    if (!code) return;
    setAnalyzing(true);
    setAiResult(null);
    try {
      const res = await fetch(`/api/stock/${code}/analyze`);
      const json = await safeJson(res);
      if (json.status === "ok") {
        setAiResult(json.data);
      }
    } catch (e) {
      console.error("AI analysis failed:", e);
    } finally {
      setAnalyzing(false);
    }
  }, [code]);

  // ── Draw Wyckoff overlays on chart ─────────────────────────────

  const wyckoffRefs = useRef<ISeriesApi<any>[]>([]);

  function drawWyckoffOverlays(chart: IChartApi, bars: OHLVCBar[], result: AIAnalysis, candleSeries?: ISeriesApi<"Candlestick"> | null, doShowSR = false, pinnedPhases?: Set<string>) {
    // Clear previous series
    wyckoffRefs.current.forEach((s) => { try { chart.removeSeries(s); } catch {} });
    wyckoffRefs.current = [];
    if (!bars.length) return;

    const firstDate = bars[0].date as Time;
    const lastDate = bars[bars.length - 1].date as Time;
    const minPrice = Math.min(...bars.map((b) => b.low));
    const maxPrice = Math.max(...bars.map((b) => b.high));

    // ── Phase bottom strips ──
    const phaseBase = minPrice * 0.96;
    result.phases?.forEach((p) => {
      const isPinned = pinnedPhases?.has(p.phase);
      const alpha = isPinned ? "0.30" : "0.06";
      const color = (PHASE_COLORS_MAP[p.phase] || "rgba(156,163,175,0.08)").replace(/0\.\d+/, alpha);
      const lw = (isPinned ? 4 : 2) as 2 | 4;

      const series = chart.addSeries(LineSeries, {
        color, lineWidth: lw,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
      series.setData([
        { time: p.start_date as Time, value: phaseBase },
        { time: p.end_date as Time, value: phaseBase },
      ]);
      wyckoffRefs.current.push(series);
    });

    // ── Support lines (only if enabled) ──
    if (doShowSR) result.support_levels?.forEach((lvl) => {
      if (!lvl.price || lvl.price <= 0) return;
      const series = chart.addSeries(LineSeries, {
        color: "rgba(34,197,94,0.7)", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
      series.setData([{ time: firstDate, value: lvl.price }, { time: lastDate, value: lvl.price }]);
      wyckoffRefs.current.push(series);
    });

    // ── Resistance lines (only if enabled) ──
    if (showSR) result.resistance_levels?.forEach((lvl) => {
      if (!lvl.price || lvl.price <= 0) return;
      const series = chart.addSeries(LineSeries, {
        color: "rgba(239,68,68,0.7)", lineWidth: 1, lineStyle: 2,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      });
      series.setData([{ time: firstDate, value: lvl.price }, { time: lastDate, value: lvl.price }]);
      wyckoffRefs.current.push(series);
    });

    // ── Signal markers (arrows with labels) ──
    const markers: any[] = [];
    result.signal_markers?.forEach((sm) => {
      if (!sm.date || !sm.signal) return;
      const bullish = ["SOS","JOC","Spring","LPS","V反转"].includes(sm.signal);
      markers.push({
        time: sm.date as Time,
        position: bullish ? "belowBar" : "aboveBar",
        color: bullish ? "#22c55e" : "#ef4444",
        shape: bullish ? "arrowUp" : "arrowDown",
        text: sm.signal,
        size: 2,
      });
    });
    if (markers.length > 0 && candleSeries) {
      createSeriesMarkers(candleSeries, markers as any);
    }
  }

  // ── Chart rendering ─────────────────────────────────────────────

  useEffect(() => {
    if (!chartRef.current || bars.length === 0) {
      // Draw support/resistance when AI result is available (even if no bars change)
      if (chartApiRef.current && aiResult) {
        drawWyckoffOverlays(chartApiRef.current, bars, aiResult, candleSeriesRef.current, showSR, pinnedPhases);
      }
      // Cleanup previous chart if bars is empty
      if (chartApiRef.current) {
        chartApiRef.current.remove();
        chartApiRef.current = null;
      }
      return;
    }

    // Remove previous chart
    if (chartApiRef.current) {
      chartApiRef.current.remove();
      chartApiRef.current = null;
    }

    const container = chartRef.current;
    const width = container.clientWidth;

    const chart = createChart(container, {
      width,
      height: 560,
      layout: {
        background: { color: COLORS.bg },
        textColor: COLORS.text,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: COLORS.grid,
        scaleMargins: { top: 0.1, bottom: 0.3 },
      },
      localization: {
        timeFormatter: (t: Time) => {
          if (typeof t === "string") return t;
          if (typeof t === "number") {
            const d = new Date(t * 1000);
            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
          }
          return String(t);
        },
      },
      timeScale: {
        borderColor: COLORS.grid,
        timeVisible: true,
        tickMarkFormatter: (t: Time) => {
          const s = typeof t === "string" ? t : "";
          // Show MM-DD for short labels
          return s.length >= 10 ? s.slice(5) : s;
        },
      },
    });

    // ── Candlestick series (main: red/green) ──
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "transparent",          // 空心阳线
      downColor: DOWN_COLOR,           // 实心阴线
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    });

    const candleData: CandlestickData[] = bars.map((b) => ({
      time: b.date as Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candleSeries.setData(candleData);

    // ── Limit-up overlay: 🟡 yellow candles ──
    const limitUpBars = bars.filter((b) => b.is_limit_up);
    if (limitUpBars.length > 0) {
      const limitUpOverlay = chart.addSeries(CandlestickSeries, {
        upColor: "#FFD600",
        downColor: "#FFD600",
        borderUpColor: "#e6c200",
        borderDownColor: "#e6c200",
        wickUpColor: "#FFD600",
        wickDownColor: "#FFD600",
      });
      // Build data with gaps (NaN) for non-limit-up bars so overlay candles
      // only render on limit-up days
      const limitUpData: CandlestickData[] = [];
      const limitDates = new Set(limitUpBars.map((b) => b.date));
      for (const b of bars) {
        if (limitDates.has(b.date)) {
          limitUpData.push({
            time: b.date as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          });
        }
        // Skip non-limit-up bars entirely to create visual gaps
      }
      limitUpOverlay.setData(limitUpData);
    }

    // ── Limit-down overlay: 🟣 purple candles ──
    const limitDownBars = bars.filter((b) => b.is_limit_down);
    if (limitDownBars.length > 0) {
      const limitDownOverlay = chart.addSeries(CandlestickSeries, {
        upColor: "#9b30ff",
        downColor: "#9b30ff",
        borderUpColor: "#7a1fd6",
        borderDownColor: "#7a1fd6",
        wickUpColor: "#9b30ff",
        wickDownColor: "#9b30ff",
      });
      const limitDownDates = new Set(limitDownBars.map((b) => b.date));
      const limitDownData: CandlestickData[] = [];
      for (const b of bars) {
        if (limitDownDates.has(b.date)) {
          limitDownData.push({
            time: b.date as Time,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          });
        }
      }
      limitDownOverlay.setData(limitDownData);
    }

    // ── Volume series ──
    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    volSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    const volData: HistogramData[] = bars.map((b) => ({
      time: b.date as Time,
      value: b.volume,
      color: b.close >= b.open ? COLORS.volUp : COLORS.volDown,
    }));
    volSeries.setData(volData);

    // ── MA lines ──
    function addMA(period: number, color: string) {
      const maData: LineData[] = [];
      for (let i = period - 1; i < bars.length; i++) {
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
        maData.push({ time: bars[i].date as Time, value: sum / period });
      }
      const lineSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      lineSeries.setData(maData);
    }

    addMA(5, COLORS.ma5);
    addMA(10, COLORS.ma10);
    addMA(20, COLORS.ma20);
    addMA(60, COLORS.ma60);

    // Draw support/resistance if AI result available
    if (aiResult) {
      drawWyckoffOverlays(chart, bars, aiResult, candleSeries, showSR, pinnedPhases);
    }

    // ── Technical signal markers ──
    if (showTechSignals && indicators?.per_bar && indicators.per_bar.length > 0) {
      const techMarkers: any[] = [];
      const perBar = indicators.per_bar;

      for (let i = 1; i < bars.length; i++) {
        const bar = bars[i];
        const prev = perBar[i - 1];
        const curr = perBar[i];
        if (!bar?.date || !curr) continue;
        const cdif = curr.macd_dif ?? 0;
        const cdea = curr.macd_dea ?? 0;
        const crsi = curr.rsi ?? 50;
        const pdif = prev?.macd_dif ?? 0;
        const pdea = prev?.macd_dea ?? 0;
        const prsi = prev?.rsi ?? 50;

        // MACD golden cross (DIF crosses above DEA)
        if (cdif > cdea && pdif <= pdea) {
          techMarkers.push({
            time: bar.date as Time,
            position: "belowBar",
            color: "#22c55e",
            shape: "arrowUp",
            text: "金叉",
            size: 1.5,
          });
        }
        // MACD death cross (DIF crosses below DEA)
        if (cdif < cdea && pdif >= pdea) {
          techMarkers.push({
            time: bar.date as Time,
            position: "aboveBar",
            color: "#ef4444",
            shape: "arrowDown",
            text: "死叉",
            size: 1.5,
          });
        }
        // RSI oversold (< 30)
        if (crsi < 30 && prsi >= 30) {
          techMarkers.push({
            time: bar.date as Time,
            position: "belowBar",
            color: "#4ade80",
            shape: "arrowUp",
            text: "RSI超卖",
            size: 1.5,
          });
        }
        // RSI overbought (> 70)
        if (crsi > 70 && prsi <= 70) {
          techMarkers.push({
            time: bar.date as Time,
            position: "aboveBar",
            color: "#f87171",
            shape: "arrowDown",
            text: "RSI超买",
            size: 1.5,
          });
        }
        // Volume breakout: vol > 2x 5-day avg + close > prev close
        const vol5avg = bars.slice(Math.max(0, i - 4), i + 1).reduce((s, b) => s + (b.volume || 0), 0) / 5;
        if (bar.volume > vol5avg * 2 && bar.close > bars[i - 1].close) {
          techMarkers.push({
            time: bar.date as Time,
            position: "belowBar",
            color: "#f59e0b",
            shape: "circle",
            text: "放量",
            size: 1.5,
          });
        }
      }

      // MA5/MA20 crossover markers
      const ma5 = bars.map((b, i) => {
        if (i < 4) return null;
        const sum = bars.slice(i - 4, i + 1).reduce((s, x) => s + x.close, 0);
        return sum / 5;
      });
      const ma20 = bars.map((b, i) => {
        if (i < 19) return null;
        const sum = bars.slice(i - 19, i + 1).reduce((s, x) => s + x.close, 0);
        return sum / 20;
      });
      for (let i = 20; i < bars.length; i++) {
        if (!bars[i]?.date) continue;
        if (ma5[i] && ma20[i] && ma5[i - 1] && ma20[i - 1]) {
          // Golden cross: MA5 crosses above MA20
          const m5 = ma5[i]!; const m20 = ma20[i]!;
          const m5p = ma5[i - 1]!; const m20p = ma20[i - 1]!;
          if (m5 > m20 && m5p <= m20p) {
            techMarkers.push({
              time: bars[i].date as Time,
              position: "belowBar",
              color: "#22c55e",
              shape: "arrowUp",
              text: "MA金叉",
              size: 1.5,
            });
          }
        }
      }

      if (techMarkers.length > 0 && candleSeries) {
        createSeriesMarkers(candleSeries, techMarkers as any);
      }
    }

    // ── Click handler: open intraday modal ──
    chart.subscribeClick((param) => {
      if (!param.time) return;
      const clickedDate = param.time as string;
      // Find the bar
      const bar = bars.find((b) => b.date === clickedDate);
      if (bar) {
        const label = `${info?.name || code} ${clickedDate}`;
        setIntradayModal({ date: clickedDate, label, x: Math.max(60, window.innerWidth - 880), y: 100 });
        // Trigger intraday fetch if not cached
        if (!intradayCache.current.has(clickedDate)) {
          fetch(`/api/stock/${code}/intraday?date=${clickedDate}`)
            .then((r) => r.json())
            .then((json) => {
              if (json.status === "ok") {
                const ibars = (json.data.bars || []).map((b: any) => ({
                  time: b.time, close: b.close, open: b.open || b.close, volume: b.volume || 0,
                }));
                intradayCache.current.set(clickedDate, {
                  bars: ibars,
                  preClose: json.data.pre_close,
                });
                setIntradayModal((prev) => prev?.date === clickedDate ? { ...prev } : prev);
              }
            }).catch(() => {});
        }
      }
    });

    // Handle resize
    const handleResize = () => {
      chart.applyOptions({ width: container.clientWidth, height: 560 });
    };
    const observer = new ResizeObserver(handleResize);
    observer.observe(container);

    // ── Crosshair handler (always tracks bar for info panel) ──
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || param.point === undefined) {
        setCrosshair(null);
        setHoveredBar(null);
        return;
      }
      const data = param.seriesData.get(candleSeries) as CandlestickData | undefined;
      const volData = param.seriesData.get(volSeries) as HistogramData | undefined;
      if (!data) { setCrosshair(null); setHoveredBar(null); return; }
      const dateStr = (data.time as string) || "";
      const bar = bars.find((b) => b.date === dateStr);
      if (bar) setHoveredBar(bar);

      // Fetch intraday data if not cached
      if (intradayCache.current.has(dateStr)) {
        const cached = intradayCache.current.get(dateStr)!;
        setIntradayBars(cached.bars);
        setIntradayPreClose(cached.preClose);
      } else {
        setIntradayBars(null);
        setIntradayPreClose(null);
        fetch(`/api/stock/${code}/intraday?date=${dateStr}`)
          .then((r) => r.json())
          .then((json) => {
            if (json.status === "ok") {
              const ibars = (json.data.bars || []).map((b: any) => ({
                time: b.time, close: b.close, open: b.open || b.close, volume: b.volume || 0,
              }));
              intradayCache.current.set(dateStr, {
                bars: ibars,
                preClose: json.data.pre_close,
              });
              // Only update if still hovering same date
              setIntradayBars((prev) => prev ?? ibars);
              setIntradayPreClose((prev) => prev ?? json.data.pre_close);
            }
          })
          .catch(() => {});
      }

      // Vol ratio from indicator data
      let volRatio: number | null = null;
      const barIdx = bar ? bars.indexOf(bar) : -1;
      if (barIdx >= 0 && indicators?.per_bar && barIdx < indicators.per_bar.length) {
        volRatio = indicators.per_bar[barIdx].vol_ratio;
      }

      // Limit-up time from intraday data
      let limitUpTime: string | null = null;
      if (bar?.is_limit_up) {
        const cached = intradayCache.current.get(dateStr);
        if (cached && cached.bars.length > 0) {
          const limitPrice = bar.close;
          const firstHit = cached.bars.find((b) => Math.abs(b.close - limitPrice) < 0.001);
          if (firstHit) limitUpTime = firstHit.time;
        }
      }

      setCrosshair({
        visible: true,
        x: param.point.x + 15,
        y: param.point.y - 80,
        date: dateStr,
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
        volume: volData?.value || 0,
        changePct: bar ? ((data.close - bar.open) / bar.open * 100) : 0,
        turnoverRate: bar?.turnover_rate || 0,
        volRatio,
        isLimitUp: bar?.is_limit_up || false,
        limitUpTime,
      });
    });

    chartApiRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volSeriesRef.current = volSeries;

    return () => {
      observer.disconnect();
      // Remove moved logo + primitives
      chart.remove();
      chartApiRef.current = null;
    };
  }, [bars, showTechSignals, showSR, aiResult, pinnedPhases, indicators]);

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="flex">
      <div className="flex-1 min-w-0 bg-[#f7f7f8] min-h-screen">
        <div className="max-w-8xl mx-auto px-4 py-6 space-y-4">
        {/* ── Search Bar ── */}
        <div className="relative">
          <div className="flex items-center gap-2 bg-white rounded-xl border border-gray-200 px-4 py-2">
            <Search className="w-4 h-4 text-gray-400" />
            <input
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                const q = searchQ.trim();
                if (!q) return;
                // If results are shown, navigate to first result
                if (searchResults.length > 0 && searchOpen) {
                  router.push(`/stock/${searchResults[0].code}`);
                  setSearchOpen(false);
                  setSearchQ("");
                  return;
                }
                // If input looks like a stock code (6 digits), navigate directly
                if (/^\d{6}$/.test(q)) {
                  router.push(`/stock/${q}`);
                  setSearchOpen(false);
                  setSearchQ("");
                }
              }}
              placeholder="搜索股票代码或名称，回车跳转..."
              className="flex-1 text-sm outline-none bg-transparent"
            />
            {code && (
              <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded">
                当前: {info?.name && !/^\d{6}$/.test(info.name) ? `${info.name} ${code}` : code}
              </span>
            )}
          </div>
          {searchOpen && searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-lg z-50 max-h-72 overflow-y-auto">
              {searchResults.map((s) => (
                <button
                  key={s.code}
                  onClick={() => {
                    router.push(`/stock/${s.code}`);
                    setSearchOpen(false);
                    setSearchQ("");
                  }}
                  className={`w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left ${
                    s.code === code ? "bg-[#10a37f]/5 border-l-2 border-l-[#10a37f]" : ""
                  }`}
                >
                  <div>
                    <span className="text-sm font-medium text-gray-800">{s.name}</span>
                    <span className="text-xs text-gray-400 ml-2">{s.code}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-sm font-medium ${s.change_pct >= 0 ? "text-[#FF381A]" : "text-[#009B67]"}`}>
                      {fmtPct(s.change_pct)}
                    </span>
                    <span className="text-xs text-gray-400">{fmt(s.close)}</span>
                    <ChevronRight className="w-3 h-3 text-gray-300" />
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ── Invalid Code ── */}
        {!validCode && rawCode && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-8 text-center">
            <AlertTriangle className="w-10 h-10 text-[#FF381A]/70 mx-auto mb-3" />
            <p className="text-lg font-semibold text-red-700">无效的股票代码</p>
            <p className="text-sm text-red-500 mt-1">
              「{rawCode}」不是有效的 A 股代码格式（6 位数字）
            </p>
            <button
              onClick={() => router.push("/dashboard")}
              className="mt-4 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50"
            >
              返回市场驾驶舱
            </button>
          </div>
        )}

        {/* ── Loading State ── */}
        {validCode && loading && !info && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
            <span className="ml-2 text-gray-400">加载 {code} 数据中...</span>
          </div>
        )}

        {/* ── Stock Info Card ── */}
        {info && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-start justify-between flex-wrap gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-bold text-gray-900">
                    {info.name && !/^\d{6}$/.test(info.name) ? info.name : info.code}
                  </h1>
                  <span className="text-sm text-gray-400">{info.code}</span>
                  <a href={`https://stockpage.10jqka.com.cn/${info.code}/`}
                     target="_blank" rel="noopener noreferrer"
                     className="text-xs text-blue-500 hover:text-blue-700 flex items-center gap-0.5">
                    <ExternalLink className="w-3 h-3" /> 同花顺
                  </a>
                  <a href="https://www.tradingview.com/"
                     target="_blank" rel="noopener noreferrer"
                     className="text-xs text-blue-500 hover:text-blue-700 flex items-center gap-0.5 ml-1"
                     title="图表引擎: TradingView">
                    <BarChart3 className="w-3 h-3" /> TV
                  </a>
                </div>
                <div className="flex items-baseline gap-3 mt-2">
                  <span className={`text-3xl font-bold ${info.change_pct >= 0 ? "text-[#FF381A]" : "text-[#009B67]"}`}>{fmt(info.close)}</span>
                  <span className={`text-lg font-semibold ${info.change_pct >= 0 ? "text-[#FF381A]" : "text-[#009B67]"}`}>
                    {fmtPct(info.change_pct)}
                  </span>
                  <span className={`text-sm ${info.change_amount >= 0 ? "text-[#FF381A]/70" : "text-[#009B67]/70"}`}>
                    {info.change_amount >= 0 ? "+" : ""}{fmt(info.change_amount)}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-3 md:grid-cols-4 gap-x-6 gap-y-1 text-sm">
                <div><span className="text-gray-400">今开</span> <span className="text-gray-700 ml-1">{fmt(info.open)}</span></div>
                <div><span className="text-gray-400">最高</span> <span className="text-[#FF381A] ml-1">{fmt(info.high)}</span></div>
                <div><span className="text-gray-400">最低</span> <span className="text-[#009B67] ml-1">{fmt(info.low)}</span></div>
                <div><span className="text-gray-400">昨收</span> <span className="text-gray-700 ml-1">{fmt(info.pre_close)}</span></div>
                <div><span className="text-gray-400">成交额</span> <span className="text-gray-700 ml-1">{fmtCap(info.amount)}</span></div>
                <div><span className="text-gray-400">换手</span> <span className="text-gray-700 ml-1">{fmtPct(info.turnover_rate)}</span></div>
                <div><span className="text-gray-400">总市值</span> <span className="text-gray-700 ml-1">{fmtCap(info.total_market_cap)}</span></div>
                <div><span className="text-gray-400">流通市值</span> <span className="text-gray-700 ml-1">{fmtCap(info.float_market_cap)}</span></div>
              </div>
            </div>
          </div>
        )}

        {/* ── Period & Range Controls ── */}
        {bars.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-3 flex items-center gap-3 flex-wrap">
            <span className="text-xs text-gray-400 font-medium">周期</span>
            {PERIODS.map((p) => (
              <button key={p.value} onClick={() => setPeriod(p.value)}
                className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                  period === p.value
                    ? "bg-[#10a37f] text-white border-[#10a37f]"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                }`}>
                {p.label}
              </button>
            ))}
            <span className="text-xs text-gray-300">|</span>
            {DAY_RANGES.map((r) => (
              <button key={r.value} onClick={() => setDayRange(r.value)}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                  dayRange === r.value
                    ? "bg-gray-800 text-white border-gray-800"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                }`}>
                {r.label}
              </button>
            ))}
          </div>
        )}

        {/* ── K-line Chart ── */}
        <div className={`${chartFullscreen
          ? "fixed inset-0 z-50 bg-white flex flex-col"
          : "bg-white rounded-xl border border-gray-200 p-4"}`}
        >
          {/* Chart header */}
          <div className={`flex items-center justify-between ${chartFullscreen ? "px-4 py-2 border-b border-gray-200 shrink-0" : "mb-3"}`}>
            <h3 className="font-semibold text-gray-700 flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-[#10a37f]" />
              {chartFullscreen
                ? (info?.name && !/^\d{6}$/.test(info.name) ? `${info.name} · ${code}` : code)
                : "K线图"}
              <span className="text-xs text-gray-400 font-normal">
                {period === "daily" ? "日线" : "周线"} · 复权
              </span>
            </h3>
            <div className="flex items-center gap-3">
              {!chartFullscreen && (
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-0.5 inline-block rounded" style={{backgroundColor:"#FFD600"}} /> 涨停柱
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-3 h-0.5 inline-block rounded" style={{backgroundColor:"#9b30ff"}} /> 跌停柱
                  </span>
                </div>
              )}
              {/* Settings */}
              <div className="relative" ref={settingsRef}>
                <button
                  onClick={() => setSettingsOpen(!settingsOpen)}
                  className={`p-1.5 rounded-lg transition-colors ${settingsOpen ? "text-gray-700 bg-gray-100" : "text-gray-400 hover:text-gray-600 hover:bg-gray-100"}`}
                  title="设置"
                >
                  <Settings className="w-4 h-4" />
                </button>
                {settingsOpen && (
                  <div className="absolute right-0 top-full mt-1 bg-white rounded-lg border border-gray-200 shadow-xl z-30 p-3 min-w-[180px] space-y-2">
                    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                      <input type="checkbox" checked={showCrosshair}
                        onChange={(e) => setShowCrosshair(e.target.checked)}
                        className="w-3.5 h-3.5 rounded accent-[#10a37f]" />
                      鼠标移上展示浮窗
                    </label>
                    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                      <input type="checkbox" checked={showSR}
                        onChange={(e) => setShowSR(e.target.checked)}
                        className="w-3.5 h-3.5 rounded accent-[#10a37f]" />
                      绘制支撑/阻力线
                    </label>
                    <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                      <input type="checkbox" checked={showTechSignals}
                        onChange={(e) => setShowTechSignals(e.target.checked)}
                        className="w-3.5 h-3.5 rounded accent-[#10a37f]" />
                      📌 技术指标信号标记
                    </label>
                  </div>
                )}
              </div>
              <button
                onClick={toggleFullscreen}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                title={chartFullscreen ? "退出专注模式 (Esc)" : "专注模式"}
              >
                {chartFullscreen
                  ? <Minimize2 className="w-4 h-4" />
                  : <Maximize2 className="w-4 h-4" />
                }
              </button>
            </div>
          </div>
          {/* Info bar — shows latest or hovered bar */}
          {bars.length > 0 && (() => {
            const b = hoveredBar || bars[bars.length - 1];
            if (!b) return null;
            const idx = bars.findIndex((x) => x.date === b.date);
            const prevClose = idx > 0 ? bars[idx - 1]?.close : null;
            const changePct = prevClose ? ((b.close - prevClose) / prevClose * 100) : 0;
            return (
              <div className={`flex items-center gap-3 text-xs border-b border-gray-100 py-1.5 flex-wrap ${chartFullscreen ? "px-4" : "px-1"}`}>
                <span className="text-gray-400 font-mono">{b.date}</span>
                <span className="text-gray-500">开 <span className="font-mono text-gray-700">{fmt(b.open)}</span></span>
                <span className="text-gray-500">高 <span className="font-mono" style={{color: UP_COLOR}}>{fmt(b.high)}</span></span>
                <span className="text-gray-500">低 <span className="font-mono" style={{color: DOWN_COLOR}}>{fmt(b.low)}</span></span>
                <span className="text-gray-500">收 <span className="font-mono font-semibold" style={{color: changePct >= 0 ? UP_COLOR : DOWN_COLOR}}>{fmt(b.close)}</span></span>
                <span className="text-gray-500">量 <span className="font-mono text-gray-700">{fmtVol(b.volume)}</span></span>
                <span className="text-gray-500">换手 <span className="font-mono text-gray-700">{b.turnover_rate > 0 ? `${b.turnover_rate.toFixed(2)}%` : "—"}</span></span>
                <span className="font-semibold font-mono" style={{color: changePct >= 0 ? UP_COLOR : DOWN_COLOR}}>{fmtPct(changePct)}</span>
                {b.is_limit_up && <span className="text-[10px] bg-yellow-100 text-yellow-700 px-1 rounded">涨停</span>}
                {b.is_limit_down && <span className="text-[10px] px-1 rounded" style={{backgroundColor: "#9b30ff20", color: "#9b30ff"}}>跌停</span>}
              </div>
            );
          })()}
          {/* Indicator bar */}
          {indicators && (
            <div className={`flex items-center gap-4 text-xs border-b border-gray-100 py-1 flex-wrap ${chartFullscreen ? "px-4" : "px-1"}`}>
              <span className="text-gray-400">指标</span>
              <span className="text-gray-500">
                MACD <span className="font-mono" style={{color: (indicators.macd_dif ?? 0) >= (indicators.macd_dea ?? 0) ? UP_COLOR : DOWN_COLOR}}>
                  DIF {indicators.macd_dif?.toFixed(3) ?? "—"}
                </span>
                {" "}
                <span className="font-mono text-gray-500">DEA {indicators.macd_dea?.toFixed(3) ?? "—"}</span>
                {" "}
                <span className="font-mono" style={{color: (indicators.macd_hist ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR}}>
                  {indicators.macd_hist != null ? (indicators.macd_hist >= 0 ? "+" : "") + indicators.macd_hist.toFixed(3) : "—"}
                </span>
              </span>
              <span className="text-gray-500">
                RSI <span className={`font-mono font-medium ${(indicators.rsi ?? 50) > 70 ? "text-red-500" : (indicators.rsi ?? 50) < 30 ? "text-green-500" : "text-gray-700"}`}>
                  {indicators.rsi?.toFixed(1) ?? "—"}
                </span>
              </span>
              <span className="text-gray-500">
                量比 <span className="font-mono text-gray-700">{indicators.vol_ratio != null ? indicators.vol_ratio.toFixed(2) : "—"}</span>
              </span>
            </div>
          )}
          {/* Chart body */}
          <div className={`relative ${chartFullscreen ? "flex-1 px-2 pb-2" : "w-full"}`}
            style={chartFullscreen ? {} : { height: 560 }}>
            <div ref={chartRef} className="w-full" style={{ height: "100%" }} />
            {/* Phase bands — DOM overlay, zero chart impact */}
            {phaseBands.map((band, i) => (
              <div key={i} className="absolute top-0 bottom-0 pointer-events-none z-10"
                style={{ left: band.x1, width: Math.max(band.x2 - band.x1, 1), backgroundColor: band.color }}
              />
            ))}
            {/* Crosshair tooltip — controlled by settings */}
            {showCrosshair && crosshair?.visible && (
              <div
                className="absolute z-20 bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-xl pointer-events-none"
                style={{ left: crosshair.x, top: crosshair.y, minWidth: 180 }}
              >
                <div className="font-semibold text-sm mb-1">{crosshair.date}</div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                  <span className="text-gray-400">开</span><span className="text-right">{fmt(crosshair.open)}</span>
                  <span className="text-gray-400">高</span><span className="text-right text-[#FF381A]/70">{fmt(crosshair.high)}</span>
                  <span className="text-gray-400">低</span><span className="text-right text-[#009B67]/70">{fmt(crosshair.low)}</span>
                  <span className="text-gray-400">收</span><span className={`text-right font-semibold ${crosshair.changePct >= 0 ? "text-[#FF381A]/70" : "text-[#009B67]/70"}`}>{fmt(crosshair.close)}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-gray-400">量</span><span>{fmtVol(crosshair.volume)}</span>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-gray-400">换手</span><span>{crosshair.turnoverRate > 0 ? `${crosshair.turnoverRate.toFixed(2)}%` : "—"}</span>
                </div>
                {crosshair.volRatio != null && (
                  <div className="flex justify-between gap-3">
                    <span className="text-gray-400">量比</span>
                    <span className={crosshair.volRatio > 2 ? "text-[#FF381A]/70" : crosshair.volRatio > 1 ? "text-amber-400" : ""}>
                      {crosshair.volRatio.toFixed(2)}x
                    </span>
                  </div>
                )}
                {crosshair.isLimitUp && (
                  <div className="flex justify-between gap-3">
                    <span className="text-yellow-400">涨停</span>
                    <span className="text-yellow-400">{crosshair.limitUpTime || "—"}</span>
                  </div>
                )}
                <div className={`text-xs mt-0.5 font-medium ${crosshair.changePct >= 0 ? "text-[#FF381A]/70" : "text-[#009B67]/70"}`}>
                  {fmtPct(crosshair.changePct)}
                </div>
                {/* Intraday mini chart */}
                <div className="mt-2 pt-2 border-t border-gray-700">
                  <div className="text-gray-400 text-[10px] mb-1">当日分时</div>
                  {intradayBars && intradayBars.length > 0 ? (
                    <MiniIntradayChart
                      bars={intradayBars}
                      preClose={intradayPreClose}
                      width={200}
                      height={60}
                    />
                  ) : (
                    <div className="text-gray-500 text-[10px] py-2 text-center">
                      {intradayBars === null ? "加载中..." : "无分时数据（休市日）"}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── AI Analysis Panel ── */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-700 flex items-center gap-2">
              <Zap className="w-4 h-4 text-[#10a37f]" />
              🤖 AI 威科夫分析
            </h3>
            <button
              onClick={runAnalysis}
              disabled={analyzing || !code}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#10a37f] hover:bg-[#0d8c6d]
                         text-white rounded-lg text-sm font-medium transition-colors
                         disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {analyzing ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> 分析中...</>
              ) : (
                <><Zap className="w-4 h-4" /> AI 分析此股</>
              )}
            </button>
          </div>

          {aiResult ? (
            <div className="space-y-4">
              {/* Rating Gauge + Phase */}
              <div className="flex items-start gap-4 flex-wrap">
                <RatingGauge rating={aiResult.rating} confidence={aiResult.confidence} />
                <div className="flex-1 min-w-[200px] space-y-2">
                  <div className="flex items-center gap-2">
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      aiResult.phase.includes("上涨") ? "bg-green-100 text-green-700" :
                      aiResult.phase.includes("下跌") ? "bg-red-100 text-red-700" :
                      aiResult.phase.includes("吸筹") ? "bg-blue-100 text-blue-700" :
                      aiResult.phase.includes("派发") ? "bg-orange-100 text-orange-700" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {aiResult.phase}
                    </span>
                    <span className="text-xs text-gray-500">置信度 {(aiResult.confidence * 100).toFixed(0)}%</span>
                  </div>
                  {/* Phase timeline */}
                  {aiResult.phases && aiResult.phases.length > 0 && (
                    <div className="flex items-center gap-1 flex-wrap">
                      <span className="text-[10px] text-gray-400 mr-1">阶段:</span>
                      {aiResult.phases.map((p, i) => {
                        const active = pinnedPhases.has(p.phase);
                        return (
                          <button key={i} className="text-[10px] px-1.5 py-0.5 rounded-full font-medium cursor-pointer border transition-all"
                            onClick={() => {
                              setPinnedPhases((prev) => {
                                const next = new Set(prev);
                                next.has(p.phase) ? next.delete(p.phase) : next.add(p.phase);
                                return next;
                              });
                            }}
                            style={{
                              backgroundColor: active
                                ? (PHASE_COLORS_MAP[p.phase] || "rgba(156,163,175,0.2)").replace("0.10","0.35")
                                : (PHASE_COLORS_MAP[p.phase] || "rgba(156,163,175,0.2)").replace("0.10","0.20"),
                              color: {accumulation:"#2563eb",markup:"#16a34a",distribution:"#ea580c",markdown:"#dc2626"}[p.phase] || "#6b7280",
                              borderColor: active ? ({accumulation:"#2563eb",markup:"#16a34a",distribution:"#ea580c",markdown:"#dc2626"}[p.phase] || "#6b7280") : "transparent",
                            }}
                          >
                            {p.label} {p.start_date.slice(5)}~{p.end_date.slice(5)}
                            {active ? " ✓" : ""}
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {/* Signals */}
                  {aiResult.signals && aiResult.signals.length > 0 && (
                    <div className="flex gap-1 flex-wrap">
                      {aiResult.signals.map((s, i) => (
                        <span key={i} className="text-xs bg-gray-100 border border-gray-200 px-1.5 py-0.5 rounded text-gray-600 font-mono">
                          {s}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Support & Resistance */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-green-600 font-medium mb-1.5">🟢 支撑位</div>
                  {aiResult.support_levels && aiResult.support_levels.length > 0 ? (
                    <div className="space-y-1">
                      {aiResult.support_levels.map((lvl, i) => (
                        <div key={i} className="flex justify-between text-xs bg-green-50 rounded px-2 py-1">
                          <span className="text-gray-500">{lvl.label}</span>
                          <span className="font-mono font-medium text-green-700">{lvl.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="text-xs text-gray-400">未识别</div>}
                </div>
                <div>
                  <div className="text-xs text-red-600 font-medium mb-1.5">🔴 阻力位</div>
                  {aiResult.resistance_levels && aiResult.resistance_levels.length > 0 ? (
                    <div className="space-y-1">
                      {aiResult.resistance_levels.map((lvl, i) => (
                        <div key={i} className="flex justify-between text-xs bg-red-50 rounded px-2 py-1">
                          <span className="text-gray-500">{lvl.label}</span>
                          <span className="font-mono font-medium text-red-700">{lvl.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  ) : <div className="text-xs text-gray-400">未识别</div>}
                </div>
              </div>

              {/* Analysis text */}
              <p className="text-sm text-gray-600">{aiResult.analysis}</p>
              <p className="text-sm font-medium text-[#10a37f]">{aiResult.advice}</p>
            </div>
          ) : analyzing ? (
            <p className="text-sm text-gray-400 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              AI 正在分析 {info?.name || code} 的威科夫结构...
            </p>
          ) : (
            <p className="text-sm text-gray-400">
              点击"AI 分析此股"，系统会将K线数据送入威科夫 Agent 进行结构分析（含 RAG 知识库增强）。
            </p>
          )}
        </div>
      </div>

      </div>

      {/* ── Intraday Modal (draggable, no backdrop) ── */}
      {intradayModal && (
        <div
          className="fixed z-50"
          style={{ left: intradayModal.x, top: intradayModal.y }}
          onMouseDown={(e) => {
            if ((e.target as HTMLElement).closest(".drag-handle")) {
              const startX = e.clientX - intradayModal.x;
              const startY = e.clientY - intradayModal.y;
              const onMove = (ev: MouseEvent) => {
                setIntradayModal((prev) => prev ? { ...prev, x: ev.clientX - startX, y: ev.clientY - startY } : null);
              };
              const onUp = () => {
                document.removeEventListener("mousemove", onMove);
                document.removeEventListener("mouseup", onUp);
              };
              document.addEventListener("mousemove", onMove);
              document.addEventListener("mouseup", onUp);
            }
          }}
        >
          <div className="bg-white rounded-2xl shadow-2xl" style={{ width: Math.min(window.innerWidth - 60, 820) }}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 drag-handle cursor-move select-none">
              <h3 className="text-sm font-semibold text-gray-800">{intradayModal.label} 分时图</h3>
              <button onClick={() => setIntradayModal(null)} className="p-1 rounded hover:bg-gray-100 text-gray-400">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-2">
              {(() => {
                const cached = intradayCache.current.get(intradayModal.date);
                if (!cached) {
                  return (
                    <div className="flex items-center justify-center py-20">
                      <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                      <span className="ml-2 text-sm text-gray-400">加载分时数据...</span>
                    </div>
                  );
                }
                const limitPct = bars.length > 0 ? (bars[0] as any).limit_pct ?? 10 : 10;
                return (
                  <IntradayChartFull
                    bars={cached.bars}
                    preClose={cached.preClose}
                    limitPct={limitPct}
                    width={Math.min(window.innerWidth - 60, 820)}
                    height={460}
                  />
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* AI Chat Panel — right side layout */}
      <AIChatPanel code={code} stockName={info?.name && !/^\d{6}$/.test(info.name) ? info.name : code} analysis={aiResult} />
    </div>
  );
}
