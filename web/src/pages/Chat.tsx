import { memo, useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Mode, ThemeConfig } from "../App";

interface Message {
  id?: number;
  role: "user" | "assistant";
  content: string;
  created_at?: string;
}

interface Memory {
  category: string;
  content: string;
}

interface Props {
  mode: Mode;
  theme: ThemeConfig;
  supportsAttachments: boolean;
}

const SCROLL_KEY = "chat_scroll";
const PAGE_SIZE = 40;

// Memoized so it doesn't re-render on every input keystroke
const MessageList = memo(function MessageList({
  messages,
  savedMemories,
  streamingIndex,
  highlightedId,
  hasOlderMessages,
  loadingOlder,
  onLoadOlder,
  scrollContainerRef,
  bottomRef,
  mode,
  theme,
}: {
  messages: Message[];
  savedMemories: Memory[];
  streamingIndex: number | null;
  highlightedId: number | null;
  hasOlderMessages: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
  scrollContainerRef: React.RefObject<HTMLDivElement>;
  bottomRef: React.RefObject<HTMLDivElement>;
  mode: Mode;
  theme: ThemeConfig;
}) {
  const emptyStateText = {
    running: {
      heading: "How can I help with your running?",
      sub: "Ask about your recent runs, training load, race prep, or anything else.",
    },
    cycling: {
      heading: "How can I help with your cycling?",
      sub: "Ask about your recent rides, training load, race prep, or anything else.",
    },
    hybrid: {
      heading: "How can I help with your training?",
      sub: "Ask about your running and cycling, cross-training load, or anything else.",
    },
  }[mode];

  return (
    <div ref={scrollContainerRef} className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-4 py-8">
        {hasOlderMessages && (
          <div className="flex justify-center mb-6">
            <button
              onClick={onLoadOlder}
              disabled={loadingOlder}
              className="text-sm text-gray-400 hover:text-gray-200 border border-gray-700 hover:border-gray-500 rounded-full px-4 py-1.5 transition-colors disabled:opacity-40"
            >
              {loadingOlder ? "Loading…" : "Load older messages"}
            </button>
          </div>
        )}

        {messages.length === 0 && !hasOlderMessages && (
          <div className="text-center mt-24">
            <h2 className="text-xl font-semibold text-gray-200 mb-2">
              {emptyStateText.heading}
            </h2>
            <p className="text-gray-500 text-sm">
              {emptyStateText.sub}
            </p>
          </div>
        )}

        <div className="space-y-6">
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div
                key={m.id ?? `session-${i}`}
                data-message-id={m.id}
                className={`flex justify-end transition-all duration-500 ${
                  highlightedId !== null && m.id === highlightedId
                    ? "opacity-100 scale-[1.01]"
                    : ""
                }`}
              >
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-[15px] leading-relaxed border transition-colors duration-700 ${
                    highlightedId !== null && m.id === highlightedId
                      ? `bg-gray-700 ${theme.accentBorder}`
                      : "bg-gray-800 text-gray-100 border-gray-700/50"
                  }`}
                >
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {m.content}
                  </ReactMarkdown>
                </div>
              </div>
            ) : (
              <div
                key={m.id ?? `session-${i}`}
                data-message-id={m.id}
                className={`text-[15px] leading-relaxed text-gray-100 coach-message transition-colors duration-700 rounded-xl ${
                  highlightedId !== null && m.id === highlightedId
                    ? `${theme.accentBg} px-3 py-1 -mx-3`
                    : ""
                }`}
              >
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


function escapeRegex(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightMatch(text: string, query: string): string {
  if (!query) return text;
  const re = new RegExp(`(${escapeRegex(query)})`, "gi");
  return text.replace(re, "**$1**");
}

function formatDate(created_at: string): string {
  try {
    return new Date(created_at + "Z").toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return created_at.slice(0, 10);
  }
}

export default function Chat({ mode, theme, supportsAttachments }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [oldestLoadedId, setOldestLoadedId] = useState<number | null>(null);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [input, setInput] = useState("");
  const [streamingIndex, setStreamingIndex] = useState<number | null>(null);
  const [savedMemories, setSavedMemories] = useState<Memory[]>([]);

  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<Message[]>([]);
  const [searching, setSearching] = useState(false);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const blobUrlsInMessagesRef = useRef<string[]>([]);

  // Abort any in-flight request on unmount (e.g. page refresh mid-stream)
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      blobUrlsInMessagesRef.current.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

  // Reset and reload history whenever mode changes
  useEffect(() => {
    setMessages([]);
    setOldestLoadedId(null);
    setHasOlderMessages(false);
    setSavedMemories([]);
    setSearchOpen(false);
    sessionStorage.removeItem(SCROLL_KEY);

    fetch(`/api/history?limit=${PAGE_SIZE}&mode=${mode}`)
      .then((r) => r.json())
      .then(({ messages: msgs, total }: { messages: Message[]; total: number }) => {
        setMessages(msgs);
        if (msgs.length > 0) {
          setOldestLoadedId(msgs[0].id ?? null);
        }
        setHasOlderMessages(total > msgs.length);
        requestAnimationFrame(() => {
          const el = scrollContainerRef.current;
          if (el) el.scrollTop = el.scrollHeight;
        });
      })
      .catch(() => {/* leave messages empty on error */});
  }, [mode]);

  // Persist scroll position on every scroll
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const save = () => sessionStorage.setItem(SCROLL_KEY, String(el.scrollTop));
    el.addEventListener("scroll", save);
    return () => el.removeEventListener("scroll", save);
  }, []);


  // Ctrl+F / Cmd+F → open search
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
      if (e.key === "Escape" && searchOpen) {
        setSearchOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [searchOpen]);

  // Focus search input when opened
  useEffect(() => {
    if (searchOpen) {
      requestAnimationFrame(() => searchInputRef.current?.focus());
    } else {
      setSearchQuery("");
      setSearchResults([]);
    }
  }, [searchOpen]);

  // Debounced search
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (!searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    searchDebounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await fetch(
          `/api/history/search?q=${encodeURIComponent(searchQuery.trim())}&limit=20&mode=${mode}`
        );
        const { results } = await res.json();
        setSearchResults(results);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, [searchQuery, mode]);

  const loadOlderMessages = useCallback(async () => {
    if (!oldestLoadedId || loadingOlder) return;
    setLoadingOlder(true);
    const el = scrollContainerRef.current;
    const prevScrollHeight = el?.scrollHeight ?? 0;
    try {
      const res = await fetch(
        `/api/history/older?before_id=${oldestLoadedId}&limit=${PAGE_SIZE}&mode=${mode}`
      );
      const { messages: older }: { messages: Message[] } = await res.json();
      if (older.length === 0) {
        setHasOlderMessages(false);
        return;
      }
      setMessages((prev) => [...older, ...prev]);
      setOldestLoadedId(older[0].id ?? null);
      if (older.length < PAGE_SIZE) setHasOlderMessages(false);
      // Preserve scroll position: restore the delta from the new content above
      requestAnimationFrame(() => {
        if (el) {
          el.scrollTop = el.scrollHeight - prevScrollHeight;
        }
      });
    } finally {
      setLoadingOlder(false);
    }
  }, [oldestLoadedId, loadingOlder, mode]);

  function flashHighlight(id: number) {
    if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
    setHighlightedId(id);
    highlightTimerRef.current = setTimeout(() => setHighlightedId(null), 2000);
  }

  async function jumpToMessage(target: Message) {
    if (!target.id) return;
    setSearchOpen(false);

    // Check if already loaded
    const alreadyLoaded = messages.some((m) => m.id === target.id);

    if (!alreadyLoaded) {
      // Load older messages until the target id is present
      let currentOldest = oldestLoadedId;
      let keepLoading = currentOldest !== null && currentOldest > target.id;
      while (keepLoading) {
        setLoadingOlder(true);
        try {
          const res = await fetch(
            `/api/history/older?before_id=${currentOldest}&limit=${PAGE_SIZE}&mode=${mode}`
          );
          const { messages: older }: { messages: Message[] } = await res.json();
          if (older.length === 0) { keepLoading = false; break; }
          const el = scrollContainerRef.current;
          const prevScrollHeight = el?.scrollHeight ?? 0;
          setMessages((prev) => [...older, ...prev]);
          currentOldest = older[0].id ?? null;
          setOldestLoadedId(currentOldest);
          if (older.length < PAGE_SIZE) { setHasOlderMessages(false); keepLoading = false; }
          else keepLoading = currentOldest !== null && currentOldest > target.id;
          // Preserve scroll
          requestAnimationFrame(() => {
            if (el) el.scrollTop = el.scrollHeight - prevScrollHeight;
          });
        } finally {
          setLoadingOlder(false);
        }
      }
    }

    // Give React time to commit new messages to DOM before scrolling
    setTimeout(() => {
      const el = document.querySelector(`[data-message-id="${target.id}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      flashHighlight(target.id!);
    }, 50);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const newFiles = Array.from(e.target.files ?? []);
    if (newFiles.length === 0) return;
    setAttachedFiles((prev) => [...prev, ...newFiles]);
    setPreviewUrls((prev) => [
      ...prev,
      ...newFiles.map((f) => (f.type.startsWith("image/") ? URL.createObjectURL(f) : "")),
    ]);
    e.target.value = ""; // allow re-selecting the same file
  }

  function removeAttachment(index: number) {
    const url = previewUrls[index];
    if (url) URL.revokeObjectURL(url);
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
    setPreviewUrls((prev) => prev.filter((_, i) => i !== index));
  }

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
    if ((!text && attachedFiles.length === 0) || streamingIndex !== null) return;

    // Snapshot files before clearing state
    const filesToSend = attachedFiles;
    const snapshotUrls = previewUrls;

    // Build the optimistic user message — use blob URLs for images so they
    // render immediately; text files fall back to a paperclip note
    const attachmentNote = filesToSend.length > 0
      ? "\n\n" + filesToSend.map((f, i) =>
          snapshotUrls[i] ? `![${f.name}](${snapshotUrls[i]})` : `📎 ${f.name}`
        ).join("\n")
      : "";
    const optimisticContent = text + attachmentNote;

    // Track blob URLs embedded in the message; revoke on unmount
    snapshotUrls.forEach((u) => { if (u) blobUrlsInMessagesRef.current.push(u); });

    setInput("");
    setAttachedFiles([]);
    setPreviewUrls([]);
    if (textareaRef.current) {
      textareaRef.current.style.height = "52px";
      textareaRef.current.style.overflowY = "hidden";
    }
    setSavedMemories([]);

    const assistantIndex = messages.length + 1;

    setMessages((prev) => [
      ...prev,
      { role: "user", content: optimisticContent },
      { role: "assistant", content: "" },
    ]);
    setStreamingIndex(assistantIndex);

    requestAnimationFrame(() => scrollToBottom());

    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const formData = new FormData();
      formData.append("message", text);
      formData.append("mode", mode);
      for (const file of filesToSend) {
        formData.append("files", file);
      }

      const res = await fetch("/api/chat", {
        method: "POST",
        body: formData,
        signal: controller.signal,
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

          if (payload.startsWith("[ERROR]")) {
            setMessages((prev) =>
              prev.map((m, i) =>
                i === assistantIndex ? { ...m, content: `_${payload.slice(7)}_` } : m
              )
            );
            continue;
          }

          setMessages((prev) =>
            prev.map((m, i) => (i === assistantIndex ? { ...m, content: m.content + payload } : m))
          );
          if (isNearBottom()) scrollToBottom();
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setMessages((prev) =>
        prev.map((m, i) =>
          i === assistantIndex ? { ...m, content: "_Error: could not reach the server._" } : m
        )
      );
    } finally {
      setStreamingIndex(null);
      scrollToBottom();
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-950 relative">
      {/* Search toggle button */}
      <button
        onClick={() => setSearchOpen((o) => !o)}
        title="Search conversation (Ctrl+F)"
        className={`absolute top-3 right-3 z-10 w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${
          searchOpen
            ? `${theme.accentButton} text-white`
            : "text-gray-500 hover:text-gray-300 hover:bg-gray-800"
        }`}
      >
        <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
          <path
            d="M10 6.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Zm-.9 3.4 2.5 2.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {/* Search panel */}
      {searchOpen && (
        <div className="border-b border-gray-800 bg-gray-950 z-10">
          <div className="max-w-3xl mx-auto px-4 py-3">
            <div className="relative">
              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search conversation…"
                className={`w-full bg-gray-800 border border-gray-700/60 rounded-xl px-4 py-2.5 pr-10 text-[14px] text-gray-100 placeholder-gray-500 focus:outline-none ${theme.accentFocus}`}
              />
              {searchQuery && (
                <button
                  onClick={() => { setSearchQuery(""); setSearchResults([]); }}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M1 1l10 10M11 1L1 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>

            {searching && (
              <p className="text-xs text-gray-500 mt-2 pl-1">Searching…</p>
            )}

            {!searching && searchResults.length > 0 && (
              <ul className="mt-2 space-y-1 max-h-64 overflow-y-auto">
                {searchResults.map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => jumpToMessage(r)}
                      className="w-full text-left rounded-lg px-3 py-2 hover:bg-gray-800 transition-colors group"
                    >
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                          r.role === "user" ? "bg-gray-700 text-gray-300" : `${theme.accentBg} ${theme.accentClass}`
                        }`}>
                          {r.role === "user" ? "You" : "Coach"}
                        </span>
                        {r.created_at && (
                          <span className="text-[11px] text-gray-600">{formatDate(r.created_at)}</span>
                        )}
                      </div>
                      <p className="text-[13px] text-gray-400 group-hover:text-gray-300 line-clamp-2 leading-snug">
                        {highlightMatch(r.content.slice(0, 200), searchQuery)
                          .split(/(\*\*.*?\*\*)/)
                          .map((part, i) =>
                            part.startsWith("**") && part.endsWith("**") ? (
                              <mark key={i} className="bg-yellow-500/30 text-yellow-200 rounded px-0.5">
                                {part.slice(2, -2)}
                              </mark>
                            ) : (
                              <span key={i}>{part}</span>
                            )
                          )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {!searching && searchQuery.trim() && searchResults.length === 0 && (
              <p className="text-xs text-gray-600 mt-2 pl-1">No messages found.</p>
            )}
          </div>
        </div>
      )}

      <MessageList
        messages={messages}
        savedMemories={savedMemories}
        streamingIndex={streamingIndex}
        highlightedId={highlightedId}
        hasOlderMessages={hasOlderMessages}
        loadingOlder={loadingOlder}
        onLoadOlder={loadOlderMessages}
        scrollContainerRef={scrollContainerRef}
        bottomRef={bottomRef}
        mode={mode}
        theme={theme}
      />

      {/* Input */}
      <div className="px-4 pb-6 pt-5 border-t border-gray-800/60">
        <div className="max-w-3xl mx-auto">
          {/* File preview strip */}
          {attachedFiles.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2">
              {attachedFiles.map((file, i) => (
                <div key={i} className="relative flex items-center gap-1.5 bg-gray-800 border border-gray-700/60 rounded-xl px-2.5 py-1.5 text-xs text-gray-300">
                  {previewUrls[i] ? (
                    <img src={previewUrls[i]} alt={file.name} className="w-8 h-8 object-cover rounded-lg" />
                  ) : (
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="text-gray-400 shrink-0">
                      <path d="M8 1H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5L8 1Z" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                      <path d="M8 1v4h4" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                  <span className="max-w-[120px] truncate">{file.name}</span>
                  <button
                    onClick={() => removeAttachment(i)}
                    className="ml-0.5 text-gray-500 hover:text-gray-200 transition-colors"
                    aria-label="Remove attachment"
                  >
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                      <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="relative">
            {/* Hidden file input */}
            {supportsAttachments && (
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,.txt,.csv,.gpx"
                className="hidden"
                onChange={handleFileChange}
              />
            )}

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
              className={`w-full resize-none rounded-2xl bg-gray-800 border border-gray-700/60 py-3.5 pr-14 text-[15px] text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 ${theme.accentFocus} disabled:opacity-50 transition-colors leading-relaxed ${supportsAttachments ? "pl-10" : "px-4"}`}
              style={{ minHeight: "52px", height: "52px", overflowY: "hidden" }}
            />

            {/* Paperclip button */}
            {supportsAttachments && (
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={streamingIndex !== null}
                title="Attach image or file"
                className="absolute left-2.5 bottom-2.5 w-8 h-8 rounded-xl text-gray-500 hover:text-gray-300 hover:bg-gray-700 flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
                  <path
                    d="M13.5 7.5 7.5 13.5A4.5 4.5 0 0 1 1 7L7.5 1A3 3 0 0 1 12 5.5L5.5 12A1.5 1.5 0 0 1 3.5 10L9 4.5"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            )}

            {/* Send button */}
            <button
              onClick={send}
              disabled={streamingIndex !== null || (!input.trim() && attachedFiles.length === 0)}
              className={`absolute right-2.5 bottom-2.5 w-8 h-8 rounded-xl ${theme.accentButton} text-white flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all`}
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
        </div>
        <p className="text-center text-xs text-gray-700 mt-2">
          Enter to send · Shift+Enter for new line{supportsAttachments ? " · Attach images & files" : ""}
        </p>
      </div>
    </div>
  );
}
