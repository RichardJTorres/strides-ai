import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Memory {
  category: string;
  content: string;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [savedMemories, setSavedMemories] = useState<Memory[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/history")
      .then((r) => r.json())
      .then((data: Message[]) => {
        if (Array.isArray(data) && data.length > 0) setMessages(data);
      })
      .catch(() => {})
      .finally(() => setHistoryLoaded(true));
  }, []);

  useEffect(() => {
    if (historyLoaded) {
      bottomRef.current?.scrollIntoView({ behavior: "instant" });
    }
  }, [historyLoaded]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setSavedMemories([]);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setStreaming(true);

    const assistantIndex = messages.length + 1;
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });

      if (!res.ok || !res.body) throw new Error("Request failed");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).replace(/\\n/g, "\n");
          if (payload === "[DONE]") break;

          if (payload.startsWith("[MEMORIES]")) {
            try {
              const mems: Memory[] = JSON.parse(payload.slice(10));
              setSavedMemories(mems);
            } catch {
              // ignore parse errors
            }
            continue;
          }

          setMessages((prev) =>
            prev.map((m, i) =>
              i === assistantIndex ? { ...m, content: m.content + payload } : m
            )
          );
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m, i) =>
          i === assistantIndex
            ? { ...m, content: "_Error: could not reach the server._" }
            : m
        )
      );
    } finally {
      setStreaming(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto">
        {historyLoaded && messages.length === 0 && (
          <div className="text-center text-gray-500 mt-24 text-base">
            Ask your coach anything about your training.
          </div>
        )}
        {messages.map((m, i) => (
          m.role === "user" ? (
            <div key={i} className="flex justify-end px-16 py-3">
              <div className="max-w-xl rounded-2xl px-5 py-3 text-[15px] leading-relaxed bg-green-700 text-white">
                {m.content}
              </div>
            </div>
          ) : (
            <div key={i} className="px-16 py-6 text-[15px] leading-relaxed text-gray-100 coach-message">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || "…"}</ReactMarkdown>
            </div>
          )
        ))}
        {savedMemories.length > 0 && (
          <div className="text-xs text-gray-500 italic text-center py-2">
            Remembered:{" "}
            {savedMemories.map((m) => `[${m.category}] ${m.content}`).join(" · ")}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-800 p-4">
        <div className="flex gap-2 max-w-3xl mx-auto">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask your coach…"
            rows={1}
            disabled={streaming}
            className="flex-1 resize-none rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-base text-gray-100 placeholder-gray-500 focus:outline-none focus:border-green-500 disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="px-5 py-3 rounded-lg bg-green-600 hover:bg-green-500 text-white text-base font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {streaming ? "…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
