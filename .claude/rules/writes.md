---
paths: ["backend/app/writes/**", "backend/app/google/tasks.py"]
---

# Google write safety (goal 4+)

Google writes begin in goal 4. They are the only mutations in the system that leave the local
DB — treat them with more care than overlay writes. Read this before editing the write layer.

## Layering

- `app/google/tasks.py` holds **thin write wrappers** — one Google API call each, no
  orchestration, no DB access, no overlay logic: `update_due_date`, `insert_task`,
  `delete_task`, `update_task_content` (title/notes/status), `update_tasklist` (list rename)
  (plus the read helper `get_task` used by the writes service). Same sync `_fn` / `async def` +
  `asyncio.to_thread(...)` split as the read functions.
- `app/writes/service.py` owns **orchestration**: it sequences Google calls and overlay-row
  updates, validates inputs, and decides what (if anything) to write: `reschedule`, `move`
  (g4); `create_task`, `update_content`, `delete`, `rename_list` (g4a). Routers stay thin and
  call the writes service.

## The Google fields that may be written (goal 4a)

- **Task metadata** (g4): due date, list membership.
- **Task content** (g4a): title, notes, and `status` (complete/uncomplete rides `status`).
- **Tasklist** (g4a): list title, via `update_tasklist` (the one write to the tasklists
  resource).
- **Never to Google:** rank and grouping stay overlay-only; Google always sees a flat list.

Each content/status edit is optimistic with a pre-op snapshot; on failure → rollback + error
toast (never swallowed). Same-value title/notes/status is a no-op skipped client-side. The two
sentinels — `app.writes.service._UNSET` and `app.google.tasks._UNSET` — are intentionally
separate objects: the service forwards only set fields so the wrapper's own default governs the
patch body.

## Invariants

- **Idempotent.** A reschedule whose target due-date bucket equals the task's current bucket
  skips the Google due-date write (the overlay upsert is naturally idempotent). A move to the
  current list is rejected (400) — the client blocks it too.
- **Insert before delete (move).** Cross-list move = insert a copy into the target list, then —
  only after the insert returns a new task id — delete the original. Never delete first.
- **`move` may reschedule on the insert leg (goal 6).** `move` takes an optional `due_date` and
  `group_id` so a cross-list drag that also changes the date bucket / lands in a group is **one
  orchestrated write**, not two chained calls that can half-fail. Semantics:
  - `due_date is _UNSET` (omitted by the router when the request has no `due_date` key) → the copy
    **preserves the source task's due**; an explicit value sets it on the insert body (`None` →
    omit `due` → `NO_DATE`). Rollback rules are unchanged — the reschedule rides the same insert.
  - `group_id` (when not None) must reference a group in the **destination** `(target_list, bucket)`
    where `bucket = due_date or NO_DATE` if provided, else the source task's current bucket — else
    **422**, raised *before* any Google write. It is set on the migrated overlay row (the g4 move
    always ungrouped; now it honours the drop target). Menu-move callers pass neither → identical
    to g4 behavior.
- **`delete_task` has exactly TWO sanctioned callers (g4a):** (1) the **move** orchestration,
  only after a confirmed successful insert; (2) the **user `delete` endpoint**
  (`writes.service.delete`). No other code path may call it. In move, if the delete fails *after*
  a successful insert, do **not** retry-delete blindly — surface the duplicate to the caller (the
  task now exists in both lists; losing it is worse than a visible duplicate).
  **The goal-5 auto-router is NOT a third `delete_task` caller** — its write path is create-only
  (next bullet).
- **`create_task` has TWO sanctioned callers (goal 5):** (1) the **user create endpoint**
  (`POST /tasks/{list}`); (2) the **auto-router** (`app.router.service`), which creates a task from a
  routed capture. The router's *entire* Google-write surface is **`create_task` + `reschedule`** (the
  g4a date path, to set the new task's due date) — both create/metadata, nothing destructive. Routing
  may **never** call `delete_task`, the complete/uncomplete `status` write, or `update_content`. This
  create-only contract lives in `.claude/rules/router.md` and is asserted by a router write-path test
  (the router's write dependency set is exactly `{create_task, reschedule}`).
- **Completion writes immediately; delete defers (g4a).** Completion (`status` patch) is
  non-destructive — Google retains completed tasks and uncomplete is cheap — so the write fires
  now; the undo-toast is mis-click recovery. **Delete is the only genuinely irreversible op**, so
  the deferral lives entirely in the **frontend**: the optimistic remove + ~5s undo-toast hold the
  `DELETE` until the window closes; Undo cancels it with **zero Google writes** (the backend
  `delete` endpoint is simply never called). The backend `delete` is immediate when invoked.
- **Rollback, not retry.** On any partial failure, raise a clean `ApiError`; do not retry the
  Google call in a loop. The frontend owns rollback (snapshot restore + toast). Never swallow a
  Google-write error — unlike overlay writes, these are not fire-and-forget.
- **Group scope on reschedule.** A `group_id` passed to reschedule must reference a group in the
  **destination** bucket `(tasklist_id, target_bucket_key)`; otherwise 422. A cross-bucket move
  touches only the dragged task's overlay row (`group_id` → destination group or NULL); source
  group siblings are never modified.
- **Overlay-row migration on move.** After a successful move, migrate the overlay row to the new
  `(tasklist_id, new_task_id)` key (rank = the request's `rank` or default, `group_id` = the
  request's `group_id` — `NULL` unless a goal-6 cross-list drag dropped into a destination group)
  and delete the old row.

## Scope / auth

Writes need the read/write `https://www.googleapis.com/auth/tasks` scope (not `tasks.readonly`).
It lives in `app.google.auth.SCOPES`; changing scopes requires re-running
`uv run python -m app.google.auth` to re-mint a token. Never run the consent flow from
request-handling code.
