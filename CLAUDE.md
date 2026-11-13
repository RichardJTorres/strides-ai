# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working Style

- **Work from a queue.** Treat all work as a queue of todos. When I propose tweaks, changes or corrections, append them to the queue — do not break the queue to suddenly prioritize my correction. Only stop when 100% of the queue is truly clear.
- **Mistakes are not your fault; don't apologize.** You are an LLM. A mistake always means a gap or issue in the instruction files. Describe which problem in the instruction files caused the mistake and suggest the fix. Be solution oriented.
- **YAGNI.** Don't overengineer. Never expand scope without permission, but do suggest possible scope improvements when they make sense. All work must be justifiable. Assess where the project sits on the scale from "quick and dirty" to "production grade" and scale the amount of engineering to match.
- **Fresh-eyes review.** Always spin up a sub agent with minimal context, using a cheap model, whose job is to review your changes and sus out possible problems.

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
make test             # runs pytest tests/ -v, then the frontend tests (cd web && npm test)
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
- `stream_turn(system, user_input, on_token, attachments) → (text, memories, plan_changes)` — stateful; appends to `self._history`. Handles `save_memory` and `update_training_plan` tool calls in a loop until the model stops. `update_training_plan` lets the coach create (a `set` item without `id`), patch (a `set` item with the entry `id` shown in its prompt) or remove (`delete` of ids) calendar entries — workouts, races, rest, travel — applied as one atomic change set; the result names the id of every entry it created. Used to generate a training block or change part of one.
- `stateless_turn(system, user_input, on_token) → text` — one-shot, no history, no tools. Used for activity deep-dive analysis.

Select backend with `PROVIDER=claude` (default), `PROVIDER=gemini`, `PROVIDER=openai`, or `PROVIDER=ollama`.

### System prompt assembly (`strides_ai/coach.py`)

On every turn `build_system()` assembles: mode-specific base prompt → units section (the athlete's `unit_system`) → current date/time → athlete profile text → coaching memories → calendar constraints (upcoming races (race entries, with goal time and priority) and blocked-out days from `calendar_prefs`) → upcoming calendar entries (next `PLANNED_WORKOUTS_WINDOW_DAYS` days, default 60, each with its entry id; the next `WORKOUT_DETAIL_DAYS` also carry the athlete's notes and route-fit verdict) → training state, with the Analytics digest's deterministic flags and, when fresh, the cached readout → streak and new records (`progress.py`) → recent activities training log (last 30, `RECENT_ACTIVITIES_IN_SYSTEM`).

At session start, `build_initial_history()` seeds the full activity log (all activities) as the first exchange in `_history`, so older runs are accessible even though the system prompt only carries the 30 most recent. Last 40 messages (`RECALL_MESSAGES`) from the DB are appended after.

### Per-turn record (`strides_ai/turn_record.py`)

Every chat turn stores what it sent and why it stopped in `chat_turns.budget_json`: context section sizes and whether each was sent, retained history, per-round sizes and timings, retries, stop reason. Sizes and timings only, never content. `TurnBudget` owns a `TurnRecord` and feeds it from `request()` / `usage()` / `tool()`; `prepare_turn` leaves the admission facts on `backend._admission`; the coordinator stores the record on success and failure. Read it at `GET /api/chat/turns/{id}/budget` (deliberately not part of `/chat/active`). `scripts/context_report.py --mode <mode>` runs the same assembly and admission offline. Section names come from `ContextPrompt.priority_keys` / `activity_keys`, so a new context section needs a key in `build_system`.

### What a turn changed: mutation log, receipt, notice (`strides_ai/db/mutations.py`, `strides_ai/turn_notice.py`)

