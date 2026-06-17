"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { Send, Sparkles, User } from "lucide-react";
import { marked } from "marked";
import DOMPurify from "dompurify";

interface Message {
  role: "user" | "assistant";
  content: string;
}

function MarkdownMessage({ content }: { content: string }) {
  const html = useMemo(() => {
    marked.setOptions({ breaks: true, gfm: true });
    return DOMPurify.sanitize(marked.parse(content) as string);
  }, [content]);

  return (
    <div
      className="markdown-body"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, [input]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: Message = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    const assistantMsg: Message = { role: "assistant", content: "" };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: messages.map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6);

          let data: string;
          try {
            data = JSON.parse(raw);
          } catch {
            continue;
          }

          if (data === "[DONE]") break;
          if (data.startsWith("[ERROR]")) throw new Error(data.slice(8));

          setMessages((prev) => {
            const updated = [...prev];
            updated[updated.length - 1] = {
              ...updated[updated.length - 1],
              content: updated[updated.length - 1].content + data,
            };
            return updated;
          });
        }
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "Unknown error";
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `❌ 错误: ${errorMsg}`,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      {/* Messages — full-width alternating sections like ChatGPT */}
      <main className="flex-1 overflow-y-auto">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400 px-4">
            <div className="w-16 h-16 rounded-full bg-[#f7f7f8] flex items-center justify-center mb-6">
              <Sparkles className="w-8 h-8 text-[#10a37f]" />
            </div>
            <h2 className="text-2xl font-semibold text-gray-700 mb-2">AI Trading OS</h2>
            <p className="text-gray-400 text-sm">AI 交易助手 — 你可以问我市场分析、选股建议、交易策略</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`px-4 py-6 ${
              msg.role === "assistant" ? "bg-[#f7f7f8]" : "bg-white"
            }`}
          >
            <div className="max-w-3xl mx-auto flex gap-4">
              {/* Avatar */}
              <div
                className={`w-7 h-7 rounded-sm flex items-center justify-center shrink-0 mt-0.5 ${
                  msg.role === "assistant"
                    ? "bg-[#10a37f]"
                    : "bg-gray-700"
                }`}
              >
                {msg.role === "assistant" ? (
                  <Sparkles className="w-4 h-4 text-white" />
                ) : (
                  <User className="w-4 h-4 text-white" />
                )}
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1 text-[15px] leading-relaxed text-gray-800">
                {msg.content ? (
                  msg.role === "assistant" ? (
                    <MarkdownMessage content={msg.content} />
                  ) : (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  )
                ) : (
                  loading && i === messages.length - 1 && (
                    <span className="inline-flex items-center gap-1 text-gray-400">
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                    </span>
                  )
                )}
              </div>
            </div>
          </div>
        ))}

        <div ref={chatEndRef} />
      </main>

      {/* Input — ChatGPT style: bottom bar with border */}
      <footer className="bg-white border-t border-gray-200 px-4 py-3">
        <div className="max-w-3xl mx-auto flex gap-3 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="发送消息..."
            rows={1}
            disabled={loading}
            className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-2.5 text-[15px]
                       text-gray-800 placeholder-gray-400 bg-white
                       focus:outline-none focus:border-[#10a37f] focus:ring-1 focus:ring-[#10a37f]
                       disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="bg-[#10a37f] hover:bg-[#0d8c6d] disabled:bg-gray-300
                       text-white rounded-xl px-3 py-2.5 transition-colors shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <p className="text-center text-xs text-gray-400 mt-2">
          AI 分析 · 人决策 · 机器执行
        </p>
      </footer>
    </div>
  );
}
