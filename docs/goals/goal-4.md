# Goal 4 — Write-back I: reschedule & move

**One line:** First Google writes. Reschedule a task by dragging it across date-buckets (due-date change, group-aware drop) and move a task to another list via a menu action; both optimistic with snapshot-rollback on failure, idempotent. No confirm dialogs. Cross-list **drag** is deferred to the layout goal — no multi-column UI yet.

## What ships
- **Cross-bucket drag = reschedule.** Dragging a task from one date-bucket to another (within the same list) sets its Google due date to the target bucket's date (`NO_DATE` bucket clears the due date). Position in the destination bucket is set **solely by drop location** (overlay rank via the same midpoint rule).
- **Group-aware drop.** The drop target decides grouping in the destination bucket, exactly like within-bucket drags: dropped inside a group's container → the task joins that group (`group_id` = destination group); dropped in the open bucket area → standalone (`group_id = NULL`). Either way the task leaves its source group; **no other task's row is touched**.
- **Move-to-list via menu.** Each task gets a small menu (⋯) with "Move to list…" → list picker. No drag between lists (the columns don't exist yet → layout goal).
- **Optimistic, no confirm dialogs.** Google writes use the same immediate-apply feel as overlay ops: the drop/menu action updates local state instantly and the write fires outside `setState`. A mis-drop is undone by dragging back (which is just another reschedule). Deliberately overrules the old "confirm-before-write" plan — these are todo items, not destructive ops.
- **Failure handling (new convention).** Unlike overlay writes, Google writes are NOT fire-and-forget. Capture a pre-op snapshot of local state before applying; a failed write restores the snapshot and shows an error toast. Never swallow Google-write errors.
- **Backend write layer:**
  - `app/google/tasks.py` gains thin write wrappers: `update_due_date(tasklist_id, task_id, due)`, `insert_task(tasklist_id, body)`, `delete_task(tasklist_id, task_id)`. One API call each, no orchestration.
  - new `backend/app/writes/` service owns orchestration: reschedule (due-date write + overlay rank/group update) and move (see below). Routers stay thin.
- **Endpoints:** `POST /tasks/{list}/{task}/reschedule {due_date, rank, group_id?}` and `POST /tasks/{list}/{task}/move {target_list_id, rank?}`. POST not PATCH — these are commands with Google side effects, not overlay field updates. `group_id` on reschedule must reference a group in the **destination** bucket (validate; 422 otherwise).

## Locked decisions
- **Groups never span buckets.** A cross-bucket drag updates only the dragged task's overlay row: `group_id` becomes the destination group's id (if dropped into one) or `NULL` (standalone). Remaining members of the source group are untouched; if the source group emptied, the existing auto-remove applies. This resolves the fork deferred from g3.
- **Cross-list move = insert + delete.** The Google Tasks API cannot move a task between lists (`tasks.move` is within-list only). The writes service must: (1) insert a copy into the target list, (2) on confirmed success, delete the original, (3) migrate the overlay row to the new `(tasklist_id, new_task_id)` key (rank per default, `group_id = NULL`). **Insert first; delete only after insert succeeds.** A failure between steps must not lose the task — if delete fails after insert, surface the duplicate to the user rather than retry-deleting blindly.
- **Sanctioned delete:** the "never hard-delete" write rule has exactly one exception — the delete-after-successful-insert inside move. No other code path may call `delete_task`.
- **Idempotency:** reschedule with the already-set due date and no group/rank change is a no-op (skip the Google call). Move to the current list is rejected client-side.
- **No Google ordering writes.** Rank/grouping remain overlay-only; Google still sees flat lists. Due date and list membership are the ONLY fields written.
- **Completed tasks:** out of scope for writes (the grouped view already excludes them).

## Out of scope (do not build)
- Confirm dialogs / undo stack — drag-back is the undo; rollback+toast is the failure path.
- Cross-list drag, multi-column layout, list visibility prefs (→ layout goal).
- Editing task title/notes/status; creating or deleting tasks (except the internal move delete).
- Calendar (→ its own goal). Scratchpad/router (→ next goal).
- Retry queues / offline support.

## Acceptance criteria
- Drag a task to another bucket (open area) → it appears at the drop position immediately, standalone; Google shows the new due date; exactly one reschedule POST; reload renders the same.
- Drag a task from bucket A's group into bucket B's group → it joins B's group at the drop position; A's group keeps its remaining members untouched; one POST (`due_date` + `rank` + `group_id`); if A's group emptied, it disappears.
- Drag to `NO_DATE` clears the due date in Google.
- Menu-move a task to another list → it disappears here, appears there (verify via API), overlay row migrated to the new task ID, old row gone.
- Force a write failure (kill backend / 500) → local state rolls back to the pre-op snapshot, error toast shows, no console crash.
- Within-bucket drag still behaves as g3 (rank/group PATCH only, no Google write, no reschedule POST).
- Reschedule POST with a `group_id` from the wrong bucket → 422.
- No console errors; Calendar panel unaffected.

## Harness reps (the goal-4 learning)
- **Agent team (primary rep).** Run this goal as a two-teammate team partitioned by layer: **backend teammate** owns `app/google/` write wrappers + `app/writes/` service + migration logic + endpoint tests; **frontend teammate** owns drag-to-bucket surfaces, the move menu, optimistic-apply + snapshot-rollback + toast. The endpoint contracts above are the interface — both teammates treat them as fixed; neither edits the other's layer. Teammates share one checkout (NOT worktree-isolated): the file partition is the safety mechanism. Lead session holds this brief and integrates.
- **`/verify` slash command** — `.claude/commands/verify.md`: invokes the `verifier` subagent with the current goal's acceptance criteria (read from this file) as the WHAT. All verification in this goal runs via `/verify` — never ad-hoc curl in the main session (g3 lesson).
- **`verifier-writes` skill** — verification recipe for write paths: use a dedicated **test task list** (create if absent, named `zz-verifier-test`), exercise reschedule/move against it only, clean up created tasks at the end, never touch real lists. The verifier subagent preloads this alongside `verifier-web`.
- **Write-safety path-scoped rule** — `.claude/rules/writes.md` scoped to `backend/app/writes/**` + `backend/app/google/**`: idempotent service; insert-before-delete invariant; `delete_task` callable only from move; rollback-not-retry on partial failure; due date + list membership are the only Google fields ever written.

## Closing checklist (this goal)
- Update `verifier-web` skill: new endpoints, menu selectors (`.task-menu`), toast selector, test-list convention pointer to `verifier-writes`.
- Update `tasks-panel.md` rule: cross-bucket drag now exists — document the reschedule branch in `handleDragEnd`, the destination-group resolution, and the snapshot-rollback pattern.
- Record the agent-team experience in the goal wrap-up: partition held? merge friction? lead coordination overhead? would worktrees have helped?
- Confirm the `tasks-panel.md` path-scoped rule fired this session (`/context`) — first real probe; record the result.
- Refresh root `README.md` (endpoints changed).
- Update `docs/goals/README.md` if the checklist itself needs amending.

## Harness wrap-up (run record — hand to planning chat)

**Agent-team rep (first run).** Ran as lead + two background teammates (`general-purpose`),
partitioned backend (`app/google` + `app/writes` + endpoints + tests + scope) / frontend
(panel + hook + css). **The partition held cleanly — zero merge friction:** the only files both
"sides" could have collided on (overlay `service.py`, calendar, `db.py`) were untouched by both;
the sole cross-file edit was mine (lead) on the shared harness docs. Defining the two endpoint
contracts *in the brief before* spawning was what made parallelism safe — each teammate coded to a
frozen interface and they integrated on the first try with no contract drift.

**Lead coordination overhead was real but front-loaded:** ~all the thinking went into writing the
two contracts + the write-safety rule up front; after spawn, integration was mechanical (run
the checks the teammates couldn't). Worktrees would NOT have helped here and would have hurt — the
value was a *shared* tree with a *logical* partition; isolated worktrees would have added a merge
step for zero conflict-avoidance benefit. Worktrees earn their keep when two goals are independent
(g7a∥b), not when two layers of one goal share a contract.

**Two teammate-sandbox gotchas:** (1) both teammates were blocked from executing `uv`/`npm`/project
binaries — they could write code but not run pytest/ruff/tsc, so **validation fell to the lead**.
Budget for that: the lead must run every gate. (2) The PostToolUse formatter twice stripped a
momentarily-unused import mid-edit in the backend teammate's context — survived because the import
was used by the final state, but worth knowing the format hook fires on *intermediate* edits.

**Lead-side formatting footgun:** `ruff format app tests` reformatted 5 pre-existing files (newer
ruff wraps lines the g3-era ruff left) → reverted to keep the g4 diff focused. Format only the
files the goal touched, not whole packages.

**Path-scoped rule probe (`/context` proxy).** `backend.md` **fired** in the lead session (injected
as context when backend files were Read). The `tasks-panel.md` / `writes.md` / `frontend.md` probes
are **inconclusive from the lead's seat** — those files were edited inside the *teammates'* separate
contexts, which the lead cannot observe. New finding: **with agent teams, path-scoped rule firing is
per-teammate-context and invisible to the lead** — to probe a rule you must read its target file in
whatever context will touch it, or ask the teammate to report `/context`. Next time, have each
teammate echo whether its layer's rule loaded.

**Verification:** runs via the `verifier` subagent (`/verify`) against `zz-verifier-test` lists only;
gated on the one manual step the team can't perform — re-consenting the widened `tasks` write scope.
