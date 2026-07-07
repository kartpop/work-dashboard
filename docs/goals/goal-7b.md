# Goal 7b — Calendar strip: today's meetings in the header

**One line:** The header whitespace right of the **Dashboard** title becomes a horizontal
today-strip — a 9a–6p axis with hour ticks, meeting blocks sized/positioned proportionally, a thin
red now-marker, and chevrons to reach early/late meetings; click opens the Meet link, hover shows
the details.

## Intent / acceptance bar

Glanceable "what's next / am I late" without scrolling to the below-fold panel. The bar: at 12:25
I glance up, see the red line just past the last morning block and the 1:1 at 3, and click straight
into the meeting from the strip. Read-only — the calendar surface gains **zero** write capability.

## What ships

- **Backend: day-window fetch.** Extend `app/google/calendar.py` (fetch+reshape only; same sync
  `_fetch_*` / `async def` + `asyncio.to_thread` split): `get_day_events()` with
  `timeMin`/`timeMax` = **today's IST day bounds**, `singleEvents=True`, `orderBy="startTime"`.
  Reshape per event: `{id, title, start, end, all_day, meet_link, location, attendees:
  [{name, email, response_status}]}`. `meet_link` = `hangoutLink`, falling back to
  `conferenceData.entryPoints` (the `video` entry point's `uri`); neither → `null`. New thin
  endpoint **`GET /calendar/day`**. The existing upcoming-events endpoint and the below-fold
  `CalendarPanel` are untouched.
- **Frontend: `CalendarStrip` in the header row.** The `<h1>` row becomes a flex header — title
  left, strip filling the remaining width. (Coordinate with 7a at `DashboardPage.tsx`: if 7a's
  rename hasn't landed, don't block on it.)
  - One horizontal axis, default window **09:00–18:00 IST**; hour ticks + labels below the line;
    meeting blocks above it, left offset and width **proportional to start time and duration**;
    truncated title inside the block; a single muted accent tint for all blocks.
  - **Now-marker:** a thin **red** vertical line with the time label above it — the only strong
    color on the strip. Recomputes every minute without a reload; hidden when "now" falls outside
    the visible window.
  - **Chevrons** at both ends shift the visible window by **1h per click**, clamped to
    00:00–24:00. The default window is stable on load — no auto-expand (chevrons, not stretching,
    reach a 7:30 or 19:00 meeting). A small hint when events exist beyond the visible window
    (dot/count) is the implementer's call.
  - **Overlaps:** stack into at most **two lanes**; beyond two, graceful overlap/truncation is an
    accepted rough edge.
  - **All-day events are excluded** from the strip (MVP — they'd span the whole axis).
  - **Click** a block → open `meet_link` in a **new tab** (`meet.google.com`; whether the browser
    hands it to a PWA/app is the OS's business — there is no reliable native deep link). No link →
    click is a no-op. A **copy-link path must exist** (the g9b lock: primary opens, secondary
    copies) — a copy icon in the tooltip or Alt+click, implementer's choice.
  - **Hover tooltip:** full title, time range, attendees (name or email), location, and the
    copy-link affordance.
  - **Height ~54px guideline** — the strip must not materially push the top row down. Below the
    g6a 1080px breakpoint, hide it or stack it sanely (match the existing stacking behavior).
  - **Refresh:** fetch on mount + every ~5 minutes (calendar changes are rare — don't inherit the
    45s task cadence). The now-marker ticks every minute independently of fetches.
- **Layout math as a pure function.** Extract `layoutBlocks(events, windowStart, windowEnd)` (or
  equivalent) as a pure, unit-tested function — proportional offsets/widths, lane assignment,
  window clipping — the strip's analog of `bulletEditor.ts`.

## Locked decisions (2026-07-07)

- **Read-only.** `calendar.readonly` is already granted — **no scope change, no re-auth, no
  owner-steps file**; the startup scope assertion is untouched.
- **Today only.** The below-fold `CalendarPanel` stays as-is (g9 decides its fate).
- **Default window 9–6 fixed; chevrons — not auto-expand — reach outside meetings.**
- **Click opens in a new tab; clipboard copy is the secondary path, never the primary.**
- No event modal, no RSVP/responses, no writes, no persistence of the shifted window (resets on
  reload).
- This goal **absorbs g9b's "Meet link + today" scope** — g9b shrinks to whatever residue daily
  use still wants (update `docs/goals/README.md`).

## Out of scope (do not build)

- Calendar writes of any kind (calendar stays read-only v1).
- Tomorrow / multi-day views, or date navigation beyond the ±1h window chevrons.
- Replacing or restyling the below-fold `CalendarPanel`.
- Meeting notes / transcripts (Granola is g8).
- Attendee avatars, RSVP status colors, event-detail modals.

## Acceptance criteria

- `GET /calendar/day` returns today's (IST) events with the reshaped fields; unit tests cover the
  IST day-bounds computation and meet-link extraction (`hangoutLink` present / `conferenceData`
  fallback / neither → `null`).
- The strip renders in the header row without materially increasing header height; block
  offsets/widths are proportional — verified by unit tests on the pure layout function **plus a
  screenshot review** (visual AC).
- The now-marker sits at the correct IST position, moves without a reload, and hides when out of
  window.
- Chevrons shift the window by 1h, clamp at midnight both ends, and make an
  outside-the-default-window meeting reachable.
- Two overlapping events render in two readable lanes (constructed-overlap check).
- All-day events produce no blocks.
- Click with a meet link opens it in a new tab; without one it's a no-op; the copy path works; the
  tooltip shows title / time range / attendees / location.
- No token/scope changes; the startup scope assertion still passes.
- Existing panels (tasks, scratchpad, below-fold calendar) intact; `tsc`, frontend build, and all
  backend tests pass.

## Harness upkeep (closing checklist — friction-driven only)

- `google-api-integration` skill: add the day-window / `conferenceData` reshape note **only if**
  the module's shape earns it.
- `verifier-web` skill: add the strip's selectors/checks for the next goal's verification.
- Record rule fire/no-fire (`/context`) on calendar-module and frontend edits.
- Refresh `docs/api-reference.md` (`GET /calendar/day`, the strip) and `docs/goals/README.md`
  (shrink the g9b entry).
- Wrap-up to the planning chat (seed status/ladder update).
- **Parallel note:** 7a and 7b are near-disjoint *except* `DashboardPage.tsx`/`index.html` — if
  run as the deferred parallel-worktrees rep, land 7a's rename first or freeze the header contract
  in both briefs. Sequential fresh sessions is the default.