Every change a chat turn makes is logged in `chat_turn_mutations` in the **same transaction** as the change (`calendar.apply_changes` and `memories.save` take `turn_id`; the coordinator sets `backend.turn_id`). A profile proposal is logged as `pending` (nothing is saved until the athlete accepts it). `build_receipt(session, turn_id)` is the only source of the receipt, stored in `conversations.receipt_json`; `conversations.notice` holds how the turn ended (`truncated`, `limit`, `failed`, `interrupted`). Both are kept out of `content`, which holds only the model's words. Wording lives in `turn_notice.py` and is rendered on read: `/api/history` returns `notice_text` / `receipt_text` (the receipt only when there is a notice), the stream sends `[NOTICE]`, and `build_initial_history` replays a notice as `[App note: …]` after the reply. `recover_interrupted_turns` builds the receipt from the log for turns a restart left running. Backends set `self._budget.notice` instead of appending text to the reply.

### Conversation persistence

- **Conversation history**: last 40 messages stored in SQLite, re-injected at session start.
- **Memories**: structured facts (category + content) saved by LLM tool calls, always injected into system prompt.
- **Profile**: one unified athlete profile shared by every mode (`strides_ai/profile.py`), stored as one JSON row per section in the `profiles` table: `shared` (personal, goals, availability, injuries, nutrition, notes, `coach_voice`) plus `running` / `cycling` / `lifting` (since, volume, focus, background, bests, gear). A mode only picks which discipline sections the coach sees in full (`DISCIPLINES_BY_MODE`; hybrid = running + cycling); other disciplines are summarised under "Also trains". Edited per section via `PUT /api/profile/{section}` (merge, never whole-document overwrite). Max HR lives only in `personal.max_hr` (`db.get_max_hr()`). Races are race entries on the calendar, not part of the profile. The coach proposes edits with the `update_profile` tool; nothing is written until the athlete accepts the `[PROFILE_PROPOSAL]` card in chat. `alembic/versions/012` converts legacy per-mode rows (kept as `legacy:<name>`). Read fresh each request.

All local data lives in `~/.strides_ai/` (`activities.db`, `token.json`, `uploads/`).

### Coaching modes

Separate system prompts and conversation history per mode (the profile is shared). Activities filtered by `sport_type`: `RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}`, `CYCLE_TYPES = {"Ride", "VirtualRide", "GravelRide"}`. Hybrid shows all. Conversation history is also mode-scoped; the profile is not.

### Web API (`strides_ai/api/app.py`)

FastAPI app; a single backend instance is created at startup via FastAPI's lifespan context manager (`deps.py`). `/api/chat` is SSE — a sync `stream_turn` thread writes tokens into a `queue.SimpleQueue`, which an async generator drains. The frontend parses `data:` lines and a `[MEMORIES]` sentinel sent after the full response.

The Vite dev server proxies `/api` and `/uploads` → `localhost:8000` (`web/vite.config.ts`), so no CORS issues in dev.

### Units (`strides_ai/units.py`, `web/src/units.ts`)

Every stored measurement is SI-based: meters, s/km, m/km, kg, ml (`distance_km` on `WorkoutDetail` and `RaceDetail` is the one km column). Nothing is ever stored in the athlete's display units. The `unit_system` setting (`metric` default | `imperial`, `settings` table, `GET/PUT /api/settings`) only controls display and what the coach is told.

