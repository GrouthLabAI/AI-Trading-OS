"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { TrendingUp, Loader2, RefreshCw, Settings, ChevronUp, ChevronDown, ExternalLink } from "lucide-react";

// ── Types ───────────────────────────────────────────────────────────

interface LimitUpStock {
  code: string; name: string;
  change_pct: number; close: number;
  amount: number; float_market_cap: number; total_market_cap: number;
  turnover_rate: number; open_count: number;
  first_limit_time: string; last_limit_time: string;
  seal_amount: number; limit_up_stat: string;
  sector: string; board_count: number;
  amplitude: number; volume_ratio: number;
}

// ── Column definitions ──────────────────────────────────────────────

interface ColumnDef {
  key: string; label: string; defaultVisible: boolean; width?: string;
}

const ALL_COLUMNS: ColumnDef[] = [
  { key: "name", label: "股票名称", defaultVisible: true, width: "w-[130px]" },
  { key: "first_limit_time", label: "涨停时间", defaultVisible: true, width: "w-[60px]" },
  { key: "close", label: "价格", defaultVisible: true, width: "w-[58px]" },
  { key: "change_pct", label: "涨幅", defaultVisible: true, width: "w-[68px]" },
  { key: "seal_amount", label: "封单", defaultVisible: true, width: "w-[76px]" },
  { key: "open_count", label: "炸板", defaultVisible: true, width: "w-[48px]" },
  { key: "turnover_rate", label: "换手率", defaultVisible: true, width: "w-[64px]" },
  { key: "amplitude", label: "振幅", defaultVisible: false, width: "w-[60px]" },
  { key: "volume_ratio", label: "量比", defaultVisible: false, width: "w-[52px]" },
  { key: "total_market_cap", label: "总市值", defaultVisible: true, width: "w-[84px]" },
  { key: "float_market_cap", label: "实际流通", defaultVisible: false, width: "w-[84px]" },
  { key: "amount", label: "成交额", defaultVisible: false, width: "w-[76px]" },
  { key: "sector", label: "板块", defaultVisible: true, width: "w-[76px]" },
  { key: "board_count", label: "连板", defaultVisible: true, width: "w-[46px]" },
  { key: "limit_up_stat", label: "类型", defaultVisible: false, width: "w-[56px]" },
  { key: "actions", label: "操作", defaultVisible: true, width: "w-[100px]" },
];

interface ColumnSetting { key: string; visible: boolean; order: number; }
const COL_KEY = "limitup-columns";

function loadCols(): ColumnSetting[] {
  try {
    const r = localStorage.getItem(COL_KEY);
    if (r) {
      const saved = JSON.parse(r) as ColumnSetting[];
      const keys = new Set(saved.map((s) => s.key));
      const merged = [...saved];
      for (const c of ALL_COLUMNS) {
        if (!keys.has(c.key)) merged.push({ key: c.key, visible: c.defaultVisible, order: merged.length });
      }
      return merged.sort((a, b) => a.order - b.order);
    }
  } catch {}
  return ALL_COLUMNS.map((c, i) => ({ key: c.key, visible: c.defaultVisible, order: i }));
}
function saveCols(s: ColumnSetting[]) { try { localStorage.setItem(COL_KEY, JSON.stringify(s)); } catch {} }

// ── Helpers ─────────────────────────────────────────────────────────

