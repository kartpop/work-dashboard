# Deploy (goal 8)

The app runs as **one container** — FastAPI serves both the API and the built Vite
SPA — behind **Caddy** (automatic Let's Encrypt TLS) on a **single small EC2** host,
with **Cloudflare DNS** (DNS-only) pointing at it. SQLite persists on a Docker volume
in WAL mode; a nightly `.backup` cron writes a second on-disk copy. Postgres and
multi-instance are deliberately out of scope (the in-process router scheduler shares
the single-instance assumption).

See `docs/goals/goal-8-owner-steps.md` for the exact, ordered owner checklist
(OAuth client, consent screen, EC2, DNS, secrets). This file is the reference.

## Architecture

```
Browser ──HTTPS──> Caddy (:443, Let's Encrypt) ──> app (:8010)
                                                     ├── FastAPI API (/auth, /tasks, /calendar, /scratch, /settings, ...)
                                                     └── StaticFiles: the built SPA (index.html + assets)
                                    SQLite (WAL) on the `dashboard-data` volume (/data/overlay.db)
```

- **Auth:** Google Sign-In = the OAuth grant. Per-user refresh tokens are stored
  Fernet-encrypted in the DB; a signed `HttpOnly`/`Secure`/`SameSite=Lax` session
  cookie carries identity. An `allowed_email` table (edited by the superuser) gates
  who can sign in; `SUPERUSER_EMAIL` bootstraps the first admin.
- **Tenancy:** every user-owned row has `user_id`; one `current_user` dependency
  scopes every query.

## Images / compose

- `Dockerfile` — multi-stage: build the SPA (`node`), then a Python image that
  `uv sync --no-dev`s the backend, copies the SPA into `/srv/frontend/dist`, and runs
  `docker-entrypoint.sh` (`alembic upgrade head` → `uvicorn`).
- `docker-compose.yml` — `app` + `caddy`. Secrets via `.env.prod` (see
  `.env.prod.example`). `client_secret.json` is mounted read-only (never baked in).
- `Caddyfile` — `{$DASHBOARD_DOMAIN}` → `reverse_proxy app:8010`.

## Prod bring-up (on the EC2 host)

```sh
git clone <repo> dashboard && cd dashboard
cp .env.prod.example .env.prod   # then fill in — see owner-steps
# place the web-client client_secret.json at the repo root (mounted by compose)
docker compose --env-file .env.prod up -d --build
```

The `--env-file .env.prod` makes `DASHBOARD_DOMAIN` available to compose (Caddy);
`app` reads the rest from `env_file`. First request triggers `alembic upgrade head`.

### Nightly backup cron (host crontab)

```
15 3 * * *  cd /home/ubuntu/dashboard && docker compose exec -T app uv run python scripts/backup.py >> /var/log/dashboard-backup.log 2>&1
```

Writes WAL-safe `.backup` copies under `/data/backups` (on the volume) and prunes to
`BACKUP_KEEP` (default 14). Off-box copies are intentionally not configured.

## Local dev (unchanged flow, web OAuth)

Local dev uses the **same web OAuth client** with a second redirect URI:

- `OAUTH_REDIRECT_URI=http://localhost:8010/auth/callback`
- `FRONTEND_ORIGIN=http://localhost:5173`
- `COOKIE_SECURE=0` (http, so the Secure flag would drop the cookie)
- `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY`, `SUPERUSER_EMAIL`, `ANTHROPIC_API_KEY` in
  `backend/.env`.

Run backend (`cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app
--reload --port 8010`) and frontend (`cd frontend && npm run dev`). Sign in at
`http://localhost:5173`. `localhost:5173` and `localhost:8010` are the same *site*, so
the `SameSite=Lax` cookie flows.

## Env vars

| Var | Purpose |
| :-- | :-- |
| `DASHBOARD_DOMAIN` | Hostname Caddy certs + serves (compose/Caddy). |
| `OAUTH_REDIRECT_URI` | Must match a redirect URI on the OAuth web client. |
| `FRONTEND_ORIGIN` | Post-sign-in redirect target. |
| `SESSION_SECRET` | Signs the session cookie. |
| `TOKEN_ENCRYPTION_KEY` | Fernet key encrypting refresh tokens at rest. |
| `SUPERUSER_EMAIL` | Bootstraps the superuser + is always allowed. |
| `ANTHROPIC_API_KEY` | One app-level key for the router (owner pays). |
| `COOKIE_SECURE` | `1` in prod (HTTPS), `0` for local http dev. |
| `CLIENT_SECRET_PATH` | Override the OAuth client secret path (defaults to repo root). |
| `DATABASE_URL` | SQLite path (compose sets `sqlite:////data/overlay.db`). |
