# Goal 7c — Daily-driver fixes: create-row date picker, instant routing, note one-liners, editable review queue

**One line:** Four small items real daily use surfaced: the add-task row gains the date picker;
capture routes **immediately** (the cron becomes a backstop); routed notes get an LLM one-liner
above the verbatim text; review-queue items become editable in place (fields follow the type the
user picks, and `event` leaves the type choices).

## Intent / acceptance bar

These are all "the machinery exists, the last step is missing" gaps. The bar: I type a thought,
Shift+Enter, and within seconds RECENT shows it *filed* — task created or note in the Doc — not
"waiting for the next tick". When the router punts to review, I fix it up right there (retitle,
set a date, edit the note) instead of round-tripping through the task panel afterwards.

## What ships

- **1. Date picker on the create row.** The add-task input in My Tasks / Follow-ups shows the
  existing date-picker control (g4a component) next to the description box. Date set → create
  lands with that due date (create + the existing reschedule path, or due-date-on-insert —
  implementer's call, one orchestrated result either way); untouched → today's default behavior
  (`NO_DATE`) stands.
- **2. Instant routing on capture.** `POST /scratch` persists the entry (unchanged, capture can
  never be lost), then **routes it inline** in the same request via the existing
  `route_entry` — response returns the routed state so RECENT renders it filed immediately.
  - The ~5s client-side undo hold (7a) is untouched — it already absorbs the added LLM latency
    invisibly (the POST fires after the hold; nothing user-facing blocks on the classifier).
  - A classifier/Google failure leaves the entry `UNROUTED` and still returns 2xx — capture
    succeeded; filing retries later.
  - **The scheduler demotes to a retry backstop** (crash/downtime recovery, failed routes):
    stretch `ROUTER_SCHEDULER_INTERVAL` default to ~15 min; `route-now` unchanged.
- **3. Note one-liner.** The classifier's structured output gains a `summary` field — a single
  phrase/one-liner capturing the note's essence (same one Haiku call, no second request). A
  routed note's Doc entry becomes: **H3 timestamp → one-liner → verbatim raw text** → the 7a
  delimiter. Style the one-liner visually distinct from the raw text (bold). Empty/missing
  summary → skip the line, never block the write.
  - **This deliberately relaxes the g7 "verbatim, LLM never authors Doc content" lock** — see
    Locked decisions. The *raw text* stays verbatim; the one-liner is the only LLM-authored line.
- **4. Editable review-queue items.** A review item's type choice is now **`task` | `note` only**
  (drop `event` from the UI — the classifier may still emit it; it lands in review where the user
  picks task or note). The fields shown follow the selected type, all editable in place:
  - **task** → title (prefilled from the proposal), description/notes, date picker.
  - **note** → the note text and the one-liner, both editable.
  The confirm endpoint gains optional override fields; deterministic code still does the write
  with whatever the user confirmed. Confirm-as-task / confirm-as-note write paths are the
  existing ones (`create_task`+`reschedule` / `append_note`) — no new writers.

## Locked decisions (2026-07-07)

- **Routing is synchronous in `POST /scratch`** — not fire-and-forget, not a queue. The 7a undo
  hold already hides the latency; the response carrying the routed state is the payoff.
- **The verbatim lock is amended, not broken silently:** the router write set stays exactly
  `{create_task, reschedule, append_note}`, insert-only, LLM-proposes/code-disposes — but the
  Doc entry now contains **one LLM-authored line** (the summary) above the verbatim raw text.
  `router.md`, `writes.md`, and the eval set get matching revisions **in the same commit as the
  code** (the g5/g7 pattern). Notes stay graded on destination; the summary is not eval-graded
  (spot-check only — it's cosmetic, not a write decision).
- **`event` is a review-queue-only concept now**: still a valid classifier output (routes to
  review), no longer a user-selectable resolution type. Calendar stays read-only.
- **No delete/edit of already-routed entries** — editing happens only in the review queue,
  before the write. The append-only store and the no-delete-endpoint stance (7a) stand.

## Out of scope (do not build)

- Any new router write capability (no calendar writes, no Doc edits/deletes).
- Re-routing or editing entries that already routed.
- Batch review actions, review-queue search/filters.
- Streaming/websocket updates — the response-carries-state + existing polling is enough.

## Acceptance criteria

- Create row: picking a date creates the task in that date bucket (one visible result, optimistic
  per frontend conventions); leaving it untouched preserves current behavior.
- Capture → the POST response carries the routed state; a high-confidence task exists in Google
  Tasks (and appears in the tasks panel) without waiting for any scheduler tick; a
  high-confidence note is in the Doc likewise. Classifier failure → entry visible as unrouted,
  capture never lost (test with the API key unset).
- Doc entry shape: timestamp, one-liner (bold), verbatim raw text, delimiter — unit
  test on the request-builder; missing summary degrades to the g7 shape.
- Review queue: type choice offers exactly task | note; switching type switches the editable
  fields; confirmed edits are what lands (task title/notes/date; note text/one-liner) —
  endpoint tests for the overrides.
- The AST write-dependency test still pins `{create_task, reschedule, append_note}` unchanged;
  eval gate still passes after the schema gains `summary`.
- `tsc`, frontend build, and all backend tests green.

## Harness upkeep (closing checklist — friction-driven only)

- `router.md` + `writes.md`: the one-LLM-authored-line amendment (same commit as the code).
- Eval set: schema change only unless grading friction demands cases.
- `verifier-web`: instant-routing check (capture → task exists, no route-now call).
- Record rule fire/no-fire (`/context`); wrap-up to the planning chat.
