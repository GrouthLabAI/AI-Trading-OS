"use client";

import { useState, useEffect, useCallback } from "react";
import { Sparkles, TrendingUp, TrendingDown, BarChart3, RefreshCw, Loader2, Target, Shield, Zap } from "lucide-react";

interface MarketSummary {
  date: string;
  breadth: {
    total: number | string;
    up: number | string;
    down: number | string;
    limit_up: number;
    limit_down: number;
    up_down_ratio: number | string;
  };
  top_sectors: Sector[];
  limit_up_count: number;
  limit_up_leaders: LimitUpStock[];
}

interface Sector {
  code: string;
  name: string;
  change_pct: number;
  up_count: number;
  down_count: number;
}

interface LimitUpStock {
  code: string;
  name: string;
  change_pct: number;
  reason: string;
  first_limit_time: string;
  open_count: number;
  sector: string;
}

/** Format raw time "092502" → "09:25:02" */
function fmtTime(raw: string): string {
  if (!raw || raw.length < 6) return raw || "-";
  return `${raw.slice(0,2)}:${raw.slice(2,4)}:${raw.slice(4,6)}`;
}

interface EmotionResult {
  phase_cn: string;
  confidence: number;
  reasoning: string;
  risk_level: string;
  suggested_position: string;
}

const PHASE_COLORS: Record<string, string> = {
  "冰点": "text-blue-600 bg-blue-50",
  "修复": "text-emerald-600 bg-emerald-50",
  "分歧": "text-amber-600 bg-amber-50",
  "一致": "text-orange-600 bg-orange-50",
  "高潮": "text-red-600 bg-red-50",
  "退潮": "text-gray-600 bg-gray-100",
};

const RISK_LABELS: Record<string, string> = {
  low: "低风险", medium: "中风险", high: "高风险", extreme: "极高风险",
};

interface PickItem {
  code: string; name: string; score: number;
  category: string; reason: string;
  buy_price: number; stop_loss: number; target_price: number;
  position_ratio: string;
}

interface FullAnalysisResult {
  emotion: { phase: string; confidence: number; risk_level: string; suggested_position: string; reasoning: string };
  sector: { main_theme: string; strength: string; rotation_pattern: string; analysis: string; risk_sectors: string; opportunity: string };
  wyckoff: { phase: string; signals: string[]; confidence: number; analysis: string; advice: string };
  risk: { risk_level: string; circuit_breaker: boolean; restrictions: string[]; max_position: string; warnings: string[]; advice: string };
  picks: PickItem[];
  summary: string;
}

