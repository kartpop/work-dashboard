# Dashboard

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

- A Google Cloud OAuth client secret at `client_secret.json` in the repo root.
- An `ANTHROPIC_API_KEY` in the backend environment if you want the scratchpad auto-router to
  classify captures. Without it, captures fall through to the manual review queue (no Google
  writes) — everything else works fine.
- **(Notes → Doc, goal 7, optional)** `NOTES_FOLDER_ID` and `NOTES_DOC_ID` in `backend/.env` to
  let high-confidence notes write to a Google Doc. Unset → notes stay kept-local (no crash). See
  the ordered setup in [docs/goals/goal-7-owner-steps.md](docs/goals/goal-7-owner-steps.md).

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

> **Notes → Google Doc (goal 7):** the notes writer adds the **`drive.file`** scope (files the app
> creates only — never full Drive/Docs; ADR `docs/goals/architecture/drive-access-scoping.md`).
> Enabling it is a one-time flow: set `NOTES_FOLDER_ID`, delete the token + re-auth (verify the
> consent screen shows *file-scoped* Drive wording), run `uv run python -m app.google.bootstrap` to
> create the notes Doc inside that folder, paste the printed `NOTES_DOC_ID` into `backend/.env`,
> then revoke the old broad grant at <https://myaccount.google.com/permissions>. Full steps:
> [docs/goals/goal-7-owner-steps.md](docs/goals/goal-7-owner-steps.md). The backend refuses to boot
> if the token carries a scope broader than `{tasks, calendar.readonly, drive.file}`.

### Frontend

```sh
cd frontend
npm install
npm run dev                             # http://localhost:5173, expects the backend on :8010
```
