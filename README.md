# strides-ai

A local AI running coach that connects to your Strava account and lets you have coaching conversations about your training. Supports Claude (via the Anthropic API) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full run history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Terminal chat** — ask your coach anything about your training: pacing, volume trends, race prep, recovery, injury prevention. Your complete activity log is included as context on every message.
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

On first run, a browser window opens to Strava's authorization page. After you approve, the token is saved locally and all subsequent runs skip this step.

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
    ├── coach.py       # Backend-agnostic chat loop
    └── cli.py         # Entry point: auth → sync → backend selection → chat
```

**Data stored locally** in `~/.strides_ai/`:
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