- **Registry** — `units.py` defines `UnitSystem`, `Quantity` (one per canonical unit) and `convert` / `to_si` / `format_value`. All conversion goes through it; don't hand-roll `/ 1000` or `* 3.28`.
- **Models** — `MeasuredModel` (`db/models.py`): each model declares `__measurements__ = {field: (Quantity, scale)}` and gets `measurement(field, system)` / `measurements(system)`, plus `Model.measure_field(row_dict, ...)` for the plain dicts the formatters pass around. A new measured column = one declaration line.
- **Cascade** — routers resolve the setting once per request (`Depends(get_units)` in `api/deps.py`) and pass `units: UnitSystem` explicitly through every formatter and prompt builder (coach, modes, compliance, plan generation, route analysis, nutrition, deep dives). The system prompt is rebuilt every turn, so a switch takes effect on the next message; stored chat messages keep their original units.
- **LLM input** — `update_training_plan` and plan generation take `distance`/`elevation` in the athlete's units (plus `distance_unit`/`elevation_unit` on the tool) and normalize to SI server-side; legacy `distance_km`/`elevation_m` still work.
- **Profile body measurements** — `personal.height_cm` / `personal.weight_kg` are numbers (`Quantity.HEIGHT` shows ft + in in imperial). Older free-text `height`/`weight` is parsed on read by `body_metrics.normalize_personal()` (called from `db/profiles.get_fields`); unparseable text is kept in `personal.body_notes`.
- **`analysis_summary`** is deterministic, so `render_analysis_summary(row, units)` rebuilds completed summaries on read in the current units.
- **Frontend** — `units.ts` mirrors the registry; `UnitsContext` (`useUnits()`) is seeded from `/api/settings` in `App.tsx` and re-renders every consumer when the Settings page switches it. `tests/fixtures/unit_cases.json` is asserted by both `tests/test_units.py` and `web/units.test.mjs` (`npm test`) so the two can't drift.

### Analysis pipeline (`strides_ai/analysis.py`)

Two stages:
1. **Metric computation** (run automatically on sync): fetches Strava streams (heartrate, velocity, cadence, altitude), computes cardiac decoupling %, HR zone distribution (Z1–Z5), pace fade, cadence std dev, effort efficiency score (0–100), and elevation flags. Writes results back to the `activities` table. Produces a rule-based NL summary (no LLM) stored as `analysis_summary`.
2. **Deep dive** (on-demand via `/api/activities/{id}/deep-dive`): calls `backend.stateless_turn()` with downsampled stream data (60-sec intervals + inflection points). The prompt also carries the planned workout for that day and how it was scored (`activity_context.planned_workout_block`), so the report can judge the session against its intent. Result cached in `deep_dive_report`; re-triggerable.

Sync backfills up to 10 pending/unanalyzed activities per cycle. Strava 429 responses mark activities `analysis_status='pending'` for retry.

### Calendar feature (`strides_ai/db/calendar.py`, `strides_ai/kinds.py`, `strides_ai/schedule.py`)

The calendar is a list of **entries** (`calendar_entry`: `id`, `date`, `kind`, `title`, `notes`). `kind` is `workout`, `race`, `rest`, `travel` or `other` and is immutable after create. Workouts and races own a detail row (`workout_detail`: `workout_type`, `objective`, distance, elevation, duration, intensity, route, structure, nutrition; `race_detail`: `sport`, distance, `goal_time_s` / `goal_text`, `priority`, `result_activity_id`, route, nutrition). Several entries may share a date; everything is addressed by id. All writes go through `db/calendar.py`, which keeps the invariants: entry + detail in one transaction, at most **one scored workout per sport group per date** (so one activity can never be credited twice), `update_entry` is a patch (absent field = unchanged, `None` = clear), and `apply_changes(ops, request_id)` applies create / update / delete operations atomically and idempotently (deletes first, so a replace works). The taxonomy (kinds, workout types, race sports, route/structure-capable, unscored) lives only in `kinds.py`; `tests/fixtures/taxonomy.json` is asserted by both pytest and `web/taxonomy.test.mjs` so `constants.ts` cannot drift. Older consumers read a flattened row (`get_plan_rows`: entry + detail, `workout_type` = display string such as "Running Race" / "Rest"); races for the coach, insights and the Profile come from race entries (`get_races`, `get_prefs()["races"]`).

The `training_plan` table became `training_plan_legacy` (and `calendar_prefs.races` → `races_legacy`) in migration `015`, which writes a SQLite backup into `~/.strides_ai/backups/` first and aborts if it can't; a later migration drops the legacy tables once the cutover is verified. Nutrition / route analysis are cached per entry and cleared only when an input those prompts read changes (`inputs_hash`); an analysis write for stale inputs is rejected.

