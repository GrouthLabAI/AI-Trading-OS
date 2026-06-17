"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles, MessageSquare, BarChart3, Wallet, FileText, TrendingUp, Search } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "AI 对话", icon: MessageSquare },
  { href: "/dashboard", label: "市场驾驶舱", icon: BarChart3 },
  { href: "/pre-market", label: "盘前筛选", icon: Search },
  { href: "/positions", label: "持仓管理", icon: Wallet },
  { href: "/backtest", label: "策略回测", icon: TrendingUp },
  { href: "/reviews", label: "AI 复盘", icon: FileText },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 h-screen bg-[#f9fafb] border-r border-gray-200 flex flex-col">
      {/* Brand */}
      <div className="px-5 py-4 border-b border-gray-200">
        <div className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-[#10a37f]" />
          <span className="font-semibold text-gray-800 text-sm">AI Trading OS</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-white text-gray-900 font-medium shadow-sm border border-gray-200"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
              }`}
            >
              <item.icon className={`w-4 h-4 ${isActive ? "text-[#10a37f]" : ""}`} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-gray-200 text-xs text-gray-400">
        AI 分析 · 人决策 · 机器执行
      </div>
    </aside>
  );
}
