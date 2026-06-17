# Work Dashboard

A personal dashboard that surfaces Google Tasks, Calendar, and Drive alongside a small
task-metadata overlay (custom sort / priority / grouping, layered on top — see `docs/goals/`).

- **Backend**: FastAPI (Python). Calls the Google APIs directly — see `backend/app/google/`.
- **Frontend**: React + Vite. One self-contained panel per surface under `frontend/src/panels/`.
- **Storage**: SQLite locally, Postgres in production, for the task-metadata overlay only.

See `CLAUDE.md` for the repo map and conventions, and `docs/goals/` for the active milestone.

## Running it

Requires a Google Cloud OAuth client secret at `client_secret.json` in the repo root (not
committed — ask whoever set up the Google Cloud project for a copy).

### Backend

```sh
cd backend
uv sync
uv run python -m app.google.auth        # one-time: opens a browser for Google OAuth consent
uv run alembic upgrade head             # run once per schema change (creates overlay.db)
uv run uvicorn app.main:app --reload --port 8010
```

The OAuth token is persisted to the gitignored `backend/.google-tokens/token.json` and reused
(and refreshed) on subsequent runs.

> **Re-authorize for write access (goal 4):** the Tasks scope widened from `tasks.readonly` to
> read/write `tasks` so the app can reschedule (change due dates) and move tasks between lists. A
> token can't widen its own scope — after pulling goal 4, **delete `backend/.google-tokens/token.json`
> and re-run `uv run python -m app.google.auth` once**. Without this, write calls return 403.

### Write endpoints (goals 4 & 4a)

Reads remain `GET /tasks` (+ overlay PATCH / group CRUD from g2–g3). Google writes cover task
metadata, task content, and list rename — rank/grouping stay overlay-only:

- `POST /tasks/{list}/{task}/reschedule` `{due_date, rank?, group_id?}` — set/clear the Google due
  date (cross-bucket drag **or** the per-task date-picker); `due_date` is `YYYY-MM-DD` (IST) or
  `null` for no date.
- `POST /tasks/{list}/{task}/move` `{target_list_id}` — move to another list (insert-then-delete;
  the overlay row migrates to the new task id).
- **`POST /tasks/{list}`** `{title, rank?}` — create a task (lands undated → `NO_DATE`, top).
- **`PATCH /tasks/{list}/{task}`** `{title?, notes?, status?}` — edit content; `status`
  `completed`/`needsAction` is complete/uncomplete. Only the fields sent are written.
- **`DELETE /tasks/{list}/{task}`** — delete a task (the UI defers this behind a ~5s undo toast).
- **`PATCH /lists/{list}`** `{title}` — rename a task list.

**From goal 4a the tasks panel is a daily-driver MVP**: create / edit / complete / delete, an
arbitrary-date picker, an Overdue rollup at the top of each list, and a per-panel refresh.
Calendar (g7) and the scratchpad/router (g5) remain WIP.

### Frontend

```sh
cd frontend
npm install
npm run dev                              # http://localhost:5173, expects the backend on :8010
```
