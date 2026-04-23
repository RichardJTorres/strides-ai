# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install everything
make install          # creates .venv and installs Python + Node deps

# Development (both processes)
make dev              # starts API on :8000 + Vite frontend on :5173

# Individual processes
make api              # FastAPI only (uvicorn, :8000)
make web              # Vite dev server only (:5173)

# Tests & formatting
make test             # runs pytest tests/ -v
```

`make install` is idempotent — it uses file-based Make targets (`$(VENV)/bin/activate`, `web/node_modules`) so it only re-runs what's stale. It also installs pre-commit hooks; the hook runs `make test` on every commit.

**Formatting:** Black with `line-length=100`, `target-version=py311`. No linter beyond that.

There is no CLI entry point — the package only exposes `strides-ai-web` → `strides_ai/api/server.py:main`.

## Git Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages:

```
<type>[optional scope]: <description>
```

Common types: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`.

Examples:
- `feat(calendar): add nutrition advice for planned workouts`
- `fix(db): handle missing elevation_m column on existing installs`

## Architecture

### Two interfaces, one shared backend

```
strides-ai-web  (Web)  →  api/app.py  →  deps.py (backend init)  ─┐
                                                                    ├─→  backends/{claude,gemini,openai,ollama}.py
                                                                    └─→  db/ / profile.py / sync.py
```

The Python package has one entry point (`pyproject.toml`): `strides-ai-web` → `strides_ai/api/server.py:main`.

### LLM backends (`strides_ai/backends/`)

`BaseBackend` (ABC) defines two methods:
- `stream_turn(system, user_input, on_token, attachments) → (text, memories)` — stateful; appends to `self._history`. Handles `save_memory` tool calls in a loop until the model stops.
- `stateless_turn(system, user_input, on_token) → text` — one-shot, no history. Used for activity deep-dive analysis.

Select backend with `PROVIDER=claude` (default), `PROVIDER=gemini`, `PROVIDER=openai`, or `PROVIDER=ollama`.

### System prompt assembly (`strides_ai/coach.py`)

On every turn `build_system()` assembles: mode-specific base prompt → current date/time → athlete profile text → coaching memories → upcoming planned workouts (next 14 days) → recent activities training log (last 30, `RECENT_ACTIVITIES_IN_SYSTEM`).

At session start, `build_initial_history()` seeds the full activity log (all activities) as the first exchange in `_history`, so older runs are accessible even though the system prompt only carries the 30 most recent. Last 40 messages (`RECALL_MESSAGES`) from the DB are appended after.

### Conversation persistence

- **Conversation history**: last 40 messages stored in SQLite, re-injected at session start.
- **Memories**: structured facts (category + content) saved by LLM tool calls, always injected into system prompt.
- **Profile**: JSON fields in `profiles` table, keyed by mode (`running`, `cycling`, `hybrid`, `personal`). `personal` fields are merged into every mode. Read fresh each request.

All local data lives in `~/.strides_ai/` (`activities.db`, `token.json`, `uploads/`).

### Coaching modes

Three separate system prompts and DB rows per mode. Activities filtered by `sport_type`: `RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}`, `CYCLE_TYPES = {"Ride", "VirtualRide", "GravelRide"}`. Hybrid shows all. Conversation history and profile are also mode-scoped.

### Web API (`strides_ai/api/app.py`)

FastAPI app; a single backend instance is created at startup via FastAPI's lifespan context manager (`deps.py`). `/api/chat` is SSE — a sync `stream_turn` thread writes tokens into a `queue.SimpleQueue`, which an async generator drains. The frontend parses `data:` lines and a `[MEMORIES]` sentinel sent after the full response.

The Vite dev server proxies `/api` and `/uploads` → `localhost:8000` (`web/vite.config.ts`), so no CORS issues in dev.

### Analysis pipeline (`strides_ai/analysis.py`)

Two stages:
1. **Metric computation** (run automatically on sync): fetches Strava streams (heartrate, velocity, cadence, altitude), computes cardiac decoupling %, HR zone distribution (Z1–Z5), pace fade, cadence std dev, effort efficiency score (0–100), and elevation flags. Writes results back to the `activities` table. Produces a rule-based NL summary (no LLM) stored as `analysis_summary`.
2. **Deep dive** (on-demand via `/api/activities/{id}/deep-dive`): calls `backend.stateless_turn()` with downsampled stream data (60-sec intervals + inflection points). Result cached in `deep_dive_report`; re-triggerable.

Sync backfills up to 10 pending/unanalyzed activities per cycle. Strava 429 responses mark activities `analysis_status='pending'` for retry.

### Calendar feature (`strides_ai/db/calendar.py`, `strides_ai/schedule.py`)

Planned workouts stored in `training_plan` table (date PK, type, distance, duration, intensity, notes). Frontend overlays actual Strava activities alongside plans. Nutrition advice is generated per-workout by a separate `stateless_turn` call (Claude Haiku by default via `schedule.py`), returning structured JSON (calories pre/during/post, hydration, notes). Results are cached; can be regenerated.

### Strava sync (`strides_ai/sync.py`)

Incremental by default — stops at the first activity ID already in the DB. Full sync re-fetches all pages. Cadence is doubled (Strava sends half-cadence). Pace derived: `moving_time_s / (distance_m / 1000)`. OAuth2 in `auth.py` — tokens stored in `~/.strides_ai/token.json`, auto-refreshed.

### Required environment variables (`.env`)

| Variable | Required for |
|---|---|
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | All modes |
| `ANTHROPIC_API_KEY` | `PROVIDER=claude` (default) |
| `GEMINI_API_KEY` | `PROVIDER=gemini` |
| `OPENAI_API_KEY` | `PROVIDER=openai` |
| `OLLAMA_MODEL` | `PROVIDER=ollama` |
| `OLLAMA_HOST` | `PROVIDER=ollama` (default: `http://localhost:11434`) |
| `CLAUDE_MODEL` | Optional; defaults to `claude-sonnet-4-6` |
| `GEMINI_MODEL` | Optional; defaults to `gemini-2.0-flash` |
| `PORT` | Optional; defaults to `8000` |

Copy `.env.example` to `.env` to get started.

### Frontend (`web/`)

React 18 + TypeScript + Tailwind CSS + Vite + recharts. Navigation uses `location.hash` (`#chat`, `#activities`, `#charts`, `#calendar`, `#profile`, `#settings`) — no router dependency. Vite HMR picks up React changes instantly; Python changes require a server restart.

File attachments (images as base64, text as UTF-8) are uploaded to `~/.strides_ai/uploads/` and forwarded to `stream_turn` as `attachments`.
