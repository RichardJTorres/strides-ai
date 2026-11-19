# Strides AI

A self-hosted AI endurance coach. Strides AI pulls your activity history from Strava (and,
optionally, your lifting sessions from HEVY) into a local SQLite database, analyses every
activity, and gives you a coach you can chat with. The coach can see your training, remember
what you tell it, and write workouts straight onto your training calendar.

It runs on your own machine. You bring the API keys: Claude (default), Gemini or ChatGPT in
the cloud, or any model you run locally with Ollama.

> **New here?** Start with the [Getting Started guide](docs/getting-started.md), then work
> through the [Tutorial](docs/tutorial.md).

## Features

- **Coach chat.** A streaming conversation with a coach that sees your profile, your recent
  activities, your training load and your upcoming calendar. It can look up anything else in
  your history on its own (for example "my longest ride this year"). Each coaching mode keeps
  its own conversation.
- **Training calendar.** Plan workouts, races, rest days and travel. Ask the coach to plan a
  block, or use **Generate block** and review the proposal before it is saved. Planned workouts
  are matched against your Strava activities, so each one shows as completed, shortened or
  missed.
- **Activity analysis.** Every synced activity gets computed metrics: HR zones, pace fade,
  cardiac decoupling (only where it is meaningful), climbing ratio and an efficiency score,
  plus a short rule-based summary. A **Deep Dive** asks the LLM for a full write-up of one
  session.
- **Analytics.** Charts for weekly volume, fitness and fatigue (CTL/ATL) and efficiency, an AI
  **Insights** readout of the last four weeks, and a **Progress** view with your plan streak and
  personal records.
- **Athlete profile and memories.** One profile (goals, availability, injuries, max HR,
  per-sport background) is shared by every mode. The coach saves facts it learns as
  **memories**, which you can edit, date or delete. It can also propose profile edits, and
  nothing is saved until you accept them.
- **Planning helpers.** Nutrition advice per workout, route checks for Strava and RideWithGPS
  routes, and `.zwo` export of structured indoor rides for Zwift.
- **Coaching modes.** Running, Cycling, Hybrid (running and cycling) and Lifting (HEVY). The
  mode chooses which activities the coach focuses on and how it talks about them.
- **Metric or imperial.** Everything is stored once in SI units and converted for display and
  for the coach.
- **Usage tracking.** Settings shows the tokens used and the estimated cost of every LLM call.

## Quick start

