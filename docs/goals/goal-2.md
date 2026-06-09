# Goal 2 — Task overlay

Objective: a local metadata overlay on top of Google Tasks providing custom ordering, priority, and a per-list date-grouped view — merged and sorted server-side and rendered as an interactive Tasks panel. The overlay holds only what Google Tasks can't (rank, priority); Google stays read-only. No AI. Stop when all acceptance criteria pass.

## Deliverables

**Persistence**
- Add a persistence layer: SQLModel models + Alembic migrations. SQLite local, Postgres prod (engine/URL from config). This layer outlives goal 2 — the scratchpad store (goal 3) and review queue (goal 4) land here too.
- First migration creates the overlay table: one row per task, primary key `(google_tasklist_id, google_task_id)`. Columns: `rank` (float), `priority` (small int/enum), created/updated timestamps. Do not key on task_id alone — the composite makes rank/priority inherently per-list, which the multi-list UI needs.

**Overlay service + endpoints**
- Add an overlay service module (`backend/app/overlay/`). It reads overlay rows and left-joins them onto the tasks from `app/google/tasks.py` (which already returns every task list and its tasks), then computes per-list ordering and date buckets. Merge / sort / group lives here and nowhere else — `app/google/*` stays fetch+reshape only, routers stay thin.
- `GET /tasks` returns all task lists, each with its tasks merged with overlay metadata, in two shapes via a `view` query param: `grouped` (default; each list's tasks bucketed by date, ordered by `rank` within each bucket) and `flat` (each list's tasks ordered by `rank`, dates ignored). Tasks with no overlay row still appear, defaulting to unranked (fall back to Google's order) with no priority. Completed tasks (`status == "completed"`) are excluded from the response by default, mirroring the Google Tasks default view — the backend still fetches them (overlay rows must survive task completion without breaking), but filters them out before returning. A `show_completed=true` query param can override this.
- Date buckets mirror the Google Tasks date-sorted view: one bucket per distinct `due` date — labelled "Today"/"Tomorrow" for those, the actual date otherwise (e.g. "Wed, Jun 10"); overdue tasks surface under their past date; tasks with no due date go in a "No date" group. Compute relative labels in the user's timezone (Asia/Kolkata), not server UTC. The agent may inspect live Google Tasks via the wired MCP to match its grouping/labels exactly. Read-only — do not change due dates.
- Ordering uses a single shared `rank` per task, scoped to its list (the composite key makes this automatic; never order across lists). Reorder = set the moved task's rank to the midpoint of its neighbors within that list. A reorder must update one row, never renumber.
- Add write endpoint(s) to upsert overlay fields for a task (set priority; set rank / reorder). Upsert by `(tasklist_id, task_id)`. Writes hit the overlay DB only.
- Confirm `app/google/tasks.py` reshape includes `due`; add it if goal 1 omitted it (grouping needs it).
- Never delete an overlay row because its task is absent from Google — a transient fetch failure must not destroy metadata. Left-join only; orphan rows are harmless.

**Frontend**
- The Tasks panel becomes interactive (the first one) and renders each task list as its own section (My Tasks, follow-ups, …) — one tasks panel with lists rendered inside it, not one top-level panel per list. Per list: grouped-by-date view (a flat toggle is optional — the backend supports both), set priority, drag to reorder within a date bucket.
- Cross-bucket and cross-list drag are not in this goal (dates are read-only; rank is per-list).
- Keep the panel self-contained per `.claude/rules/frontend.md` (panel-local hook/state; shared leaf utilities at `src/` root only).

## Constraints / out of scope
- No writes to Google Tasks. Rescheduling (changing a due date) is a later goal — do not add it, including via drag.
- Cross-list task movement is out of scope. Moving a task between Google Task lists requires a destructive Google API write (delete from source list, insert into destination list) and cannot be represented as local metadata alone. This belongs in a later goal that adds Google write-back capabilities.
- Drag is within-bucket only (same list, same date bucket). Cross-bucket drag (moving between date buckets within a list) is also out of scope — dates are read-only.
- No AI / LLM / MCP in any path.
- No tags this goal. Priority is a settable, displayed attribute; ordering is by manual rank (no separate priority-sort mode).

## Acceptance criteria
- [ ] `alembic upgrade head` runs clean on a fresh SQLite DB and creates the overlay table.
- [ ] Overlay rows are keyed by `(tasklist_id, task_id)`; a set priority/rank persists across a backend restart.
- [ ] `GET /tasks` returns every task list with its tasks; each task carries merged overlay metadata; tasks with no overlay row still appear with defaults (left-join). Completed tasks are excluded by default; `show_completed=true` includes them.
- [ ] `view=grouped` buckets each list's tasks by exact due date (Today/Tomorrow labels, actual dates otherwise, overdue under past dates, a No-date group), rank-ordered within each bucket, labels computed in IST; `view=flat` orders each list's tasks by rank.
- [ ] A reorder within a list issues a single-row overlay write, not a renumber; ranks never cross lists.
- [ ] Completing/deleting a task in Google drops it from the dashboard on next load; its overlay row is left untouched and no error is raised.
- [ ] Frontend: each task list renders as its own section; priority settable; within-bucket drag reorders and persists; no console errors on live data.
- [ ] No Google write call, LLM, or MCP appears in any goal-2 code path.
- [ ] Closing checklist (`docs/goals/README.md`): refresh README if run/setup changed; review `.claude/skills/`; review `.claude/rules/` — in particular update `backend.md` / the google-api skill so the "endpoints are dumb / no merging" line names the overlay service as the one sanctioned place merge+sort may live.
