# strides-ai

A local AI multisport coach that connects to your Strava account and lets you have coaching conversations about your training. Supports Claude (via the Anthropic API) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full activity history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Multi-mode coaching** — switch between **Running**, **Cycling**, and **Hybrid** (multisport) modes. Each mode has its own coaching persona, filtered activity history, and separate conversation history and athlete profile.
- **Web UI** — a browser-based interface with a sidebar nav for chat, activities, training charts, calendar, profile editing, and settings.
- **Terminal chat** — a CLI alternative for coaching conversations directly in the terminal.
- **Athlete profile** — fill in your background, PBs, goals, injuries, and gear via the web UI. Profiles are per-mode (running vs. cycling), loaded fresh every session.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations. History is scoped per mode.
- **Training calendar** — plan upcoming workouts on a calendar, overlay your actual Strava activities, and get AI-powered nutrition recommendations per workout.
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

On first run, a browser window opens to Strava's authorization page — approve it and the token is saved locally.

---

## Web UI

`make dev` starts both the FastAPI backend (`:8000`) and the Vite frontend (`:5173`). Open `http://localhost:5173` in your browser.

| Tab | What it does |
|---|---|
| Coach | Streaming chat with your AI coach; conversation persists across sessions and is scoped to the active mode |
| Activities | Your full Strava history filtered by active mode — sortable, filterable, links to each activity on Strava |
| Charts | Training visualisations: weekly volume with 4-week rolling average, ATL/CTL fitness & fatigue curves, aerobic efficiency scatter plot |
| Calendar | Plan upcoming workouts, see actual Strava activities overlaid, and get AI nutrition advice per workout |
| Profile | Structured editor for your athlete profile (per-mode) |
| Settings | Switch between Running, Cycling, and Hybrid coaching modes |

The URL uses hash-based navigation (`#chat`, `#activities`, `#charts`, `#calendar`, `#profile`, `#settings`), so refreshing the page keeps you on the same tab.

To run only the backend: `make api`. To run only the frontend: `make web`.

---

## Coaching Modes

Switch between modes from the **Settings** tab. The active mode affects:

- **Activities shown** — Running shows runs only; Cycling shows rides only; Hybrid shows everything
- **Coaching persona** — the coach's framing, metrics, and terminology adapt to the sport
- **Conversation history** — each mode has its own separate history so advice stays contextually relevant
- **Athlete profile** — running and cycling profiles can be filled in independently

After switching modes, sync your activities with `POST /api/sync?full=true` if you haven't done a full sync before, to ensure all sport types are in the database.

---

## Training Calendar

The **Calendar** tab lets you plan upcoming workouts and see how your actual training lines up with the plan.

### Planned workouts

Click any date to open the detail panel below the calendar. If no workout exists for that day, you'll see an **Add Planned Workout** form with:

- **Type** — Easy Run, Long Run, Tempo Run, Intervals, Race, Cross-Training, or Rest
- **Distance** (km, optional)
- **Elevation** (m, optional) — used to improve nutrition estimates for hilly workouts
- **Duration** (minutes, optional)
- **Intensity** — easy, moderate, hard, or rest
- **Notes** — free-text goal or description for the session

Saved workouts appear as colour-coded badges on the calendar grid and are surfaced to the coach in every conversation (next 14 days), so the AI can factor your upcoming schedule into its advice.

### Strava activity overlay

Actual Strava activities appear on their calendar date as grey badges alongside any planned workout. Clicking a date shows the full activity stats (name, sport, distance, duration, pace or speed, avg HR, elevation gain) in the detail panel, making it easy to compare planned vs. actual.

### Nutrition advice

For any non-Rest planned workout, click **Get advice** in the detail panel to get AI-generated nutrition recommendations. The analysis uses your athlete profile and workout details (type, distance, elevation, duration, intensity) to return:

- **Calories** — pre-workout, during, and post-workout targets (kcal)
- **Hydration** — pre-workout, during, and post-workout fluid targets (ml)
- **Notes** — 2–3 sentences of practical advice tailored to the specific workout

Recommendations are cached per workout. Click **Refresh** to regenerate them (e.g. after editing the workout details).

---

## Athlete Profile

Your profile lives in the SQLite database, with a separate profile per mode (running, cycling). Edit it through the **Profile** tab in the web UI.

The profile includes fields relevant to each sport: personal background, experience, PBs or FTPs, goals, injuries, gear, and training preferences. It is loaded fresh on every request and sent to the coach as context.

---

## Backends

The `PROVIDER` env var controls which LLM is used for the coaching chat.

### Claude (default)

Uses the [Anthropic API](https://console.anthropic.com). Requires an API key.

```env
PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

# Optional: change the model (default: claude-sonnet-4-6)
CLAUDE_MODEL=claude-opus-4-6
```

Nutrition analysis uses `claude-haiku-4-5` for fast, cost-effective structured output regardless of the `CLAUDE_MODEL` setting.

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
│   ├── app.py      # FastAPI routes, SSE streaming for /api/chat
│   └── server.py   # uvicorn entry point (strides-ai-web)
├── backends/
│   ├── base.py     # BaseBackend ABC — stream_turn(system, input, on_token)
│   ├── claude.py   # Anthropic SDK, tool_use loop
│   └── ollama.py   # httpx → Ollama /api/chat, streaming + tools
├── auth.py         # Strava OAuth2 — token exchange, storage, auto-refresh
├── db.py           # SQLite — activities, history, memories, profiles, calendar
├── sync.py         # Strava API pagination, incremental sync (runs + rides)
├── profile.py      # Profile fields — defaults per mode, serialization
├── schedule.py     # Nutrition analysis — Claude Haiku, structured JSON output
├── coach.py        # System prompt assembly, training log formatting, CLI chat loop
└── cli.py          # CLI entry point: auth → sync → backend → chat
web/
└── src/pages/
    ├── Chat.tsx        # Streaming chat UI, mode-aware history
    ├── Activities.tsx  # Strava activity table, mode-filtered
    ├── Charts.tsx      # Weekly volume, ATL/CTL, aerobic efficiency
    ├── Calendar.tsx    # Planned workouts, Strava overlay, nutrition advice
    ├── Profile.tsx     # Athlete profile editor (per-mode)
    └── Settings.tsx    # Mode selector (Running / Cycling / Hybrid)
```

**Data stored locally** in `~/.strides_ai/`:
- `activities.db` — SQLite database (activities, conversation history, memories, profiles, calendar plan)
- `token.json` — Strava OAuth token (auto-refreshed when expired)
- `uploads/` — image attachments sent in chat

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
| Charts | Recharts |