Prerequisites: Python 3.11+, Node.js 18+, a [Strava API application](https://www.strava.com/settings/api),
and an API key for one LLM provider (or a running Ollama install).

```bash
git clone https://github.com/RichardJTorres/strides-ai.git
cd strides-ai
cp .env.example .env      # add your Strava credentials and an LLM key
make install
make dev                  # API on :8000, web UI on :5173
```

Open <http://localhost:5173>, go to **Activities** and click **Sync Activities** to connect Strava. The
[Getting Started guide](docs/getting-started.md) covers each step, including creating the
Strava app.

## Documentation

| Document | What it covers |
|---|---|
| [Getting Started](docs/getting-started.md) | Installing, configuring, connecting Strava, the first sync, troubleshooting |
| [Tutorial](docs/tutorial.md) | The main workflows: chatting with the coach, building a plan, reviewing activities, tracking progress |
| [CLAUDE.md](CLAUDE.md) | Detailed architecture notes for contributors (and for AI coding agents) |

## Configuration

All configuration is in `.env`. See [`.env.example`](.env.example) for a commented template.

| Variable | Required | Purpose |
|---|---|---|
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` | Yes | Your Strava API application |
| `PROVIDER` | No | LLM provider: `claude` (default), `gemini`, `openai` or `ollama`. It applies until you pick a provider in **Settings**. From then on the saved choice wins. |
| `ANTHROPIC_API_KEY` | For Claude | |
| `GEMINI_API_KEY` | For Gemini | |
| `OPENAI_API_KEY` | For ChatGPT | |
| `OLLAMA_HOST` | No | Ollama address, default `http://localhost:11434` |
| `CLAUDE_MODEL` / `GEMINI_MODEL` / `OPENAI_MODEL` / `OLLAMA_MODEL` | No | Starting model per provider. Claude defaults to `claude-sonnet-4-6`, OpenAI to `gpt-4o`, and Gemini and Ollama to the first model the provider lists. You can also pick a model in **Settings**. |
| `THINKING_EFFORT` | No | `off`, `low`, `medium` (default) or `high`: how much the model reasons on each chat turn |
| `HEVY_API_KEY` | For Lifting mode | Requires a HEVY Pro subscription |
| `CHAT_LIMITS` | No | JSON overrides for per-turn limits (see [Advanced: chat limits](#advanced-chat-limits)) |
| `PORT` | No | API port, default `8000`. The Vite dev proxy always targets `localhost:8000`, so with `make dev` the UI only works if you leave this as 8000. |
| `STRIDES_DATA_DIR` | No | Where local data lives, default `~/.strides_ai` |

### LLM providers

| Provider | Notes |
|---|---|
| **Claude** (default) | Key from the [Anthropic Console](https://console.anthropic.com). The cost estimates in Settings cover Claude models only. |
| **Gemini** | Key from [Google AI Studio](https://aistudio.google.com/apikey). |
| **ChatGPT** | Key from the [OpenAI platform](https://platform.openai.com/api-keys). |
| **Ollama** | No key. Run Ollama and pull a model that supports tool calling (for example `llama3.1` or `qwen2.5`). Small local models follow coaching instructions and tool calls much less reliably than the cloud models. |

At startup the server checks that the key for `PROVIDER` is set (Ollama needs none). Every AI
feature (chat, plan generation, deep dives, Insights, route checks, nutrition advice) uses the
provider and model selected in Settings. Image and file attachments in chat need Claude.
Attaching an activity works with every provider.

## Your data

Everything is stored locally in `~/.strides_ai/` (or `STRIDES_DATA_DIR`):

| Path | Contents |
|---|---|
| `activities.db` | SQLite: activities and their analysis, chat history, memories, profile, calendar, settings, usage log |
| `token.json` | Your Strava OAuth token (refreshed automatically) |
| `uploads/` | Files you attach in chat |
| `backups/` | Database backups some migrations write before they change data |

Strides AI has no server of its own. Your data goes to Strava and HEVY (to fetch activities) and
to the LLM provider you pick. Each chat turn sends your profile, memories, recent training and
calendar to that provider. Ollama keeps everything on your machine.

## Architecture

```
web/ (React + Vite, :5173)
   │  /api, /uploads (proxied in dev)
   ▼
strides_ai/
   ├── api/                           FastAPI app (:8000): app.py, routers/ (one per area), chat-turn coordination
   ├── coach.py, context_builder.py   build the coach's system prompt for each turn
   ├── backends/                      Claude, Gemini, OpenAI, Ollama behind one BaseBackend
   │      └── tools: save_memory, update_profile, update_training_plan
   │                 + read-only lookups (lookup_tools.py)
   ├── sources/                       Strava, HEVY, route providers
   ├── analysis.py, hevy_analysis.py  per-activity metrics, deep dives
   ├── training_state.py              load (CTL/ATL), ramp, typical week
   ├── compliance.py, progress.py     plan vs. actual, streak, records
   ├── insights.py, plan_generation.py
   └── db/                            SQLModel + Alembic, SQLite in ~/.strides_ai
```

**How a chat turn works.** The frontend posts your message to `/api/chat`, which streams the
reply back over server-sent events. For every turn the server rebuilds the system prompt from
your profile, protected and ranked memories, training state, upcoming workouts, recent
activities and summaries of older ones. When the prompt is too large for the model, it drops
the lowest-priority sections first and says what it left out. The model can call tools in a
bounded loop: it can save a memory, propose a profile change, change the calendar (one atomic
change set per call, checked against training-load guardrails), or look things up in your full
history. Each turn stores a receipt of what it changed and why it stopped.

**Data flow.** Syncing pulls new Strava activities, fetches each one's streams and computes its
metrics. Everything the UI and the coach show (load, compliance, streaks, records) is computed
from that one database with deterministic code. The LLM interprets those figures but never
produces them.

[CLAUDE.md](CLAUDE.md) documents each subsystem in depth: units, calendar invariants, context
budgeting, the turn record and the usage log.

### Project layout

```
strides_ai/          Python package (FastAPI app, backends, analysis, db)
  api/routers/       HTTP endpoints by area (chat, calendar, activities, charts, …)
  backends/          LLM provider adapters, model capability lookup, pricing
  db/                SQLModel models and data-access modules
  analytics/         chart datasets
  sources/           Strava, HEVY, RideWithGPS / Strava routes
alembic/             database migrations (run automatically on startup)
web/src/             React frontend
  pages/             one folder or file per tab (calendar/, profile/, charts/, Chat.tsx, …)
  ui/                shared components (Button, Modal, states, theme, api helpers)
  charts/, progress/ Analytics and streak/record components
scripts/             context_report.py, replay_chat.py (developer tools)
tests/               pytest suite and shared fixtures
docs/                user guides and feature specs
```

## Development

```bash
make install   # venv + Python deps + Node deps + pre-commit hook (idempotent)
make dev       # API (:8000) and Vite (:5173) together; Ctrl+C stops both
make api       # API only
make web       # frontend only
make test      # pytest, then the frontend tests (npm test)
```

- Python changes need a server restart. Vite hot-reloads frontend changes.
- Run the API as a **single process**. Chat-turn coordination is in-memory.
- Formatting: Black, `line-length = 100`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/). The pre-commit
  hook runs `make test`.
- Database migrations live in `alembic/versions/` and run automatically when the server starts.

Developer tools:

```bash
.venv/bin/python scripts/context_report.py --mode hybrid   # what the coach's prompt would contain, offline
```

`scripts/replay_chat.py` replays ten fixed coach questions against a copy of your database
with a real provider. It costs real money (about $2), so it requires `--confirm-cost`.

### Advanced: chat limits

Each chat turn is bounded: a few tool rounds followed by a closing reply, plus output and time
ceilings derived from the model's context window and maximum output. When a turn hits a limit,
the coach still replies, the app shows a notice saying why the turn stopped, and anything the
turn already saved is listed. `CHAT_LIMITS` overrides the limits, keyed by `default`, a provider
name or an exact backend label:

```dotenv
CHAT_LIMITS={"default":{"tool_rounds":3},"ollama":{"round_max_tokens":2000,"context_window":8192}}
```

Valid keys are `round_max_tokens`, `reply_reserve`, `turn_output_ceiling`, `context_target`,
`input_ceiling`, `context_window`, `tool_rounds`, `tools`, `retries`, `history_messages`,
`recent_activities`, `first_event_s`, `stream_idle_s`, `round_deadline_s`, `reply_deadline_s`
and `turn_deadline_s`. An unknown key stops the server at startup. A value beyond what the model
supports is clamped, with a warning in the log. The per-turn record of what was sent is at
`GET /api/chat/turns/{id}/budget`.

## Stack

FastAPI, SQLModel/SQLite, Alembic, httpx, and the `anthropic`, `google-genai` and `openai`
SDKs on the backend. React 18, TypeScript, Tailwind CSS, Vite and Recharts on the frontend.
