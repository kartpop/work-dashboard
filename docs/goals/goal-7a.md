# Goal 7a — Daily-driver polish: scratchpad + tasks UX, Doc formatting, rename to "Dashboard"

**One line:** Friction fixes from daily use — a mis-fire-proof capture (deferred-capture undo
toast), a taller editor with a bounded Recent list, at-a-glance date-urgency color cues on both
task panels, breathing room + delimiters between Doc notes, and the app/repo renamed from
"Work Dashboard" to **"Dashboard"**.

## Intent / acceptance bar

Pure polish on shipped surfaces — **no new Google write surface, no new LLM behavior, no schema
change**. The bar: the dashboard *feels* right at a glance — an accidental Shift+Enter is
recoverable in one click, the editor is big enough to think in, overdue-vs-today-vs-tomorrow reads
from color before reading a date, and the notes Doc reads as separated entries, not a run-on wall.

## What ships

1. **Deferred-capture undo toast (scratchpad).** Shift+Enter (and Cmd/Ctrl+Enter) still captures:
   the editor clears immediately and a ~5s toast shows **"Captured — Undo"**, but the
   `POST /scratch` is **held until the undo window closes** (the g4a deferred-delete pattern in
   reverse). **Undo restores the captured text with zero backend writes** — undo-by-never-sending;
   the append-only store is untouched, no delete endpoint exists or is added. If the user typed new
   text during the window, Undo prepends the captured text above it (blank line between). A POST
   failure after the window → error shown + text restored by the same prepend rule. Known,
   accepted: **Route now** clicked inside the window won't include the still-held capture.
2. **Editor / Recent proportions.** The editor is much taller by default — **≥60% (target
   ~60–70%) of the scratchpad column**, min ~10 visible rows. RECENT takes the remainder with its
   **own scrollbar**, and shows **unresolved entries (unrouted + in-review) first, then only the
   ~5 most recently routed/resolved as a dimmed confirmation tail** — nothing older. Client-side
   filtering of the existing `GET /scratch` is fine (or a `limit`/`state` query param — keep the
   endpoint dumb either way).
3. **Date-urgency color cues (both pinned task panels).** Each bucket section gets a **faint tint
   on the header row + a 3px colored left edge** running down that bucket's items: Overdue = light
   red, Today = light green, Tomorrow = light yellow; all later buckets and `NO_DATE` stay plain.
   Simultaneously **demote group boxes to a hairline light gray** so the date signal dominates.
   Very low saturation — a cue, not decoration. Exact values are the implementer's choice.
4. **Task-panel height caps.** My Tasks and Follow-ups get a max height (viewport-bound) with an
   internal scrollbar; the panel header (title + refresh) stays visible while the list scrolls.
5. **Doc note separation.** `insert_note` adds vertical spacing between entries and a **light-gray
   horizontal delimiter**. The Docs API has no horizontal-rule request — use an empty paragraph
   styled with a light-gray `borderBottom` via `updateParagraphStyle` (plus
   `spaceAbove`/`spaceBelow`). Still strictly insert-only — the AST guardrail test must keep
   passing unchanged. Applies to **new notes only** (existing Doc content is never restyled).
6. **Rename to "Dashboard".** Every *live* occurrence of "Work Dashboard" / "work-dashboard" /
   "work dashboard" → "Dashboard" / "dashboard": the frontend `<h1>` (`DashboardPage.tsx`) and
   `<title>` (`index.html`), the FastAPI `title` (`main.py`), the bootstrap Doc title →
   **`Dashboard — Notes`** (`bootstrap.py`), README, CLAUDE.md, `docs/`, `.claude/` rules/skills,
   the seed doc (incl. the repo URL once renamed), and the future plugin name `work-dashboard-dev`
   → `dashboard-dev` wherever planned. **Historical goal briefs (goal-0 … goal-7) and the ADR stay
   as written** — they're records, not live docs.
