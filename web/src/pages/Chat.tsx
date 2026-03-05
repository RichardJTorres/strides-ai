import { memo, useEffect, useRef, useState } from "react";
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

// Memoized so it doesn't re-render on every input keystroke
const MessageList = memo(function MessageList({
  messages,
  savedMemories,
  historyLoaded,
  streamingIndex,
  scrollContainerRef,
  bottomRef,
}: {
  messages: Message[];
  savedMemories: Memory[];
  historyLoaded: boolean;
  streamingIndex: number | null;
  scrollContainerRef: React.RefObject<HTMLDivElement>;
  bottomRef: React.RefObject<HTMLDivElement>;
}) {
  return (
    <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-8">
        {historyLoaded && messages.length === 0 && (
          <div className="text-center mt-24">
            <h2 className="text-xl font-semibold text-gray-200 mb-2">
              How can I help with your training?
            </h2>
            <p className="text-gray-500 text-sm">
              Ask about your recent runs, training load, race prep, or anything else.
            </p>
          </div>
        )}

        <div className="space-y-6">
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[75%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed bg-gray-800 text-gray-100 border border-gray-700/50">
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={i} className="text-[15px] leading-relaxed text-gray-100 coach-message">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {m.content || (i === streamingIndex ? "" : "…")}
                </ReactMarkdown>
              </div>
            )
          )}
        </div>

        {savedMemories.length > 0 && (
          <div className="mt-4 text-xs text-gray-600 italic text-center">
            Remembered:{" "}
            {savedMemories.map((m) => `[${m.category}] ${m.content}`).join(" · ")}
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
});

// Characters revealed per animation frame (~60fps). 25 chars/frame ≈ 1500 chars/sec —
// fast enough to feel responsive, slow enough for the eye to follow.
const CHARS_PER_FRAME = 25;

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streamingIndex, setStreamingIndex] = useState<number | null>(null);
  const [savedMemories, setSavedMemories] = useState<Memory[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Full received text (fills as fast as API delivers)
  const streamBufferRef = useRef("");
  // How many chars we've revealed on screen so far
  const displayCountRef = useRef(0);
  // True once the API stream has fully ended
  const streamDoneRef = useRef(false);
  const rafRef = useRef<number | null>(null);

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
    if (historyLoaded) scrollToBottom();
  }, [historyLoaded]);

  // Cancel any running animation on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  function autoResize() {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    const newHeight = Math.min(el.scrollHeight, 200);
    el.style.height = newHeight + "px";
    el.style.overflowY = el.scrollHeight > 200 ? "auto" : "hidden";
  }

  function isNearBottom() {
    const el = scrollContainerRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scrollToBottom() {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }

  async function send() {
    const text = input.trim();
    if (!text || streamingIndex !== null) return;

    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "52px";
      textareaRef.current.style.overflowY = "hidden";
    }
    setSavedMemories([]);

    const assistantIndex = messages.length + 1;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setStreamingIndex(assistantIndex);

    streamBufferRef.current = "";
    displayCountRef.current = 0;
    streamDoneRef.current = false;

    // Scroll after React renders the new messages (next frame)
    requestAnimationFrame(() => scrollToBottom());

    // Typewriter loop: reveal CHARS_PER_FRAME chars per frame from the buffer.
    // Self-terminates once stream is done and all chars have been revealed.
    function typewriterFrame() {
      const buffer = streamBufferRef.current;
      const next = Math.min(displayCountRef.current + CHARS_PER_FRAME, buffer.length);

      if (next > displayCountRef.current) {
        displayCountRef.current = next;
        const shown = buffer.slice(0, next);
        setMessages((prev) =>
          prev.map((m, i) => (i === assistantIndex ? { ...m, content: shown } : m))
        );
      }

      // Always scroll while content hasn't started yet, then track bottom
      if (displayCountRef.current === 0 || isNearBottom()) scrollToBottom();

      const finished = streamDoneRef.current && displayCountRef.current >= buffer.length;
      if (!finished) {
        rafRef.current = requestAnimationFrame(typewriterFrame);
      } else {
        rafRef.current = null;
        setStreamingIndex(null);
        scrollToBottom();
      }
    }
    rafRef.current = requestAnimationFrame(typewriterFrame);

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
              // ignore
            }
            continue;
          }

          // Buffer received tokens — typewriter loop handles display
          streamBufferRef.current += payload;
        }
      }
    } catch {
      streamBufferRef.current = "_Error: could not reach the server._";
    } finally {
      // Signal the typewriter loop that no more tokens are coming.
      // It will drain the remaining buffer then clear streamingIndex itself.
      streamDoneRef.current = true;
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-950">
      <MessageList
        messages={messages}
        savedMemories={savedMemories}
        historyLoaded={historyLoaded}
        streamingIndex={streamingIndex}
        scrollContainerRef={scrollContainerRef}
        bottomRef={bottomRef}
      />

      {/* Input */}
      <div className="px-4 pb-6 pt-5 border-t border-gray-800/60">
        <div className="max-w-3xl mx-auto relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              autoResize();
            }}
            onKeyDown={onKeyDown}
            placeholder="Message your coach…"
            disabled={streamingIndex !== null}
            className="w-full resize-none rounded-2xl bg-gray-800 border border-gray-700/60 px-4 py-3.5 pr-14 text-[15px] text-gray-100 placeholder-gray-500 focus:outline-none focus:border-green-500/40 focus:ring-1 focus:ring-green-500/10 disabled:opacity-50 transition-colors leading-relaxed"
            style={{ minHeight: "52px", height: "52px", overflowY: "hidden" }}
          />
          <button
            onClick={send}
            disabled={streamingIndex !== null || !input.trim()}
            className="absolute right-2.5 bottom-2.5 w-8 h-8 rounded-xl bg-green-600 hover:bg-green-500 text-white flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            {streamingIndex !== null ? (
              <span className="text-xs leading-none">●</span>
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path
                  d="M7 12V2M7 2L3 6M7 2L11 6"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </button>
        </div>
        <p className="text-center text-xs text-gray-700 mt-2">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
