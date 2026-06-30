"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { Star, Search, Plus, X, Settings, Loader2, RefreshCw, ChevronUp, ChevronDown } from "lucide-react";

// ── Column definitions ─────────────────────────────────────────────

interface ColumnDef {
  key: string;
  label: string;
  defaultVisible: boolean;
  width?: string;
}

const ALL_COLUMNS: ColumnDef[] = [
  { key: "name", label: "股票名称", defaultVisible: true },
  { key: "price", label: "价格", defaultVisible: true, width: "w-[72px]" },
  { key: "change_pct", label: "涨幅", defaultVisible: true, width: "w-[80px]" },
  { key: "sector", label: "板块", defaultVisible: true },
  { key: "float_market_cap", label: "实际流通", defaultVisible: true, width: "w-[90px]" },
  { key: "turnover_rate", label: "换手率", defaultVisible: true, width: "w-[72px]" },
  { key: "add_date", label: "自选日", defaultVisible: true, width: "w-[80px]" },
  { key: "add_price", label: "自选价格", defaultVisible: true, width: "w-[72px]" },
  { key: "add_return", label: "自选收益", defaultVisible: true, width: "w-[80px]" },
  { key: "amplitude", label: "振幅", defaultVisible: false, width: "w-[72px]" },
  { key: "main_buy", label: "主力买入", defaultVisible: false },
  { key: "main_sell", label: "主力卖出", defaultVisible: false },
  { key: "committee_ratio", label: "委比", defaultVisible: false, width: "w-[72px]" },
  { key: "volume_ratio", label: "量比", defaultVisible: false, width: "w-[64px]" },
  { key: "total_market_cap", label: "流通市值", defaultVisible: false, width: "w-[90px]" },
  { key: "total_mcap_full", label: "总市值", defaultVisible: false, width: "w-[90px]" },
  { key: "actions", label: "操作", defaultVisible: true, width: "w-[96px]" },
];

interface ColumnSetting {
  key: string;
  visible: boolean;
  order: number;
}

const COL_CONFIG_KEY = "watchlist-columns";

function loadColumnSettings(): ColumnSetting[] {
  try {
    const raw = localStorage.getItem(COL_CONFIG_KEY);
    if (raw) {
      const saved = JSON.parse(raw) as ColumnSetting[];
      // Merge with defaults (new columns may have been added)
      const savedKeys = new Set(saved.map((s) => s.key));
      const merged = [...saved];
      for (const col of ALL_COLUMNS) {
        if (!savedKeys.has(col.key)) {
          merged.push({ key: col.key, visible: col.defaultVisible, order: merged.length });
        }
      }
      return merged.sort((a, b) => a.order - b.order);
    }
  } catch {}
  return ALL_COLUMNS.map((c, i) => ({ key: c.key, visible: c.defaultVisible, order: i }));
}

function saveColumnSettings(settings: ColumnSetting[]) {
  try { localStorage.setItem(COL_CONFIG_KEY, JSON.stringify(settings)); } catch {}
}

// ── Types ───────────────────────────────────────────────────────────

interface WatchlistStock {
  id: number;
  code: string;
  name: string;
  price: number;
  change_pct: number;
  change_amount: number;
  open: number;
  high: number;
  low: number;
  pre_close: number;
  volume: number;
  amount: number;
  amplitude: number;
  turnover_rate: number;
  volume_ratio: number;
  committee_ratio: number;
  total_market_cap: number;
  float_market_cap: number;
  pe: number;
  sector: string;
  add_price: number;
  add_date: string;
  add_return: number;
  amount_fmt: string;
  total_mcap_fmt: string;
  float_mcap_fmt: string;
  main_buy: number | null;
  main_sell: number | null;
  consecutive_boards: string | null;
}

// ── Helpers ─────────────────────────────────────────────────────────

function pctColor(v: number): string {
  if (v > 0) return "text-red-500";
  if (v < 0) return "text-green-500";
  return "text-gray-500";
}

