# Goal 3 — Task grouping & ordering

**One line:** Replace priority with user-defined **groups** inside each `(list, date-bucket)`; drag to reorder, group, and ungroup within a bucket. Grouping and order are overlay-only — Google sees a flat list per list. Read-only on Google.

## What ships
- **Drop priority entirely.** Remove the priority enum, badges, and the click-to-cycle behaviour. Migration drops `task_overlay.priority`. (Position in a bucket is the only importance signal — no separate tag.)
- **Groups** (overlay-only): a named cluster of tasks inside one `(list, date-bucket)`. The backend never writes grouping or order to Google.
- Inside a bucket the rendered order is a sequence of **items**, where an item is either a standalone task or a group; a group holds its own ordered tasks.
- **Drag (within a single bucket only):** reorder a task inside its group; reorder items (standalone tasks + groups) at bucket level; drag a task into a group; drag a task out of a group (back to standalone).
- All mutations are **optimistic** — update local state in place, compute the new rank in the component, PATCH *outside* `setState`, never full-reload + Google-refetch. (Carries the goal-2 convention; with priority gone the old priority-click reload is moot, but this governs every group/drag op.)

## Locked decisions
- **Group scope = `(tasklist_id, bucket_key)`.** A group lives in exactly one date-bucket of one list. `bucket_key` = the exact due date as `YYYY-MM-DD` (IST) or the sentinel `NO_DATE` (same date logic as goal 2). Whether a group persists across buckets is **deferred** with cross-bucket drag (→ goal 6).
- **Schema — one Alembic migration:**
  - new `task_group(id PK, tasklist_id, bucket_key, name, rank REAL, created_at, updated_at)`; unique `(tasklist_id, bucket_key, name)`.
  - `task_overlay`: **drop `priority`**; **add `group_id`** (nullable FK → `task_group.id`, `ON DELETE SET NULL`). Keep composite PK `(tasklist_id, task_id)`, `rank`, timestamps.
- **rank (unchanged from goal 2):** float, ascending = top; reorder = midpoint of new neighbours; one-row write, never renumber. A task's `rank` orders it at bucket level when standalone, or *within its group* when grouped. A group's `rank` orders it among bucket-level items. Tasks with no overlay row render standalone after ranked items (keep goal-2 fallback).
- **API shape:** rename the date-bucket key in `GET /tasks?view=grouped` from `groups` → **`buckets`** (frees "group" for the new concept). Each bucket carries `items[]`, where an item is `{type:"task", …}` or `{type:"group", id, name, rank, items:[<task>…]}`.
- **Endpoints** (overlay service owns group CRUD; routers stay thin):
  - `PATCH /tasks/{list}/{task}/overlay {rank?, group_id?}` — priority removed; `group_id:null` ungroups.
  - `POST   /tasks/{list}/groups {name, bucket_key, rank}` — create.
  - `PATCH  /tasks/{list}/groups/{id} {name?, rank?}` — rename / reorder.
  - `DELETE /tasks/{list}/groups/{id}` — delete; member tasks fall back to standalone via FK `SET NULL`.
- **Group UX:**
  - a group renders as a visually distinct container (name header + indented/bordered task list). This also disambiguates drops: inside the box = into the group; bucket open area = standalone.
  - create via an explicit "+ group" affordance per bucket → name it → drag tasks in. (Drag-two-tasks-to-merge is a later nicety.)
  - a group emptied by dragging out its last task is auto-removed; explicit delete also available.
- **Render robustness:** if a task's computed bucket no longer matches its group's `bucket_key` (e.g. its due date was changed directly in Google), render it standalone — don't crash or show it in the wrong bucket.
- **Layering (unchanged):** all merge/group/order logic in `backend/app/overlay/`; `app/google/*` stays fetch+reshape; routers thin.

## Out of scope (do not build)
- Any Google write — grouping, ordering, due dates, and list membership are all local.
- Cross-bucket or cross-list drag (→ goal 6, the first Google write-back).
- Side-by-side / list-selection layout (→ goal 4).
- Auto-grouping tasks by name prefix (possible later nicety).

## Acceptance criteria
- `alembic upgrade head` on the existing DB drops `priority`, adds `task_group` + `group_id`; existing tasks keep their rank and render standalone.
- `GET /tasks?view=grouped` returns `task_lists[].buckets[].items[]` with task/group items; no `priority` field anywhere; no `groups` key.
- Create a group in a `(list, bucket)`, name it, drag two tasks in → exactly **one** PATCH per drag (`group_id` + `rank`); the group renders with both tasks; reload shows the same.
- Drag a task within its group → one PATCH (`rank` only); order persists across reload.
- Drag a task out → one PATCH (`group_id:null` + `rank`); the task is standalone; if it was the group's last member, the group disappears.
- Reorder a group among standalone tasks → one PATCH to the group's `rank`.
- `DELETE` a group → its member tasks become standalone (not deleted).
- No console errors; the Calendar panel is unaffected; optimistic updates appear immediately (no "Loading…" / full reload on any single op).

## Harness reps (the goal-3 learning)
- **`verifier` subagent** — create `.claude/agents/verifier.md`: `skills: verifier-web` (preloads the cold-start recipe in full), tools restricted to read + Bash (+ the browser MCP if Playwright is used), returns only the PASS/FAIL report. Run this goal's verification *through the subagent* so curl/Playwright/log output stays out of the main session's context.
- **First hook** — add a `PostToolUse` formatter in `.claude/settings.json` (script in `.claude/hooks/format.sh`): on `Edit|Write` of `*.py` run the project's Python formatter/linter; on `*.ts|*.tsx` run the JS formatter. Verify by editing a file and confirming it is auto-formatted without the model being asked.

## Closing checklist (this goal)
- Update the `verifier-web` skill for the new API shape (`buckets` / `items`, the group endpoints, priority removed).
- Update the backend / `google-api-integration` rule: the date-bucket key is now `buckets`; the overlay service owns group CRUD.
- Add a frontend rule for the optimistic group/drag convention if the implementation shows it isn't being followed (rank-in-component, PATCH-outside-`setState`, no reload).
- Refresh root `README.md` for the new endpoints if run/setup changed.
- Update `.claude/agents/` note in `docs/goals/README.md` now that subagents are part of the harness.
