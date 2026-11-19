# Getting Started

This guide takes you from a fresh clone to a coach that knows your training. Allow about 20
minutes, plus however long the first Strava sync takes for your history.

1. [Prerequisites](#1-prerequisites)
2. [Create a Strava API application](#2-create-a-strava-api-application)
3. [Get an LLM key](#3-get-an-llm-key)
4. [Install](#4-install)
5. [Configure `.env`](#5-configure-env)
6. [Start the app](#6-start-the-app)
7. [Connect Strava and run the first sync](#7-connect-strava-and-run-the-first-sync)
8. [Set your preferences](#8-set-your-preferences)
9. [Fill in your profile](#9-fill-in-your-profile)
10. [Optional: connect HEVY for lifting](#10-optional-connect-hevy-for-lifting)
11. [Keeping data up to date](#11-keeping-data-up-to-date)
12. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

- **Python 3.11 or newer** (`python3 --version`)
- **Node.js 18 or newer** and npm (`node --version`)
- **make** (preinstalled on macOS and most Linux distributions)
- A **Strava account** with some activities in it
- An API key for **one** LLM provider, or [Ollama](https://ollama.com) running locally

Strides AI runs on one computer. The server, the database and the Strava login all live on
the machine where you run `make dev`. Open the UI in a browser on that same machine for the
first-time setup (the Strava login opens a browser there, see step 7).

## 2. Create a Strava API application

Strides AI reads your activities through your own Strava API application. It is free and takes
two minutes.

1. Go to <https://www.strava.com/settings/api> and sign in.
2. Fill in the form:
   - **Application Name:** anything, for example `Strides AI (personal)`
   - **Category:** any, for example *Training*
   - **Website:** anything, for example `http://localhost`
   - **Authorization Callback Domain:** `localhost`. This one matters: the login sends you back
     to `http://localhost:8282/callback`.
3. Save. Strava now shows a **Client ID** and a **Client Secret**. Keep the page open for step 5.

The app asks Strava for `read,activity:read_all` access, which includes private activities. It
never writes to your Strava account.

## 3. Get an LLM key

Pick one provider to start with. You can add others later and switch between them in Settings.

| Provider | Where to get a key | `.env` variable |
|---|---|---|
| Claude (recommended, default) | <https://console.anthropic.com> | `ANTHROPIC_API_KEY` |
| Gemini | <https://aistudio.google.com/apikey> | `GEMINI_API_KEY` |
| ChatGPT | <https://platform.openai.com/api-keys> | `OPENAI_API_KEY` |
| Ollama (local, free) | Install Ollama, then `ollama pull llama3.1` | none |

Things to know before you choose:

- **One key is enough.** Every AI feature uses the provider you select. The only difference
  is that image and file attachments in chat need Claude.
- **Costs.** Each chat turn sends your profile, memories, recent training and calendar, so
  turns are much larger than the message you type. **Settings → Model usage** shows tokens and an
  estimated cost per day (estimates exist for Claude models only).
- **Local models.** Ollama works, but small local models follow the coaching instructions and
  calendar tools much less reliably than the cloud models.

## 4. Install

```bash
git clone https://github.com/RichardJTorres/strides-ai.git
cd strides-ai
make install
```

`make install` creates a Python virtualenv in `.venv`, installs the Python and Node
dependencies and sets up the pre-commit hook. You can run it again safely: it only redoes what
is out of date.

## 5. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in at least these values:

```dotenv
STRAVA_CLIENT_ID=12345
STRAVA_CLIENT_SECRET=abc123...

PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

To start with a different provider, set `PROVIDER` to `gemini`, `openai` or `ollama` and add
that provider's key (or `OLLAMA_MODEL` for Ollama). The [README](../README.md#configuration)
lists every variable.

`PROVIDER` applies until you pick a provider in **Settings**. Your choice there is saved in
the database and wins from then on, so later edits to `PROVIDER` have no effect.

## 6. Start the app

```bash
make dev
```

This starts the API on port 8000 and the web UI on port 5173. Leave this terminal open: the
Strava login in the next step prints messages here. Press `Ctrl+C` to stop both.

Open **<http://localhost:5173>**. The app opens on the **Coach** tab in **Running** mode. Don't
chat yet: the coach knows nothing about you until you sync.

> **Before you sync, set your max heart rate.** Go to **Profile → You → Max heart rate (bpm)**
> and save it. Every activity's HR zones are computed from it when the activity is analysed,
> using a default of 190 bpm until you set it. You can recompute them later with **Settings →
> Strava Sync → Reanalyse all**, but that refetches every activity from Strava, which takes a
> while for a long history.

## 7. Connect Strava and run the first sync

There is no separate connect button: the first sync starts the Strava login.

1. Go to **Activities** and click **Sync Activities**.
2. A new browser tab opens on Strava's authorization page. If it doesn't open, look in the
   `make dev` terminal for a line starting with *"If it doesn't open automatically, paste this
   URL"* and open that URL yourself.
3. Click **Authorize**. You'll see *"Authorization successful! You can close this tab."*
4. Return to the Strides AI tab. The **Sync Activities** button keeps spinning while the
   sync runs.

Your token is saved in `~/.strides_ai/token.json` and refreshed automatically, so you only log
in once.

### What the first sync does

The first sync downloads your **whole** Strava history, then fetches the detailed data
(heart rate, pace, cadence, altitude) for each activity and computes its metrics:

- **HR zone distribution** (based on your max HR, see step 6)
- **Pace fade** (last third against the first third)
- **Cardiac decoupling**, only where it means something: steady runs that are not hilly and
  last 20 minutes or more. It is shown as `n/a` for rides, hilly runs and short activities.
- **Climbing ratio**, **cadence** and an **efficiency score**
- A short rule-based **summary**, generated without an LLM call, so it costs nothing

With a large history, the first sync can take several minutes and will probably hit Strava's
API rate limit. Strava allows only a limited number of requests per 15 minutes and per day.
That is expected: all your activities are saved, and the ones that could not be analysed yet
are marked *pending*. Each later sync analyses up to 10 more pending activities, so the backlog
clears over the following days. The coach can see every activity right away. Only the computed
metrics fill in over time.

When the sync finishes, the button area shows *"N new items synced."* and the Activities list
fills in.

## 8. Set your preferences

Open **Settings** (bottom of the sidebar).

| Setting | What to choose |
|---|---|
| **Mode** | *Running*, *Cycling*, *Hybrid* (running and cycling together) or *Lifting* (HEVY). The mode chooses which activities the coach and the Activities and Analytics tabs focus on, and which discipline sections of your profile the coach reads in full. Each mode has its own chat history. Your profile, calendar and memories are shared by every mode. |
| **Units** | *Metric* or *Imperial*. You can change it at any time: data is stored once and converted for display. |
| **Calendar Week Start** | *Monday* or *Sunday*. This only changes how the calendar is drawn. Training weeks, streaks and ramp are always counted Monday to Sunday. |
| **Coach Voice** | *Default*, *Supportive*, *Technical*, *Beginner Friendly* and others, or *Custom* to write your own instruction. It applies to every mode. |
| **LLM Provider** | Providers whose key is missing are greyed out, with a hint. Click a configured provider to switch, and choose a model from its dropdown. |

**If you do both running and cycling, pick Hybrid.** Running mode, for example, shows only runs
in its activity list and charts. The calendar always shows everything.

## 9. Fill in your profile

Open **Profile**. The profile is the most important context the coach has, and a few minutes
here makes a big difference to its advice. A completeness meter at the top shows what's
missing.

Start with these:

1. **You → Max heart rate (bpm)**, if you skipped it in step 6. A new value applies to
   activities analysed from then on. To update activities already analysed, use **Settings →
   Strava Sync → Reanalyse all**.
2. **Goals & schedule.** Your goal ("sub-4 marathon at Berlin in September"), sessions per
   week, your long-session day and the days you can train.
3. **Injuries & health.** Anything current or recurring. The coach always keeps injury notes in
   context.
4. **Your discipline cards** (Running, Cycling, Lifting). How long you have done the sport,
   your current volume, your focus and your personal bests.

Each section saves on its own. Races don't belong in the profile: add them to the calendar
(the [Tutorial](tutorial.md#4-add-your-races) shows how).

## 10. Optional: connect HEVY for lifting

Lifting mode reads your workouts from [HEVY](https://hevy.com). It needs a HEVY Pro
subscription.

1. Get your API key at <https://hevy.com/settings?developer>.
2. Add it to `.env`:
   ```dotenv
   HEVY_API_KEY=your_hevy_api_key
   ```
3. Restart `make dev`, which reads `.env` only at startup.
4. In **Settings → HEVY Sync**, click **Sync New**. **Refresh Templates** downloads HEVY's
   exercise catalogue, which provides the muscle-group breakdowns.
5. Switch **Mode** to **Lifting**.

Each HEVY workout is analysed for total volume, working sets, average RPE, estimated one-rep
maxes and muscle groups. Lifting mode hides the Calendar tab.

## 11. Keeping data up to date

The app does not sync on its own. Sync whenever you want the coach to see your latest
sessions:

- **Activities → Sync Activities** fetches new activities from Strava (and HEVY, if
  configured). It stops at the first activity it already has, so it is quick.
- The chat's activity picker (the ⚡ *Attach an activity's stats and analysis* button) has a
  **Sync now** button that does the same.
- **Settings → Strava Sync → Full Sync** fetches your whole history again. Use it to pick up
  activities you edited on Strava, to fill gaps, or on a new machine. It updates each
  activity's basic fields but does not reanalyse activities that already have metrics.
- **Settings → Strava Sync → Reanalyse all** recomputes every activity's metrics, for example
  after you change your max HR. It refetches each activity's data from Strava, so with a long
  history it stops at Strava's rate limit. Click **Continue** after 15 minutes to pick up where
  it stopped.

The *"Synced 3h ago"* label on Activities and in the chat's activity picker shows how fresh
your data is.

You're set up. Continue with the **[Tutorial](tutorial.md)**.

---

## Troubleshooting

### `make dev` prints "No .env file found"
Run `cp .env.example .env` and fill it in (step 5).

### The server exits saying an API key must be set
The key for the provider in `PROVIDER` is missing: `ANTHROPIC_API_KEY` for `claude` (the
default), `GEMINI_API_KEY` for `gemini`, `OPENAI_API_KEY` for `openai`. Add it, or change
`PROVIDER` to match the key you have.

### The server exits with "Missing STRAVA_CLIENT_ID or STRAVA_CLIENT_SECRET"
Both values are required, even if you only plan to use Lifting mode.

### Clicking Sync does nothing, or keeps spinning
The first sync waits until you authorize on Strava. Look in the `make dev` terminal for the
authorization URL and open it. If you're running the app on a remote machine, the login has to
complete in a browser on **that** machine, because Strava redirects to `localhost:8282`.

### Strava says "redirect_uri invalid"
In your Strava API settings, the **Authorization Callback Domain** must be exactly `localhost`.

### Port 8282 is already in use
The Strava login listens on port 8282 for a moment during the first sync. Stop whatever is
using that port and sync again.

### Many activities show no metrics
They are still *pending* analysis because of Strava's rate limit. Each sync analyses up to 10
more. Manual entries and activities recorded without GPS or a heart-rate monitor have no
detailed data, so some metrics never appear for them.

### HR zones look wrong
Check **Profile → You → Max heart rate**, then run **Settings → Strava Sync → Reanalyse all**
to recompute the zones of activities already analysed.

### A provider is greyed out in Settings
Its key is missing from `.env` (for Ollama: Ollama isn't running, or no model is pulled). Add
it and restart `make dev`.

### The coach says the message is too large (HTTP 413)
The parts of the context that are never trimmed (profile, injury notes, upcoming workouts)
already fill the model's window. Shorten long profile fields or memories, or choose a model with
a larger context window.

### Start over
Stop the server and move `~/.strides_ai/` somewhere else (or delete it). The next start
creates a fresh database, and the next sync asks you to log in to Strava again. Back the folder
up first if you want to keep your chat history, profile and calendar.
