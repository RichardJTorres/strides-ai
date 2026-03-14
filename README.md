# strides-ai

A local AI multisport coach that connects to your Strava account and lets you have coaching conversations about your training. Supports Claude, Gemini, and ChatGPT (cloud APIs) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full activity history into a local SQLite database. Incremental sync on every startup keeps it current.
- **Multi-mode coaching** — switch between **Running**, **Cycling**, and **Hybrid** (multisport) modes. Each mode has its own coaching persona, filtered activity history, and separate conversation history and athlete profile.
- **Web UI** — a browser-based interface with a sidebar nav for chat, activities, training charts, calendar, profile editing, and settings.
- **Terminal chat** — a CLI alternative for coaching conversations directly in the terminal.
- **Athlete profile** — fill in your background, PBs, goals, injuries, and gear via the web UI. Profiles are per-mode (running vs. cycling), loaded fresh every session.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations. History is scoped per mode.
- **Training calendar** — plan upcoming workouts on a calendar, overlay your actual Strava activities, and get AI-powered nutrition recommendations per workout.
- **Swappable backends** — run Claude, Gemini, or ChatGPT in the cloud, or a local model via Ollama. Switch providers live from the Settings tab without restarting the server.
- **Run analysis pipeline** — every synced activity is automatically enriched with derived fitness metrics (cardiac decoupling, HR zone distribution, pace fade, cadence consistency, effort efficiency) and a natural language summary. The Activities tab shows colour-coded metric badges and an on-demand Deep Dive button that generates a full LLM coaching analysis for any individual run.

## Setup

### 1. Prerequisites

- Python 3.11+
- Node.js 18+ (for the web UI)
- A [Strava API app](https://www.strava.com/settings/api) — set **Authorization Callback Domain** to `localhost`
- An Anthropic API key, a Google Gemini API key, an OpenAI API key, **or** a local [Ollama](https://ollama.com) installation (see [Backends](#backends) below)

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
| Activities | Your full Strava history filtered by active mode — sortable, filterable, analysis badges, Deep Dive button |
| Charts | Training visualisations: weekly volume with 4-week rolling average, ATL/CTL fitness & fatigue curves, aerobic efficiency scatter plot |
| Calendar | Plan upcoming workouts, see actual Strava activities overlaid, and get AI nutrition advice per workout |
| Profile | Structured editor for your athlete profile (per-mode) |
| Settings | Switch between Running, Cycling, and Hybrid coaching modes; switch LLM provider |

The URL uses hash-based navigation (`#chat`, `#activities`, `#charts`, `#calendar`, `#profile`, `#settings`), so refreshing the page keeps you on the same tab.

To run only the backend: `make api`. To run only the frontend: `make web`.

---

## Coaching Modes

Switch between modes from the **Settings** tab. The active mode affects:

- **Activities shown** — Running shows runs only; Cycling shows rides only; Hybrid shows everything
- **Coaching persona** — the coach's framing, metrics, and terminology adapt to the sport
- **Conversation history** — each mode has its own separate history so advice stays contextually relevant
- **Athlete profile** — running and cycling profiles can be filled in independently

After switching modes for the first time, use the **Full Sync** button in the **Settings** tab to fetch your complete Strava history and ensure all sport types are in the database.

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

### Gemini

Uses the [Google Gemini API](https://aistudio.google.com/apikey). Get a free API key from Google AI Studio.

```env
PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key

# Optional: change the model (default: gemini-2.0-flash)
GEMINI_MODEL=gemini-2.5-pro
```

### ChatGPT (OpenAI)

Uses the [OpenAI API](https://platform.openai.com/api-keys). Requires an API key.

```env
PROVIDER=openai
OPENAI_API_KEY=sk-...

# Optional: change the model (default: gpt-4o)
OPENAI_MODEL=gpt-4o-mini
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

## Run Analysis Pipeline

Every activity synced from Strava is automatically analysed using time-series stream data (heartrate, velocity, cadence, altitude). Results are stored as flat columns on each activity record and surfaced in the Activities tab and to the AI coach.

### Computed metrics

| Metric | Description | Threshold |
|---|---|---|
| **Cardiac decoupling %** | Aerobic efficiency — how much the HR/pace ratio drifts across the run | <5% excellent, 5–10% acceptable, >10% high stress |
| **HR zones (Z1–Z5)** | Time distribution across HR intensity zones (based on `max_hr` setting, default 190) | Z1 recovery, Z2 aerobic, Z3 tempo, Z4 threshold, Z5 VO2max |
| **Pace fade (sec/mile)** | Last-third avg pace minus first-third avg pace | Positive = slowing, negative = negative split |
| **Cadence avg / std dev** | Mean and variability of step rate (spm for runs, rpm for rides) | — |
| **Effort efficiency score** | 0–100, normalized across athlete history; higher = better pace for a given HR | — |
| **Elevation per mile** | Total elevation gain in ft/mile; flags hilly courses (>100 ft/mile) | — |
| **Suffer score validation** | Cross-checks Strava's suffer score against computed HR zone distribution | Flags potential HR sensor issues |

### Analysis summary

After computing metrics, a short rule-based natural language summary is generated (no LLM call, no cost). Example:

> _"Strong aerobic run — 3.2% cardiac decoupling. 81% time in Z1/Z2. Pace held steady throughout."_

This summary appears as a subtitle under the activity name in the Activities tab and as an ANALYSIS column in the training log the coach reads.

### Configuring max HR

The HR zone thresholds use `max_hr` from the settings table (default 190 bpm). To set your actual max HR, use the Strava API or set it via a future settings UI. The DB key is `max_hr`.

### Backfilling existing activities

On every sync, the pipeline also backfills up to 10 activities that were previously synced without analysis. To trigger a full backfill:

```bash
# From Settings tab — use the "Full Sync" button
# Or via API:
curl -X POST "http://localhost:8000/api/sync?full=true"
```

Rate limits are handled gracefully: if Strava returns 429, remaining activities are marked `analysis_status='pending'` and retried on the next sync.

### Deep Dive

Click **Deep Dive** on any activity row to generate a detailed LLM coaching analysis for that specific run. The deep dive:

1. Fetches the full time-series stream from Strava
2. Downsamples to 60-second intervals plus key inflection points (pace surges, HR spikes)
3. Sends to the active LLM backend (Claude, Gemini, Ollama, or ChatGPT) with a coaching analysis prompt
4. Returns a 4–6 paragraph analysis covering pacing strategy, HR drift, cadence patterns, elevation impact, and actionable coaching notes

Results are cached — clicking the button again shows the saved report instantly. Use **Regenerate** to force a fresh analysis.

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
│   ├── gemini.py   # Google Gemini SDK, function calling loop
│   ├── openai.py   # OpenAI SDK, streaming + tool calling loop
│   └── ollama.py   # httpx → Ollama /api/chat, streaming + tools
├── analysis.py     # Stream fetching, metric computation, NL summary, deep-dive formatting
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
| Gemini API | `google-genai` |
| OpenAI API | `openai` |
| Ollama API | `httpx` |
| Web framework | `fastapi` + `uvicorn` |
| Database | `sqlite3` (stdlib) |
| Terminal UI | `rich` |
| Config | `python-dotenv` |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Charts | Recharts |
