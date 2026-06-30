"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, Brain } from "lucide-react";

interface TradeStats {
  total_trades: number; completed_trades: number;
  wins: number; losses: number; win_rate: number;
  total_profit: number;
  strategies: { name: string; total: number; wins: number; win_rate: number }[];
}

interface AIReview {
  stats?: { total?: number; wins?: number; losses?: number; win_rate?: string };
  biggest_mistake?: string;
  suggestions?: string[];
  strategy_review?: string;
  improvement_plan?: string;
}

interface ReviewHistory {
  id: number; date: string; win_rate: number;
  mistakes: string; suggestions: string;
}

export default function ReviewsPage() {
  const [stats, setStats] = useState<TradeStats | null>(null);
  const [aiReview, setAiReview] = useState<AIReview | null>(null);
  const [history, setHistory] = useState<ReviewHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, histRes] = await Promise.all([
        fetch("/api/reviews/summary"),
        fetch("/api/reviews/history"),
      ]);
      const statsJson = await statsRes.json();
      const histJson = await histRes.json();
      if (statsJson.status === "ok") setStats(statsJson.data);
      if (histJson.status === "ok") setHistory(histJson.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const generateReview = async () => {
    setGenerating(true);
    try {
      const res = await fetch("/api/reviews/generate");
      const json = await res.json();
      if (json.status === "ok") {
        setAiReview(json.data);
        fetchAll(); // refresh stats + history
      }
    } catch (e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => { fetchAll(); }, [fetchAll]);

  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <main className="max-w-8xl mx-auto px-4 py-6 space-y-6">
        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard label="总交易" value={stats?.total_trades ?? "?"} color="text-blue-500" />
          <StatCard label="已完成" value={stats?.completed_trades ?? "?"} color="text-purple-500" />
          <StatCard label="胜率" value={stats ? `${stats.win_rate}%` : "?"} color={stats && stats.win_rate >= 50 ? "text-red-500" : "text-green-500"} />
          <StatCard label="盈利次数" value={stats?.wins ?? "?"} color="text-red-500" />
          <StatCard label="总盈亏" value={stats ? `${stats.total_profit >= 0 ? "+" : ""}${stats.total_profit.toFixed(0)}` : "?"} color={stats && stats.total_profit >= 0 ? "text-red-500" : "text-green-500"} />
        </div>

        {/* Generate AI Review */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-700">🧠 AI 生成复盘报告</h3>
            <button onClick={generateReview} disabled={generating}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#10a37f] hover:bg-[#0d8c6d] text-white rounded-lg text-sm font-medium disabled:opacity-50">
              {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
              {generating ? "生成中..." : "生成复盘"}
            </button>
          </div>
          {aiReview && (
            <div className="space-y-3">
              {aiReview.stats && (
                <div className="flex gap-3 text-sm">
                  <span className="text-gray-500">总交易: {aiReview.stats.total} | </span>
                  <span className="text-red-500">盈: {aiReview.stats.wins} | </span>
                  <span className="text-green-500">亏: {aiReview.stats.losses} | </span>
                  <span className="font-medium">胜率: {aiReview.stats.win_rate}</span>
                </div>
              )}
              {aiReview.biggest_mistake && (
                <div className="bg-red-50 rounded-lg p-3">
                  <p className="text-sm font-medium text-red-600">⚠ 最大问题</p>
                  <p className="text-sm text-red-700">{aiReview.biggest_mistake}</p>
                </div>
              )}
              {aiReview.strategy_review && (
                <div className="bg-blue-50 rounded-lg p-3">
                  <p className="text-sm font-medium text-blue-600">📊 策略评价</p>
                  <p className="text-sm text-blue-700">{aiReview.strategy_review}</p>
                </div>
              )}
              {aiReview.suggestions && aiReview.suggestions.length > 0 && (
                <div className="bg-green-50 rounded-lg p-3">
                  <p className="text-sm font-medium text-green-600">💡 改进建议</p>
                  <ul className="list-disc list-inside text-sm text-green-700">
                    {aiReview.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </div>
              )}
              {aiReview.improvement_plan && (
                <div className="bg-[#f7f7f8] rounded-lg p-3">
                  <p className="text-sm font-medium text-gray-600">🎯 改进计划</p>
                  <p className="text-sm text-gray-700">{aiReview.improvement_plan}</p>
                </div>
              )}
            </div>
          )}
          {!aiReview && !generating && (
            <p className="text-sm text-gray-400">点击按钮，AI 将分析最近交易记录并生成复盘报告</p>
          )}
        </div>

        {/* Strategy Stats */}
        {stats?.strategies && stats.strategies.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="font-semibold text-gray-700 mb-3">📈 策略胜率统计</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                    <th className="pb-2">策略</th>
                    <th className="pb-2">总次数</th>
                    <th className="pb-2">盈利</th>
                    <th className="pb-2">胜率</th>
                    <th className="pb-2">表现</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.strategies.map((s, i) => (
                    <tr key={i} className="border-b border-gray-50">
                      <td className="py-2 font-medium text-gray-700">{s.name}</td>
                      <td className="py-2 text-gray-500">{s.total}</td>
                      <td className="py-2 text-red-500">{s.wins}</td>
                      <td className="py-2 font-medium">{s.win_rate}%</td>
                      <td className="py-2">
                        <div className="w-24 bg-gray-100 rounded-full h-2">
                          <div className={`h-2 rounded-full ${s.win_rate >= 60 ? "bg-green-500" : s.win_rate >= 40 ? "bg-amber-500" : "bg-red-500"}`}
                            style={{ width: `${s.win_rate}%` }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Review History */}
        {history.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="font-semibold text-gray-700 mb-3">📝 历史复盘</h3>
            <div className="space-y-2">
              {history.map((r, i) => (
                <div key={i} className="flex items-center gap-3 text-sm bg-[#f7f7f8] rounded-lg px-4 py-2">
                  <span className="text-gray-400 text-xs">{r.date}</span>
                  <span className={`font-medium ${r.win_rate >= 50 ? "text-red-500" : "text-green-500"}`}>
                    胜率 {r.win_rate}%
                  </span>
                  <span className="text-gray-500 text-xs truncate">{r.mistakes}</span>
                  <span className="text-gray-400 text-xs truncate hidden md:inline">{r.suggestions}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className={`text-xl font-bold text-gray-800`}>{value}</div>
    </div>
  );
}
