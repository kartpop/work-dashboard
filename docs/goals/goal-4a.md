# Goal 4a — Write-back II: full task CRUD (tasks MVP)

**One line:** Complete the write surface — create, edit (title + notes), complete/uncomplete, and delete tasks; set arbitrary due dates; rename task lists; fix the g4 move-menu (clipping + optimistic destination). **From this goal the tasks surface is a daily-driver MVP** (real personal use against real Google lists); Calendar and Scratchpad stay WIP. All Google writes, optimistic, no confirm dialogs.

## MVP intent
The acceptance bar for this goal is *"Kartikeya can run his actual tasks through the dashboard."* The full daily loop must work end-to-end against real lists: **capture → schedule (incl. arbitrary dates + overdue) → organize → edit → complete → delete**. Calendar (g7b) and Scratchpad/router (g5) remain WIP — only the tasks panel graduates here.

## What ships
- **Create task.** A per-list "+ add task" affordance → new task in that list's `NO_DATE` bucket, top of bucket. (Set a date immediately via the picker below — no drag needed.)
- **Edit title.** Inline: click the title → editable → Enter/blur commits. Same-value edit is a no-op.
- **Notes / description.** An expand/hide triangle per task reveals a notes area; edit inline (textarea, placeholder "Add notes" when empty). Google `notes` field, plain text. Collapsed by default.
- **Complete / uncomplete toggle.** A checkbox on **every** task (standalone or grouped). Click → optimistic complete: the task checks, animates out of the active (completed-excluded) view, and a "Completed — Undo" toast (~5s) appears. The Google status write fires **immediately** (completion is non-destructive — Google retains completed tasks, uncomplete is cheap); Undo calls uncomplete and restores status + position + group from the snapshot. If the completed task was a group's last member, the group auto-removes (restored on Undo). Distinct from delete: **complete writes now; delete defers.**
- **Due-date picker.** A date control on each task (and on create) to set / change / clear the due date to an **arbitrary** date — not just drag between visible buckets. Calls the existing g4 `POST …/reschedule` (no new endpoint); clearing = `NO_DATE`. This is what makes scheduling beyond the rendered buckets possible (drag only reaches buckets that already exist).
- **Overdue rollup.** Tasks with a past due date surface in an **Overdue** bucket at the top of the list, not scattered/hidden in past-date buckets. (If the g2 bucketing already rolls these up → verify; if it buckets by exact past date → add the rollup.)
- **Manual refresh.** A refresh affordance per panel (re-run `GET /tasks`) so changes made elsewhere (phone app; the next instance of a recurring task after completion) appear without a hard page reload.
- **Delete task.** `⋯` menu → Delete. Optimistic remove + "Task deleted — Undo" toast (~5s). The Google `DELETE` fires **only after** the window expires; Undo cancels it before it leaves (zero Google writes on undo). Overlay row removed on the actual delete.
- **Move-to-list (fix two g4 bugs — the move itself works).** (1) **Menu clipped by the group boundary:** for a task low in a group, the move-to-list menu's bottom is truncated by the group container's edge. Render the menu in a **portal/overlay that escapes the group's clip context** so it's never truncated, regardless of the task's position or group size. *Don't* use an inner scrollbar — a one-item group makes the menu too short to use. (2) **Destination insert isn't optimistic:** the task leaves the source immediately but takes ~2-3s to appear in the target (a refetch). Insert the moved task into the destination list **from the move response (its new id)**, not via a reload — the g3 `createGroup` insert-from-response pattern; the source-side removal is already optimistic.
- **Rename list.** Inline edit of the list/column header → first write to the **tasklists** resource (distinct from tasks). New `update_tasklist` wrapper.
- **Subtask render-robustness.** Tasks carrying a Google `parent` must not vanish, crash, or duplicate; render them flat as standalone for MVP (nesting UI deferred — see Out of scope, and the open question in the brief notes).

