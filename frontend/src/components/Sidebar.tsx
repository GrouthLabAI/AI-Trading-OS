"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles, MessageSquare, BarChart3, Wallet, FileText, TrendingUp, Search, Star, ChevronLeft, ChevronRight } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "AI 对话", icon: MessageSquare },
  { href: "/dashboard", label: "市场驾驶舱", icon: BarChart3 },
  { href: "/watchlist", label: "自选股", icon: Star },
  { href: "/pre-market", label: "盘前筛选", icon: Search },
  { href: "/positions", label: "持仓管理", icon: Wallet },
  { href: "/backtest", label: "策略回测", icon: TrendingUp },
  { href: "/reviews", label: "AI 复盘", icon: FileText },
];

const STORAGE_KEY = "ai-trading-sidebar-collapsed";

export default function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Load persisted state on mount — default to collapsed
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      setCollapsed(saved === null ? true : saved === "true");
    } catch {
      setCollapsed(true);
    }
    setMounted(true);
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  // Avoid hydration mismatch — render nothing until mounted
  if (!mounted) {
    return (
      <aside className="w-56 shrink-0 h-screen bg-[#f9fafb] border-r border-gray-200" />
    );
  }

  return (
    <aside
      className={`shrink-0 h-screen bg-[#f9fafb] border-r border-gray-200 flex flex-col transition-all duration-200 ${
        collapsed ? "w-14" : "w-56"
      }`}
    >
      {/* Brand */}
      <div className={`px-4 py-4 border-b border-gray-200 flex items-center ${collapsed ? "justify-center" : "gap-2"}`}>
        <Sparkles className="w-5 h-5 text-[#10a37f] shrink-0" />
        {!collapsed && <span className="font-semibold text-gray-800 text-sm whitespace-nowrap">AI Trading OS</span>}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-3 space-y-0.5">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`relative flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm transition-colors group ${
                isActive
                  ? "bg-white text-gray-900 font-medium shadow-sm border border-gray-200"
                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-100"
              } ${collapsed ? "justify-center" : ""}`}
            >
              <item.icon className={`w-4 h-4 shrink-0 ${isActive ? "text-[#10a37f]" : ""}`} />
              {!collapsed && <span className="whitespace-nowrap">{item.label}</span>}
              {/* Instant tooltip when collapsed */}
              {collapsed && (
                <span className="absolute left-full ml-2 px-2 py-1 bg-gray-800 text-white text-xs rounded
                                 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none
                                 whitespace-nowrap z-50 shadow-md">
                  {item.label}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Toggle button */}
      <button
        onClick={toggle}
        className="flex items-center justify-center h-10 border-t border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
        title={collapsed ? "展开侧边栏" : "收起侧边栏"}
      >
        {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
      </button>

      {/* Footer */}
      {!collapsed && (
        <div className="px-4 py-3 border-t border-gray-200 text-xs text-gray-400 text-center whitespace-nowrap">
          AI 分析 · 人决策 · 机器执行
        </div>
      )}
    </aside>
  );
}
