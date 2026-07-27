import { useState, useEffect } from "react";
import type { ThemeConfig } from "../App";

interface Memory {
  id: number;
  category: string;
  content: string;
  created_at: string;
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
  }

  function cancelEdit() {
    setEditingId(null);
    setEditCategory("");
    setEditContent("");
  }

  async function saveEdit(id: number) {
    if (!editContent.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/memories/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category: editCategory, content: editContent.trim() }),
      });
      if (!res.ok) throw new Error();
      const updated: Memory = await res.json();
      setMemories((prev) => prev.map((m) => (m.id === id ? updated : m)));
      setEditingId(null);
    } catch {
      // leave edit open on error
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
      if (!res.ok) throw new Error(await res.text());
      const data: FlaggedMemory[] = await res.json();
      setFlagged(data);
      // Pre-select all flagged memories
      setSelected(new Set(data.map((m) => m.id)));
    } catch (e) {
      setReviewError("Review failed. Please try again.");
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

  async function deleteSelected() {
    if (selected.size === 0) return;
    setDeleting(true);
    try {
      await Promise.all(
        [...selected].map((id) => fetch(`/api/memories/${id}`, { method: "DELETE" }))
      );
      const removed = selected;
      setMemories((prev) => prev.filter((m) => !removed.has(m.id)));
      setFlagged(null);
      setSelected(new Set());
    } catch {
      // no-op
    } finally {
      setDeleting(false);
    }
  }

  const grouped = CATEGORIES.reduce<Record<string, Memory[]>>((acc, cat) => {
    acc[cat] = memories.filter((m) => m.category === cat);
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
          memory.
        </p>

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
                    Uncheck any you'd like to keep, then delete the rest.
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
                    onClick={deleteSelected}
                    disabled={selected.size === 0 || deleting}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 hover:bg-red-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {deleting ? "Deleting…" : `Delete ${selected.size} selected`}
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
                        <p className="flex-1 text-sm text-gray-300 leading-relaxed">
                          {memory.content}
                        </p>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
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
