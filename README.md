# strides-ai

A local AI running coach that connects to your Strava account and lets you have coaching conversations about your training. Supports Claude (via the Anthropic API) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full run history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Web UI** — a browser-based interface with a chat page, activity table, and an athlete profile editor.
- **Terminal chat** — a CLI alternative for coaching conversations directly in the terminal.
- **Athlete profile** — fill in your background, PBs, goals, injuries, and gear via the web UI or by editing `~/.strides_ai/profile.md` directly. Loaded fresh every session.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations.
- **Swappable backends** — run Claude in the cloud or a local model via Ollama, configured with a single env var.

## Setup

### 1. Prerequisites

- Python 3.11+
- Node.js 18+ (for the web UI)
- A [Strava API app](https://www.strava.com/settings/api) — set **Authorization Callback Domain** to `localhost`
- An Anthropic API key **or** a local [Ollama](https://ollama.com) installation (see [Backends](#backends) below)

### 2. Install

```bash
git clone https://github.com/RichardJTorres/strides-ai.git
cd strides-ai
cp .env.example .env   # then fill in your credentials
make install
```

`make install` creates a Python virtualenv and installs Node dependencies for the web UI.

### 3. Configure

Edit `.env` with at minimum your Strava credentials and LLM backend:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret

PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run

```bash
make dev      # web UI: API on :8000, frontend on :5173
# or
make cli      # terminal-only coaching app
```

On first run, a browser window opens to Strava's authorization page — approve it and the token is saved locally. Your athlete profile is created at `~/.strides_ai/profile.md` from a template.

---

## Web UI

`make dev` starts both the FastAPI backend (`:8000`) and the Vite frontend (`:5173`). Open `http://localhost:5173` in your browser.

| Tab | What it does |
|---|---|
| Coach | Streaming chat with your AI running coach |
| Activities | Your full Strava history — sortable, filterable, links to each activity on Strava |
| Charts | Training visualisations (coming soon) |
| Profile | Structured editor for your athlete profile |

The URL uses hash-based navigation (`#coach`, `#activities`, etc.), so refreshing the page keeps you on the same tab.

To run only the backend: `make api`. To run only the frontend: `make web`.

---

## Athlete Profile

Your profile lives at `~/.strides_ai/profile.md`. You can edit it through the **Profile** tab in the web UI, or directly in any text editor:

```bash
make profile   # opens it in $EDITOR
```

The file is read at the start of every session and sent verbatim to your coach as context. The template includes:

| Section | What to fill in |
|---|---|
| Personal | Name, gender, date of birth, height, weight |
| Running background | Years running, athletic history, typical weekly volume |
| Personal bests | 5K, 10K, half marathon, marathon times |
| Goals | Upcoming races, time targets, non-race goals |
| Injuries & health | Current/recurring injuries, medical conditions |
| Gear | Shoes (model + km on them), vest, poles, watch, other kit |
| Other notes | Training preferences, coaching style, anything else |

If you edit the file manually and the web UI can't parse it, an error state is shown with an option to reset to the template.

---

## Backends

The `PROVIDER` env var controls which LLM is used.

### Claude (default)

Uses the [Anthropic API](https://console.anthropic.com). Requires an API key.

```env
PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

# Optional: change the model (default: claude-sonnet-4-6)
CLAUDE_MODEL=claude-opus-4-6
```

### Ollama (local)

Runs any model locally via [Ollama](https://ollama.com). No API key or internet connection required after the model is downloaded.

```bash
ollama pull llama3.1        # recommended — good tool-use support
```

```env
PROVIDER=ollama
OLLAMA_MODEL=llama3.1

# Optional: override the default host
OLLAMA_HOST=http://localhost:11434
```

Tool use and memory saving work with models that support function calling (llama3.1, llama3.2, mistral-nemo, qwen2.5, and others).

---

## How it works

```
strides_ai/
├── api/
│   ├── app.py     # FastAPI routes, SSE streaming for /api/chat
│   └── server.py  # uvicorn entry point (strides-ai-web)
├── backends/
│   ├── base.py    # BaseBackend ABC — stream_turn(system, input, on_token)
│   ├── claude.py  # Anthropic SDK, tool_use loop
│   └── ollama.py  # httpx → Ollama /api/chat, streaming + tools
├── auth.py        # Strava OAuth2 — token exchange, storage, auto-refresh
├── db.py          # SQLite — activities, conversation history, memories
├── sync.py        # Strava API pagination, incremental sync
├── profile.py     # Profile Markdown — template, parse, serialize
├── coach.py       # Backend-agnostic chat loop (CLI)
└── cli.py         # CLI entry point: auth → sync → backend → chat
web/               # React + TypeScript + Tailwind (Vite)
```

**Data stored locally** in `~/.strides_ai/`:
- `profile.md` — athlete profile (editable via web UI or text editor)
- `activities.db` — SQLite database (activities, conversation history, memories)
- `token.json` — Strava OAuth token (auto-refreshed when expired)

---

## Stack

| Concern | Library |
|---|---|
| Strava API | `httpx` |
| Anthropic API | `anthropic` |
| Ollama API | `httpx` |
| Web framework | `fastapi` + `uvicorn` |
| Database | `sqlite3` (stdlib) |
| Terminal UI | `rich` |
| Config | `python-dotenv` |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
