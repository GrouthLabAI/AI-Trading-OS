"use client";

import { useState, useEffect, useCallback } from "react";
import { Search, Loader2, TrendingUp, Shield, Target, Zap, AlertTriangle, CheckCircle2, XCircle, ExternalLink } from "lucide-react";

interface Candidate {
  code: string;
  name: string;
  score: number;
  candidate_status: string;
  pool_id: string;
  screening_strategy: string;
  night_score: number;
  morning_score: number;
  buy_price: number;
  stop_loss: number;
  target_price: number;
  position_ratio: number;
  reason: string;
}

interface PoolSummary {
  pool_id: string;
  trade_date: string;
  stage: string;
  total_screened: number;
  total_qualified: number;
}

interface PoolData {
  trade_date: string;
  total_candidates: number;
  candidates: Candidate[];
  pools: PoolSummary[];
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  night_screened: { label: "前晚初筛", color: "bg-indigo-100 text-indigo-700" },
  morning_calibrated: { label: "盘前校准", color: "bg-amber-100 text-amber-700" },
  confirmed: { label: "AI确认", color: "bg-emerald-100 text-emerald-700" },
  active: { label: "进行中", color: "bg-blue-100 text-blue-700" },
  executed: { label: "已执行", color: "bg-green-100 text-green-700" },
  expired: { label: "已过期", color: "bg-gray-100 text-gray-500" },
  abandoned: { label: "已淘汰", color: "bg-red-100 text-red-500" },
};

const STRATEGY_LABELS: Record<string, string> = {
  first_board: "首板",
  strong_seal: "强封",
  sector_aligned: "板块共振",
  wyckoff_sos: "SOS",
  wyckoff_joc: "JOC",
  wyckoff_spring: "Spring",
  dragon_low: "龙头低吸",
};

function getScoreColor(score: number): string {
  if (score >= 85) return "text-red-600";
  if (score >= 70) return "text-amber-600";
  if (score >= 50) return "text-yellow-600";
  return "text-gray-400";
}

