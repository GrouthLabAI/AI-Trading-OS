"use client";

import { useState, useEffect, useCallback } from "react";
import { TrendingUp, TrendingDown, BarChart3, Wallet, Plus, X, Loader2, Brain } from "lucide-react";

interface Position {
  id: number; code: string; name: string;
  buy_price: number; current_price: number;
  quantity: number; profit: number; profit_rate: number;
  status: string; buy_time: string;
}

interface AIAnalysis {
  positions: Position[];
  ai_analysis: { code: string; action: string; reason: string }[];
  summary: string;
}

const ACTION_LABELS: Record<string, string> = {
  hold: "继续持有", reduce: "建议减仓", profit: "建议止盈", sell: "建议清仓",
};
const ACTION_COLORS: Record<string, string> = {
  hold: "text-green-600 bg-green-50", reduce: "text-amber-600 bg-amber-50",
  profit: "text-blue-600 bg-blue-50", sell: "text-red-600 bg-red-50",
};

export default function PositionsPage() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [aiAnalysis, setAiAnalysis] = useState<AIAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [showAdd, setShowAdd] = useState(false);

  // Add form
  const [addCode, setAddCode] = useState("");
  const [addName, setAddName] = useState("");
  const [addPrice, setAddPrice] = useState("");
  const [addQty, setAddQty] = useState("100");
  const [addReason, setAddReason] = useState("");

  const fetchPositions = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/positions/");
      const json = await res.json();
      if (json.status === "ok") setPositions(json.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  const runAIAnalysis = useCallback(async () => {
    setAnalyzing(true);
    try {
      const res = await fetch("/api/positions/analyze");
      const json = await res.json();
      if (json.status === "ok") setAiAnalysis(json.data);
    } catch (e) {
      console.error(e);
    } finally {
      setAnalyzing(false);
    }
  }, []);

  const addPosition = async () => {
    if (!addCode || !addName || !addPrice) return;
    try {
      await fetch("/api/positions/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: addCode, name: addName,
          buy_price: parseFloat(addPrice),
          quantity: parseInt(addQty) || 100,
          reason: addReason,
        }),
      });
      setShowAdd(false);
      setAddCode(""); setAddName(""); setAddPrice(""); setAddQty("100"); setAddReason("");
      fetchPositions();
    } catch (e) {
      console.error(e);
    }
  };

  const updatePrice = async (id: number, price: number) => {
    try {
      await fetch(`/api/positions/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_price: price }),
      });
      fetchPositions();
    } catch (e) {
      console.error(e);
    }
  };

  const closePosition = async (id: number) => {
    try {
      await fetch(`/api/positions/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "closed" }),
      });
      fetchPositions();
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => { fetchPositions(); }, [fetchPositions]);

  const holdingPositions = positions.filter(p => p.status === "holding");
  const totalPL = holdingPositions.reduce((sum, p) => sum + p.profit, 0);
  const totalPLRate = holdingPositions.length > 0
    ? (holdingPositions.reduce((sum, p) => sum + p.profit_rate, 0) / holdingPositions.length * 100)
    : 0;

  return (
    <div className="bg-[#f7f7f8] min-h-screen">
      <main className="max-w-8xl mx-auto px-4 py-6 space-y-6">
        {/* Summary */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="持仓数量" value={`${holdingPositions.length} 只`} icon={<Wallet className="w-4 h-4" />} color="text-blue-500" />
          <StatCard label="总盈亏" value={`${totalPL >= 0 ? "+" : ""}${totalPL.toFixed(2)}`} icon={totalPL >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />} color={totalPL >= 0 ? "text-red-500" : "text-green-500"} />
          <StatCard label="平均盈亏率" value={`${totalPLRate >= 0 ? "+" : ""}${totalPLRate.toFixed(2)}%`} icon={<BarChart3 className="w-4 h-4" />} color={totalPLRate >= 0 ? "text-red-500" : "text-green-500"} />
          <button
            onClick={() => setShowAdd(true)}
            className="bg-white rounded-xl border border-dashed border-gray-300 p-4 flex items-center justify-center gap-2 text-gray-400 hover:text-[#10a37f] hover:border-[#10a37f] transition-colors"
          >
            <Plus className="w-5 h-5" /> 新增持仓
          </button>
        </div>

        {/* Add Form */}
        {showAdd && (
          <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-700">新增持仓</h3>
              <button onClick={() => setShowAdd(false)}><X className="w-4 h-4 text-gray-400" /></button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <input placeholder="代码" value={addCode} onChange={e => setAddCode(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <input placeholder="名称" value={addName} onChange={e => setAddName(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <input placeholder="买入价" type="number" step="0.01" value={addPrice} onChange={e => setAddPrice(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <input placeholder="数量" type="number" value={addQty} onChange={e => setAddQty(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <button onClick={addPosition} className="bg-[#10a37f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#0d8c6d]">确认添加</button>
            </div>
          </div>
        )}

        {/* AI Analysis */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-gray-700">🤖 AI 持仓分析</h3>
            <button onClick={runAIAnalysis} disabled={analyzing || holdingPositions.length === 0}
              className="flex items-center gap-1.5 px-4 py-2 bg-[#10a37f] hover:bg-[#0d8c6d] text-white rounded-lg text-sm font-medium disabled:opacity-50">
              {analyzing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
              {analyzing ? "分析中..." : "AI 分析"}
            </button>
          </div>
          {aiAnalysis && (
            <div className="space-y-2">
              <p className="text-sm text-gray-600">{aiAnalysis.summary}</p>
              {aiAnalysis.ai_analysis.map((a, i) => (
                <div key={i} className="flex items-center gap-2 text-sm">
                  <span className="font-medium text-gray-700">{a.code}</span>
                  <span className={`px-2 py-0.5 rounded text-xs ${ACTION_COLORS[a.action] || "bg-gray-100"}`}>
                    {ACTION_LABELS[a.action] || a.action}
                  </span>
                  <span className="text-gray-500 text-xs">{a.reason}</span>
                </div>
              ))}
            </div>
          )}
          {!aiAnalysis && !analyzing && (
            <p className="text-sm text-gray-400">{holdingPositions.length === 0 ? "暂无持仓" : "点击 AI 分析获取持仓建议"}</p>
          )}
        </div>

        {/* Position List */}
        {holdingPositions.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="font-semibold text-gray-700 mb-3">📊 当前持仓</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-gray-500 text-xs">
                    <th className="pb-2">股票</th>
                    <th className="pb-2">板块</th>
                    <th className="pb-2">成本</th>
                    <th className="pb-2">现价</th>
                    <th className="pb-2">数量</th>
                    <th className="pb-2">盈亏</th>
                    <th className="pb-2">盈亏率</th>
                    <th className="pb-2">操作</th>
                    <th className="pb-2 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {holdingPositions.map(p => (
                    <tr key={p.id} className="border-b border-gray-50 hover:bg-gray-50">
                      <td className="py-2"><span className="font-medium">{p.name}</span><span className="text-gray-400 text-xs ml-1">{p.code}</span></td>
                      <td className="py-2 text-xs text-gray-500">-</td>
                      <td className="py-2 text-gray-600">{p.buy_price.toFixed(2)}</td>
                      <td className="py-2">
                        <input type="number" step="0.01" defaultValue={p.current_price}
                          onBlur={e => updatePrice(p.id, parseFloat(e.target.value))}
                          className="w-20 border border-gray-200 rounded px-1.5 py-0.5 text-xs" />
                      </td>
                      <td className="py-2 text-gray-600">{p.quantity}</td>
                      <td className={`py-2 font-medium ${p.profit >= 0 ? "text-red-500" : "text-green-500"}`}>
                        {p.profit >= 0 ? "+" : ""}{p.profit.toFixed(2)}
                      </td>
                      <td className={`py-2 ${p.profit_rate >= 0 ? "text-red-500" : "text-green-500"}`}>
                        {(p.profit_rate * 100).toFixed(1)}%
                      </td>
                      <td className="py-2">
                        <button onClick={() => closePosition(p.id)}
                          className="text-xs text-red-500 hover:text-red-700">平仓</button>
                      </td>
                      <td className="py-2">
                        <a href={`https://stockpage.10jqka.com.cn/${p.code}/`}
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

function StatCard({ label, value, icon, color }: { label: string; value: string; icon: React.ReactNode; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
        <span className={color}>{icon}</span>{label}
      </div>
      <div className="text-xl font-bold text-gray-800">{value}</div>
    </div>
  );
}
