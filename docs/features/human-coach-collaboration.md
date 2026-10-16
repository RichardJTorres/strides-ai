# Human-coach collaboration

Status: Proposed feature specification · v1

## Purpose and success criteria

Help athletes use Strides AI alongside a human coach: understand prescribed workouts,
consider alternatives, retain control of their calendar, and prepare a useful weekly
update for their coach.

The feature serves anyone following an external training plan, whether supplied by a
professional coach, club, friend, or published program. A coach account is not required.

Success means:

- An athlete can identify who prescribed a workout and whether it is protected.
- AI explanations and suggested alternatives cannot silently change protected sessions.
- The athlete can review a concrete change before applying it, without implying that
  their human coach approved it.
- A weekly report clearly distinguishes the prescription, subsequent changes, actual
  training, athlete comments, and questions.
- Sharing requires a separate action by the athlete; generating a report sends nothing.

## Athlete experience

### Enable collaboration

Add **Human coach collaboration** to Settings, off by default. Enabling it shows a short
explanation: “AI can explain your plan and propose changes. You decide what gets applied.”
An optional coach/program name is a display label, not an invitation or account connection.
The setting applies to the shared calendar across coaching modes.

When enabled, all AI calendar changes require review, including changes to unprotected
workouts. Protection remains enforced even if collaboration mode is later disabled.
Disabling the mode neither unlocks sessions nor applies outstanding proposals.

### Identify and protect workouts

The workout editor offers **Coach-prescribed**, **Athlete-created**, and **AI-generated**
origins. A manually created workout defaults to Athlete-created; selecting Coach-prescribed
turns protection on by default. An athlete can explicitly turn protection off. Existing
workouts migrate to **Unspecified**, retaining their content and remaining unprotected;
never infer their origin from descriptions or past conversations.

The calendar badge shows origin and a lock icon; the detail panel also shows optional
coach/program label and the latest modification's actor and date. Label and protect
existing sessions individually or through a calendar date-range action. Range actions
show the affected sessions before applying and do not create workouts on empty dates.

Origin records the prescription's source, not whoever last touched the row. Editing a
coach session preserves Coach-prescribed and adds modification history. Accepting an AI
alternative to that session shows “Coach-prescribed · modified with AI.” The athlete may
correct an origin explicitly; record that correction in history. Only the athlete can
change origin or protection. AI tools cannot unlock or relabel an existing workout.

### Understand or adapt a prescribed session

The workout detail panel adds two actions:

- **Explain this workout:** Open coaching chat with the selected date, workout snapshot,
  origin, protection, and relevant training context. Ask the AI to explain its likely
  purpose and execution. Distinguish inferred purpose from instructions actually supplied
  by the coach. This action has no calendar side effects.
- **Suggest an alternative:** Open the same contextual chat with an optional reason, such
  as limited time, fatigue, unavailable equipment, or travel. Ask for the intended stimulus,
  a practical alternative, and what differs from the prescription. A suggestion remains
  advice until the AI creates a reviewable proposal.

Resolve the selected workout fresh when admitting the chat turn. Preserve the snapshot in
that turn so “this workout” stays unambiguous. If deleted before admission, show an error
and ask the athlete to select another workout.

### Review proposed changes

In collaboration mode, the existing AI plan-update tool creates a pending proposal rather
than writing the calendar. Generated training blocks use the same proposal workflow.
Outside collaboration mode, an AI batch touching any protected session also becomes a
proposal in its entirety. Batches affecting only unprotected sessions retain current behavior.

A proposal card opens a review panel showing all additions, edits, removals, and moves,
with before/after values and a concise reason. Highlight affected protected sessions.
A move is an atomic removal and addition, preserving origin, protection, and source label.
An occupied destination is an explicit replacement requiring review; never silently evict it.

The athlete can **Apply proposal** or **Discard**. V1 applies the whole proposal; selecting
individual changes is out of scope. For protected sessions, applying requires an unchecked
acknowledgment: “I understand this changes a protected prescription.” This is the athlete's
approval, not the human coach's. Applying is a one-time override; the session stays protected.

Direct athlete edits and deletes use the same before/after review when a protected session
is affected. Unprotected manual edits keep the existing save experience. Bulk relabeling,
unlocking, and editing must also show protected sessions and require acknowledgment.

Pending proposals survive refresh. A new proposal does not silently replace an older one.
If any affected date changes after a proposal was created, block the entire application and
show “Plan changed since this suggestion. Review a fresh suggestion.” Reapplying an already
applied proposal returns its existing outcome without duplicating edits or history.

## Weekly update for a coach

Add **Weekly coach update** to Calendar. Default to the previous Monday–Sunday in the
app's calendar timezone; allow selecting any Monday-starting week. The report covers all
sports because the calendar is shared, including training hidden by the current coaching mode.
Show timezone, date range, generation time, and units in the preview.

The report contains:

1. **Overview:** completed sessions, duration, distance separated by sport, elevation, and
   existing compliance results. Label those results as estimates from activity matching.
2. **Daily plan versus actual:** the prescription entering the week, final plan, and actual
   sessions. Include every actual activity once, including unplanned and multiple activities
   on a day. Describe unmatched days as “No matching activity recorded,” not proof of skipping.
3. **Changes:** date, before/after prescription, athlete or AI actor, recorded reason, and
   whether a protected session was changed. Include deleted sessions and changed dates.
4. **Athlete notes:** saved activity notes and an editable weekly reflection. Include comments
   only when their preview checkbox is selected; deselection affects export, not stored notes.
