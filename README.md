# Work Dashboard

A personal dashboard that surfaces Google Tasks (and, later, Calendar and Drive) alongside a
small local task-metadata overlay — custom sort, grouping, and a capture-box that auto-files
dumped thoughts to the right place.

- **Backend**: FastAPI (Python). Calls the Google APIs directly — see `backend/app/google/`.
- **Frontend**: React + Vite. One self-contained panel per surface under `frontend/src/panels/`.
- **Storage**: SQLite locally, Postgres in production, for the task-metadata overlay only.

See `CLAUDE.md` for the repo map and conventions. For the HTTP endpoints and feature details,
see [docs/api-reference.md](docs/api-reference.md); for the milestone history, see
[docs/goals/](docs/goals/).

## Prerequisites

- A Google Cloud OAuth client secret at `client_secret.json` in the repo root (not committed —
  ask whoever set up the Google Cloud project for a copy).
- An `ANTHROPIC_API_KEY` in the backend environment if you want the scratchpad auto-router to
  classify captures. Without it, captures fall through to the manual review queue (no Google
  writes) — everything else works fine.

## Running it

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

> **Re-authorize for write access:** the app needs read/write Google Tasks scope to create,
> reschedule, edit, and complete tasks. A token can't widen its own scope — if write calls return
> 403, **delete `backend/.google-tokens/token.json` and re-run `uv run python -m app.google.auth`**.

### Frontend

```sh
cd frontend
npm install
npm run dev                             # http://localhost:5173, expects the backend on :8010
```
