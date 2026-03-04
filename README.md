# strides-ai

A local AI running coach that connects to your Strava account and lets you have coaching conversations about your training. Supports Claude (via the Anthropic API) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full run history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Terminal chat** — ask your coach anything about your training: pacing, volume trends, race prep, recovery, injury prevention. Your complete activity log is included as context on every message.
- **Athlete profile** — a plain Markdown file you edit freely to tell your coach who you are: background, PBs, goals, injuries, anything relevant. Loaded fresh every session.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations.
- **Swappable backends** — run Claude in the cloud or a local model via Ollama, configured with a single env var.

## Setup

### 1. Prerequisites

- Python 3.11+
- A [Strava API app](https://www.strava.com/settings/api) — set **Authorization Callback Domain** to `localhost`
- An Anthropic API key **or** a local [Ollama](https://ollama.com) installation (see [Backends](#backends) below)

### 2. Install

```bash
git clone https://github.com/RichardJTorres/strides-ai.git
cd strides-ai
python -m venv .venv
source .venv/bin/activate  # on fish: source .venv/bin/activate.fish
pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
```

At minimum you need your Strava credentials and whichever backend you intend to use (see [Backends](#backends)):

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret

PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run

```bash
strides-ai
```

On first run:
1. A browser window opens to Strava's authorization page — approve it and the token is saved locally for all future runs.
2. Your athlete profile file is created at `~/.strides_ai/profile.md` and opened in your `$EDITOR`. Fill it in and save — see [Athlete Profile](#athlete-profile) below.

---

## Athlete Profile

Your profile lives at `~/.strides_ai/profile.md`. It's plain Markdown — edit it in any text editor whenever your situation changes.

```bash
strides-ai --setup-profile   # open it in your $EDITOR directly
```

The file is read at the start of every session and sent verbatim to your coach as context. The more detail you fill in, the more tailored the coaching advice will be.

The template includes sections for:

| Section | What to fill in |
|---|---|
| Personal | Name, gender, date of birth, height, weight |
| Running background | Years running, athletic history, typical weekly volume |
| Personal bests | 5K, 10K, half marathon, marathon times |
| Goals | Upcoming races, time targets, non-race goals |
| Injuries & health | Current/recurring injuries, medical conditions |
| Other notes | Training preferences, coaching style, anything else |

There's no required format — write in whatever way feels natural. You can add or remove sections freely.

---

## Backends

The `PROVIDER` env var controls which LLM is used. The active backend is shown in the startup banner.

### Claude (default)

Uses the [Anthropic API](https://console.anthropic.com). Requires an API key.

```env
PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

# Optional: change the model (default: claude-sonnet-4-6)
CLAUDE_MODEL=claude-opus-4-6
```

Supported models: any `claude-*` model ID available on your Anthropic account.

### Ollama (local)

Runs any model locally via [Ollama](https://ollama.com). No API key or internet connection required after the model is downloaded.

**1. Install Ollama** — follow the instructions at [ollama.com](https://ollama.com/download)

**2. Pull a model:**

```bash
ollama pull llama3.1        # recommended — good tool-use support
ollama pull mistral-nemo    # smaller, also supports tools
ollama pull qwen2.5         # strong reasoning
```

**3. Set env vars:**

```env
PROVIDER=ollama
OLLAMA_MODEL=llama3.1

# Optional: override the default host (http://localhost:11434)
OLLAMA_HOST=http://localhost:11434
```

**Tool use and memory saving** work with models that support function calling (llama3.1, llama3.2, mistral-nemo, qwen2.5, and others). Models without tool-use support will still chat fine but won't proactively save memories.

---

## How it works

```
strides-ai/
└── strides_ai/
    ├── backends/
    │   ├── base.py    # BaseBackend ABC — label + stream_turn()
    │   ├── claude.py  # Anthropic SDK, tool_use loop
    │   └── ollama.py  # httpx → Ollama /api/chat, streaming + tools
    ├── auth.py        # Strava OAuth2 — token exchange, storage, auto-refresh
    ├── db.py          # SQLite — activities, conversation history, memories
    ├── sync.py        # Strava API pagination, incremental sync
    ├── profile.py     # Profile file template, loader
    ├── coach.py       # Backend-agnostic chat loop
    └── cli.py         # Entry point: auth → sync → backend selection → chat
```

**Data stored locally** in `~/.strides_ai/`:
- `profile.md` — your athlete profile (edit freely)
- `activities.db` — SQLite database (activities, conversation history, memories)
- `token.json` — Strava OAuth token (auto-refreshed when expired)

**Activity fields synced from Strava:** date, distance, moving time, elapsed time, average pace, average HR, max HR, elevation gain, cadence, suffer score, perceived exertion.

**Memory tool** — the coach calls `save_memory` mid-response to persist facts about you. Saved memories are injected into the system prompt on every future session. Example triggers: mentioning a goal race, describing an injury, stating a weekly mileage target.

---

## Stack

| Concern | Library |
|---|---|
| Strava API | `httpx` |
| Ollama API | `httpx` |
| Anthropic API | `anthropic` |
| Database | `sqlite3` (stdlib) |
| Terminal UI | `rich` |
| Config | `python-dotenv` |