5. **Questions for my coach:** an editable list stored with that week. AI may suggest questions
   on request, but must not replace athlete text or include suggestions without acceptance.

The initial prescription is the last recorded state before Monday, or the first creation
within the week if added later. Show late additions as such. If history predates feature
installation, label the available plan as “History unavailable before tracking began”; never
invent an original prescription or earlier changes. Show compliance against the final plan,
with changes separately visible so retrospective edits do not conceal the original record.

Preview and export use deterministic calculations and athlete-authored text; generating a
report requires no LLM call. The athlete can download **Markdown** or copy the rendered text.
Export exactly the previewed snapshot, including selection choices. Do not automatically
include chat transcripts, memories, profile health information, or account credentials.
There is no email, public link, automatic send, coach portal, or scheduled report in v1.

## Data and implementation contracts

### Persistence and write enforcement

Extend planned workouts with origin (`coach`, `athlete`, `ai`, `unspecified`), protection,
optional source label, and a revision. Keep the existing one-workout-per-date constraint.
New AI-created sessions receive AI origin from the server, not model-supplied attribution.

Add append-only change records containing change-set ID, date, revision, before/after
snapshots, actor (`athlete` or `ai`), timestamp, optional reason, and proposal ID. Track origin,
protection, and source-label changes too. Retain date revisions after deletion to detect
concurrent delete/recreate operations. Seed current snapshots at migration time and record
that history starts there; do not backdate them as original prescriptions.

Store proposals with operations, affected-date base revisions, reason, origin of the proposed
changes, timestamps, and state (`pending`, `applied`, `discarded`). Store weekly reflections,
questions, and note-selection preferences separately from synced activity data.

All calendar writes—including single-day endpoints, bulk acceptance, database facade calls,
and every LLM provider's plan tool—must use one mutation service. This service validates
protection and revisions, assigns trusted actor/origin, invalidates affected nutrition/route
caches, writes history, and commits the complete batch in one transaction. A blocked,
invalid, or stale operation changes nothing. Prompt instructions supplement this enforcement;
they are not the protection mechanism. Derived analysis cache writes do not change a
prescription and do not require unlocking it.

The AI execution path has no access to user approval flags. Approval is available only through
an explicit athlete review request with matching revisions. Existing request bodies cannot
bypass protection by omitting new fields. Preserve the current local single-user trust model;
remote authentication and multi-user permissions are outside this feature.

### Interfaces

- Extend calendar responses with origin, protection, source label, and revision. Manual and
  bulk writes accept expected revisions and an explicit protected-change acknowledgment;
  reject stale or unacknowledged protected writes with HTTP 409 and structured conflict dates.
  Old clients may continue writing unprotected dates; protected writes must fail closed.
- Add proposal list/detail/create endpoints and explicit apply/discard endpoints under
  `/api/calendar/proposals`. Apply checks all revisions again inside the transaction.
- Keep the AI tool's existing `set`/`delete` operations; add optional reason. Its server-side
  result distinguishes `applied` from `proposed`, including a proposal ID when applicable.
  Surface a separate proposal SSE event/card; emit the existing plan-updated event only after
  a committed calendar change. Support Claude, OpenAI, Gemini, and Ollama consistently.
- Add optional selected-workout date to chat admission and include origin/protection in
  upcoming-workout context and plan-generation input.
- Add weekly-update read/save/preview endpoints keyed by week-start date. Preview returns a
  report snapshot and export content; downloading/copying uses that same snapshot. Saving
  reflections and exporting reports never edits the training plan.

### Delivery sequence

1. Add migration, history, revisions, and centralized write enforcement; exercise every writer.
2. Add workout origin/protection controls and manual protected-change review.
3. Add persistent AI proposals and contextual explanation/alternative actions across providers.
4. Add weekly report preview, reflection/questions editor, and Markdown/copy export.

## Acceptance and test scenarios

- A new coach session defaults to protected; athlete and AI sessions receive correct origins.
  Legacy sessions retain content and migrate without fabricated attribution.
- AI cannot edit, delete, move, relabel, or unlock a protected session through any provider,
  direct CRUD wrapper, generated block, or mixed bulk request. A protected move preserves its
  metadata and cannot overwrite an occupied destination without review.
- Explanations leave the calendar unchanged. Collaboration-mode changes always become pending
  proposals; outside it, mixed protected/unprotected batches are proposed without partial writes.
- Athlete approval applies exactly the reviewed batch, retains protection, and creates accurate
  audit records. Discard has no plan effects; duplicate apply is idempotent.
- Editing any affected date—including delete/recreate—from another tab makes a proposal stale.
  Failed validation, conflicts, and interrupted requests do not partially commit a batch.
- Reports include original/final prescriptions, deletions, unplanned and multiple actual
  activities, modification reasons, notes, and questions without double-counting actuals.
- Empty, current/incomplete, historical, and cross-year weeks render correctly. Unavailable
  history and estimated compliance are explicit; distance is not combined across sports.
- Deselected notes and private profile/chat/memory data never enter export. Markdown and copied
  text match the preview; report generation/export performs no outbound sharing request.
- Calendar badges, protected review, proposal actions, and report export work on desktop and
  mobile. Add a mobile Calendar entry (direct tab or More menu); it is currently omitted from
  mobile navigation. All controls remain keyboard accessible and text labels explain lock state.

## Deferred capabilities

Coach accounts and messaging, automatic plan imports, third-party calendar connections,
multiple planned sessions per day, full subjective-readiness tracking, partial proposal
acceptance, PDF generation, and scheduled delivery are separate features. V1 uses existing
activity notes and adds only weekly reflection/questions.
