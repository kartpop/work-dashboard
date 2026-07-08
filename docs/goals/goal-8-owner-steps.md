# Goal 8 — owner steps (non-code actions)

The ordered checklist of things only the owner can do (Google Cloud, secrets, EC2,
DNS). Code is done; these wire it to the real world. Do them top-to-bottom.

> **Test locally first.** See [goal-8-owner-steps-local.md](goal-8-owner-steps-local.md)
> for the local walkthrough (cleanup, web OAuth client, `backend/.env`, sign-in flow,
> two-user isolation test). Come back here once local is green.

## A. Google Cloud — OAuth web client + consent screen

- [ ] In [Google Cloud Console](https://console.cloud.google.com/), select (or create)
      the project used for this app.
- [ ] **APIs & Services → Enabled APIs**: ensure **Google Tasks API**, **Google
      Calendar API**, **Google Drive API**, and **Google Docs API** are enabled.
- [ ] **OAuth consent screen**: User type **External**. App name "Dashboard", support
      email, developer email. **Scopes** — add exactly these (identity + the three):
      `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`,
      `.../auth/tasks`, `.../auth/calendar.readonly`, `.../auth/drive.file`.
      **Do NOT add `.../auth/documents` or `.../auth/drive`** (ADR: drive-access-scoping).
- [ ] **Publish the app** (Publishing status → *In production*). Leave it
      **unverified** — users click through the "unverified app" interstitial once;
      refresh tokens then don't expire (testing mode's 7-day expiry is the disqualifier).
      Full Google verification is not pursued.
- [ ] **Credentials → Create credentials → OAuth client ID → Web application.**
      Authorized redirect URIs:
      - `https://<DASHBOARD_DOMAIN>/auth/callback` (prod)
      - `http://localhost:8010/auth/callback` (local dev)
      Download the JSON as **`client_secret.json`** (it will have a `"web"` key).
      > ⚠️ **Never replace this OAuth client id later.** Under `drive.file`, Google keys
      > per-file access to the client id that *created* a file — a new client id (or a new
      > GCP project) is a different app and gets 404 on every user's existing notes
      > folder/Doc. Rotating the client **secret** is fine; changing the client **id** is
      > not. (The app self-heals into a *fresh* Doc if this ever happens — goal 8a — but
      > that orphans the old notes; don't rely on it.)

## B. Secrets

- [ ] `SESSION_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] `TOKEN_ENCRYPTION_KEY`:
      `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
      **Keep this stable** — rotating it makes every stored refresh token undecryptable
      (users must re-sign-in).
- [ ] `SUPERUSER_EMAIL`: your @gmail address (bootstraps the admin + is always allowed).
- [ ] `ANTHROPIC_API_KEY`: the one app-level key (owner pays for everyone's routing).

## C. EC2 host

- [ ] Launch a small instance (~$10/mo class, e.g. t3.small; 2 GB+ RAM). Ubuntu LTS.
- [ ] Security group inbound: **22** (your IP), **80**, **443** (0.0.0.0/0).
- [ ] Install Docker Engine + the compose plugin.
- [ ] `git clone` the repo to `~/dashboard`.

## D. DNS (Cloudflare)

- [ ] Add an **A record** `dashboard` → the EC2 public IP.
- [ ] Set it **DNS only (grey cloud)** — not proxied — so Caddy can complete the
      Let's Encrypt HTTP-01 challenge directly (locked: Cloudflare proxy/Tunnel skipped).

## E. Deploy

- [ ] On the host: `cp .env.prod.example .env.prod` and fill every value (domain,
      redirect URI, `FRONTEND_ORIGIN=https://<domain>`, the three secrets, API key).
- [ ] Copy `client_secret.json` (the **web** client from step A) to the repo root
      (`~/dashboard/client_secret.json`) — compose mounts it read-only.
- [ ] `docker compose --env-file .env.prod up -d --build`
- [ ] Watch `docker compose logs -f app` for `alembic upgrade head` + uvicorn start,
      and `docker compose logs -f caddy` for a successful certificate.

## F. First sign-in + invites

- [ ] Visit `https://<DASHBOARD_DOMAIN>`, click **Sign in with Google**, accept the
      "unverified app" interstitial, grant the scopes. You land on the dashboard.
- [ ] Open **⚙ Settings → Allowed emails** (visible only to the superuser) and invite
      your wife / friends' Google addresses. They can now sign in; each gets their own
      empty dashboard, their own notes folder/Doc (auto-created on first note or
      settings visit), and their own calendar toggles.
- [ ] (Optional) In **Settings → Calendars**, toggle on any shared/extra calendars.

## G. Backups

- [ ] Add the nightly backup cron to the host crontab (see `docs/deploy.md`):
      `15 3 * * * cd ~/dashboard && docker compose exec -T app uv run python scripts/backup.py >> /var/log/dashboard-backup.log 2>&1`
- [ ] Confirm a copy appears under the `dashboard-data` volume's `/data/backups`.
- [ ] **Never `docker compose down -v`** and never migrate hosts without copying the
      `dashboard-data` volume — the volume holds each user's notes folder/Doc ids (and all
      overlay/session data). Losing it re-bootstraps everyone's notes into fresh Docs.
      *(Two durability invariants — the volume here + the OAuth client id in step A. See
      `docs/deploy.md` → "Durable per-user config".)*

## Notes / gotchas

- The old single-user artifacts are gone: `NOTES_FOLDER_ID`, `NOTES_DOC_ID`,
  `EXTRA_CALENDAR_IDS`, the `.google-tokens/` file, and the `app.google.bootstrap` CLI.
  Per-user equivalents live in the DB and are created on demand.
- Existing local overlay/review rows are **not** migrated — the server starts from an
  empty `overlay.db` (they were test-mode + recreatable). No claim/DB-copy step.
- If a user ever sees a permissions error on notes, it means their token predates a
  scope change — they just sign out and back in to re-grant.
