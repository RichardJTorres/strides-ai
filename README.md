# strides-ai

A local AI multisport coach that connects to your Strava account and lets you have coaching conversations about your training. Also integrates with [HEVY](https://hevy.com) for weightlifting sessions. Supports Claude, Gemini, and ChatGPT (cloud APIs) and any model running locally via Ollama.

## What it does

- **Strava sync** — authenticates via OAuth2 and pulls your full activity history into a local SQLite database. Incremental sync on every startup keeps it current.
- **HEVY sync** — connects to the HEVY API (Pro subscription required) to pull your weightlifting sessions. Each workout is automatically analysed for volume, estimated 1RMs, and muscle group breakdown.
- **Multi-mode coaching** — switch between **Running**, **Cycling**, **Hybrid** (multisport), and **Lifting** modes. Each mode has its own coaching persona, filtered activity history, and separate conversation history and athlete profile.
- **Web UI** — a browser-based interface with a sidebar nav for chat, activities, training charts, calendar, profile editing, and settings.
- **Athlete profile** — fill in your background, PBs, goals, injuries, and gear via the web UI. Profiles are per-mode (running vs. cycling), loaded fresh every session.
- **Persistent memory** — the coach proactively saves key facts (goals, injuries, preferences, upcoming races) and recalls them at the start of every session.
- **Conversation history** — the last 40 messages from previous sessions are reloaded so coaching advice stays consistent across conversations. History is scoped per mode.
- **Training calendar** — plan upcoming workouts on a calendar, overlay your actual Strava activities, and get AI-powered nutrition recommendations per workout.
- **Swappable backends** — run Claude, Gemini, or ChatGPT in the cloud, or a local model via Ollama. Switch providers live from the Settings tab without restarting the server.
- **Run analysis pipeline** — every synced activity is automatically enriched with derived fitness metrics (cardiac decoupling, HR zone distribution, pace fade, cadence consistency, effort efficiency) and a natural language summary. The Activities tab shows colour-coded metric badges and an on-demand Deep Dive button that generates a full LLM coaching analysis for any individual run.
- **Lifting analysis pipeline** — every HEVY workout is automatically analysed for total volume, set count, avg RPE, estimated 1RMs (Epley formula), and primary muscle groups. A natural language summary is generated with no LLM call. Deep Dive generates a full strength coaching analysis from the raw set data.

## Setup

### 1. Prerequisites

- Python 3.11+
- Node.js 18+ (for the web UI)
- A [Strava API app](https://www.strava.com/settings/api) — set **Authorization Callback Domain** to `localhost`
- An Anthropic API key, a Google Gemini API key, an OpenAI API key, **or** a local [Ollama](https://ollama.com) installation (see [Backends](#backends) below)
- _(Optional)_ A [HEVY Pro](https://hevy.com) subscription and API key for weightlifting mode

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

# Optional: HEVY weightlifting integration (requires HEVY Pro)
# HEVY_API_KEY=your_hevy_api_key
```

### 4. Run

```bash
make dev      # API on :8000, frontend on :5173
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

The URL uses hash-based navigation (`#chat`, `#activities`, `#analytics`, `#calendar`, `#profile`, `#settings`), so refreshing the page keeps you on the same tab.

To run only the backend: `make api`. To run only the frontend: `make web`.

---

## Coaching Modes

Switch between modes from the **Settings** tab. The active mode affects:

- **Activities shown** — Running shows runs only; Cycling shows rides only; Hybrid shows everything; Lifting shows HEVY weightlifting sessions only
- **Coaching persona** — the coach's framing, metrics, and terminology adapt to the sport
- **Conversation history** — each mode has its own separate history so advice stays contextually relevant
- **Athlete profile** — running, cycling, and lifting profiles can be filled in independently
- **Visible tabs** — Lifting mode hides Charts and Calendar (not applicable to strength training)

After switching modes for the first time, use the **Full Sync** button in the **Settings** tab to fetch your complete activity history. For Lifting mode this triggers a full HEVY sync.

### Lifting mode

Requires a [HEVY Pro](https://hevy.com) subscription and `HEVY_API_KEY` set in `.env`. The lifting coach has access to your full session log including exercise names, sets, reps, weights, and RPE. It can track progressive overload, estimate 1RMs, analyse fatigue across a session, and give programming advice.

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

Set `THINKING_EFFORT` (`off`, `low`, `medium` default, or `high`; `CLAUDE_THINKING_EFFORT` still works) to
control how hard the coach thinks per chat request. Each provider maps it to what its model accepts,
read from the provider's capability API where there is one (`backends/model_profile.py`); a model it
cannot identify gets no thinking parameter. Thinking counts
against the per-round `round_max_tokens` limit (16,000 by default, derived from the model; see "Bounded
coaching turns"), and the effort is the same on every round of a turn.

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
| **Pace fade** | Last-third avg pace minus first-third avg pace (stored in s/km, shown in s/km or s/mi) | Positive = slowing, negative = negative split |
| **Cadence avg / std dev** | Mean and variability of step rate (spm for runs, rpm for rides) | — |
| **Effort efficiency score** | 0–100, normalized across athlete history; higher = better pace for a given HR | — |
| **Climbing ratio** | Elevation gain per distance (stored in m/km, shown in m/km or ft/mi); flags hilly courses (>100 ft/mi ≈ 19 m/km) | — |
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

## Lifting Analysis Pipeline

Every workout synced from HEVY is automatically analysed from its raw exercise/set data. No LLM call is made — the summary is generated from rules so it's instant and free.

### Computed metrics

| Metric | Description |
|---|---|
| **Total volume (kg)** | Sum of weight × reps across all working sets (warmups excluded) |
| **Total sets** | Number of working sets across the session |
| **Avg RPE** | Mean rate of perceived exertion across all sets that have it recorded |
| **Estimated 1RMs** | Per-exercise best estimated 1-rep max using the Epley formula (`weight × (1 + reps/30)`), limited to sets ≤ 12 reps |
| **Muscle group volume** | Total volume broken down by primary muscle group |

### Analysis summary

A concise NL summary is generated immediately after sync. Example:

> _"Bench Press: 4×8 @ 100.0 kg, Squat: 5×5 @ 120.0 kg (+3 more) | 32 working sets | 8640 kg total volume | avg RPE 7.5 | primary: Chest/Legs/Shoulders"_

### Deep Dive

Click **Deep Dive** on any lifting session to generate a full strength coaching analysis. The deep dive:

1. Formats the raw exercise log (set type, weight, reps, RPE) into a structured prompt
2. Sends to the active LLM backend as a one-shot stateless call
3. Returns a detailed analysis covering volume/intensity appropriateness, exercise sequencing, set quality, estimated 1RM trends, and fatigue signs
4. Ends with 3–5 specific, actionable coaching notes for the next session

Results are cached — use **Regenerate** to force a fresh analysis.

---

## How it works

```
strides_ai/
├── api/
│   ├── app.py          # FastAPI routes, SSE streaming for /api/chat
│   ├── server.py       # uvicorn entry point (strides-ai-web)
│   └── routers/
│       └── hevy.py     # /api/hevy/sync endpoint
├── backends/
│   ├── base.py         # BaseBackend ABC — stream_turn(system, input, on_token)
│   ├── claude.py       # Anthropic SDK, tool_use loop
│   ├── gemini.py       # Google Gemini SDK, function calling loop
│   ├── openai.py       # OpenAI SDK, streaming + tool calling loop
│   └── ollama.py       # httpx → Ollama /api/chat, streaming + tools
├── sources/
│   ├── base.py         # DataSource protocol / error types
│   ├── strava.py       # Strava DataSource (wraps sync.py + analysis.py)
│   └── hevy.py         # HEVY DataSource (wraps hevy_sync.py + hevy_analysis.py)
├── analysis.py         # Cardio stream fetching, metric computation, NL summary, deep-dive
├── hevy_analysis.py    # Lifting metric computation (volume, 1RM, muscle groups), NL summary
├── auth.py             # Strava OAuth2 — token exchange, storage, auto-refresh
├── db.py               # SQLite — activities, history, memories, profiles, calendar
├── sync.py             # Strava API pagination, incremental sync (runs + rides)
├── hevy_sync.py        # HEVY API pagination, incremental + full sync
├── modes.py            # ModeConfig registry — per-mode prompts, log format, profile sections
├── profile.py          # Profile fields — defaults per mode, serialization
├── schedule.py         # Nutrition analysis — Claude Haiku, structured JSON output
└── coach.py            # System prompt assembly, training log formatting
web/
└── src/pages/
    ├── Chat.tsx        # Streaming chat UI, mode-aware history
    ├── Activities.tsx  # Activity table (Strava + HEVY), mode-filtered
    ├── Charts.tsx      # Weekly volume, ATL/CTL, aerobic efficiency
    ├── calendar/       # Planned workouts, Strava overlay, nutrition advice (CalendarPage + parts)
    ├── Profile.tsx     # Athlete profile editor (per-mode)
    └── Settings.tsx    # Mode selector (Running / Cycling / Hybrid / Lifting)
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
| HEVY API | `httpx` |
| Anthropic API | `anthropic` |
| Gemini API | `google-genai` |
| OpenAI API | `openai` |
| Ollama API | `httpx` |
| Web framework | `fastapi` + `uvicorn` |
| Database | `sqlite3` (stdlib) |
| Config | `python-dotenv` |
| Frontend | React 18, TypeScript, Tailwind CSS, Vite |
| Charts | Recharts |

## Chat conversations

Each coaching mode has one persistent conversation shared across browser tabs.
Only one chat turn per mode can run at a time; a busy mode returns HTTP 409 and
keeps the draft and attachments ready for retry. Other modes can run concurrently.
Each turn captures its provider/model and reconstructs private history from stored
messages. Settings, profile edits, and activity sync apply to subsequent turns.
Interrupted or failed turns leave an explicit history marker. Cancellation is
cooperative: a mode stays busy until provider execution and cleanup finish.

Run the API as a **single process**. Multiple API workers require shared turn
coordination, which is outside this implementation.

Frontend admission tests: `npm --prefix web test`.

### Bounded coaching turns

Limits follow the model in use. From the model's context window (W) and maximum output (M),
read from the provider where it has a capability API (`backends/model_profile.py`), a turn gets
(for a 200k window and 64k output, the numbers in brackets):

| Limit | Default | |
|---|---|---|
| `round_max_tokens` | `min(16000, M, W / 4)` | output cap of a tool round, thinking included (16,000) |
| `reply_reserve` | `min(4000, round_max_tokens / 2)` | output kept back for the closing reply (4,000) |
| `turn_output_ceiling` | `3 x round_max_tokens + reply_reserve` | all output of a turn (52,000) |
| `context_target` | `min(60000, (W - round_max_tokens) x 3/4)` | what prompt selection aims for (60,000) |
| `input_ceiling` | `min(W - round_max_tokens, context_target + turn_output_ceiling + tools x 1500)` | no tool round above this input (136,000) |
| `tool_rounds` | 5 | tool rounds; one reply round follows |
| `tools`, `retries`, `history_messages`, `recent_activities` | 16, 2, 40, 30 | |
| `first_event_s`, `stream_idle_s` | 60, 120 | connect and read timeouts on the provider client |
| `round_deadline_s`, `reply_deadline_s`, `turn_deadline_s` | 240, 120, 600 | |

A tool round is offered only while tool rounds and tool calls remain, at least
`round_max_tokens + reply_reserve` of output remains under the ceiling, the estimated input is
within `input_ceiling`, and `turn_deadline_s` leaves room for a round and a reply. Its
`max_tokens` is `round_max_tokens`. Otherwise the next request is the **reply round**: tools are
switched off (`tool_choice` none on Claude and OpenAI, function calling mode NONE on Gemini,
no `tools` on Ollama), a note after the tool results asks the model to summarise what was done
and what remains, and `max_tokens` is `min(round_max_tokens, max(remaining, reply_reserve))`.
The turn ends with the reply, and its stop code is stored as the turn's notice: `round_limit`,
`tool_limit`, `output_ceiling`, `input_ceiling` or `deadline`. If even that reply would not
fit the model's window, the turn ends with the receipt of what it saved. A response cut off at
its token limit (`truncated`) never has its tool calls run, and neither does a reply round's.
Tool arguments that do not parse are not run: the model is told. Calls skipped at the tool
limit are answered "Not executed: tool limit reached". Time is checked before every request
and on every stream event; a stalled stream ends the turn as `deadline`, and repeated transport
failures as `retry_limit`. Completed writes are always kept and summarised in the receipt.

An `update_training_plan` call may change at most 31 entries (`set` items plus `delete` ids); a
larger call is rejected whole and the coach is told to split it. Its result lists every created,
updated and removed id, with at most five warnings or reasons of 200 characters each.

The coach recalls at most 40 messages as complete exchanges and individually
represents at most 30 recent activities. Older records become deterministic sport
aggregates: weekly for the preceding 12 weeks, monthly for up to 24 older months,
and a coarsened earlier bucket. Source conversations and activities are preserved.
Context is built in two kinds of parts (`context_builder.py`). **Required** parts are never cut:
base instructions, tool definitions, your message and attachments, the profile, calendar
constraints, the coaching voice, the training state, workouts in the next 14 days, and protected
notes (injury, or temporary). If they alone exceed `context_target`, the message is rejected with
HTTP 413 before anything is saved; the message names the three largest parts and says to shorten
them or choose a model with a larger window. The smallest supported window is 16,384 tokens.
**Reducible** parts each have a cap (a share of `context_target`) and may be empty: history 35%
(newest whole exchanges), recent activities 25% (one table: 30 rows, 15, 7), other notes 15%
(ranked by category, newest start, newest id), later workouts 10% (to 60 days, 28), the older
summary 10%, and the analysis guide with streak and plan compliance 5%. Each starts at the
fullest level within its cap. If the total is still over the target they are cut in a fixed
order (older summary; activities to 15; history to 20%; workouts to 28 days; notes halved;
activities to 7; guide and streak; later workouts; history to one exchange, then none; notes;
activities), which always ends at the required context. Everything left out is labelled in the
prompt, for example "12 notes omitted". The date and time come last, so the rest of the prompt
is identical between turns; Claude gets them as a second system block after the cached one.
Messages and attachments are never shortened.

Set `CHAT_LIMITS` to a JSON object with overrides keyed by `default`, provider
(`claude`, `gemini`, `openai`, `ollama`), or the exact backend label shown in chat.
Keys are the names above plus `context_window`; the older `output_tokens`,
`total_output_tokens`, `input_tokens` and `rounds` still work as aliases. Overrides may raise
or lower a default (values past what the model supports are clamped, with a logged warning),
and an unknown key or a bad value stops the server at startup. For example:

```dotenv
CHAT_LIMITS={"default":{"tool_rounds":3},"ollama":{"round_max_tokens":2000,"context_window":8192}}
```

Claude requests ask for automatic prompt caching, so later rounds of a turn read the earlier
prefix from cache.

Input is estimated from UTF-8 bytes at a static per-model ratio plus framing, an image
counting a flat 5,000 tokens; after the first round it is built from the provider's own
usage. The provider's token-count endpoint is only a last resort when admitting a message.
Generated output is estimated as it streams and replaced by the reported usage, including
reasoning. Structured `chat_budget` logs identify measured versus estimated
input size, provider/model, retained context counts, rounds, tool executions, and
stop reason; they do not include prompt or attachment contents.

Each turn also stores a record of what it sent: the size of every context section and whether
it was sent or left out, the retained history, per-round sizes and timings, retries, and why
the turn stopped. It holds sizes and timings only, never prompt or reply text. Read it at
`GET /api/chat/turns/{id}/budget`. A message rejected at admission has no turn, so it is
logged as one `chat_admission_rejected` JSON line instead.

To see what the coach's context costs for a mode without calling a model or writing to the
database:

```bash
.venv/bin/python scripts/context_report.py --mode hybrid
```

Add `--measure` to let admission call the provider's token-count endpoint, as a live turn does.

## Dated goals and preferences

In **Memories**, edit a fact's state (**Current**, **Temporary**, or **Superseded**),
its effective start date, and optional inclusive end date. New facts saved by the
coach default to today's start date; existing memories keep their unspecified dates.

Use the same **topic** for facts that replace one another, such as `running_intensity`.
Within a topic, the most recent effective start wins; a temporary fact wins a tie.
After a temporary fact expires, the applicable standing fact resumes. Leave the end
date blank when the duration is unknown. Unrelated facts should have different topics
or no topic. Superseded facts stay available under **Show superseded memories** and
are excluded from coaching context.

Chat and fresh activity analyses use currently applicable facts. Training plan
generation resolves facts across the requested block, respecting future starts and
mid-block expirations. Applicable dated context takes precedence over conflicting
older profile goals and recalled conversations. Existing free-text facts are not
automatically classified or dated; use **Review for staleness** to find candidates
and archive selected facts, or edit their dates and topics directly. Previously
cached activity analyses require regeneration to reflect changed context.
