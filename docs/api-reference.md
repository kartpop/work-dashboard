# API reference & feature details

The HTTP surface of the backend, grouped by the milestone that introduced it. For setup and run
steps see the root [README](../README.md); for milestone history see [goals/](goals/).

## Tasks: reads & overlay

Reads are `GET /tasks` (all lists, merged with the local overlay), plus overlay PATCH and group
CRUD. Rank and grouping are **overlay-only** — they never sync to Google.

## Write endpoints

Google writes cover task metadata, task content, and list rename — rank/grouping stay overlay-only:

- `POST /tasks/{list}/{task}/reschedule` `{due_date, rank?, group_id?}` — set/clear the Google due
  date (cross-bucket drag **or** the per-task date-picker); `due_date` is `YYYY-MM-DD` (IST) or
  `null` for no date.
- `POST /tasks/{list}/{task}/move` `{target_list_id, rank?, due_date?, group_id?}` — move to another
  list (insert-then-delete; the overlay row migrates to the new task id). Cross-list drag (goal 6)
  may also reschedule + regroup in the same write: an **omitted** `due_date` preserves the source
  due, an explicit value (or `null` → `NO_DATE`) sets it on the insert leg; `group_id` names a
  destination group (validated against the dest bucket, else 422).
- `POST /tasks/{list}` `{title, rank?}` — create a task (lands undated → `NO_DATE`, top).
- `PATCH /tasks/{list}/{task}` `{title?, notes?, status?}` — edit content; `status`
  `completed`/`needsAction` is complete/uncomplete. Only the fields sent are written.
- `DELETE /tasks/{list}/{task}` — delete a task (the UI defers this behind a ~5s undo toast).
- `PATCH /lists/{list}` `{title}` — rename a task list.

The tasks panel is a daily-driver MVP: create / edit / complete / delete, an arbitrary-date picker,
an Overdue rollup at the top of each list, and a per-panel refresh.

## Scratchpad + auto-router

An append-only capture box files a dumped thought to the right place. A captured entry is run
through the **only runtime LLM in the system** (`app.router.classifier`) — a small/cheap model
(`claude-haiku-4-5`) that returns a schema-validated `{destination, confidence, fields}`.
**Deterministic code does every write** (`app.router.service`); the LLM never writes. The router's
Google-write surface is **create-only** (`create_task` + the date path) — never delete/complete.

- `POST /scratch` `{text}` — append a capture (append-only; never edits/deletes prior entries).
- `GET /scratch` — recent entries with their routing state (`unrouted` / `routed_task` /
  `kept_note` / `in_review` / `resolved`).
- `POST /scratch/route-now` — route every unrouted entry now (same code path as the scheduled job;
  idempotent — route-once).
- `GET /review` — pending review items (low-confidence / `event` / `unknown` — calendar is
  read-only v1, so events go to review for a manual add).
- `POST /review/{id}/confirm` `{destination?, fields?}` — confirm (edit-then-confirm); a `task`
  fires exactly one `create_task`. `POST /review/{id}/dismiss` — writes nothing.

A periodic in-process job auto-routes unrouted entries (no Celery). Disable with
`ROUTER_SCHEDULER_ENABLED=0`; tune the cadence with `ROUTER_SCHEDULER_INTERVAL` (seconds).

> **Set `ANTHROPIC_API_KEY`** for the router to classify. Without it, classification fails closed —
> every entry routes to `unknown` → the review queue (no Google writes). Override the model with
> `ROUTER_MODEL` and the auto-write confidence gate with `ROUTER_CONFIDENCE_THRESHOLD`.

### Evaluating the router

The router's quality is *measured, not asserted* — a labelled set gates the goal:

```sh
cd backend && uv run python -m app.router.evals.runner          # scorecard + GATE: PASS/FAIL
```

Or via the `/eval` command, which fans the cases across cheap-model `eval-worker` subagents and
aggregates (see `.claude/skills/eval-runner/SKILL.md`).
