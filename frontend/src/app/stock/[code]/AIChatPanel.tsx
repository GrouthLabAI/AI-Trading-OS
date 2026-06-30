"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageSquare, X, Send, Loader2 } from "lucide-react";
import { marked } from "marked";
import DOMPurify from "dompurify";

marked.setOptions({ breaks: true, gfm: true });

function renderMd(text: string): string {
  return DOMPurify.sanitize(marked.parse(text) as string);
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  code: string;
  stockName: string;
  analysis?: Record<string, any> | null;
}

export default function AIChatPanel({ code, stockName, analysis }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [panelWidth, setPanelWidth] = useState(() => {
    try { return parseInt(localStorage.getItem("ai-panel-width") || "380", 10); } catch { return 380; }
  });
  const bottomRef = useRef<HTMLDivElement>(null);
  const resizing = useRef(false);

  // ── Drag-to-resize ─────────────────────────────────────────────

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!resizing.current) return;
      const w = window.innerWidth - e.clientX;
      setPanelWidth(Math.max(280, Math.min(600, w)));
    };
    const onMouseUp = () => { resizing.current = false; document.body.style.cursor = ""; };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem("ai-panel-width", String(panelWidth)); } catch {}
  }, [panelWidth]);
  const inputRef = useRef<HTMLInputElement>(null);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input on open
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  // ── History persistence ────────────────────────────────────────

  const saveMessages = useCallback(async (msgs: ChatMessage[]) => {
    try {
      await fetch("/api/chat/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stock_code: code, messages: msgs }),
      });
    } catch (e) {
      console.error("保存对话历史失败:", e);
    }
  }, [code]);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const res = await fetch(`/api/chat/history/${code}?page=1&page_size=50`);
      const json = await res.json();
      if (json.status === "ok" && json.data.messages.length > 0) {
        setMessages(json.data.messages.map((m: any) => ({ role: m.role, content: m.content })));
      } else {
        setMessages([]);
      }
    } catch {
      setMessages([]);
    } finally {
      setLoadingHistory(false);
    }
  }, [code]);

  const handleClear = useCallback(async () => {
    try { await fetch(`/api/chat/clear/${code}`, { method: "DELETE" }); } catch {}
    setMessages([]);
  }, [code]);

  // Load history when stock changes
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || loading) return;
    const userMsg: ChatMessage = { role: "user", content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const allMsgs = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));
      const res = await fetch(`/api/stock/${code}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: allMsgs, analysis }),
      });
      const json = await res.json();
      if (json.status === "ok") {
        const assistantMsg: ChatMessage = { role: "assistant", content: json.reply };
        setMessages((prev) => [...prev, assistantMsg]);
        saveMessages([userMsg, assistantMsg]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: "抱歉，AI 助手暂时不可用。" }]);
      }
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "网络错误，请稍后重试。" }]);
    } finally {
      setLoading(false);
    }
  }, [code, messages, loading, analysis, saveMessages]);

  const quickAsk = (q: string) => sendMessage(q);

  // ── Closed state: slim toggle strip ──
  if (!open) {
    return (
      <div className="shrink-0 w-11 border-l border-gray-200 bg-gray-50 flex items-start pt-4 justify-center sticky top-0 h-screen">
        <button
          onClick={() => setOpen(true)}
          className="p-1.5 rounded-lg bg-[#10a37f] text-white hover:bg-[#0d8c6d] transition-colors"
          title="打开 AI 助手"
        >
          <MessageSquare className="w-4 h-4" />
        </button>
      </div>
    );
  }

  // ── Open state: full panel ──
  return (
    <div className="shrink-0 border-l border-gray-200 bg-white flex flex-col sticky top-0 h-screen relative" style={{ width: panelWidth }}>
          {/* Drag handle */}
          <div className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-[#10a37f]/30 z-10"
            onMouseDown={(e) => { e.preventDefault(); resizing.current = true; document.body.style.cursor = "col-resize"; }}
          />
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-[#10a37f]" />
          <span className="text-sm font-semibold text-gray-700">AI 助手</span>
          <span className="text-xs text-gray-400">{stockName} {code}</span>
        </div>
        {messages.length > 0 && (
          <button onClick={handleClear} title="清空对话"
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-red-500 transition-colors text-xs"
          >
            清空
          </button>
        )}
        <button onClick={() => setOpen(false)} className="p-1 rounded hover:bg-gray-100 text-gray-400">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Quick prompts — only when no messages and done loading */}
      {messages.length === 0 && !loadingHistory && (
        <div className="px-4 py-3 border-b border-gray-100 shrink-0 space-y-1.5">
          <p className="text-xs text-gray-400 mb-1">快捷提问:</p>
          {[
            "当前威科夫结构是否准确？",
            "最近的支撑位和阻力位在哪里？",
            "这个股票现在适合买入吗？",
            "请详细分析最近的成交量特征",
          ].map((q) => (
            <button key={q} onClick={() => quickAsk(q)}
              className="block w-full text-left text-xs text-gray-500 hover:text-[#10a37f] hover:bg-gray-50 rounded px-2 py-1 transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && !loadingHistory && (
          <p className="text-sm text-gray-400 text-center py-8">
            我是该股票的 AI 分析助手，可以回答关于 {stockName}({code}) 的任何问题。
          </p>
        )}
        {loadingHistory && (
          <div className="flex items-center justify-center py-8 gap-2 text-sm text-gray-400">
            <Loader2 className="w-4 h-4 animate-spin" /> 加载历史中...
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
              m.role === "user"
                ? "bg-[#10a37f] text-white"
                : "bg-gray-100 text-gray-700"
            }`}>
              {m.role === "assistant"
                ? <div className="markdown-body text-sm" dangerouslySetInnerHTML={{ __html: renderMd(m.content) }} />
                : <div className="whitespace-pre-wrap">{m.content}</div>
              }
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-xl px-3 py-2 text-sm text-gray-400 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> 思考中...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => { e.preventDefault(); sendMessage(input); }}
        className="px-4 py-3 border-t border-gray-200 shrink-0 flex gap-2"
      >
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入你的问题..."
          disabled={loading}
          className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 outline-none focus:border-[#10a37f] disabled:bg-gray-50"
        />
        <button type="submit" disabled={loading || !input.trim()}
          className="p-2 bg-[#10a37f] text-white rounded-lg hover:bg-[#0d8c6d] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
    </div>
  );
}
