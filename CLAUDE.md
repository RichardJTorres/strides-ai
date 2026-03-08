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
make cli              # terminal coaching app

# One-off
make profile          # open profile.md in $EDITOR
```

`make install` is idempotent — it uses file-based Make targets (`$(VENV)/bin/activate`, `web/node_modules`) so it only re-runs what's stale.

There are no automated tests yet.

## Git Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for all commit messages:

```
<type>[optional scope]: <description>

[optional body]
```

Common types: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`.

Examples:
- `feat(calendar): add nutrition advice for planned workouts`
- `fix(db): handle missing elevation_m column on existing installs`
- `docs: update README with calendar and cycling mode features`

## Architecture

### Two interfaces, one shared backend

```
strides-ai        (CLI)  →  coach.py:chat()  ─┐
strides-ai-web    (Web)  →  api/app.py       ─┤─→  backends/{claude,gemini,ollama}.py
                                               └─→  db.py / profile.py / sync.py
```

The Python package has two entry points (`pyproject.toml`): `strides-ai` → `strides_ai/cli.py:main` and `strides-ai-web` → `strides_ai/api/server.py:main`.

### LLM backends (`strides_ai/backends/`)

`BaseBackend` (ABC) defines `stream_turn(system, user_input, on_token) → (text, memories)`. All concrete backends maintain in-memory message history. Each call streams tokens via the `on_token` callback and handles tool calls (`save_memory`) in a loop until the LLM stops calling tools.

Select backend with `PROVIDER=claude` (default, uses `ANTHROPIC_API_KEY`), `PROVIDER=gemini` (uses `GEMINI_API_KEY`), or `PROVIDER=ollama` (uses `OLLAMA_MODEL` + `OLLAMA_HOST`).

### System prompt assembly

On every turn: `BASE_SYSTEM_PROMPT + profile text (from ~/.strides_ai/profile.md) + memories (from DB)`. The profile is a structured Markdown file with sections parsed/serialized by `profile.py`. The web UI reads/writes it via `GET|PUT /api/profile`.

### Conversation persistence

- **Conversation history**: last 40 messages (`RECALL_MESSAGES`) stored in SQLite, re-injected at session start.
- **Memories**: structured facts (category + content) saved by LLM tool calls, always injected into system prompt.
- **Profile**: plain Markdown read fresh each session — never cached in DB.

All local data lives in `~/.strides_ai/` (`activities.db`, `profile.md`, `token.json`).

### Web API (`strides_ai/api/app.py`)

FastAPI app with a single backend instance created at startup. `/api/chat` is SSE — it bridges a sync `stream_turn` thread to an async generator via `queue.SimpleQueue`. The frontend parses `data:` lines and a special `[MEMORIES]` sentinel sent after the response.

The Vite dev server proxies `/api` → `localhost:8000` (`web/vite.config.ts`), so no CORS issues in dev.

### Strava sync (`strides_ai/sync.py`)

Incremental by default — stops at the first activity ID already in the DB. Filters to `{"Run", "TrailRun", "VirtualRun"}`. Cadence is doubled (Strava sends half-cadence). Pace is derived: `moving_time_s / (distance_m / 1000)`.

OAuth2 lives in `auth.py` — tokens stored in `~/.strides_ai/token.json`, auto-refreshed on expiry.

### Required environment variables (`.env`)

| Variable | Required for |
|---|---|
| `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | All modes |
| `ANTHROPIC_API_KEY` | `PROVIDER=claude` (default) |
| `GEMINI_API_KEY` | `PROVIDER=gemini` |
| `OLLAMA_MODEL` | `PROVIDER=ollama` |
| `OLLAMA_HOST` | `PROVIDER=ollama` (default: `http://localhost:11434`) |
| `CLAUDE_MODEL` | Optional; defaults to `claude-sonnet-4-6` |
| `GEMINI_MODEL` | Optional; defaults to `gemini-2.0-flash` |
| `PORT` | Optional; defaults to `8000` |

Copy `.env.example` to `.env` to get started. The `_check_env` Make target enforces `.env` exists before running any server.

### Frontend (`web/`)

React 18 + TypeScript + Tailwind CSS + Vite. Navigation uses `location.hash` (`#chat`, `#activities`, `#charts`, `#profile`) — no router dependency. Vite HMR picks up React changes instantly; Python changes require a server restart.