The chat coach writes through the `update_training_plan` tool (see "LLM backends"); writes are surfaced to the frontend as a `[PLAN_UPDATED]` SSE sentinel, shown as a "Calendar updated" confirmation in the chat UI.

Cycling workouts can also carry a structured (ERG-style) workout in `workout_detail.structure_json`, defined and validated only in `strides_ai/workout_structure.py` (`normalize_structure`; intensities are fractions of FTP, so no FTP is needed). A valid structure is authoritative for `duration_min`; it is discarded on non-cycling types, and a patch that omits it leaves it alone. `GET /calendar/entries/{id}/zwo` exports it as a Zwift `.zwo`. Indoor Rides are prompted to carry distance + elevation (Zwift simulated climbing); the UI derives the climb ratio on read (`plannedClimbRate`), never stored.

API: `GET /calendar/entries`, `POST /calendar/entries`, `PATCH|DELETE /calendar/entries/{id}`, `POST /calendar/entries/bulk` (`{ops, request_id}`), `POST /calendar/entries/{id}/nutrition|analyze-route`, `GET /calendar/kinds`. Date-keyed write endpoints no longer exist. The generic `workout_type` strings "Race" / "Running Race" / "Cycling Race" / "Rest" and a `description` field are still accepted on create and resolved server-side into kind + detail.

The Calendar UI lives in `web/src/pages/calendar/`. The grid is Monday-first by default, so each row is exactly one backend week (ramp, streak); the `week_start` setting (`monday` | `sunday`, `GET/PUT /api/settings`, Settings page) only changes the display, since the backend's weeks are always Monday–Sunday. The selected day is the URL (`#calendar/<date>`), not component state. `CalendarPage` owns range, drag state and `moveWorkout`; `useCalendarData` owns every fetch and the preference mutations; `DayPanel` owns the edit form and `saveWorkout` and is remounted (by key) on each selection, which is what resets it; `grid.ts` is pure and unit-tested. Entries are held as `Plan = Record<date, Entry[]>` and compliance by entry id; write behaviour (move, form → request body, accept-a-generated-block change set) lives in the pure helpers in `entryOps.ts`, which `web/calendar.test.mjs` tests directly. Dragging an entry is a date-only PATCH; accepting a generated block shows a replace / append choice and sends one atomic bulk request with a `request_id`.

A planned workout or race can also have a route URL attached (`route_url`) — either a Strava or a RideWithGPS route, only shown/accepted for Running and Cycling workout types. `strides_ai/sources/routes.py` dispatches by domain to `sources/ridewithgps.py` (unauthenticated legacy `routes/{id}.json` endpoint, public routes only, no API key) or `sources/strava_routes.py` (authenticated with this app's existing Strava `read` scope — confirmed to work for *any* public route, not just the connected athlete's own; distinct from `sources/strava.py`, which handles activity sync/deep-dive). `POST /calendar/plan/{date}/analyze-route` fetches the route and asks the LLM (`strides_ai/route_analysis.py`) whether its distance/elevation/terrain actually fits the workout's stated goal, returning a `verdict`/`explanation`/`suggestion`. Cached in `route_analysis_json`; cleared when an input it reads changes, same as `nutrition_json`; `?force=true` regenerates.

### Charts insights (`strides_ai/insights.py`, `web/src/charts/InsightsCard.tsx`)

