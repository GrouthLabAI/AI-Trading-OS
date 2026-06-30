"use client";

import { useState, useCallback } from "react";
import { TrendingUp, Loader2, Download, Send, Check, BarChart3 } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";

/** Format number with thousand separators: 100000 → 100,000 */
function fmt(n: number | string | undefined | null, decimals = 0): string {
  if (n === undefined || n === null || n === "") return "-";
  const num = typeof n === "string" ? parseFloat(n) : n;
  if (isNaN(num)) return String(n);
  return num.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtPct(n: number | string | undefined | null): string {
  const v = typeof n === "string" ? parseFloat(n) : (n ?? 0);
  if (isNaN(v)) return "-";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

interface StrategyInfo {
  name: string; description: string;
  params: Record<string, { label: string; type: string; default: number; min: number; max: number }>;
}

interface BacktestStats {
  code: string; date_range: string;
  stats: {
    return_pct: number; buy_hold_return_pct: number;
    max_drawdown_pct: number; sharpe_ratio: number;
    win_rate_pct: number; total_trades: number;
    best_trade_pct: number; worst_trade_pct: number;
    avg_trade_pct: number;
  };
  trades: { entry_time: string; exit_time: string; entry_price: number; exit_price: number; pnl: number; return_pct: number; hold_days: number }[];
  equity_curve: { date: string; equity: number }[];
  risk_metrics?: { avg_win: number; avg_loss: number; profit_loss_ratio: number; profit_factor: number; max_consecutive_wins: number; max_consecutive_losses: number; calmar_ratio: number; annual_volatility_pct: number; var_95_pct: number; var_99_pct: number; expectancy: number };
}

interface ResultItem {
  strategy: string; name: string; data: BacktestStats; error?: string; _code?: string;
}

const RANGES = [
  { label: "1年", value: "1y" }, { label: "2年", value: "2y" },
  { label: "3年", value: "3y" }, { label: "5年", value: "5y" },
  { label: "自定义", value: "custom" },
];

function rangeDates(range: string): { start: string; end: string } {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  let start = end;
  const y = today.getFullYear();
  const m = String(today.getMonth() + 1).padStart(2, "0");
  const d = String(today.getDate()).padStart(2, "0");
  switch (range) {
    case "1y": start = `${y - 1}-${m}-${d}`; break;
    case "2y": start = `${y - 2}-${m}-${d}`; break;
    case "3y": start = `${y - 3}-${m}-${d}`; break;
    case "5y": start = `${y - 5}-${m}-${d}`; break;
  }
  return { start, end };
}

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<Record<string, StrategyInfo>>({});
  const [loaded, setLoaded] = useState(false);

  const [codes, setCodes] = useState("");
  const [selected, setSelected] = useState<string[]>(["first_board"]);
  const [cash, setCash] = useState(100000);
  const [range, setRange] = useState("1y");
  const [startDate, setStartDate] = useState(rangeDates("1y").start);
  const [endDate, setEndDate] = useState(rangeDates("1y").end);
  const [optimize, setOptimize] = useState(false);
  const [params, setParams] = useState<Record<string, number>>({});
  const [optimizeParams, setOptimizeParams] = useState<Record<string, string[]>>({});
  const [results, setResults] = useState<ResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [htmlPath, setHtmlPath] = useState("");
  const [showChart, setShowChart] = useState(false);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartHtml, setChartHtml] = useState("");
  const [activeTab, setActiveTab] = useState("");

  async function loadChart(strategyKey: string) {
    setChartLoading(true); setShowChart(true); setChartHtml("");
    const firstCode = codes.trim().split(/[,\s\n]+/).filter(Boolean)[0] || "002636";
    try {
      const res = await fetch("/api/backtest/report/chart-image", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: firstCode, strategy: strategyKey, cash, start_date: startDate, end_date: endDate, params }),
      });
      setChartHtml(await res.text());
    } catch { /* */ } finally { setChartLoading(false); }
  }

  const loadStrategies = useCallback(async () => {
    if (loaded) return;
    try {
      const res = await fetch("/api/backtest/strategies");
      const json = await res.json();
      if (json.status === "ok") {
        setStrategies(json.strategies);
        const keys = Object.keys(json.strategies);
        if (keys.length > 0) {
          setSelected([keys[0]]);
          const first = json.strategies[keys[0]] as StrategyInfo;
          const d: Record<string, number> = {};
          Object.entries(first.params).forEach(([k, v]) => { d[k] = v.default; });
          setParams(d);
        }
      }
    } catch { /* */ }
    setLoaded(true);
  }, [loaded]);

  function toggleStrategy(key: string) {
    setSelected(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
    // Update params to match the first selected strategy
    const info = strategies[key];
    if (info && selected.length === 0) {
      const d: Record<string, number> = {};
      Object.entries(info.params).forEach(([k, v]) => { d[k] = v.default; });
      setParams(d);
    }
  }

  function selectRange(r: string) {
    setRange(r);
    if (r !== "custom") {
      const d = rangeDates(r);
      setStartDate(d.start);
      setEndDate(d.end);
    }
  }

  async function run() {
    if (!codes.trim() || selected.length === 0) return;
    setLoading(true);
    setResults([]);
    try {
      const body: any = { codes, strategies: selected, cash, start_date: startDate, end_date: endDate, params, optimize };
      if (optimize) {
        const op: Record<string, (number)[]> = {};
        Object.entries(optimizeParams).forEach(([k, valStr]) => {
          if (valStr && valStr.length > 0) {
            const info = strategies[selected[0]]?.params[k];
            op[k] = valStr[0].split(",").map(v =>
              info?.type === "int" ? parseInt(v.trim()) : parseFloat(v.trim())
            ).filter(v => !isNaN(v));
          }
        });
        body.optimize_params = op;
      }
      const res = await fetch("/api/backtest/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const json = await res.json();
      if (json.status === "ok" && json.stocks?.length > 0) {
        // Flatten into old format for compatibility
        const flat: ResultItem[] = [];
        json.stocks.forEach((s: any) => {
          s.results.forEach((r: any) => {
            flat.push({ ...r, _code: s.code, data: r.data ? { ...r.data, code: s.code } : null });
          });
        });
        setResults(flat);
        if (flat.length > 0) setActiveTab(flat[0].strategy);
      }
    } catch { /* */ } finally {
      setLoading(false);
    }
  }

  async function exportHtml() {
    try {
      const res = await fetch("/api/backtest/report/html", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes, strategies: selected, cash, start_date: startDate, end_date: endDate, params }) });
      const json = await res.json();
      if (json.status === "ok") setHtmlPath(json.filepath);
    } catch { /* */ }
  }

  async function pushFeishu() {
    try {
      await fetch("/api/backtest/report/feishu", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes, strategies: selected, cash, start_date: startDate, end_date: endDate, params }) });
      alert("已推送到飞书");
    } catch { /* */ }
  }

  if (!loaded) loadStrategies();

  const firstInfo = selected.length > 0 ? strategies[selected[0]] : null;

  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <div className="max-w-8xl mx-auto px-4 py-6 space-y-6">
        <h2 className="text-lg font-semibold text-gray-700 flex items-center gap-2">
          <TrendingUp className="w-5 h-5 text-[#10a37f]" /> 策略回测
        </h2>

        {/* Input Form */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">股票代码 *（多个用逗号/空格/换行分隔）</label>
              <textarea value={codes} onChange={e => setCodes(e.target.value)}
                placeholder="002636, 000768&#10;或每行一个代码"
                rows={2} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">初始资金</label>
              <input type="number" value={cash} onChange={e => setCash(Number(e.target.value))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">回测范围 *</label>
              <div className="flex gap-1 flex-wrap">
                {RANGES.map(r => (
                  <button key={r.value} onClick={() => selectRange(r.value)}
                    className={`px-2 py-1 text-xs rounded border ${range === r.value ? "bg-[#10a37f] text-white border-[#10a37f]" : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"}`}>
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {range === "custom" && (
            <div className="flex gap-4 mb-4">
              <div><label className="block text-xs text-gray-500 mb-1">开始日期</label><input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" /></div>
              <div><label className="block text-xs text-gray-500 mb-1">结束日期</label><input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" /></div>
            </div>
          )}

          {/* Strategy checkboxes */}
          <div className="border-t border-gray-100 pt-4 mb-4">
            <label className="block text-xs text-gray-500 mb-2">策略选择（可多选）</label>
            <div className="flex flex-wrap gap-2">
              {Object.entries(strategies).map(([key, info]) => (
                <button key={key} onClick={() => toggleStrategy(key)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border transition-colors ${selected.includes(key) ? "bg-[#10a37f] text-white border-[#10a37f]" : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"}`}>
                  {selected.includes(key) && <Check className="w-3 h-3" />}
                  {info.name}
                </button>
              ))}
            </div>
          </div>

          {/* Strategy params */}
          {firstInfo && (
            <div className="border-t border-gray-100 pt-4 mb-4">
              <p className="text-xs text-gray-400 mb-2">参数设置（应用于所有选中策略）</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(firstInfo.params).map(([key, val]) => (
                  <div key={key}>
                    <label className="block text-xs text-gray-500 mb-1">{val.label}</label>
                    <input type="number" step={val.type === "int" ? 1 : 0.1}
                      value={params[key] ?? val.default}
                      onChange={e => setParams(p => ({ ...p, [key]: val.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value) }))}
                      className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm" />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center gap-2 mb-4">
            <input type="checkbox" checked={optimize} onChange={() => setOptimize(!optimize)} className="w-4 h-4" />
            <span className="text-sm text-gray-600">参数优化（网格搜索，耗时长）</span>
          </div>

          {optimize && firstInfo && (
            <div className="bg-amber-50 rounded-lg p-3 mb-4">
              <p className="text-xs text-amber-700 mb-2">为每个参数输入候选值，逗号分隔（如: 3,5,7）</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {Object.entries(firstInfo.params).map(([key, val]) => (
                  <div key={key}>
                    <label className="block text-xs text-gray-500 mb-1">{val.label}</label>
                    <input placeholder={`${val.default}`}
                      value={optimizeParams[key] || ""}
                      onChange={e => setOptimizeParams(p => ({ ...p, [key]: e.target.value ? [e.target.value] : [] }))}
                      className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm" />
                  </div>
                ))}
              </div>
            </div>
          )}

          <button onClick={run} disabled={loading || !codes.trim() || selected.length === 0}
            className="bg-[#10a37f] hover:bg-[#0d8c6d] disabled:bg-gray-300 text-white rounded-lg px-6 py-2.5 text-sm font-medium">
            {loading ? <><Loader2 className="w-4 h-4 inline animate-spin mr-1" /> 回测中...</> : "运行回测"}
          </button>
        </div>

        {/* Results */}
        {results.length > 0 && (
          <div className="space-y-6">
            {/* Comparison table */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">📊 策略对比</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                      <th className="pb-2">指标</th>
                      {results.filter(r => !r.error).map(r => (
                        <th key={r.strategy+r._code} className="pb-2 font-medium text-gray-700">{r._code ? `${r._code} ` : ""}{r.name || r.strategy}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {["return_pct","win_rate_pct","max_drawdown_pct","sharpe_ratio","total_trades","best_trade_pct","worst_trade_pct","avg_trade_pct","buy_hold_return_pct"].map(metric => {
                      const labels: Record<string,string> = { return_pct:"总收益率", win_rate_pct:"胜率", max_drawdown_pct:"最大回撤", sharpe_ratio:"夏普", total_trades:"交易次数", best_trade_pct:"最佳交易", worst_trade_pct:"最差交易", avg_trade_pct:"平均交易", buy_hold_return_pct:"买入持有" };
                      const isPct = metric.includes("pct") || metric.includes("drawdown");
                      return (
                        <tr key={metric} className="border-b border-gray-50">
                          <td className="py-1.5 text-gray-500 text-xs">{labels[metric]||metric}</td>
                          {results.filter(r => !r.error).map(r => {
                            const s = r.data?.stats; if (!s) return <td key={r.strategy} className="py-1.5 text-xs">-</td>;
                            const val = Number(s[metric as keyof typeof s]);
                            const color = metric === "return_pct" || metric === "buy_hold_return_pct" ? (val >= 0 ? "text-red-500" : "text-green-500") : metric === "max_drawdown_pct" ? "text-amber-500" : metric === "sharpe_ratio" ? (val >= 1 ? "text-red-500" : "text-gray-500") : "";
                            return (<td key={r.strategy} className={`py-1.5 text-xs font-medium ${color}`}>{isPct ? fmtPct(val) : metric === "sharpe_ratio" ? val.toFixed(2) : fmt(val)}</td>);
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Equity Curve + Action buttons */}
            <div className="flex gap-3 flex-wrap">
              <button onClick={exportHtml}
                className="flex items-center gap-1.5 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
                <Download className="w-4 h-4" /> 导出HTML
              </button>
              <button onClick={pushFeishu}
                className="flex items-center gap-1.5 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
                <Send className="w-4 h-4" /> 推送到飞书
              </button>
              {activeTab && (
                <button onClick={() => loadChart(activeTab)} disabled={chartLoading}
                  className="flex items-center gap-1.5 px-4 py-2 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                  {chartLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
                  查看图表
                </button>
              )}
              {htmlPath && <p className="text-xs text-gray-400 self-center">已生成: {htmlPath}</p>}
            </div>

            {/* Equity curve (Recharts) */}
            {results.filter(r => !r.error && r.data?.equity_curve?.length > 0).length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-700 mb-3">📈 权益曲线</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {results.filter(r => !r.error && r.data?.equity_curve?.length > 0).map(r => (
                    <div key={r.strategy}>
                      <p className="text-xs text-gray-500 mb-2">{r.name || r.strategy}</p>
                      <ResponsiveContainer width="100%" height={200}>
                        <AreaChart data={r.data.equity_curve}>
                          <defs>
                            <linearGradient id={`grad-${r.strategy}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#10a37f" stopOpacity={0.3} />
                              <stop offset="100%" stopColor="#10a37f" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis dataKey="date" tick={{fontSize:10}} interval="preserveStartEnd" />
                          <YAxis tick={{fontSize:10}} domain={["auto","auto"]} />
                          <Tooltip formatter={(v: any) => `¥${Number(v).toFixed(0)}`} />
                          <Area type="monotone" dataKey="equity" stroke="#10a37f" fill={`url(#grad-${r.strategy})`} strokeWidth={2} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Risk metrics */}
            {results.filter(r => !r.error && r.data?.risk_metrics).length > 0 && (
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="font-semibold text-gray-700 mb-3">🛡️ 风控指标</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                        <th className="pb-2">指标</th>
                        {results.filter(r => !r.error).map(r => <th key={r.strategy} className="pb-2 font-medium text-gray-700">{r.name||r.strategy}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {["profit_loss_ratio","profit_factor","calmar_ratio","annual_volatility_pct","max_consecutive_wins","max_consecutive_losses","var_95_pct","var_99_pct","expectancy"].map(metric => {
                        const labels: Record<string,string> = { profit_loss_ratio:"盈亏比", profit_factor:"盈利因子", calmar_ratio:"Calmar比率", annual_volatility_pct:"年化波动率%", max_consecutive_wins:"最长连胜", max_consecutive_losses:"最长连败", var_95_pct:"VaR(95%)", var_99_pct:"VaR(99%)", expectancy:"期望值" };
                        return (
                          <tr key={metric} className="border-b border-gray-50">
                            <td className="py-1.5 text-gray-500 text-xs">{labels[metric]||metric}</td>
                            {results.filter(r => !r.error).map(r => {
                              const val = r.data?.risk_metrics?.[metric as keyof typeof r.data.risk_metrics];
                              if (val === undefined || val === null) return <td key={r.strategy} className="py-1.5 text-xs">-</td>;
                              const pctMetrics = ["annual_volatility_pct","var_95_pct","var_99_pct"];
                              const formatted = pctMetrics.includes(metric) ? `${Number(val).toFixed(1)}%` : Number(val).toFixed(2);
                              return <td key={r.strategy} className="py-1.5 text-xs font-medium">{formatted}</td>;
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Bokeh chart iframe */}
            {showChart && (
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold text-gray-700">📊 回测图表（K线+买卖点+权益+回撤）</h3>
                  <button onClick={() => setShowChart(false)} className="text-xs text-gray-400 hover:text-gray-600">收起</button>
                </div>
                {chartLoading ? (
                  <p className="text-sm text-gray-400 py-8 text-center"><Loader2 className="w-4 h-4 inline animate-spin mr-1" /> 生成图表中...</p>
                ) : chartHtml ? (
                  <iframe srcDoc={chartHtml} className="w-full rounded-lg border border-gray-100" style={{ height: "780px" }} title="回测图表" />
                ) : (
                  <p className="text-sm text-gray-400 py-4">图表加载失败</p>
                )}
              </div>
            )}

            {/* Trade details tabs */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="font-semibold text-gray-700 mb-3">📋 交易明细</h3>
              {/* Strategy tabs */}
              <div className="flex gap-2 mb-3">
                {results.filter(r => !r.error && r.data?.trades?.length > 0).map(r => (
                  <button key={r.strategy} onClick={() => setActiveTab(r.strategy)}
                    className={`px-3 py-1 text-xs rounded-lg border ${activeTab === r.strategy ? "bg-[#10a37f] text-white border-[#10a37f]" : "bg-white text-gray-500 border-gray-200"}`}>
                    {r.name || r.strategy} ({r.data.trades.length}笔)
                  </button>
                ))}
              </div>
              {/* Trades table */}
              {results.filter(r => r.strategy === activeTab && r.data?.trades?.length > 0).map(r => (
                <div key={r.strategy} className="overflow-x-auto max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                        <th className="pb-2 sticky top-0 bg-white">入场时间</th>
                        <th className="pb-2 sticky top-0 bg-white">出场时间</th>
                        <th className="pb-2 sticky top-0 bg-white">入场价</th>
                        <th className="pb-2 sticky top-0 bg-white">出场价</th>
                        <th className="pb-2 sticky top-0 bg-white">持有天数</th>
                        <th className="pb-2 sticky top-0 bg-white">盈亏</th>
                        <th className="pb-2 sticky top-0 bg-white">收益率</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.data.trades.map((t, i) => (
                        <tr key={i} className="border-b border-gray-50">
                          <td className="py-1.5 text-xs text-gray-600 whitespace-nowrap">{t.entry_time || "-"}</td>
                          <td className="py-1.5 text-xs text-gray-600 whitespace-nowrap">{t.exit_time || "-"}</td>
                          <td className="py-1.5 text-xs">{fmt(t.entry_price, 2)}</td>
                          <td className="py-1.5 text-xs">{fmt(t.exit_price, 2)}</td>
                          <td className="py-1.5 text-xs text-gray-500">{t.hold_days}天</td>
                          <td className={`py-1.5 text-xs font-medium ${t.pnl >= 0 ? "text-red-500" : "text-green-500"}`}>
                            {t.pnl >= 0 ? "+" : ""}{fmt(Math.abs(t.pnl), 2)}
                          </td>
                          <td className={`py-1.5 text-xs ${t.return_pct >= 0 ? "text-red-500" : "text-green-500"}`}>
                            {fmtPct(t.return_pct * 100)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
