# strides-ai

A local AI running coach that connects to your Strava account and lets you have coaching conversations about your training — powered by Claude.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full run history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Terminal chat** — ask Claude anything about your training: pacing, volume trends, race prep, recovery, injury prevention. Your complete activity log is included as context on every message.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations.

## Setup

### 1. Prerequisites

- Python 3.11+
- A [Strava API app](https://www.strava.com/settings/api) — set **Authorization Callback Domain** to `localhost`
- An [Anthropic API key](https://console.anthropic.com)

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

Edit `.env` with your credentials:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
ANTHROPIC_API_KEY=sk-ant-...
```

### 4. Run

```bash
strides-ai
```

On first run, a browser window opens to Strava's authorization page. After you approve, the token is saved locally and all subsequent runs skip this step.

## How it works

```
strides-ai
├── strides_ai/
│   ├── auth.py    # Strava OAuth2 — token exchange, storage, auto-refresh
│   ├── db.py      # SQLite — activities, conversation history, memories
│   ├── sync.py    # Strava API pagination, incremental sync
│   ├── coach.py   # Claude chat loop with tool use for memory saving
│   └── cli.py     # Entry point: auth → sync → chat
```

**Data stored locally** in `~/.strides_ai/`:
- `activities.db` — SQLite database with all tables
- `token.json` — Strava OAuth token (auto-refreshed when expired)

**Activity fields synced from Strava:** date, distance, moving time, elapsed time, average pace, average HR, max HR, elevation gain, cadence, suffer score, perceived exertion.

**Memory tool** — Claude can call `save_memory` mid-response to persist facts about you. Saved memories are injected into the system prompt on every future session. Example triggers: mentioning a goal race, describing an injury, stating a weekly mileage target.

## Stack

| Concern | Library |
|---|---|
| Strava API | `httpx` |
| Database | `sqlite3` (stdlib) |
| LLM | `anthropic` (claude-sonnet-4-6) |
| Terminal UI | `rich` |
| Config | `python-dotenv` |