7. **Owner steps** — write `docs/goals/goal-7a-owner-steps.md`:
   - Rename the GitHub repo to `dashboard` (repo Settings → General; old URLs auto-redirect).
   - `git remote set-url origin git@github.com:kartpop/dashboard.git` (or the https form).
   - **Optional** local-folder rename, with the caveat spelled out: Claude Code keys project
     history/memory/scratchpads to the absolute path — renaming the folder resets session
     continuity. Recommended: keep the local folder name, or accept the reset knowingly.
   - Manually rename the existing notes Doc in Drive to "Dashboard — Notes" (`NOTES_DOC_ID` in
     `.env` is unchanged — the title is cosmetic).

## Locked decisions (2026-07-07)

- **Shift+Enter stays.** Mis-fire recovery = deferred capture + undo toast, not removing the
  binding. Undo works by never sending — append-only holds, forever no scratch-delete endpoint.
- **RECENT = unresolved + ~5-item routed/resolved tail**, dimmed, height-capped, scrollable.
- **Color treatment = header tint + left edge**, not full-section washes. Groups → hairline gray.
- **Panel heights are CSS-only and ephemeral** — no `ui_prefs` (that's g9a).
- **Delimiter = `borderBottom` paragraph**; no H2/date headings in the Doc (explicitly deferred).
- **Rename is live-docs-wide; history untouched.** Git history/commit messages are never rewritten.

## Out of scope (do not build)

- The calendar header strip — that's **goal 7b**.
- H2 date grouping in the notes Doc; restyling existing Doc content in any way.
- `ui_prefs` persistence of panel sizes or Recent filters (g9a).
- DragOverlay / DnD rough-edge fixes (tracked in `tasks-panel.md`).
- Any router/classifier/write-surface change. The write set stays exactly
  `{create_task, reschedule, append_note}`.

## Acceptance criteria

- **Capture undo:** Shift+Enter clears the editor and shows the toast; Undo inside the window
  restores the exact text and **zero** `POST /scratch` calls fire; letting the window lapse fires
  **exactly one** POST; capture → type new text → Undo prepends correctly; a failed POST restores
  the text and shows an error.
- **Proportions:** editor ≥60% of the scratchpad column by default; RECENT scrolls independently
  and shows all unresolved + at most ~5 dimmed routed/resolved entries.
- **Color cues:** Overdue/Today/Tomorrow carry the tint + edge in both pinned panels; later
  buckets plain; group boxes hairline gray. This is a **visual AC — screenshot review required**
  (the g4 lesson: functional checks can't judge visual quality).
- **Height caps:** My Tasks and Follow-ups scroll internally with the panel header visible.
- **Doc:** a newly routed note lands with visible spacing + a light horizontal line separating it
  from the previous note; the AST insert-only test passes unchanged; the bootstrap (fresh run)
  titles the Doc "Dashboard — Notes".
- **Rename:** a case-insensitive grep for `work.?dashboard` over the repo matches only historical
  goal briefs / the ADR / git history; app title, page title, API title, README, CLAUDE.md, seed
  all say "Dashboard".
- `goal-7a-owner-steps.md` exists with the GitHub + Drive steps in order.
- `tsc`, frontend build, and all backend tests pass; capture→route→task/note behavior, the g6
  layout, and all g4a task behaviors are intact.

## Harness upkeep (closing checklist — friction-driven only)

- Two deferred-write undo toasts now exist (delete g4a, capture 7a) — if a shared pattern emerged,
  note the convention in `frontend.md`; don't force an abstraction.
- `writes.md` / `google-api-integration` only if `insert_note`'s documented shape changed
  (delimiter paragraph) — one-line touch-ups, not rewrites.
- Record rule fire/no-fire (`/context`) on scratch-panel and docs-module edits.
- Refresh root `README.md` + `docs/api-reference.md` (rename, capture-undo, Recent behavior);
  update `docs/goals/README.md`; wrap-up to the planning chat (seed status/ladder update).
- **Parallel note:** 7a and 7b are near-disjoint *except the header file*
  (`DashboardPage.tsx`/`index.html`) — if ever run in parallel worktrees, land 7a's rename first.
  Sequential fresh sessions is the default.
