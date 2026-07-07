# Goal 7b — Calendar strip: today's meetings in the header

**One line:** The header whitespace right of the **Dashboard** title becomes a horizontal
day-strip — a 9a–6p axis with hour ticks, meeting blocks sized/positioned proportionally, a thin
red now-marker, chevrons to reach early/late meetings, and **prev/next-day navigation** with a
Today jump-back; click copies the Meet link, hover shows the details. The strip **replaces** the
below-fold calendar panel, and the dashboard slims to `My Tasks | Follow-ups | Scratchpad`.

## Intent / acceptance bar

Glanceable "what's next / am I late" without scrolling to the below-fold panel. The bar: at 12:25
I glance up, see the red line just past the last morning block and the 1:1 at 3, single-click the
block and the Meet link is on my clipboard, ready to paste. Read-only — the calendar surface gains
**zero** write capability.

## What ships

- **Backend: day-window fetch.** Extend `app/google/calendar.py` (fetch+reshape only; same sync
  `_fetch_*` / `async def` + `asyncio.to_thread` split): `get_day_events()` with
  `timeMin`/`timeMax` = **today's IST day bounds**, `singleEvents=True`, `orderBy="startTime"`.
  Reshape per event: `{id, title, start, end, all_day, meet_link, location, attendees:
  [{name, email, response_status}]}`. `meet_link` = `hangoutLink`, falling back to
  `conferenceData.entryPoints` (the `video` entry point's `uri`); neither → `null`. New thin
  endpoint **`GET /calendar/day?date=YYYY-MM-DD`** — the optional `date` param (IST calendar
  date; default = today) serves the day navigation below; invalid date → 400 in the standard
  error envelope.
- **Multi-calendar fetch (added 2026-07-07).** The owner's **work calendar is shared into the
  personal account** (read-only, full details) — shared-calendar events do **not** appear under
  `calendarId="primary"`; each shared calendar is its own entity queried by its calendar ID (the
  sharing account's email). So `get_day_events()` fetches the day window from `primary` **plus
  every ID in `EXTRA_CALENDAR_IDS`** (new comma-separated env var in `backend/.env`; unset or
  empty → primary-only, no crash), merges, and sorts by start. **Dedupe by `iCalUID`** — an event
  where the personal address is an invited attendee appears in *both* primary and the work
  calendar; keep the primary copy. Extra calendars are **best-effort**: a per-calendar fetch
  failure (share revoked, bad ID) logs a warning and the rest of the strip still renders; a
  primary failure is still an error. Calendar IDs are **config-only** — never from LLM output or
  request payloads (same hygiene rule as the Docs IDs). No visual distinction between calendars on
  the strip (single accent tint stands).
- **Frontend: `CalendarStrip` in the header row.** The `<h1>` row becomes a flex header — title
  left, strip filling the remaining width. (Coordinate with 7a at `DashboardPage.tsx`: if 7a's
  rename hasn't landed, don't block on it.)
  - One horizontal axis, default window **09:00–18:00 IST**; hour ticks + labels below the line;
    meeting blocks above it, left offset and width **proportional to start time and duration**;
    truncated title inside the block; a single muted accent tint for all blocks.
  - **Now-marker:** a thin **red** vertical line with the time label above it — the only strong
    color on the strip. Recomputes every minute without a reload; hidden when "now" falls outside
    the visible window **or when the viewed day is not today**.
  - **Day navigation (added 2026-07-07)** — a compact row under the axis (per the owner's mockup):
    the viewed date centered (`Tuesday, 7 July`), flanked by prev/next-day pills showing weekday +
    day number (`« Mon 6` / `Wed 8 »`). Clicking a pill refetches `GET /calendar/day` for that
    date. When the viewed day ≠ today, a small **Today** button appears beside the date and jumps
    back. The viewed date is ephemeral — resets to today on reload (same rule as the shifted hour
    window). The ±1h chevrons keep shifting the *hour* window; the pills shift the *day*.
  - **Chevrons** at both ends shift the visible window by **1h per click**, clamped to
    00:00–24:00. The default window is stable on load — no auto-expand (chevrons, not stretching,
    reach a 7:30 or 19:00 meeting). A small hint when events exist beyond the visible window
    (dot/count) is the implementer's call.
  - **Overlaps:** stack into at most **two lanes**; beyond two, graceful overlap/truncation is an
    accepted rough edge.
  - **All-day events are excluded** from the strip (MVP — they'd span the whole axis).
  - **Click copies (amended 2026-07-07):** a **single click** on a block copies `meet_link` to
    the clipboard — one click, no menu, no extra step. **Every click gives visible feedback**: a
    small transient toast/snackbar — "Meet link copied" on success, "No Meet link for this event"
    when the event has none (never a silent no-op). Keep it clean: unobtrusive, auto-dismissing
    (~2s), one at a time; exact wording/placement is the implementer's call.
    **Open-in-new-tab becomes the secondary path**: an open affordance in the tooltip (or
    Alt+click, implementer's choice) still opens `meet.google.com` in a new tab — the g9b lock's
    "both paths exist" holds, primary/secondary swapped.
  - **Hover tooltip:** all relevant details, nicely formatted — full title, time range, attendees
    (name or email), location — plus the open-in-new-tab affordance.
  - **Height guideline:** the axis + day-nav row together stay compact (~80px, per the mockup) —
    the strip must not materially push the top row down. Below the g6a 1080px breakpoint, hide it
    or stack it sanely (match the existing stacking behavior).
  - **Refresh:** fetch on mount + every ~5 minutes (calendar changes are rare — don't inherit the
    45s task cadence). The now-marker ticks every minute independently of fetches.
- **Layout math as a pure function.** Extract `layoutBlocks(events, windowStart, windowEnd)` (or
  equivalent) as a pure, unit-tested function — proportional offsets/widths, lane assignment,
  window clipping — the strip's analog of `bulletEditor.ts`.
- **Dashboard slimming (added 2026-07-07).** With the strip carrying day navigation, the page
  keeps only what daily use touches:
  - **Remove the below-fold `CalendarPanel` entirely** — the component, the upcoming-events
    endpoint, and `get_upcoming_events` in `app/google/calendar.py` (dead code goes with it:
    tests, `docs/api-reference.md` entry). This closes g9b's "below-fold panel's fate" question.
  - **Remove the collapsed "Other tasks" section** (g6) — the dashboard becomes exactly
    `My Tasks | Follow-ups | Scratchpad`. Non-pinned lists lose their UI surface; the
    move-to-list menu still offers them (tasks can be sent there, just not viewed) — if daily
    use misses them, g9a's list-visibility chooser is the answer, not a revert.
  - **Scratchpad split → 70/30:** the editor defaults to **70%** of the scratchpad column and
    RECENT to **30%** (7a shipped "≥60%"; daily use wants more editor real estate). Same
    height-cap/scroll behavior otherwise.

## Locked decisions (2026-07-07)

- **Read-only.** `calendar.readonly` is already granted — **no scope change, no re-auth, no
  owner-steps file**; the startup scope assertion is untouched. This holds for the shared work
  calendar too: `calendar.readonly` covers every calendar shared *into* the personal account, at
  whatever permission level the share granted ("see all event details" → full fields).
- **Work calendar via `EXTRA_CALENDAR_IDS`** *(2026-07-07)*: the owner shared the work calendar
  into the personal account, so the day fetch merges `primary` + the configured extra calendar
  IDs (dedupe by `iCalUID`, extras best-effort). The owner's only step is putting the work email
  in `.env` — document it in the README, no owner-steps file needed.
- **Day navigation, not multi-day views** *(amended 2026-07-07; supersedes the "today only" lock)*:
  prev/next-day pills + a Today jump-back, one day rendered at a time; the now-marker shows only
  on today. The viewed date is ephemeral (resets to today on reload). No date picker, no
  week/agenda view.
- **The below-fold `CalendarPanel` is removed in this goal** *(amended 2026-07-07; was "g9
  decides")* — component, endpoint, and `get_upcoming_events` all go. Everything daily use needs
  lives in the strip.
- **"Other tasks" is removed; scratchpad split is 70/30** *(added 2026-07-07)* — the dashboard is
  exactly `My Tasks | Follow-ups | Scratchpad`; non-pinned lists stay reachable only via the
  move-to-list menu (g9a's visibility chooser is the future answer if that hurts).
- **Default window 9–6 fixed; chevrons — not auto-expand — reach outside meetings.**
- **Click copies the Meet link to the clipboard; opening in a new tab is the secondary path**
  *(amended 2026-07-07; supersedes "click opens, copy is secondary")* — daily use wants the link
  on the clipboard in one click; the open affordance lives in the tooltip (or Alt+click).
- No event modal, no RSVP/responses, no writes, no persistence of the shifted window (resets on
  reload).
- This goal **absorbs g9b's "Meet link + today" scope** — g9b shrinks to whatever residue daily
  use still wants (update `docs/goals/README.md`).

## Out of scope (do not build)

- Calendar writes of any kind (calendar stays read-only v1).
- Week/agenda/multi-day views, or a date picker — day navigation is prev/next/Today only.
- Persisting the viewed date or shifted window across reloads.
- Meeting notes / transcripts (Granola is g8).
- Attendee avatars, RSVP status colors, event-detail modals.

## Acceptance criteria

- `GET /calendar/day` returns today's (IST) events with the reshaped fields; with `?date=`, that
  day's events; invalid date → 400 envelope. Unit tests cover the IST day-bounds computation (for
  an arbitrary date, not just today) and meet-link extraction (`hangoutLink` present /
  `conferenceData` fallback / neither → `null`).
- With `EXTRA_CALENDAR_IDS` set, the response merges primary + extra-calendar events sorted by
  start, an event present in both (invited-attendee case) appears **once** (`iCalUID` dedupe),
  and a failing extra calendar degrades to a logged warning — primary events still return. Unset
  → primary-only, no crash. Unit tests cover merge, dedupe, and the unset fallback.
- The strip renders in the header row without materially increasing header height; block
  offsets/widths are proportional — verified by unit tests on the pure layout function **plus a
  screenshot review** (visual AC).
- The now-marker sits at the correct IST position, moves without a reload, and hides when out of
  window **or when viewing a day other than today**.
- Day navigation: prev/next pills show the adjacent days' weekday + day number and refetch on
  click; the centered label shows the viewed date; a **Today** button appears only when viewing
  another day and jumps back; reload resets to today.
- Chevrons shift the window by 1h, clamp at midnight both ends, and make an
  outside-the-default-window meeting reachable.
- Two overlapping events render in two readable lanes (constructed-overlap check).
- All-day events produce no blocks.
- A single click on a block with a meet link puts the link on the clipboard and shows a transient
  "copied" confirmation; a click on a block without one copies nothing and shows a "no Meet link"
  notice (no silent clicks either way); the secondary open path opens the link in a new tab; the
  tooltip shows title / time range / attendees / location, nicely formatted.
- No token/scope changes; the startup scope assertion still passes.
- **Slimming:** the below-fold `CalendarPanel`, its endpoint, and `get_upcoming_events` are gone
  (no dead code, `docs/api-reference.md` updated); the "Other tasks" section is gone — the page
  is exactly `My Tasks | Follow-ups | Scratchpad`; the move-to-list menu still offers non-pinned
  lists; the scratchpad editor defaults to ~70% of its column with RECENT at ~30%.
- Remaining panels (My Tasks, Follow-ups, Scratchpad) intact; `tsc`, frontend build, and all
  backend tests pass.

## Harness upkeep (closing checklist — friction-driven only)

- `google-api-integration` skill: add the day-window / `conferenceData` reshape note **only if**
  the module's shape earns it.
- `verifier-web` skill: add the strip's selectors/checks for the next goal's verification.
- Record rule fire/no-fire (`/context`) on calendar-module and frontend edits.
- Refresh `docs/api-reference.md` (add `GET /calendar/day` + `date` param; **remove** the
  upcoming-events endpoint) and `docs/goals/README.md` (g9b's calendar residue is now closed —
  the panel is removed here; note the "Other tasks" removal against g9a's residue).
- Wrap-up to the planning chat (seed status/ladder update).
- **Parallel note:** 7a and 7b are near-disjoint *except* `DashboardPage.tsx`/`index.html` — if
  run as the deferred parallel-worktrees rep, land 7a's rename first or freeze the header contract
  in both briefs. Sequential fresh sessions is the default.