function pctColor(v: number): string { if (v > 0) return "text-red-500"; if (v < 0) return "text-green-500"; return "text-gray-500"; }
function fmtPct(v: number): string { if (!v) return "0.00%"; return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`; }
function fmtAmt(v: number): string { if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`; if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`; return v.toFixed(0); }
function fmtTime(t: string): string { if (!t || t.length < 4) return "-"; return `${t.slice(0, 2)}:${t.slice(2, 4)}`; }

const TABS = [
  { key: "1", label: "一板" },
  { key: "2", label: "二板" },
  { key: "3", label: "三板" },
  { key: "4", label: "四板" },
  { key: "high", label: "更高" },
] as const;

// ── Component ───────────────────────────────────────────────────────

export default function LimitUpPage() {
  const [stocks, setStocks] = useState<LimitUpStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [colSettings, setColSettings] = useState<ColumnSetting[]>(loadCols);
  const [showSettings, setShowSettings] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<string>("1");

  const visibleCols = colSettings.filter((s) => s.visible).sort((a, b) => a.order - b.order)
    .map((s) => ALL_COLUMNS.find((c) => c.key === s.key)!).filter(Boolean);

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetch("/api/market/limit-ups");
      const json = await res.json();
      if (json.status === "ok") setStocks(json.data);
      else setError(json.message || "加载失败");
    } catch { setError("网络错误"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => { const t = setInterval(fetchData, 30000); return () => clearInterval(t); }, [fetchData]);
  useEffect(() => {
    const onClick = (e: MouseEvent) => { if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) setShowSettings(false); };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // ── Filter by tab ──
  const filtered = stocks.filter((s) => {
    const bc = s.board_count || 1;
    if (activeTab === "high") return bc >= 5;
    return bc === parseInt(activeTab);
  });

  // ── Counts per tab ──
  const counts = {} as Record<string, number>;
  for (let b = 1; b <= 4; b++) counts[String(b)] = stocks.filter((s) => (s.board_count || 1) === b).length;
  counts.high = stocks.filter((s) => (s.board_count || 1) >= 5).length;

  // ── Column settings ──
  const toggleCol = (k: string) => {
    const n = colSettings.map((s) => s.key === k ? { ...s, visible: !s.visible } : s);
    setColSettings(n); saveCols(n);
  };
  const moveCol = (k: string, d: -1 | 1) => {
    const s = [...colSettings].sort((a, b) => a.order - b.order);
    const i = s.findIndex((x) => x.key === k);
    if (i < 0) return; const ni = i + d; if (ni < 0 || ni >= s.length) return;
    [s[i], s[ni]] = [s[ni], s[i]];
    const n = s.map((x, j) => ({ ...x, order: j }));
    setColSettings(n); saveCols(n);
  };

  // ── Render cell ──
  const cell = (s: LimitUpStock, k: string) => {
    switch (k) {
      case "name": return <div><Link href={`/stock/${s.code}`} className="text-sm font-medium text-gray-800 hover:text-[#10a37f] hover:underline">{s.name}</Link><div className="text-xs text-gray-400">{s.code}</div></div>;
      case "first_limit_time": return <span className="text-xs font-mono text-gray-500">{fmtTime(s.first_limit_time)}</span>;
      case "close": return <span className={`text-sm font-mono font-medium ${pctColor(s.change_pct)}`}>{s.close?.toFixed(2) || "-"}</span>;
      case "change_pct": return <span className={`text-sm font-mono font-medium ${pctColor(s.change_pct)}`}>{fmtPct(s.change_pct)}</span>;
      case "seal_amount": return <span className="text-xs font-mono text-gray-600">{s.seal_amount > 0 ? fmtAmt(s.seal_amount) : "-"}</span>;
      case "open_count": return <span className={`text-xs ${s.open_count > 0 ? "text-amber-600 font-medium" : "text-gray-400"}`}>{s.open_count > 0 ? `${s.open_count}次` : "0"}</span>;
      case "turnover_rate": return <span className={`text-xs font-mono ${s.turnover_rate > 10 ? "text-red-500" : "text-gray-600"}`}>{s.turnover_rate > 0 ? `${s.turnover_rate.toFixed(2)}%` : "-"}</span>;
      case "amplitude": return <span className="text-xs font-mono text-gray-600">{s.amplitude > 0 ? `${s.amplitude.toFixed(2)}%` : "-"}</span>;
      case "volume_ratio": return <span className="text-xs font-mono text-gray-600">{s.volume_ratio > 0 ? s.volume_ratio.toFixed(2) : "-"}</span>;
      case "total_market_cap": return <span className="text-xs font-mono text-gray-600">{s.total_market_cap > 0 ? fmtAmt(s.total_market_cap) : "-"}</span>;
      case "float_market_cap": return <span className="text-xs font-mono text-gray-600">{s.float_market_cap > 0 ? fmtAmt(s.float_market_cap) : "-"}</span>;
      case "amount": return <span className="text-xs font-mono text-gray-600">{s.amount > 0 ? fmtAmt(s.amount) : "-"}</span>;
      case "sector": return <span className="text-xs text-gray-500">{s.sector || "-"}</span>;
      case "board_count": {
        const bc = s.board_count || 1;
        return <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${bc === 1 ? "bg-blue-100 text-blue-700" : bc <= 3 ? "bg-purple-100 text-purple-700" : bc <= 4 ? "bg-indigo-100 text-indigo-700" : "bg-red-100 text-red-700"}`}>{bc}板</span>;
      }
      case "limit_up_stat": return <span className="text-xs text-gray-500">{s.limit_up_stat || "-"}</span>;
      case "actions": return (
        <div className="flex items-center gap-1.5">
          <a href={`https://stockpage.10jqka.com.cn/${s.code}/`} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap">同花顺</a>
          <Link href={`/stock/${s.code}`} target="_blank" className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap">分析</Link>
        </div>
      );
      default: return null;
    }
  };

  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <main className="max-w-full mx-auto px-4 py-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-[#10a37f]" />
            <h1 className="text-lg font-bold text-gray-800">涨停板</h1>
            <span className="text-sm text-gray-400">({stocks.length})</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={fetchData} disabled={loading}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5">
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> 刷新
            </button>
            <div className="relative" ref={settingsRef}>
              <button onClick={() => setShowSettings(!showSettings)}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5">
                <Settings className="w-3 h-3" /> 列设置
              </button>
              {showSettings && (
                <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-50 p-3 w-56 max-h-96 overflow-y-auto">
                  <p className="text-xs text-gray-400 mb-2">排序 · 显隐</p>
                  {colSettings.sort((a, b) => a.order - b.order).map((cs, i) => {
                    const d = ALL_COLUMNS.find((c) => c.key === cs.key); if (!d) return null;
                    return (
                      <div key={cs.key} className="flex items-center gap-2 py-1">
                        <button onClick={() => moveCol(cs.key, -1)} disabled={i === 0} className="text-gray-300 hover:text-gray-500 disabled:opacity-20"><ChevronUp className="w-3 h-3" /></button>
                        <button onClick={() => moveCol(cs.key, 1)} disabled={i === colSettings.length - 1} className="text-gray-300 hover:text-gray-500 disabled:opacity-20"><ChevronDown className="w-3 h-3" /></button>
                        <label className="flex items-center gap-1.5 flex-1 cursor-pointer text-xs text-gray-600">
                          <input type="checkbox" checked={cs.visible} onChange={() => toggleCol(cs.key)} className="accent-[#10a37f] w-3.5 h-3.5" />
                          {d.label}
                        </label>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 flex-wrap">
          {TABS.map((tab) => {
            const count = counts[tab.key] ?? 0;
            return (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                className={`relative px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === tab.key ? "bg-gray-900 text-white" : "bg-white text-gray-600 hover:bg-gray-100 border border-gray-200"
                }`}>
                {tab.label}
                {count > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] flex items-center justify-center rounded-full bg-red-500 text-white text-[10px] font-bold px-1">
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Error */}
        {error && <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-600">{error}</div>}

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm table-fixed">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                  {visibleCols.map((col) => (
                    <th key={col.key} className={`pb-3 pt-3 px-3 font-medium whitespace-nowrap ${col.width || ""}`}>{col.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && stocks.length === 0 && (
                  <tr><td colSpan={visibleCols.length} className="py-12 text-center"><Loader2 className="w-5 h-5 animate-spin text-gray-400 mx-auto mb-2" /><p className="text-sm text-gray-400">加载中...</p></td></tr>
                )}
                {!loading && filtered.length === 0 && (
                  <tr><td colSpan={visibleCols.length} className="py-12 text-center"><TrendingUp className="w-8 h-8 text-gray-300 mx-auto mb-2" /><p className="text-sm text-gray-400">该分类无标的</p></td></tr>
                )}
                {filtered.map((s) => (
                  <tr key={s.code} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                    {visibleCols.map((col) => (
                      <td key={col.key} className="py-2.5 px-3 align-middle truncate">{cell(s, col.key)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