The Analytics page (formerly Charts; legacy `#charts` hashes still resolve) has an "Insights" tab, shown first, holding an analytical "Training Insights" card (cardio modes only). `build_digest()` deterministically computes the metrics (last 4 full weeks vs the prior 8, in-progress week excluded, values formatted in the athlete's units), rule-based flags, next race and recent plan compliance — reusing `analytics.cardio` and `compliance`. The LLM (`stateless_turn`, user-selected backend) only interprets the digest into structured JSON (`status`, `headline`, `findings`, `recommendations`, each citing digest metric ids; unknown ids are dropped by `parse_insights_response`). The UI renders figures from the digest, never from model text.

`GET /api/charts/insights` returns the live digest + cached report + `stale` (never calls the LLM); `POST` generates (`?force=true` to bypass a fresh cache). The cache lives in the `settings` table under `charts_insights:{mode}:{unit_system}` and is invalidated by `digest_fingerprint` (activity count/latest id/date, unit system, ISO week). ATL/CTL are distance-based, so the load flag uses the ATL/CTL ratio rather than a TSB threshold.

### Progress: streak and records (`strides_ai/progress.py`)

`GET /api/progress` is computed on read (nothing stored, no mode parameter) from every planned workout and every activity; `build_progress(plan_rows, activity_rows, today, units)` is pure. Weeks are Monday–Sunday. **Streak:** a week is hit when at least one scored plan day was done (completed or shortened) and at most `MAX_MISSES` (1) was missed; weeks with nothing scored pause it, more than two paused weeks in a row end it, and the in-progress week never counts (`this_week.status` says where it is heading). **Records:** per sport (`run`, `ride`, `lift`), only once that sport has 6 activities and 28 days of history; ties go to the earliest; no pace records (Strava best efforts aren't fetched).

Plan compliance has one entry point, `compliance.compliance_for_range(...)`, and always takes **all** activities, never a mode-filtered list. Each `DayCompliance` carries its `entry_id`; an activity is credited to at most one entry per day (race results first, then sport-specific workouts, then sport-ambiguous ones). A race is never scored: it is neutral (`unscored`, so it can't break a streak) until the athlete links the activity (`result_activity_id`); travel and other entries are not planned training. The streak counts scored workouts, so adding a race, rest or travel entry never changes the miss allowance — the plan is shared across modes, so filtering would turn a completed planned ride into "missed" in running mode. The coach, Calendar, Insights digest and progress all go through it.

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
| `THINKING_EFFORT` | Optional; `off` / `low` / `medium` (default) / `high` — chat thinking effort for every provider (`CLAUDE_THINKING_EFFORT` is the old name) |
| `GEMINI_MODEL` | Optional; defaults to `gemini-2.0-flash` |
| `PORT` | Optional; defaults to `8000` |

Copy `.env.example` to `.env` to get started.

### Frontend (`web/`)

React 18 + TypeScript + Tailwind CSS + Vite + recharts. Navigation uses `location.hash` — no router dependency. `web/src/nav.ts` owns the grammar `#<tab>[/<param>]` (`#activities/<id>`, `#calendar/<YYYY-MM-DD>`, `#analytics/<section>`; invalid params are dropped): link with `hrefFor` / `navigate`, never a hand-written hash.

Shared UI lives in `web/src/ui/` — use it instead of hand-rolling Tailwind per page: `Button` (primary takes the mode accent), `Modal` (labelled, Escape, focus handling), `Spinner`, `LoadingState` / `ErrorState` / `EmptyState` / `Notice` (`states.tsx`), `PageHeader`, `formatDate` / `formatDuration` (`format.ts`), and `fetchJson` / `useApi` (`api.ts`), which throw on non-2xx so a failed request can't render as empty data. The mode theme is defined once in `ui/theme.tsx` and read with `useTheme()`; it is also exposed as the `--accent` CSS variable.

Streak and records reach the UI through `web/src/progress/` (`useProgress`, `ProgressStrip` on the Calendar, `ProgressCard` in Analytics → Progress, `NewRecordBanner` in chat). Pages hand things to the chat through `pages/chatActivityHandoff.ts` (one-shot sessionStorage, never a URL, so a reload cannot re-fire it). Vite HMR picks up React changes instantly; Python changes require a server restart.

File attachments (images as base64, text as UTF-8) are uploaded to `~/.strides_ai/uploads/` and forwarded to `stream_turn` as `attachments`.
