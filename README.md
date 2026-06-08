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
uv run uvicorn app.main:app --reload --port 8010
```

The OAuth token is persisted to the gitignored `backend/.google-tokens/token.json` and reused
(and refreshed) on subsequent runs.

### Frontend

```sh
cd frontend
npm install
npm run dev                              # http://localhost:5173, expects the backend on :8010
```
