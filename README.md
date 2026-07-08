# Dashboard

A personal, **multi-user** dashboard that surfaces Google Tasks and Calendar alongside a small
local task-metadata overlay — custom sort, grouping, and a capture-box that auto-files dumped
thoughts to the right place (tasks, or a per-user notes Doc). Each user signs in with Google and
gets their own fully-isolated dashboard.

- **Backend**: FastAPI (Python). Calls the Google APIs directly — see `backend/app/google/`.
- **Frontend**: React + Vite. One self-contained panel per surface under `frontend/src/panels/`.
- **Storage**: SQLite (WAL) for the task-metadata overlay, per-user settings, and auth rows.
- **Auth (goal 8)**: Google Sign-In = the OAuth grant; per-user refresh tokens stored
  Fernet-encrypted; a signed session cookie; an email allowlist gates who can sign in.

See `CLAUDE.md` for the repo map and conventions. For the HTTP endpoints and feature details, see
[docs/api-reference.md](docs/api-reference.md); for deployment, see [docs/deploy.md](docs/deploy.md)
and [docs/goals/goal-8-owner-steps.md](docs/goals/goal-8-owner-steps.md).

## Prerequisites

- A Google Cloud **web** OAuth client secret at `client_secret.json` (repo root). Add both
  `http://localhost:8010/auth/callback` (dev) and your prod callback as authorized redirect URIs.
  Enable the Tasks, Calendar, Drive, and Docs APIs; publish the consent screen (unverified is fine).
- `backend/.env` with:
  - `SESSION_SECRET` — signs the session cookie.
  - `TOKEN_ENCRYPTION_KEY` — a Fernet key encrypting refresh tokens at rest
    (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
  - `SUPERUSER_EMAIL` — your @gmail; bootstraps the superuser (always allowed; edits the invite list).
  - `ANTHROPIC_API_KEY` — for the scratchpad auto-router (without it, captures fall to the manual
    review queue; everything else works).
  - `OAUTH_REDIRECT_URI=http://localhost:8010/auth/callback`, `FRONTEND_ORIGIN=http://localhost:5173`,
    `COOKIE_SECURE=0` for local http dev.

The `NOTES_FOLDER_ID` / `NOTES_DOC_ID` / `EXTRA_CALENDAR_IDS` env vars are **gone** — the notes
folder + Doc are app-created per user, and calendars are toggled per user in the Settings panel.

## Running it (local dev)

### Backend

```sh
cd backend
uv sync
uv run alembic upgrade head             # run once per schema change (creates overlay.db)
uv run uvicorn app.main:app --reload --port 8010
```

There is no CLI auth step — sign in through the web flow from the frontend. Each user's encrypted
token lives in the DB. If Google write calls ever 403 with a scope error, sign out and back in to
re-grant (Drive access is **`drive.file` only** — never full Drive/Docs; ADR
`docs/goals/architecture/drive-access-scoping.md`).

### Frontend

```sh
cd frontend
npm install
npm run dev                             # http://localhost:5173, expects the backend on :8010
```

Open `http://localhost:5173`, click **Sign in with Google**, and grant the scopes. `localhost:5173`
and `localhost:8010` are the same *site*, so the `SameSite=Lax` session cookie flows in dev.

## Deploying

One container (FastAPI serves the built SPA) behind Caddy on a small EC2 host with Cloudflare DNS.
See [docs/deploy.md](docs/deploy.md) and the ordered
[owner checklist](docs/goals/goal-8-owner-steps.md).

```sh
cp .env.prod.example .env.prod   # fill in; place the web client_secret.json at the repo root
docker compose --env-file .env.prod up -d --build
```
