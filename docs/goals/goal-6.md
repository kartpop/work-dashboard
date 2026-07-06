# Goal 6 — MVP layout: pinned lists side-by-side + cross-list drag

**One line:** The dashboard becomes the daily screen: a full-width top row `My Tasks | Follow-up | Scratchpad`, tasks draggable *between* the two pinned lists (the g4 `move` write layer gains its drag surface), every other list stashed in a collapsed **Other tasks** section, calendar and the rest below the fold.

> **Objective shift (applies from this goal on):** the repo's primary objective is now **prod-usability for the owner's daily personal use**. Harness learning is secondary — no goal introduces a capability for its own sake anymore; `.claude/` files (rules, skills, agents) are updated at the **end** of each goal, friction-driven, via the closing checklist.

## Intent / acceptance bar
The bar: **"the dashboard opens to the two lists I actually work from, with the scratchpad beside them."** My Tasks and Follow-up fill the screen side by side; dragging a task from one to the other moves it in Google (and, if dropped on a different date bucket, reschedules it) in one gesture. Everything else — other lists, calendar — is reachable but out of the way. No new backend surface except a small extension to `move`; this is a layout + drag goal on top of machinery that already exists.

## What ships
- **Full-width three-column top row.** `My Tasks | Follow-up | Scratchpad` — scratchpad rightmost, and given real estate (wider and taller than today's capture box; the *editor internals* are goal 7, this goal only gives it the column).
- **Pinned lists, static config.** A frontend config constant (e.g. `PINNED_LIST_TITLES = ["My Tasks", "Follow-up"]`), resolved to list IDs **by title** against `GET /tasks` at load. A missing title renders an empty column with a "list '<title>' not found" hint (fix by renaming in Google or editing the constant). No `ui_prefs`, no visibility chooser — that stays deferred (old g7a residue).
- **Cross-list drag.** Drag a task from either pinned list into the other: any `(bucket, position, group)` drop target in the destination list. Semantics = the g4 cross-bucket rules **plus** the list move:
  - list changes → `move` (insert-then-delete, overlay row migrates to the new composite key — all existing);
  - bucket differs from the task's current bucket → due date updates too (see locked decision on the `move` extension);
  - dropped into a group → joins that group; else ungrouped. **Only the dragged task's row changes** (g4 rule stands).
  - Optimistic with pre-op snapshot; failure → rollback + error toast (writes.md conventions).
- **Shared DnD context across the pinned pair.** g4 established one `DndContext` per list; cross-list drag needs the two pinned lists under **one** context. This is a real DnD architecture change — document it in `tasks-panel.md` (which owns all DnD architecture + bug history).
- **Other tasks (collapsed).** All non-pinned lists render inside a collapsed disclosure section below the top row; expanding shows them as today's stacked panels, fully functional (all g4a CRUD, buckets, groups). Collapsed by default; expand/collapse state is ephemeral component state (no persistence).
- **Below the fold.** Calendar panel and anything else sit below, unchanged.

## Locked decisions
- **Pinned lists are static in code, matched by title** (`My Tasks`, `Follow-up` — both exist in the owner's Google Tasks). `ui_prefs` / a list-visibility chooser is deferred to a later polish goal.
- **Cross-list drop that also changes the bucket = one backend command** *(ACCEPTED 2026-07-06)*: extend the existing `move` endpoint/service with an optional `due_date`, applied on the **insert** leg of insert-then-delete. One user gesture → one orchestrated write path with writes.md's rollback rules — not two chained frontend calls that can half-fail. *(Rejected alternative: frontend chains `move` then `reschedule` with a joint snapshot.)*
- **Collapsed-state is ephemeral.** Server-side `ui_prefs` remains the plan for *persisted* view prefs, later.
- **Scratchpad panel moves rightmost and grows; its behavior is untouched here.** Capture/route/review all work exactly as g5 left them.
- **No confirm dialogs** (project stance holds); a mis-drop's undo is drag-back, same as g4.

## Out of scope (do not build)
- The bullet editor / note→Doc pipeline (goal 7).
- `ui_prefs`, list-visibility chooser, persisted layout, list reordering.
- Calendar panel changes (still read-only, below the fold).
- Drag into/out of the **Other tasks** section (move-to-list menu still covers those lists).
- Touch DnD, DragOverlay, and the other tracked rough edges in `tasks-panel.md` (unless a mis-drop regression forces the DragOverlay promotion).
- Deployment / Postgres (future goal, after the MVP set settles).

## Acceptance criteria
- Top row renders `My Tasks | Follow-up | Scratchpad` full-width; scratchpad rightmost with the enlarged footprint; calendar below the fold.
- Both pinned columns keep **every** g4a behavior: buckets + Overdue rollup, groups, create/edit/complete/delete with their undo-toasts, date picker, manual refresh, move-to-list menu.
- Dragging a task between the pinned lists moves it in Google (insert-then-delete; overlay row migrates); same-bucket drop preserves the due date; different-bucket drop sets the destination bucket's date; drop into a group joins it. Optimistic; induced failure → rollback + error toast; reload persists the end state.
- A pinned title missing from Google renders the empty-column hint, no crash, other columns unaffected.
- **Other tasks** collapses/expands; expanded lists are fully functional.
- Scratchpad routing / review confirm still refreshes the task columns (the g5 `onRouted` path survives the layout change).
- `tsc --noEmit`, frontend build, and the backend test suite pass; no console errors; g5 router behavior untouched (if `move` gains `due_date`, existing `move` callers are unaffected and new backend tests cover the extension).

## Harness upkeep (closing checklist — friction-driven only)
- Update `tasks-panel.md`: the shared-`DndContext`-across-pinned-lists architecture, plus any new DnD bugs earned during the build.
- Update `writes.md` **only if** `move` gains `due_date` (document the extended contract; rollback rules unchanged).
- `frontend.md`: note the pinned-list config constant + top-row grid convention if it becomes a pattern.
- Record path-scoped rule fire/no-fire (`/context`) for `tasks-panel.md` / `frontend.md` on the touched files.
- Refresh root `README.md` + `docs/api-reference.md` if `move` changed; update `docs/goals/README.md` status.
- Verification through `/verify` (functional); the browser-in-verifier gap persists — do a **manual pass on the real lists** for the drag flows (they write to Google).
