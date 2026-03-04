import { useEffect, useState } from "react";

export default function Profile() {
  const [content, setContent] = useState("");
  const [original, setOriginal] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/profile")
      .then((r) => r.json())
      .then((data) => {
        setContent(data.content);
        setOriginal(data.content);
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      setOriginal(content);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

  const dirty = content !== original;

  return (
    <div className="flex flex-col h-full p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">Athlete Profile</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Loaded fresh every session — tell your coach who you are.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saved && <span className="text-sm text-green-400">Saved!</span>}
          <button
            onClick={handleSave}
            disabled={saving || !dirty}
            className="px-3 py-1.5 rounded-md bg-green-600 hover:bg-green-500 text-white text-sm disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck={false}
          className="flex-1 w-full rounded-lg bg-gray-900 border border-gray-800 p-4 font-mono text-sm text-gray-100 focus:outline-none focus:border-green-500 resize-none"
        />
      )}
    </div>
  );
}