function fmtPct(v: number): string {
  if (v === 0) return "0.00%";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

function fmtVal(v: number, decimals: number = 2): string {
  if (v === 0) return "-";
  return v.toFixed(decimals);
}

// ── Component ───────────────────────────────────────────────────────

export default function WatchlistPage() {
  const [stocks, setStocks] = useState<WatchlistStock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [columnSettings, setColumnSettings] = useState<ColumnSetting[]>(() =>
    ALL_COLUMNS.map((c, i) => ({ key: c.key, visible: c.defaultVisible, order: i }))
  );
  const [showSettings, setShowSettings] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<{ code: string; name: string; close: number; change_pct: number }[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchWarming, setSearchWarming] = useState(false);  // 数据预热中
  const [adding, setAdding] = useState<string | null>(null);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchContainerRef = useRef<HTMLDivElement>(null);
  const warmRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Visible columns (ordered) ──
  const visibleColumns = columnSettings
    .filter((s) => s.visible)
    .sort((a, b) => a.order - b.order)
    .map((s) => ALL_COLUMNS.find((c) => c.key === s.key)!)
    .filter(Boolean);

  // ── Load persisted column settings after mount (SSR-safe) ──
  useEffect(() => {
    setColumnSettings(loadColumnSettings());
    setMounted(true);
  }, []);

  // ── Fetch quotes ──
  const fetchQuotes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/watchlist/quotes");
      const json = await res.json();
      if (json.status === "ok") {
        setStocks(json.data.stocks);
      } else {
        setError(json.message || "加载失败");
      }
    } catch {
      setError("网络错误，请稍后重试");
    } finally {
      // Minimum 500ms loading for visible feedback
      setTimeout(() => setLoading(false), 500);
    }
  }, []);

  useEffect(() => { fetchQuotes(); }, [fetchQuotes]);

  // ── Auto-refresh every 30s ──
  useEffect(() => {
    const timer = setInterval(fetchQuotes, 30000);
    return () => clearInterval(timer);
  }, [fetchQuotes]);

  // ── Remove stock ──
  const removeStock = useCallback(async (id: number) => {
    try {
      await fetch(`/api/watchlist/${id}`, { method: "DELETE" });
      setStocks((prev) => prev.filter((s) => s.id !== id));
    } catch {}
  }, []);

  // ── Add stock ──
  const addStock = useCallback(async (code: string, name: string, close: number) => {
    setAdding(code);
    try {
      const res = await fetch("/api/watchlist/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, name, add_price: close }),
      });
      const json = await res.json();
      if (json.status === "ok") {
        fetchQuotes();
        setSearchQuery("");
        setSearchResults([]);
      } else {
        alert(json.message || "添加失败");
      }
    } catch {
      alert("添加失败，请稍后重试");
    } finally {
      setAdding(null);
    }
  }, [fetchQuotes]);

  // ── Search stocks (debounced 300ms) ──
  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 1) { setSearchResults([]); setSearching(false); setSearchWarming(false); return; }
    setSearching(true);
    try {
      const res = await fetch(`/api/stock/search?q=${encodeURIComponent(q)}`);
      const json = await res.json();
      if (json.status === "ok") {
        setSearchResults(json.data.slice(0, 10));
        setHighlightIdx(-1);
        setSearchWarming(false);
      } else if (json.message && json.message.includes("数据加载中")) {
        setSearchResults([]);
        setSearchWarming(true);
        // Auto-retry in 5s if still focused
        if (warmRetryRef.current) clearTimeout(warmRetryRef.current);
        warmRetryRef.current = setTimeout(() => doSearch(q), 5000);
      } else {
        setSearchResults([]);
        setSearchWarming(false);
      }
    } catch {
      setSearchResults([]);
      setSearchWarming(false);
    } finally { setSearching(false); }
  }, []);

  const searchStocks = useCallback((q: string) => {
    setSearchQuery(q);
    if (searchDebounce.current) clearTimeout(searchDebounce.current);
    if (q.trim().length < 1) { setSearchResults([]); setSearching(false); return; }
    setSearching(true);
    searchDebounce.current = setTimeout(() => doSearch(q), 300);
  }, [doSearch]);

  // ── Click outside to close search dropdown ──
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setSearchResults([]);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // ── Keyboard nav ──
  const handleSearchKey = (e: React.KeyboardEvent) => {
    if (searchResults.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((prev) => (prev + 1) % searchResults.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((prev) => (prev - 1 + searchResults.length) % searchResults.length);
    } else if (e.key === "Enter" && highlightIdx >= 0) {
      e.preventDefault();
      const r = searchResults[highlightIdx];
      if (r) addStock(r.code, r.name, r.close);
    } else if (e.key === "Escape") {
      setSearchResults([]);
    }
  };

  // ── Column settings ──
  const toggleColumn = (key: string) => {
    const next = columnSettings.map((s) =>
      s.key === key ? { ...s, visible: !s.visible } : s
    );
    setColumnSettings(next);
    saveColumnSettings(next);
  };

  const moveColumn = (key: string, direction: -1 | 1) => {
    const sorted = [...columnSettings].sort((a, b) => a.order - b.order);
    const idx = sorted.findIndex((s) => s.key === key);
    if (idx < 0) return;
    const newIdx = idx + direction;
    if (newIdx < 0 || newIdx >= sorted.length) return;
    [sorted[idx], sorted[newIdx]] = [sorted[newIdx], sorted[idx]];
    const next = sorted.map((s, i) => ({ ...s, order: i }));
    setColumnSettings(next);
    saveColumnSettings(next);
  };

  // ── Render cell ──
  const renderCell = (s: WatchlistStock, colKey: string) => {
    switch (colKey) {
      case "name":
        return (
          <div>
            <Link href={`/stock/${s.code}`} className="text-sm font-medium text-gray-800 hover:text-[#10a37f] hover:underline">
              {s.name}
            </Link>
            <div className="text-xs text-gray-400">{s.code}</div>
          </div>
        );
      case "price":
        return <span className={`text-sm font-mono font-medium ${pctColor(s.change_pct)}`}>{s.price > 0 ? s.price.toFixed(2) : "-"}</span>;
      case "change_pct":
        return (
          <div>
            <span className={`text-sm font-mono font-medium ${pctColor(s.change_pct)}`}>{fmtPct(s.change_pct)}</span>
            {s.consecutive_boards && (
              <span className="ml-1 px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">{s.consecutive_boards}</span>
            )}
          </div>
        );
      case "sector":
        return <span className="text-xs text-gray-500">{s.sector || "-"}</span>;
      case "float_market_cap":
        return <span className="text-xs text-gray-600 font-mono">{s.float_mcap_fmt || "-"}</span>;
      case "turnover_rate":
        return <span className={`text-sm font-mono ${s.turnover_rate > 5 ? "text-red-500" : "text-gray-600"}`}>{s.turnover_rate > 0 ? `${s.turnover_rate.toFixed(2)}%` : "-"}</span>;
      case "add_date":
        return <span className="text-xs text-gray-500">{s.add_date || "-"}</span>;
      case "add_price":
        return <span className="text-sm text-gray-600 font-mono">{s.add_price > 0 ? s.add_price.toFixed(2) : "-"}</span>;
      case "add_return":
        return <span className={`text-sm font-mono font-medium ${pctColor(s.add_return)}`}>{fmtPct(s.add_return)}</span>;
      case "amplitude":
        return <span className="text-sm text-gray-600 font-mono">{s.amplitude > 0 ? `${s.amplitude.toFixed(2)}%` : "-"}</span>;
      case "main_buy":
        return <span className="text-xs text-red-500 font-mono">{s.main_buy != null ? fmtVal(s.main_buy) : "-"}</span>;
      case "main_sell":
        return <span className="text-xs text-green-500 font-mono">{s.main_sell != null ? fmtVal(s.main_sell) : "-"}</span>;
      case "committee_ratio":
        return <span className={`text-sm font-mono ${pctColor(s.committee_ratio)}`}>{s.committee_ratio !== 0 ? `${s.committee_ratio.toFixed(2)}%` : "-"}</span>;
      case "volume_ratio":
        return <span className={`text-sm font-mono ${s.volume_ratio > 1.5 ? "text-red-500" : s.volume_ratio < 0.5 ? "text-green-500" : "text-gray-600"}`}>{s.volume_ratio > 0 ? s.volume_ratio.toFixed(2) : "-"}</span>;
      case "total_market_cap":
        return <span className="text-xs text-gray-600 font-mono">{s.float_mcap_fmt || "-"}</span>;
      case "total_mcap_full":
        return <span className="text-xs text-gray-600 font-mono">{s.total_mcap_fmt || "-"}</span>;
      case "actions":
        return (
          <div className="flex items-center gap-1.5">
            <a href={`https://stockpage.10jqka.com.cn/${s.code}/`} target="_blank" rel="noopener noreferrer"
              className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap">同花顺</a>
            <Link href={`/stock/${s.code}`} target="_blank"
              className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap">分析</Link>
            <button onClick={() => removeStock(s.id)} className="text-xs text-gray-400 hover:text-red-500" title="移出自选">
              <X className="w-3 h-3" />
            </button>
          </div>
        );
      default:
        return null;
    }
  };

  // ── Render ──
  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <main className="max-w-full mx-auto px-4 py-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Star className="w-5 h-5 text-[#10a37f]" />
            <h1 className="text-lg font-bold text-gray-800">自选股</h1>
            <span className="text-sm text-gray-400">({stocks.length})</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={fetchQuotes} disabled={loading}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5"
            >
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} /> 刷新
            </button>
            <div className="relative">
              <button onClick={() => setShowSettings(!showSettings)}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg px-2.5 py-1.5"
              >
                <Settings className="w-3 h-3" /> 列设置
              </button>
              {showSettings && (
                <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-50 p-3 w-56 max-h-96 overflow-y-auto">
                  <p className="text-xs text-gray-400 mb-2">拖拽排序 · 勾选显示</p>
                  {columnSettings.sort((a, b) => a.order - b.order).map((cs, idx) => {
                    const def = ALL_COLUMNS.find((c) => c.key === cs.key);
                    if (!def) return null;
                    return (
                      <div key={cs.key} className="flex items-center gap-2 py-1">
                        <button onClick={() => moveColumn(cs.key, -1)} disabled={idx === 0}
                          className="text-gray-300 hover:text-gray-500 disabled:opacity-20">
                          <ChevronUp className="w-3 h-3" />
                        </button>
                        <button onClick={() => moveColumn(cs.key, 1)} disabled={idx === columnSettings.length - 1}
                          className="text-gray-300 hover:text-gray-500 disabled:opacity-20">
                          <ChevronDown className="w-3 h-3" />
                        </button>
                        <label className="flex items-center gap-1.5 flex-1 cursor-pointer text-xs text-gray-600">
                          <input type="checkbox" checked={cs.visible} onChange={() => toggleColumn(cs.key)}
                            className="accent-[#10a37f] w-3.5 h-3.5" />
                          {def.label}
                        </label>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Search / Add */}
        <div className="relative" ref={searchContainerRef}>
          <div className={`flex items-center gap-2 bg-white border rounded-xl px-3 py-2 transition-colors ${searchResults.length > 0 ? "border-[#10a37f] shadow-sm" : "border-gray-200"}`}>
            <Search className="w-4 h-4 text-gray-400 shrink-0" />
            <input
              value={searchQuery}
              onChange={(e) => searchStocks(e.target.value)}
              onKeyDown={handleSearchKey}
              placeholder="搜索股票代码或名称，添加到自选..."
              className="flex-1 text-sm outline-none bg-transparent"
            />
            {searching && <Loader2 className="w-4 h-4 animate-spin text-gray-400 shrink-0" />}
            {searchResults.length > 0 && (
              <span className="text-xs text-gray-400 shrink-0">{searchResults.length} 个结果</span>
            )}
          </div>
          {(searchResults.length > 0 || searchWarming) && (
            <div className="absolute left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-xl shadow-lg z-50 max-h-80 overflow-y-auto">
              {searchWarming && (
                <div className="px-4 py-4 text-center">
                  <Loader2 className="w-4 h-4 animate-spin text-[#10a37f] mx-auto mb-1" />
                  <p className="text-xs text-gray-400">数据加载中，请稍候...</p>
                  <p className="text-xs text-gray-300 mt-0.5">首次加载约需1分钟</p>
                </div>
              )}
              {searchResults.map((r, idx) => {
                const alreadyAdded = stocks.some((s) => s.code === r.code);
                const isHighlighted = idx === highlightIdx;
                return (
                  <button key={r.code}
                    onClick={() => addStock(r.code, r.name, r.close)}
                    disabled={adding === r.code || alreadyAdded}
                    className={`w-full text-left px-4 py-2.5 flex items-center justify-between transition-colors disabled:opacity-40 ${isHighlighted ? "bg-[#10a37f]/10" : "hover:bg-gray-50"}`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm font-medium text-gray-800 truncate">{r.name}</span>
                      <span className="text-xs text-gray-400 font-mono shrink-0">{r.code}</span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 ml-4">
                      <div className="text-right">
                        <span className="text-sm text-gray-700 font-mono">{r.close.toFixed(2)}</span>
                        <span className={`ml-1.5 text-xs font-mono ${r.change_pct > 0 ? "text-red-500" : r.change_pct < 0 ? "text-green-500" : "text-gray-400"}`}>
                          {r.change_pct > 0 ? "+" : ""}{r.change_pct.toFixed(2)}%
                        </span>
                      </div>
                      {adding === r.code ? (
                        <Loader2 className="w-4 h-4 animate-spin text-[#10a37f]" />
                      ) : alreadyAdded ? (
                        <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">已添加</span>
                      ) : (
                        <Plus className="w-4 h-4 text-[#10a37f]" />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-600">{error}</div>
        )}

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                  {visibleColumns.map((col) => (
                    <th key={col.key} className={`pb-3 pt-3 px-3 font-medium whitespace-nowrap ${col.width || ""}`}>
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading && stocks.length === 0 && (
                  <tr>
                    <td colSpan={visibleColumns.length} className="py-12 text-center">
                      <Loader2 className="w-5 h-5 animate-spin text-gray-400 mx-auto mb-2" />
                      <p className="text-sm text-gray-400">加载中...</p>
                    </td>
                  </tr>
                )}
                {!loading && stocks.length === 0 && (
                  <tr>
                    <td colSpan={visibleColumns.length} className="py-12 text-center">
                      <Star className="w-8 h-8 text-gray-300 mx-auto mb-2" />
                      <p className="text-sm text-gray-400">暂无自选股</p>
                      <p className="text-xs text-gray-300 mt-1">在上方搜索框中搜索股票代码或名称添加</p>
                    </td>
                  </tr>
                )}
                {stocks.map((s) => (
                  <tr key={s.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                    {visibleColumns.map((col) => (
                      <td key={col.key} className="py-2.5 px-3 align-middle">
                        {renderCell(s, col.key)}
                      </td>
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