export default function PreMarketPage() {
  const [poolData, setPoolData] = useState<PoolData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"all" | "night" | "morning" | "confirmed">("all");

  const fetchPool = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/candidate-pool/current");
      const json = await res.json();
      if (json.status === "ok") {
        setPoolData(json.data);
      } else {
        setError("Failed to load pool data");
      }
    } catch (e) {
      setError("Network error fetching pool data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPool();
  }, [fetchPool]);

  // Filter candidates by tab
  const filtered = poolData?.candidates?.filter((c) => {
    if (activeTab === "all") return true;
    if (activeTab === "night") return c.candidate_status === "night_screened";
    if (activeTab === "morning") return c.candidate_status === "morning_calibrated";
    if (activeTab === "confirmed") return c.candidate_status === "confirmed";
    return true;
  }) || [];

  // Count by status
  const counts = poolData?.candidates?.reduce((acc, c) => {
    acc[c.candidate_status] = (acc[c.candidate_status] || 0) + 1;
    return acc;
  }, {} as Record<string, number>) || {};

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Search className="w-6 h-6 text-[#10a37f]" />
            盘前筛选
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {poolData?.trade_date || "—"} · 前晚初筛 → 盘前校准 → AI确认 三段式候选池管理
          </p>
        </div>
        <button
          onClick={fetchPool}
          disabled={loading}
          className="px-4 py-2 text-sm bg-[#10a37f] text-white rounded-lg hover:bg-[#0d8c6d] disabled:opacity-50 flex items-center gap-2"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          刷新数据
        </button>
      </div>

      {/* Summary Cards */}
      {poolData && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">候选总数</div>
            <div className="text-2xl font-bold text-gray-900">{poolData.total_candidates}</div>
          </div>
          <div className="bg-indigo-50 rounded-xl border border-indigo-100 p-4">
            <div className="text-xs text-indigo-600 mb-1">前晚初筛</div>
            <div className="text-2xl font-bold text-indigo-700">{counts["night_screened"] || 0}</div>
          </div>
          <div className="bg-amber-50 rounded-xl border border-amber-100 p-4">
            <div className="text-xs text-amber-600 mb-1">盘前校准通过</div>
            <div className="text-2xl font-bold text-amber-700">{counts["morning_calibrated"] || 0}</div>
          </div>
          <div className="bg-emerald-50 rounded-xl border border-emerald-100 p-4">
            <div className="text-xs text-emerald-600 mb-1">AI确认</div>
            <div className="text-2xl font-bold text-emerald-700">{counts["confirmed"] || 0}</div>
          </div>
        </div>
      )}

      {/* Pool Stage History */}
      {poolData?.pools && poolData.pools.length > 0 && (
        <div className="mb-6 bg-white rounded-xl border border-gray-200 p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-3">筛选批次</h3>
          <div className="flex gap-2 flex-wrap">
            {poolData.pools.map((p) => (
              <span
                key={p.pool_id}
                className={`px-3 py-1 rounded-full text-xs font-medium ${
                  p.stage === "night_screen"
                    ? "bg-indigo-100 text-indigo-700"
                    : p.stage === "morning_calibrate"
                    ? "bg-amber-100 text-amber-700"
                    : "bg-emerald-100 text-emerald-700"
                }`}
              >
                {p.stage === "night_screen" ? "🌙 前晚初筛" : p.stage === "morning_calibrate" ? "☀️ 盘前校准" : "🤖 LLM确认"}
                : {p.total_qualified}/{p.total_screened}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tab Filter */}
      <div className="flex gap-2 mb-4">
        {[
          { key: "all", label: "全部" },
          { key: "night", label: "🌙 前晚初筛" },
          { key: "morning", label: "☀️ 盘前校准" },
          { key: "confirmed", label: "🤖 AI确认" },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? "bg-gray-900 text-white"
                : "bg-white text-gray-600 hover:bg-gray-100 border border-gray-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Candidates Table */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
        </div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700">{error}</div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-gray-400">
          <Search className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-lg">暂无候选数据</p>
          <p className="text-sm mt-1">前晚 18:00 盘后初筛自动运行，次日 08:30 盘前校准</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-center px-3 py-3 font-medium text-gray-400 w-12">#</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">股票</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">状态</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">评分</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">前晚分</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">校准分</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">命中策略</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">买入价</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">止损</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">目标</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">理由</th>
                  <th className="text-center px-4 py-3 font-medium text-gray-600">操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c, i) => {
                  const statusInfo = STATUS_LABELS[c.candidate_status] || { label: c.candidate_status, color: "bg-gray-100 text-gray-600" };
                  return (
                    <tr key={`${c.code}-${i}`} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-3 py-3 text-center text-xs text-gray-400">
                        {i + 1}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-900">{c.name}</div>
                        <div className="text-xs text-gray-400">{c.code}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-xs ${statusInfo.color}`}>
                          {statusInfo.label}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-center font-bold text-red-600 ${getScoreColor(c.score)}`}>
                        {c.score}
                      </td>
                      <td className="px-4 py-3 text-center text-gray-600">{c.night_score || "-"}</td>
                      <td className="px-4 py-3 text-center text-gray-600">{c.morning_score || "-"}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {c.screening_strategy ? c.screening_strategy.split(",").map((s) => (
                            <span key={s} className="px-1.5 py-0.5 rounded text-xs bg-gray-100 text-gray-600">
                              {STRATEGY_LABELS[s.trim()] || s.trim()}
                            </span>
                          )) : <span className="text-xs text-gray-400">-</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center font-mono text-gray-500">{c.buy_price?.toFixed(2) || "-"}</td>
                      <td className="px-4 py-3 text-center font-mono text-red-500">{c.stop_loss?.toFixed(2) || "-"}</td>
                      <td className="px-4 py-3 text-center font-mono text-green-500">{c.target_price?.toFixed(2) || "-"}</td>
                      <td className="px-4 py-3 text-xs text-gray-500 max-w-[200px] truncate" title={c.reason}>
                        {c.reason || "-"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <a
                          href={`https://stockpage.10jqka.com.cn/${c.code}/`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs text-[#10a37f] hover:text-white hover:bg-[#10a37f] border border-[#10a37f] rounded transition-colors"
                        >
                          <ExternalLink className="w-3 h-3" />
                          同花顺
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Explanation footer */}
      <div className="mt-8 bg-gray-50 rounded-xl border border-gray-200 p-5">
        <h3 className="text-sm font-medium text-gray-700 mb-3">📋 候选池生命周期</h3>
        <div className="flex items-center gap-2 text-xs text-gray-500 flex-wrap">
          <span className="px-2 py-1 bg-indigo-100 text-indigo-700 rounded">🌙 night_screened</span>
          <span>→</span>
          <span className="px-2 py-1 bg-amber-100 text-amber-700 rounded">☀️ morning_calibrated</span>
          <span>→</span>
          <span className="px-2 py-1 bg-emerald-100 text-emerald-700 rounded">🤖 confirmed</span>
          <span>→</span>
          <span className="px-2 py-1 bg-green-100 text-green-700 rounded">✅ executed</span>
          <span className="mx-2">|</span>
          <span className="px-2 py-1 bg-red-100 text-red-500 rounded">❌ abandoned</span>
          <span className="px-2 py-1 bg-gray-100 text-gray-500 rounded">⏰ expired</span>
        </div>
        <div className="mt-3 text-xs text-gray-400">
          <p>🌙 前晚 18:00 自动初筛（规则筛选） → ☀️ 次日 08:30 隔夜校准 → 🤖 09:00 LLM 深度确认（竞价结束后）</p>
        </div>
      </div>
    </div>
  );
}