## Locked decisions
- **Completion = immediate write + undo-toast** (vs delete's deferred write). Google retains completed tasks and uncomplete is a cheap status flip, so the write fires now; the toast is mis-click recovery and the "it vanished" affordance, not a deferral.
- **Delete = deferred-delete + undo-toast, not a dialog.** The g4 "no confirm dialogs" stance holds. Delete is the only genuinely irreversible op (Google Tasks delete is permanent — no trash), so the destructive call is held until the undo window closes. Move's *internal* delete (g4, post-successful-insert) is unchanged and immediate.
- **Arbitrary due dates via a date-picker that reuses the g4 reschedule endpoint.** Drag-reschedule stays for the visible range; the picker covers everything outside it. New tasks land in `NO_DATE` and are dated via the picker (per-bucket "+add" stays deferred — the picker removes the create-then-drag friction).
- **Overdue rollup bucket at top.** Past-due items are surfaced, never buried in past-date buckets.
- **`writes.md` rule revised (first revision).** `delete_task` is no longer move-only — exactly two sanctioned callers: (1) the move-delete (after successful insert), (2) the user delete endpoint (after the undo window). No other path calls it.
- **Endpoint conventions.** Orchestration with multi-step side effects → POST named command (`/reschedule`, `/move`, unchanged). Single-resource field updates → PATCH: `/overlay` for local fields, bare `/tasks/{list}/{task}` for Google content — **title, notes, and `status`** (complete/uncomplete rides this path). Create = `POST /tasks/{list}`; delete = `DELETE`; list rename = `PATCH /lists/{id}`. Mirrors Google's `tasks.patch` / `tasklists.patch`.
- **Content/status edits are Google writes** → optimistic, pre-op snapshot, failure → rollback + error toast, never swallowed. Same-value title/notes/status = no-op skip.
- **Empty title rejected client-side.**
- **Subtasks render flat for MVP.** Hierarchy UI deferred; a `parent` task must never be dropped or duplicated. *(If the user relies on subtasks day-to-day this flips to in-scope — open question, resolve before running.)*
- **No cross-session completed-tasks view in this goal.** The undo-toast recovers in-session mis-clicks; unchecking a task completed in a prior session is deferred. (g2's `show_completed` flat mode makes a "show completed" toggle a cheap later add if wanted.)

## Out of scope (do not build)
- Subtask *hierarchy* / nesting UI; cross-session completed-tasks browser; starred; due-*time* (date only); recurrence editing; per-bucket "+add" affordance.
- Confirm dialogs.
- Multi-column layout / list visibility (→ g7a). Calendar (→ g7b). Scratchpad/router (→ g5).
- Retry queues / offline support.

## Acceptance criteria
- "+ add task" → new task at the top of `NO_DATE` immediately; one create POST; Google shows it; reload renders it.
- Set a due date via the picker to a date with **no existing bucket** (incl. weeks out) → the task moves to that date's bucket (or Overdue if past); one reschedule POST; clearing the date → `NO_DATE`. (This is the case drag cannot do.)
- Overdue tasks appear in an Overdue bucket at the top.
- Toggle a task complete — standalone **and** grouped → it checks, leaves the active view, one status write; the "Undo" toast restores status + position + group; reload reflects Google's state. Completing a group's last member removes the group (restored on undo).
- Inline-edit a title → one bare-task PATCH on Enter/blur; same-value edit fires none; reload persists.
- Expand notes, type, collapse → one PATCH; reload persists; empty notes shows placeholder and fires no PATCH.
- Delete → vanishes + undo-toast; **Undo within the window restores it with zero Google writes**; expiry fires exactly one `DELETE` + removes the overlay row; reload confirms gone.
- Move-to-list via `⋯` → optimistic on **both** sides: the task leaves the source list and appears in the target list **immediately** (no ~2-3s wait), overlay row migrated. The move-to-list menu renders **fully (not clipped)** even for a task low in a tall group and for a one-item group.
- Rename a list header inline → one `PATCH /lists`; Google shows the new name; reload persists.
- Manual refresh pulls a change made in the Google app (and the next instance of a completed recurring task).
- A task with a subtask `parent` renders (flat) without error or duplication.
- Any write failure (500 / killed backend) → the optimistic change rolls back, error toast, no console crash.
- **MVP gate:** the full daily loop — capture, schedule (arbitrary dates + overdue), organize, edit, complete, delete — works against real lists. g3/g4 behaviour intact (grouping, reorder, reschedule, move). No console errors; Calendar unaffected.

## Harness reps (the goal-4a learning)
- **No new *major* capability — deliberately.** 4a is feature-completion; the project rule is "exercise *or* introduce," and force-fitting a queued capability (dynamic workflow / runtime MCP / agent view / plugin) onto a CRUD goal violates "don't force-fit." Both reps below are friction-driven — the project's actual trigger for harness evolution.
- **UI-flow verification (supporting, friction-driven).** Extend `verifier-web` with Playwright checks for behaviors endpoint checks can't see: **complete-toggle + undo (undo fires zero Google writes; the deferred DELETE fires only post-window)**, the **date-picker reaching a no-bucket date**, the **overdue rollup**, **refresh** — alongside create / inline edit / notes / delete / list-rename / move. *Corrected motivation:* g4's `move` worked and the verifier was right; manual use still caught a clipped menu (visual) and a non-optimistic destination (latency) — the honest lesson is that **functional checks miss *visual* and *latency* issues** (those need visual/manual review or perf assertions), while undo-toast/picker *state-machine* properties are the real case for UI-flow checks. `/verify` + the subagent are unchanged; the *coverage* deepens.
- **Agent team, second run (exercise + validate).** Re-run the layer-partitioned team — backend (`app/google` CRUD + status + `update_tasklist` wrappers; `app/writes` CRUD orchestration + deferred-delete contract; endpoints; tests) / frontend (+add, inline edits, notes triangle, complete-toggle + undo, date-picker, overdue rollup, refresh, undo-toast state machines, move-menu wiring) — applying g4's findings: the **lead runs every gate** (teammate sandboxes can't run `uv`/`npm`), and **each teammate echoes `/context`** so per-teammate path-scoped rule firing is finally observable (g4's probe was inconclusive from the lead's seat). Goal: confirm the gotcha-mitigations are a repeatable method and get a clean `tasks-panel.md` / `writes.md` rule-fire reading.

## Closing checklist (this goal)
- Extend `verifier-web`: CRUD + MVP selectors (+add, inline-edit, notes triangle, complete-checkbox, undo-toast, date-picker, overdue bucket, refresh, list-header edit), Playwright UI-flow checks (incl. move's optimistic destination; menu-clipping is a visual issue → manual review).
- Revise `writes.md`: `delete_task` is no longer move-only — document the two sanctioned callers and the deferred-delete / undo-window for the user path; note completion writes immediately.
- Update `tasks-panel.md`: new-task insertion, inline-edit + notes-expand UI, the two undo-toast state machines (immediate-write completion vs deferred-write delete), the date-picker → reschedule path, the overdue rollup, the move-menu **portal/clip fix + optimistic-destination (insert-from-response)**, subtask flat-render.
- Record the second team run: did the gotcha-mitigations hold? Per-teammate `/context` rule-fire result for `tasks-panel.md` and `writes.md`.
- Refresh root `README.md` (new endpoints: create / edit / status / delete / list-rename; note the tasks surface is now MVP).
- Update `docs/goals/README.md` — full CRUD write surface, `delete_task` two callers, tasks-surface-MVP from this goal.

## Harness wrap-up (run record — hand to planning chat)

- **2nd agent-team run: DEFERRED.** Executed inline, single-session (user choice at kickoff). The
  team-run rep + the conclusive *per-teammate* `/context` reading roll forward to a future goal
  (g7a∥b is the natural next parallel opportunity).
- **Rule-fire reading (inline analog of the `/context` probe):** all four path-scoped rules fired
  in-session — `backend.md` + `writes.md` bodies were injected on backend edits, `frontend.md` +
  `tasks-panel.md` on the tasks-panel edits. So in a *single* context, path-scoping works; the
  open question (per-teammate firing invisible to the lead) remains untested because there were no
  teammates.
- **Hook gotcha recurred, as predicted:** the PostToolUse formatter stripped a momentarily-unused
  import (`_reshape_task` in the test file) on an *intermediate* edit — the exact g4 finding.
  Re-adding it *after* the usage existed made it stick. Lesson banked: when an import's first use
  lands in a *later* edit, the formatter will delete it in between; add import + usage together, or
  re-add last.
- **UI-flow verification — built but BLOCKED this run.** `verifier-web` now carries Playwright
  checks for the behaviours API checks can't see (complete+undo = zero writes; deferred-DELETE
  fires only post-window; picker→no-bucket date; overdue rollup; refresh; optimistic move
  destination + non-clipped portaled menu). The verifier sandbox had **no Playwright/browser**, so
  every UI-flow/visual check came back BLOCKED — the state-machine + clip-fix behaviours are
  **unverified by automation** (their backing endpoints all PASS). Needs a manual pass or a browser
  in the verifier env.
- **The functional verifier caught a real functional bug** (consistent with the g4 lesson that
  functional checks catch functional issues, not visual/latency): PATCH/DELETE on an unknown task
  id leaked a **500/502 instead of 404** because Google returns HTTP **400** (not 404) for bad ids
  and `_get_task` only mapped 404→None — the 500 also broke the error-envelope rule. Fixed
  (`_get_task` maps 400|404→None; `delete` pre-checks existence) + 3 regression tests.
- **Tasks MVP loop:** the full daily loop (create→schedule incl. arbitrary/overdue→organize→edit→
  complete→delete) passed at the **API level** against `zz-verifier-test` lists; g3/g4 behaviour
  intact; Calendar unaffected. A manual real-list pass is still recommended before relying on it
  daily, given the BLOCKED UI-flow checks.
