import type { Metadata } from "next";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Trading OS",
  description: "个人 AI 交易操作系统 — AI analyzes, you decide, machine executes",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="flex">
        <Sidebar />
        <main className="flex-1 overflow-y-auto h-screen">
          {children}
        </main>
      </body>
    </html>
  );
}
