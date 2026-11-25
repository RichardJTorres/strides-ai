# Tutorial

This tutorial walks through the main workflows in the order you'd use them in your first week.
It assumes you have finished the [Getting Started guide](getting-started.md): the app is
running, your activities are synced and your profile has at least a goal and your max HR.

1. [A tour of the app](#1-a-tour-of-the-app)
2. [Your first conversation with the coach](#2-your-first-conversation-with-the-coach)
3. [Look at an activity and discuss it](#3-look-at-an-activity-and-discuss-it)
4. [Add your races](#4-add-your-races)
5. [Build a training plan](#5-build-a-training-plan)
6. [Work with the calendar day to day](#6-work-with-the-calendar-day-to-day)
7. [Track progress: compliance, load, streaks and Insights](#7-track-progress)
8. [Manage what the coach remembers](#8-manage-what-the-coach-remembers)
9. [A weekly routine](#9-a-weekly-routine)
10. [Lifting mode](#10-lifting-mode)

---

## 1. A tour of the app

The sidebar (or the bottom bar on a phone) has these tabs:

| Tab | What it's for |
|---|---|
| **Coach** | Chat with your coach. Each mode has its own conversation. |
| **Activities** | Your synced activities with computed metrics, notes and Deep Dives. |
| **Analytics** | **Insights**, **Progress** (streak and records), **Training Load** and **Performance** charts. |
| **Calendar** | Your plan: workouts, races, rest, travel and blocked days, compared with what you actually did. |
| **Profile** | Your athlete profile, shared by every mode. |
| **Memories** | Facts the coach has saved about you. |
| **Settings** | Mode, units, week start, coach voice, LLM provider, sync, usage. |

The current mode is shown under the "Strides AI" title and sets the accent colour. Change it in
**Settings → Mode**.

**What depends on the mode, and what doesn't:**

| Depends on the mode | Shared by every mode |
|---|---|
| Chat history | Profile |
| Activities list and Analytics charts | Calendar (always shows every sport) |
| Which profile disciplines the coach reads in full | Memories |
| The coach's sport focus | Streak and records |

---

## 2. Your first conversation with the coach

Open **Coach**. Every turn, the coach is given:

- your **profile** and your current **memories**
- your **training state**: fitness (CTL), fatigue (ATL), your **proven weekly level** and
  longest recent sessions, and each week's ramp against your recent normal weeks (travel and
  other off weeks are set aside)
- the **planning principles** it builds blocks with: start from your proven level, load 3:1,
  grow the long session toward race demand, taper before the goal race
- your **calendar**: races, blocked days and the coming workouts
- your **30 most recent activities** with their metrics, plus weekly and monthly summaries of
  older ones
- the last **40 messages** of this mode's conversation

For anything else it uses **lookup tools**: it can search your whole activity history, add up
weekly totals or read any part of the calendar. You may see it do this before it answers.

### Try these

Start broad, then narrow down:

> How has my training gone over the last month? Anything you'd change?

> What was my longest run this year, and how did my heart rate behave on it?

> I'm targeting a half marathon in March. Based on what I'm doing now, what's realistic?

Tips:

- **Enter** sends, **Shift+Enter** adds a new line. While the coach is replying, the send button
  turns into a **Stop** button.
- **Ctrl+F** (or the search icon) searches the whole conversation. **Load older messages**
  appears at the top when there's more history.
- You can leave the page while the coach replies: the reply keeps going on the server, and a
  dot on the **Coach** tab tells you when it's ready.

### What the coach can change

Below a reply you may see one or more of these:

- **"Remembered: [goal] …"** The coach saved a fact as a memory. **View memories** opens the
  list (see [section 8](#8-manage-what-the-coach-remembers)).
- **"Profile change suggested by your coach"** card. The coach wants to update your profile,
  for example after you mention a new PB. Nothing changes until you accept the card. You can
  also dismiss it.
- **"Calendar updated: scheduled 3, removed 1"**. The coach changed your calendar.
  **View calendar** jumps to the first changed day.
- **A notice in small print.** The turn stopped early (it hit a time or size limit, or you
  stopped it). The notice lists anything the turn saved before it stopped, so you can tell
  what took effect.

### Attaching things

Two buttons sit in the message box:

- **⚡ Attach an activity** (every provider). Pick an activity (search by name or date) to
  include its stats, analysis and Deep Dive, if it has one. The picker also has a **Sync now**
  button. You don't have to attach: "my run last Saturday" works too, because the coach can
  find it with its lookup tools.
- **📎 Attach image or file** (Claude only). Screenshots, photos of a training plan, `.txt`,
  `.csv` or `.gpx` files (up to 20 MB each).

---

## 3. Look at an activity and discuss it

Open **Activities**. Filter by type or date range at the top, and click a row to open its
detail panel.

The panel shows:

- **Analysis Summary.** The rule-based one-paragraph summary.
- **Computed Metrics.** Badges for pace fade, cardiac decoupling, efficiency score and
  climbing. Hover a badge for its definition. Decoupling reads `n/a` when it isn't meaningful
  (rides, hilly runs, activities under 20 minutes).
- **HR Zone Distribution.**
- **Planned.** The calendar workout this activity was matched to, with a link to **Open in
  Calendar →**.
- **Personal record** badges, if the activity set one.
- **Your Notes.** How you felt, the weather, what you were going for. The Deep Dive reads them.

### Run a Deep Dive

1. Optionally, write a few lines in **Your Notes** first ("legs heavy after yesterday's
   intervals, very windy").
2. Click **Run Deep Dive**. It takes 10–20 seconds.
3. You get a multi-paragraph analysis of pacing, heart-rate drift, cadence and climbing,
   judged against the workout you had planned that day, with practical notes for next time.

The report is saved. Click **Regenerate** under it to produce a fresh one.

### Take it to the coach

Click **Discuss in chat →** to open the Coach tab with this activity attached to your next
message. Then ask, for example:

> Was this a good long run for where I am in the block? Should next week's be longer?

---

## 4. Add your races

Races drive everything the coach plans, so add them before you ask for a plan.

1. Open **Calendar** and click the race date.
2. In the side panel, choose **Race** under *What are you adding?* (if the day already has
   entries, click **+ Add** first).
3. Fill in the sport, distance, an optional **Goal time** (for example `1:45:00`) and a
   **Priority**:
   - **A**: the goal race of the season
   - **B**: important, but not one to taper fully for
   - **C**: a training race or tune-up
4. Optionally paste a Strava or RideWithGPS **route URL**.
5. **Save**.

A goal time also helps the load figures: the app counts a race by its goal time, and a race
without one leaves that week's planned load reading low.

While you're on the calendar, block out days you can't train: click a day and tick **Mark as
blocked (unavailable)**. The coach and the plan generator both work around blocked days. For a
trip, add a **Travel** entry.

You can also just tell the coach: *"I've entered the Valencia Half on 1 March as my A race,
goal 1:38."*

---

## 5. Build a training plan

There are two ways to get a plan onto your calendar. Both check the plan against your
training load before anything is saved.

### Option A: Generate block (review before saving)

Use this for a fresh block of a few weeks.

1. On **Calendar**, select the range. Click the first day, then **Shift-click** the last day.
   The side panel shows *"N days selected"*.
2. Click **Generate plan for selection**. (The **✨ Generate block** button at the top also
   works, but it starts with today as both the start and end date, so set the dates in the
   dialog.)
3. In **Notes (optional)**, add anything the coach should know: *"Focus on hills, I have a
   hilly 50K in May"* or *"Travelling 10–12 Feb, keep it light."*
4. Choose what to do with workouts already in that range:
   - **Replace existing workouts** in the range
   - **Add alongside existing workouts**
5. Click **Generate**. It usually takes 15–45 seconds, and longer blocks can take a minute or
   two. Keep the dialog open.
6. Review the proposal: a summary, any notes (for example a week ramping well above your
   recent normal weeks, or a block whose biggest week stays below your proven level), and
   every workout with its distance, duration, intensity and description. Workouts that would
   replace an existing one are flagged **⚠ replaces …**.
7. Click **Accept & Add to Calendar** to save it all at once, **Regenerate** to try again, or
   **Discard**.

### Option B: Ask the coach in chat

Use this to adjust a plan or to plan with some back and forth.

> Plan the next three weeks for me. Four runs a week, long run on Sundays, one quality
> session. Keep Wednesday as a rest day.

> I'm sick and need to skip the next three days. Rework this week.

> Move my long ride to Saturday and make Sunday an easy spin.

The coach writes directly to the calendar. Each change it makes is applied as one atomic set,
and the reply ends with **Calendar updated** and a link. Each change is checked. A
change is refused outright, with nothing saved, if it puts a workout on a blocked day or a race
day, or two scored workouts of the same sport on one day. A sharp jump against your recent
normal weeks, a fourth loading week without a down week, or a run much longer than your
longest of the last 30 days is saved, but comes back to the coach as an advisory note. The
coach keeps the plan when your proven level supports it and says why, or adjusts it. These
checks are screening heuristics, not injury predictions.

**Which to use?** *Generate block* when you want to see the whole block before anything
changes. *Chat* for edits and when you want to discuss the plan.

---

## 6. Work with the calendar day to day

### Reading the grid

- Each row is a week. The box at the end of the row has the week's totals. Click it for a
  day-by-day breakdown and **Ask coach about this week**. A gold ★ marks a perfect week.
- Planned entries are coloured by type, and your Strava activities appear next to them.
- Past workouts show their **compliance**: *Completed*, *Shortened*, *Missed* or *Not scored*
  (yoga, rest, races).
- A ⚠ badge marks a conflict: a workout planned on a blocked day or on a race day.
- The **load strip** above the grid shows **CTL** (fitness, 42-day), **ATL** (fatigue, 7-day)
  and their **Ratio** (context, not a limit). Load is measured in **hours of moving time**: all
  sports in Hybrid mode; in Running or Cycling mode, that sport plus cross-training and strength.
- Each week's box shows its **ramp** against your recent normal weeks, for example *−12% vs
  recent*. A travel week, race-taper week or unusually low week shows **off** instead and is
  left out of the comparison; it counts as a down week.
- The **streak strip** shows your current plan streak.

### Editing

- **Add:** click a day and choose Workout, Race, Rest, Travel or Other. (On a day that already
  has entries, click **+ Add** first.)
- **Edit or delete:** click the entry in the day panel, then **Edit** or **Delete**.
- **Move:** drag an entry to another day.
- **Ask coach** (workouts): opens the chat with a drafted question. For an upcoming workout it
  asks what the session is for. For a done one it asks how it went against the plan, with the
  matched activity attached. Edit the draft or send it as is.

### Per-workout helpers

In the day panel of a planned workout:

- **Nutrition: Get advice.** Calorie and hydration targets for before, during and after,
  based on the workout and your profile.
- **+ Add route → Analyze Route.** Paste a Strava or RideWithGPS route URL (runs and rides).
  The app checks whether the route's distance, climbing and terrain fit the workout's purpose,
  and suggests changes.
- **Structured workout (% FTP).** For ride workouts the coach can attach an interval
  structure. **Download .zwo for Zwift** exports it.

### Races after the fact

Races are never matched to activities automatically. After the race, open it on the calendar
and link the activity under **Race result**.

---

## 7. Track progress

### Compliance and streak

- A planned workout counts as **completed** when a matching activity is on the same day, and
  as **shortened** when that activity was noticeably shorter than planned.
- A **week is hit** when you completed at least one scored workout and missed at most one.
  Weeks with nothing scored pause the streak rather than end it. More than two paused weeks in a
  row end it. The current week never counts until it's over.
- **Analytics → Progress** shows your current and best streak, how this week is going, and
  personal records per sport. Records start once a sport has 6 activities over 28 days.

### Insights

**Analytics → Insights** (Running, Cycling and Hybrid modes):

1. Click **Generate insights**. It takes 10–20 seconds.
2. You get a status (*Building*, *Maintaining*, *Peaking*, *Overreaching*, *Recovering*,
   *Detraining*, or *Not enough data*), a headline, **Findings** that cite specific numbers, and **Do next**
   recommendations.
3. Click **Plan this with coach** next to a recommendation to open the chat with a drafted
   request. It isn't sent until you send it.

The numbers are calculated by the app: the last 4 complete weeks against the 8 before them.
The model only interprets them. The readout is saved and marked stale when new activities
arrive or a new week starts. **Refresh** regenerates it.

### Charts

**Training Load** has weekly volume, CTL/ATL and climbing. **Performance** has efficiency
trends (split into Run and Ride in Hybrid mode). Use the date filter to change the window.

---

## 8. Manage what the coach remembers

Open **Memories**. Each memory has a category, its content, and optionally:

- **State**: *Current*, *Temporary* (with an end date, for example "knee niggle, easy only
  until 20 Dec") or *Superseded* (kept, but no longer sent to the coach).
- **Topic**: give facts that replace each other the same topic (for example
  `running_intensity`). Within a topic, the most recent start date wins, and a temporary fact
  wins a tie. When a temporary fact ends, the standing fact applies again.
- **Start and end dates.**

Injury notes and temporary facts are always sent to the coach. The others are ranked and
trimmed if the prompt gets too large.

Click **Review for staleness** from time to time. The coach suggests memories that look out of
date, and you can archive the ones you choose. **Show superseded memories** brings back old
facts.

If the coach keeps getting something wrong, check here first: a stale memory is the most common
cause.

---

## 9. A weekly routine

A routine that gets the most out of the app:

1. **After each session:** sync (**Activities → Sync Activities**), add a line in **Your
   Notes**, and run a Deep Dive for key sessions.
2. **End of the week:** click the week's totals box → **Ask coach about this week**. Discuss
   what went well and what to change.
3. **Every few weeks:** check **Analytics → Insights** and act on a recommendation with
   **Plan this with coach**.
4. **Before each new block:** update your goals in **Profile**, check your races and blocked
   days, then generate the next block.

---

## 10. Lifting mode

With HEVY connected (see [Getting Started](getting-started.md#10-optional-connect-hevy-for-lifting)),
switch **Settings → Mode** to **Lifting**:

- **Activities** lists HEVY workouts with volume, working sets, average RPE, estimated 1RMs and
  muscle groups. **Run Deep Dive** analyses a session's sets.
- **Analytics** shows lifting charts (volume and working sets by muscle group).
- **Coach** talks about progressive overload, volume and programming, and has its own chat
  history.
- The **Calendar** tab is hidden in Lifting mode.
