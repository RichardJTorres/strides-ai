import { useState, useEffect } from "react";
import type { ThemeConfig } from "../App";

interface Memory {
  id: number;
  category: string;
  content: string;
  created_at: string;
  status: "current" | "temporary" | "superseded";
  topic: string | null;
  effective_from: string | null;
  effective_until: string | null;
  applicable: boolean;
}

interface FlaggedMemory extends Memory {
  reason: string;
}

const CATEGORIES = ["goal", "race", "injury", "preference", "training", "other"] as const;

const CATEGORY_LABELS: Record<string, string> = {
  goal: "Goal",
  race: "Race",
  injury: "Injury",
  preference: "Preference",
  training: "Training",
  other: "Other",
};

const CATEGORY_COLORS: Record<string, string> = {
  goal: "text-green-400 bg-green-500/10 border-green-500/20",
  race: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  injury: "text-red-400 bg-red-500/10 border-red-500/20",
  preference: "text-purple-400 bg-purple-500/10 border-purple-500/20",
  training: "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
  other: "text-gray-400 bg-gray-500/10 border-gray-500/20",
};

interface Props {
  theme: ThemeConfig;
}

export default function Memories({ theme }: Props) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editCategory, setEditCategory] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editStatus, setEditStatus] = useState<Memory["status"]>("current");
  const [editTopic, setEditTopic] = useState("");
  const [editFrom, setEditFrom] = useState("");
  const [editUntil, setEditUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // Review state
  const [reviewing, setReviewing] = useState(false);
  const [flagged, setFlagged] = useState<FlaggedMemory[] | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    fetch("/api/memories")
      .then((r) => r.json())
      .then((data: Memory[]) => setMemories(data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function startEdit(memory: Memory) {
    setEditingId(memory.id);
    setEditCategory(memory.category);
    setEditContent(memory.content);
    setEditStatus(memory.status);
    setEditTopic(memory.topic ?? "");
    setEditFrom(memory.effective_from ?? "");
    setEditUntil(memory.effective_until ?? "");
    setError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditCategory("");
    setEditContent("");
  }

  async function saveEdit(id: number) {
    if (!editContent.trim()) return;
    setError(null);
    setSaving(true);
    try {
      const res = await fetch(`/api/memories/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: editCategory, content: editContent.trim(),
          status: editStatus, topic: editTopic.trim() || null,
          effective_from: editFrom || null, effective_until: editUntil || null }),
      });
      if (!res.ok) throw new Error();
      await res.json();
      const refreshed = await fetch("/api/memories");
      if (!refreshed.ok) throw new Error();
      setMemories(await refreshed.json());
      setEditingId(null);
    } catch {
      setError("Could not save. Check the date range and ensure the content is unique.");
    } finally {
      setSaving(false);
    }
  }

  async function deleteMemory(id: number) {
    setDeletingId(id);
    try {
      const res = await fetch(`/api/memories/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error();
      setMemories((prev) => prev.filter((m) => m.id !== id));
    } catch {
      // no-op
    } finally {
      setDeletingId(null);
    }
  }

  async function startReview() {
    setReviewing(true);
    setFlagged(null);
    setReviewError(null);
    setSelected(new Set());
    try {
      const res = await fetch("/api/memories/review", { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      const data: FlaggedMemory[] = await res.json();
      setFlagged(data);
      // Pre-select all flagged memories
      setSelected(new Set(data.map((m) => m.id)));
    } catch (e) {
      setReviewError(`Review failed: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setReviewing(false);
    }
  }

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function archiveSelected() {
    if (selected.size === 0) return;
    setDeleting(true);
    try {
      const results = await Promise.all(
        [...selected].map(async (id) => {
          const memory = memories.find((m) => m.id === id)!;
          const res = await fetch(`/api/memories/${id}`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category: memory.category, content: memory.content, status: "superseded" }),
          });
          return res.ok;
        })
      );
      const refreshed = await fetch("/api/memories");
      if (!refreshed.ok) throw new Error();
      setMemories(await refreshed.json());
      if (results.some((ok) => !ok)) throw new Error();
      setFlagged(null);
      setSelected(new Set());
    } catch {
      setReviewError("Some memories could not be archived. Please review and try again.");
    } finally {
      setDeleting(false);
    }
  }

  const grouped = CATEGORIES.reduce<Record<string, Memory[]>>((acc, cat) => {
    acc[cat] = memories.filter((m) => m.category === cat && (showHistory || m.status !== "superseded"));
    return acc;
  }, {} as Record<string, Memory[]>);

  const nonemptyCategories = CATEGORIES.filter((c) => grouped[c].length > 0);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-10">
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-xl font-semibold text-gray-100">Memories</h2>
          {memories.length > 0 && (
            <button
              onClick={startReview}
              disabled={reviewing || loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-400 border border-gray-700 hover:border-gray-500 hover:text-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {reviewing ? (
                <>
                  <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56" strokeLinecap="round"/>
                  </svg>
                  Reviewing…
                </>
              ) : (
                <>
                  <svg xmlns="http://www.w3.org/2000/svg" className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                  </svg>
                  Review for staleness
                </>
              )}
            </button>
          )}
        </div>
        <p className="text-sm text-gray-500 mb-8">
          Facts your coach has remembered from previous conversations. You can edit or delete any
          memory. Temporary facts override standing facts with the same topic during their date range.
        </p>
        <label className="flex gap-2 text-sm text-gray-400 mb-4">
          <input type="checkbox" checked={showHistory} onChange={(e) => setShowHistory(e.target.checked)} />
          Show superseded memories
        </label>
        {error && <p role="alert" className="text-red-400 text-sm mb-4">{error}</p>}

        {/* Review results panel */}
        {reviewError && (
          <div className="mb-6 p-3 rounded-lg border border-red-500/20 bg-red-500/5 text-xs text-red-400">
            {reviewError}
          </div>
        )}

        {flagged !== null && (
          <div className="mb-8 rounded-lg border border-gray-700 bg-gray-900 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-200">
                  {flagged.length === 0
                    ? "All memories look current"
                    : `${flagged.length} memor${flagged.length === 1 ? "y" : "ies"} flagged for review`}
                </p>
                {flagged.length > 0 && (
                  <p className="text-xs text-gray-500 mt-0.5">
                    Uncheck any you'd like to keep, then archive the rest as superseded.
                  </p>
                )}
              </div>
              <button
                onClick={() => { setFlagged(null); setSelected(new Set()); }}
                className="text-gray-600 hover:text-gray-400 transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
              </button>
            </div>

            {flagged.length > 0 && (
              <>
                <ul className="divide-y divide-gray-800">
                  {flagged.map((m) => (
                    <li key={m.id} className="flex items-start gap-3 px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(m.id)}
                        onChange={() => toggleSelected(m.id)}
                        className="mt-0.5 shrink-0 accent-red-500 cursor-pointer"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${CATEGORY_COLORS[m.category]}`}>
                            {CATEGORY_LABELS[m.category]}
                          </span>
                        </div>
                        <p className="text-sm text-gray-300">{m.content}</p>
                        <p className="text-xs text-gray-500 mt-1 italic">{m.reason}</p>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="px-4 py-3 border-t border-gray-800 flex items-center gap-3">
                  <button
                    onClick={archiveSelected}
                    disabled={selected.size === 0 || deleting}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting ? "Archiving…" : `Archive ${selected.size} selected`}
                  </button>
                  <button
                    onClick={() => { setFlagged(null); setSelected(new Set()); }}
                    disabled={deleting}
                    className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                  >
                    Keep all
                  </button>
                </div>
              </>
            )}

            {flagged.length === 0 && (
              <p className="px-4 py-4 text-xs text-gray-500">
                No stale or outdated memories detected. Everything looks good.
              </p>
            )}
          </div>
        )}

        {loading && (
          <p className="text-sm text-gray-600">Loading…</p>
        )}

        {!loading && memories.length === 0 && (
          <div className="text-center py-16">
            <p className="text-gray-600 text-sm">No memories saved yet.</p>
            <p className="text-gray-700 text-xs mt-1">
              Your coach will remember things as you chat.
            </p>
          </div>
        )}

        {!loading && nonemptyCategories.length > 0 && (
          <div className="space-y-8">
            {nonemptyCategories.map((cat) => (
              <section key={cat}>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-3">
                  {CATEGORY_LABELS[cat]}
                </h3>
                <div className="space-y-2">
                  {grouped[cat].map((memory) =>
                    editingId === memory.id ? (
                      <div
                        key={memory.id}
                        className="p-3 rounded-lg border border-gray-600 bg-gray-900"
                      >
                        <select
                          value={editCategory}
                          onChange={(e) => setEditCategory(e.target.value)}
                          disabled={saving}
                          className="mb-2 w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:outline-none focus:border-gray-500 disabled:opacity-50"
                        >
                          {CATEGORIES.map((c) => (
                            <option key={c} value={c}>
                              {CATEGORY_LABELS[c]}
                            </option>
                          ))}
                        </select>
                        <div className="grid grid-cols-2 gap-2 mb-2 text-xs text-gray-400">
                          <label>State
                            <select aria-label="Memory state" value={editStatus} disabled={saving} onChange={(e) => setEditStatus(e.target.value as Memory["status"])} className="block w-full bg-gray-800 rounded p-2 mt-1">
                              <option value="current">Current</option><option value="temporary">Temporary</option><option value="superseded">Superseded</option>
                            </select>
                          </label>
                          <label>Topic
                            <input value={editTopic} disabled={saving} onChange={(e) => setEditTopic(e.target.value)} maxLength={100} placeholder="e.g. running_intensity" className="block w-full bg-gray-800 rounded p-2 mt-1" />
                          </label>
                          <label>Effective from
                            <input type="date" value={editFrom} disabled={saving} onChange={(e) => setEditFrom(e.target.value)} className="block w-full bg-gray-800 rounded p-2 mt-1" />
                          </label>
                          <label>Effective through (optional)
                            <input type="date" value={editUntil} min={editFrom || undefined} disabled={saving} onChange={(e) => setEditUntil(e.target.value)} className="block w-full bg-gray-800 rounded p-2 mt-1" />
                          </label>
                        </div>
                        <p className="text-xs text-gray-500 mb-2">Only replacement facts should share a topic. Leave the end date blank if unknown.</p>
                        <textarea
                          value={editContent}
                          onChange={(e) => setEditContent(e.target.value)}
                          disabled={saving}
                          rows={3}
                          className="w-full bg-gray-800 text-gray-200 text-sm rounded px-2 py-1.5 border border-gray-700 focus:outline-none focus:border-gray-500 disabled:opacity-50 resize-none"
                        />
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={() => saveEdit(memory.id)}
                            disabled={saving || !editContent.trim()}
                            className={`px-3 py-1 rounded text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${theme.accentButton} text-white`}
                          >
                            {saving ? "Saving…" : "Save"}
                          </button>
                          <button
                            onClick={cancelEdit}
                            disabled={saving}
                            className="px-3 py-1 rounded text-xs font-medium text-gray-400 hover:text-gray-200 transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        key={memory.id}
                        className={`flex items-start gap-3 p-3 rounded-lg border bg-gray-900 group transition-colors ${
                          flagged?.some((f) => f.id === memory.id)
                            ? "border-yellow-500/30 bg-yellow-500/5"
                            : "border-gray-800"
                        }`}
                      >
                        <span
                          className={`shrink-0 mt-0.5 text-[10px] font-medium px-1.5 py-0.5 rounded border ${CATEGORY_COLORS[memory.category]}`}
                        >
                          {CATEGORY_LABELS[memory.category]}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-gray-400 mb-1">
                            {memory.status} · {memory.applicable ? "In use" : "Not currently in use"}
                            {memory.topic && ` · ${memory.topic}`}
                          </p>
                          <p className="text-xs text-gray-500 mb-1">
                            {memory.effective_from ? `From ${memory.effective_from}` : "Start date unspecified"}
                            {memory.effective_until ? ` through ${memory.effective_until}` : " · No end date"}
                          </p>
                          <p className="text-sm text-gray-300 leading-relaxed">{memory.content}</p>
                        </div>
                        <div className="flex gap-1 md:opacity-0 md:group-hover:opacity-100 focus-within:opacity-100 transition-opacity shrink-0">
                          <button
                            onClick={() => startEdit(memory)}
                            title="Edit"
                            className="p-1 rounded text-gray-600 hover:text-gray-300 transition-colors"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              className="w-3.5 h-3.5"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                            </svg>
                          </button>
                          <button
                            onClick={() => deleteMemory(memory.id)}
                            disabled={deletingId === memory.id}
                            title="Delete"
                            className="p-1 rounded text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
                          >
                            <svg
                              xmlns="http://www.w3.org/2000/svg"
                              className="w-3.5 h-3.5"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <polyline points="3 6 5 6 21 6" />
                              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                              <path d="M10 11v6" />
                              <path d="M14 11v6" />
                              <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    )
                  )}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