export default function Dashboard() {
  const [summary, setSummary] = useState<MarketSummary | null>(null);
  const [emotion, setEmotion] = useState<EmotionResult | null>(null);
  const [fullAnalysis, setFullAnalysis] = useState<FullAnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [runningFull, setRunningFull] = useState(false);

  const fetchSummary = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/market/summary");
      const json = await res.json();
      if (json.status === "ok") setSummary(json.data);
    } catch (e) {
      console.error("Failed to fetch market summary:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  const analyzeEmotion = useCallback(async () => {
    setAnalyzing(true);
    setEmotion(null);
    try {
      const res = await fetch("/api/market/emotion");
      const json = await res.json();
      if (json.status === "ok") setEmotion(json.data);
    } catch (e) {
      console.error("Failed to analyze emotion:", e);
    } finally {
      setAnalyzing(false);
    }
  }, []);

  const runFullAnalysis = useCallback(async () => {
    setRunningFull(true);
    setFullAnalysis(null);
    try {
      // 1. Start the background task
      const startRes = await fetch("/api/market/analyze");
      const startJson = await startRes.json();
      if (!startJson.task_id) throw new Error("No task_id returned");
      const taskId = startJson.task_id;

      // 2. Poll until done
      const poll = async (): Promise<void> => {
        const res = await fetch(`/api/market/analyze/${taskId}`);
        const json = await res.json();
        if (json.status === "running") {
          await new Promise((r) => setTimeout(r, 2000)); // wait 2s
          return poll();
        }
        if (json.status === "ok") {
          setFullAnalysis(json.data);
        } else {
          console.error("Analysis failed:", json.detail);
        }
      };
      await poll();
    } catch (e) {
      console.error("Full analysis failed:", e);
    } finally {
      setRunningFull(false);
    }
  }, []);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  const b = summary?.breadth;

  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Date & loading */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-700">
            {summary ? `市场概览 · ${summary.date}` : "加载中..."}
          </h2>
          <button
            onClick={fetchSummary}
            disabled={loading}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            刷新数据
          </button>
        </div>

        {/* Market Breadth Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="涨停"
            value={b?.limit_up ?? "?"}
            icon={<TrendingUp className="w-4 h-4" />}
            color="text-red-500"
          />
          <StatCard
            label="跌停"
            value={b?.limit_down ?? "?"}
            icon={<TrendingDown className="w-4 h-4" />}
            color="text-green-500"
          />
          <StatCard
            label="涨跌比"
            value={b?.up_down_ratio ?? "?"}
            icon={<BarChart3 className="w-4 h-4" />}
            color="text-blue-500"
          />
          <StatCard
            label="涨停池"
            value={summary?.limit_up_count ?? "?"}
            icon={<Sparkles className="w-4 h-4" />}
            color="text-purple-500"
          />
        </div>

        {/* Emotion Analysis */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-700">🤖 AI 市场情绪分析</h3>
            <button
              onClick={analyzeEmotion}
              disabled={analyzing}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#10a37f] hover:bg-[#0d8c6d]
                         text-white rounded-lg text-sm font-medium transition-colors
                         disabled:opacity-50"
            >
              {analyzing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              {analyzing ? "分析中..." : "AI 分析情绪"}
            </button>
          </div>

          {emotion ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className={`px-3 py-1 rounded-full text-sm font-semibold ${PHASE_COLORS[emotion.phase_cn] || "bg-gray-100 text-gray-600"}`}>
                  {emotion.phase_cn}
                </span>
                <span className="text-sm text-gray-500">
                  置信度 {(emotion.confidence * 100).toFixed(0)}%
                </span>
                <span className="text-sm text-gray-400">
                  · {RISK_LABELS[emotion.risk_level] || emotion.risk_level}
                </span>
                <span className="text-sm font-medium text-[#10a37f]">
                  建议仓位：{emotion.suggested_position}
                </span>
              </div>
              <p className="text-sm text-gray-600">{emotion.reasoning}</p>
            </div>
          ) : (
            <p className="text-sm text-gray-400">
              {analyzing ? "AI 正在分析市场情绪..." : "点击按钮启动 AI 市场情绪分析"}
            </p>
          )}
        </div>

        {/* Full Analysis: Emotion + Sector + Stock Picks */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-700">
              🧠 AI 全部分析
              <span className="text-xs text-gray-400 ml-2 font-normal">情绪 → 板块 → 选股</span>
            </h3>
            <button
              onClick={runFullAnalysis}
              disabled={runningFull}
              className="flex items-center gap-1.5 px-4 py-2 bg-gradient-to-r from-[#10a37f] to-[#0d8c6d]
                         hover:from-[#0d8c6d] hover:to-[#0a7a5d]
                         text-white rounded-lg text-sm font-medium transition-all
                         disabled:opacity-50 shadow-sm"
            >
              {runningFull ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Zap className="w-4 h-4" />
              )}
              {runningFull ? "全部分析执行中..." : "运行全部分析"}
            </button>
          </div>

          {runningFull && (
            <div className="space-y-2 py-4">
              <p className="text-sm text-gray-400 flex items-center gap-2">
                <Loader2 className="w-3 h-3 animate-spin" />
                AI 正在依次分析情绪 → 板块 → 威科夫 → 选股 → 风控...（约 30-60 秒）
              </p>
            </div>
          )}

          {fullAnalysis && !runningFull && (
            <div className="space-y-4">
              {/* Emotion Result */}
              <div className="bg-[#f7f7f8] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Shield className="w-4 h-4 text-[#10a37f]" />
                  <span className="text-sm font-semibold text-gray-700">市场情绪</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${PHASE_COLORS[fullAnalysis.emotion.phase] || "bg-gray-100 text-gray-600"}`}>
                    {fullAnalysis.emotion.phase}
                  </span>
                  <span className="text-xs text-gray-500">置信度 {(fullAnalysis.emotion.confidence * 100).toFixed(0)}%</span>
                  <span className="text-xs text-gray-400">· {RISK_LABELS[fullAnalysis.emotion.risk_level] || fullAnalysis.emotion.risk_level}</span>
                  <span className="text-xs font-medium text-[#10a37f]">仓位: {fullAnalysis.emotion.suggested_position}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1.5">{fullAnalysis.emotion.reasoning}</p>
              </div>

              {/* Sector Result */}
              <div className="bg-[#f7f7f8] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Target className="w-4 h-4 text-[#10a37f]" />
                  <span className="text-sm font-semibold text-gray-700">板块轮动</span>
                </div>
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-sm font-medium text-gray-800">{fullAnalysis.sector.main_theme}</span>
                  <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">{fullAnalysis.sector.rotation_pattern}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    fullAnalysis.sector.opportunity === "high" ? "bg-green-100 text-green-700" :
                    fullAnalysis.sector.opportunity === "medium" ? "bg-amber-100 text-amber-700" :
                    "bg-gray-100 text-gray-500"
                  }`}>
                    机会: {fullAnalysis.sector.opportunity === "high" ? "高" : fullAnalysis.sector.opportunity === "medium" ? "中" : "低"}
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-1.5">{fullAnalysis.sector.analysis}</p>
                {fullAnalysis.sector.risk_sectors && (
                  <p className="text-xs text-red-500 mt-1">⚠ {fullAnalysis.sector.risk_sectors}</p>
                )}
              </div>

              {/* Wyckoff Result */}
              {fullAnalysis.wyckoff && (
                <div className="bg-[#f7f7f8] rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Zap className="w-4 h-4 text-[#10a37f]" />
                    <span className="text-sm font-semibold text-gray-700">威科夫分析</span>
                    <span className="text-xs text-gray-400">· RAG增强</span>
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      fullAnalysis.wyckoff.phase.includes("上涨") ? "bg-green-100 text-green-700" :
                      fullAnalysis.wyckoff.phase.includes("下跌") ? "bg-red-100 text-red-700" :
                      fullAnalysis.wyckoff.phase.includes("吸筹") ? "bg-blue-100 text-blue-700" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {fullAnalysis.wyckoff.phase}
                    </span>
                    <span className="text-xs text-gray-500">置信度 {(fullAnalysis.wyckoff.confidence * 100).toFixed(0)}%</span>
                    {fullAnalysis.wyckoff.signals && fullAnalysis.wyckoff.signals.length > 0 && (
                      <div className="flex gap-1 flex-wrap">
                        {fullAnalysis.wyckoff.signals.map((s: string, i: number) => (
                          <span key={i} className="text-xs bg-white border border-gray-200 px-1.5 py-0.5 rounded text-gray-600">{s}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1.5">{fullAnalysis.wyckoff.analysis}</p>
                </div>
              )}

              {/* Risk Result */}
              {fullAnalysis.risk && (
                <div className="bg-[#f7f7f8] rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <Shield className="w-4 h-4 text-[#10a37f]" />
                    <span className="text-sm font-semibold text-gray-700">风险控制</span>
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      fullAnalysis.risk.risk_level === "low" ? "bg-green-100 text-green-700" :
                      fullAnalysis.risk.risk_level === "medium" ? "bg-amber-100 text-amber-700" :
                      fullAnalysis.risk.risk_level === "high" ? "bg-orange-100 text-orange-700" :
                      "bg-red-100 text-red-700"
                    }`}>
                      风险：{RISK_LABELS[fullAnalysis.risk.risk_level] || fullAnalysis.risk.risk_level}
                    </span>
                    <span className="text-xs font-medium text-[#10a37f]">最大仓位：{fullAnalysis.risk.max_position}</span>
                    {fullAnalysis.risk.circuit_breaker && (
                      <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded font-semibold">⛔ 熔断</span>
                    )}
                  </div>
                  {fullAnalysis.risk.restrictions && fullAnalysis.risk.restrictions.length > 0 && (
                    <div className="flex gap-1 mt-1.5 flex-wrap">
                      {fullAnalysis.risk.restrictions.map((r: string, i: number) => (
                        <span key={i} className="text-xs bg-red-50 text-red-600 px-1.5 py-0.5 rounded">{r}</span>
                      ))}
                    </div>
                  )}
                  {fullAnalysis.risk.warnings && fullAnalysis.risk.warnings.length > 0 && (
                    <div className="mt-1.5">
                      {fullAnalysis.risk.warnings.map((w: string, i: number) => (
                        <p key={i} className="text-xs text-amber-600">⚠ {w}</p>
                      ))}
                    </div>
                  )}
                  <p className="text-xs text-gray-500 mt-1.5">{fullAnalysis.risk.advice}</p>
                </div>
              )}

              {/* Stock Picks */}
              {fullAnalysis.picks && fullAnalysis.picks.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <TrendingUp className="w-4 h-4 text-[#10a37f]" />
                    <span className="text-sm font-semibold text-gray-700">AI 选股推荐</span>
                    <span className="text-xs text-gray-400">· {fullAnalysis.summary}</span>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                          <th className="pb-2 font-medium">股票</th>
                          <th className="pb-2 font-medium">评分</th>
                          <th className="pb-2 font-medium">类型</th>
                          <th className="pb-2 font-medium hidden sm:table-cell">买入</th>
                          <th className="pb-2 font-medium hidden sm:table-cell">止损</th>
                          <th className="pb-2 font-medium hidden sm:table-cell">目标</th>
                          <th className="pb-2 font-medium">仓位</th>
                          <th className="pb-2 font-medium hidden md:table-cell">理由</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fullAnalysis.picks.map((p, i) => (
                          <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                            <td className="py-2">
                              <span className="font-medium text-gray-800">{p.name}</span>
                              <span className="text-gray-400 ml-1 text-xs">{p.code}</span>
                            </td>
                            <td className="py-2">
                              <span className={`font-semibold ${
                                p.score >= 85 ? "text-red-500" : p.score >= 70 ? "text-amber-500" : "text-gray-500"
                              }`}>{p.score}</span>
                            </td>
                            <td className="py-2 text-xs text-gray-500">{p.category}</td>
                            <td className="py-2 text-red-500 text-xs hidden sm:table-cell">{p.buy_price}</td>
                            <td className="py-2 text-green-600 text-xs hidden sm:table-cell">{p.stop_loss}</td>
                            <td className="py-2 text-blue-600 text-xs hidden sm:table-cell">{p.target_price}</td>
                            <td className="py-2 text-xs font-medium text-[#10a37f]">{p.position_ratio}</td>
                            <td className="py-2 text-xs text-gray-500 hidden md:table-cell max-w-[120px] truncate">{p.reason}</td>
                            <td className="py-2 flex items-center gap-1">
                              <a
                                href={`https://stockpage.10jqka.com.cn/${p.code}/`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap"
                              >
                                同花顺
                              </a>
                              <ExecuteButton code={p.code} name={p.name} price={p.buy_price} quantity={100} reason={p.reason} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {fullAnalysis.picks.length === 0 && (
                <p className="text-sm text-gray-400 py-2">当前市场环境下 AI 未推荐任何标的（可能退潮期或数据不足）</p>
              )}
            </div>
          )}

          {!runningFull && !fullAnalysis && (
            <p className="text-sm text-gray-400">点击运行完整的 AI 分析流程（情绪→板块→选股），耗时约 10-30 秒</p>
          )}
        </div>

        {/* Limit-up Leaders */}
        {summary?.limit_up_leaders && summary.limit_up_leaders.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="font-semibold text-gray-700 mb-3">🔥 涨停板龙虎榜</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-gray-500">
                    <th className="pb-2 font-medium">股票</th>
                    <th className="pb-2 font-medium">涨幅</th>
                    <th className="pb-2 font-medium">板块</th>
                    <th className="pb-2 font-medium hidden md:table-cell">封板时间</th>
                    <th className="pb-2 font-medium hidden md:table-cell">炸板</th>
                    <th className="pb-2 font-medium hidden lg:table-cell">原因</th>
                    <th className="pb-2 font-medium w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {summary.limit_up_leaders.slice(0, 15).map((s, i) => (
                    <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                      <td className="py-2">
                        <span className="font-medium text-gray-800">{s.name}</span>
                        <span className="text-gray-400 ml-1.5 text-xs">{s.code}</span>
                      </td>
                      <td className="py-2 text-red-500 font-medium">{(s.change_pct >= 0 ? "+" : "")}{s.change_pct.toFixed(2)}%</td>
                      <td className="py-2 text-xs text-gray-500">{s.sector || "-"}</td>
                      <td className="py-2 text-gray-500 hidden md:table-cell">{fmtTime(s.first_limit_time)}</td>
                      <td className="py-2 hidden md:table-cell">
                        {s.open_count > 0 ? (
                          <span className="text-amber-500">{s.open_count}次</span>
                        ) : (
                          <span className="text-green-500">0</span>
                        )}
                      </td>
                      <td className="py-2 text-gray-500 hidden lg:table-cell max-w-[200px] truncate">
                        {s.reason || "-"}
                      </td>
                      <td className="py-2">
                        <a href={`https://stockpage.10jqka.com.cn/${s.code}/`}
                           target="_blank" rel="noopener noreferrer"
                           className="text-xs text-blue-500 hover:text-blue-700 hover:underline whitespace-nowrap">
                          同花顺
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

/** Execute buy order button */
function ExecuteButton({ code, name, price, quantity, reason }: {
  code: string; name: string; price: number; quantity: number; reason: string;
}) {
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function execute() {
    setExecuting(true);
    setResult(null);
    try {
      const res = await fetch("/api/execute/buy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, name, price, quantity, reason }),
      });
      const json = await res.json();
      setResult(json.status === "ok" ? "✅ 已执行" : `❌ ${json.data?.message || "失败"}`);
    } catch {
      setResult("❌ 网络错误");
    } finally {
      setExecuting(false);
    }
  }

  return (
    <button
      onClick={execute}
      disabled={executing || !!result}
      className="text-xs px-2 py-0.5 rounded bg-[#10a37f] text-white hover:bg-[#0d8c6d] disabled:bg-gray-300 disabled:text-gray-500 whitespace-nowrap"
    >
      {executing ? "..." : result || "执行"}
    </button>
  );
}

/** Simple stat card component */
function StatCard({ label, value, icon, color }: {
  label: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
        <span className={color}>{icon}</span>
        {label}
      </div>
      <div className="text-2xl font-bold text-gray-800">{value}</div>
    </div>
  );
}
