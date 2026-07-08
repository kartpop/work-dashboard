# Goal 8 — local test walkthrough

Get the goal-8 multi-user web-OAuth flow running on your dev machine first.
Once this works end-to-end, do the server steps in
[goal-8-owner-steps.md](goal-8-owner-steps.md).

---

## 0. Clean up pre-goal-8 single-user artifacts

Skip this section if you're starting from a fresh clone.

If you ran the app before goal-8 (InstalledAppFlow + `.google-tokens/`):

- [ ] Delete `.google-tokens/` from the repo root — the CLI token file is gone,
      each user's token now lives encrypted in the DB.
- [ ] Remove `NOTES_FOLDER_ID`, `NOTES_DOC_ID`, `EXTRA_CALENDAR_IDS` from
      `backend/.env` — these are replaced by per-user settings in the DB.
- [ ] The upcoming `alembic upgrade head` drops and recreates the overlay tables
      (`task_group`, `task_overlay`, `scratch_entry`, `review_item`), so any local
      test-mode overlay rows are gone. That's fine — they were recreatable.

---

## 1. Google Cloud — web OAuth client (localhost)

If you previously had a **Desktop** (InstalledAppFlow) OAuth client, you need a new
**Web application** client. The client type is not upgradeable; create a fresh one.
You can keep both in the same project and same consent screen.

- [ ] In [Google Cloud Console](https://console.cloud.google.com/), open the project.
- [ ] **APIs & Services → Enabled APIs**: confirm Tasks, Calendar, Drive, Docs are on.
- [ ] **OAuth consent screen** (if not done): External, add the six scopes below, leave
      Publishing status at *Testing* for now (you can add your own email as a test user —
      testing mode is fine for local; you'll publish when you deploy to production):
      `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`,
      `.../auth/tasks`, `.../auth/calendar.readonly`, `.../auth/drive.file`.
      Do NOT add `.../auth/documents` or `.../auth/drive`.
- [ ] **Credentials → Create credentials → OAuth client ID → Web application.**
      Name: "Dashboard (local dev)".
      **Authorized redirect URIs:** add exactly one for now:
      `http://localhost:8010/auth/callback`
      (You'll add the prod URI to this same client — or a second client — when deploying.)
- [ ] Download the JSON as **`client_secret.json`** and place it at the **repo root**
      (`/path/to/work-dashboard/client_secret.json`). It must have a `"web"` top-level
      key, not `"installed"`.

---

## 2. Generate secrets + write `backend/.env`

```sh
# SESSION_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"

# TOKEN_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Create `backend/.env` (never committed — already in `.gitignore`):

```dotenv
# Auth
SESSION_SECRET=<output from above>
TOKEN_ENCRYPTION_KEY=<output from above>
SUPERUSER_EMAIL=kartikeya@projecttech4dev.org

# OAuth redirect — must match the URI on the web client
OAUTH_REDIRECT_URI=http://localhost:8010/auth/callback
FRONTEND_ORIGIN=http://localhost:5173

# Use 0 for local http (Secure cookie flag breaks on http)
COOKIE_SECURE=0

# Router (without this every capture goes to the review queue — everything else works)
ANTHROPIC_API_KEY=<your key>
```

---

## 3. Migrate and run

```sh
# Terminal A — backend
cd backend
uv sync
uv run alembic upgrade head        # drops+recreates overlay tables; creates user/settings tables
uv run uvicorn app.main:app --reload --port 8010

# Terminal B — frontend
cd frontend
npm install
npm run dev                         # http://localhost:5173
```

There is **no CLI auth step** anymore — no `python -m app.google.auth`, no
`python -m app.google.bootstrap`. Everything flows through the web UI.

---

## 4. Test the flow

- [ ] Open `http://localhost:5173`. You should see the **Sign in with Google** page (not
      the dashboard — the app is now auth-gated).
- [ ] Click **Sign in with Google**. If you added yourself as a test user on the consent
      screen, you'll see the "unverified app" interstitial — click **Continue**. Grant the
      six scopes. You land on the dashboard.
- [ ] `GET /auth/me` in the browser or `curl http://localhost:8010/auth/me` with the
      session cookie should return `{id, email, name, is_superuser: true}`.
- [ ] Open **⚙ Settings**. The calendar list loads from `calendarList.list`. Toggle one
      on and click Save. The day strip should reflect it on next fetch.
- [ ] In **Settings → Allowed emails**, invite a second Google account. Sign out, sign
      in as that account — it should land on its own empty dashboard, isolated from yours.
      The notes folder + Doc for that user are auto-created on first settings visit or
      first captured note.
- [ ] Drop a capture in the scratchpad. With `ANTHROPIC_API_KEY` set, it should route
      within the inline call (you'll see the scratchpad entry flip state); without it, it
      lands in the review queue.
- [ ] Sign out (`POST /auth/logout` or the sign-out button). Reloading takes you back to
      the sign-in page. Re-signing-in should restore your dashboard.

---

## 5. After local testing — proceed to server deploy

Once everything above works locally, follow
[goal-8-owner-steps.md](goal-8-owner-steps.md) for the server deploy
(sections A–G). The only overlap with what you did here:

- **Section A** (Google Cloud): add the **prod redirect URI**
  (`https://<DASHBOARD_DOMAIN>/auth/callback`) to the same OAuth web client (or create a
  second "Dashboard (prod)" client — separate clients make key rotation independent).
  Download the updated (or new) `client_secret.json` for the server.
- **Section B** (secrets): generate fresh `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEY`
  for production — **do not reuse the local ones**. Especially `TOKEN_ENCRYPTION_KEY`:
  rotating it on a running server makes every stored token undecryptable.

---

## 6. Keeping local dev and server in sync

You don't need branches per environment. One `main` branch; two env files.

```
repo root/
  client_secret.json        ← local dev web client (gitignored)
  .env.prod                 ← prod secrets on the server (gitignored)
  backend/.env              ← local dev secrets (gitignored)
```

**Daily dev loop:**

1. Develop locally (`npm run dev` + `uvicorn --reload`). Commit + push to `main`.
2. On the server: `git pull && docker compose --env-file .env.prod up -d --build`
   — compose rebuilds the image, `alembic upgrade head` runs on start, Caddy stays up.

If you add a new migration (`alembic revision --autogenerate`):
- Test `alembic upgrade head` locally first.
- The server applies it automatically on the next `docker compose up --build`
  (entrypoint runs `alembic upgrade head` before uvicorn).
- **No prod data loss** for additive migrations (new columns with defaults, new tables).
  Destructive migrations (drop column, drop table) need a manual backup first — see
  `docs/deploy.md` for the backup cron.

**The `client_secret.json` lives in two places:**
- Repo root on your local machine (for dev).
- `~/dashboard/client_secret.json` on the server (compose mounts it read-only).
  If you created separate local/prod OAuth clients, these files differ — that's fine.

**Schema changes while both are running:**
- Run `uv run alembic upgrade head` locally, verify tests pass, push.
- The server picks it up on the next deploy (`up --build`). The old schema runs fine
  until you deploy (additive changes are backward-compatible; breaking ones need a
  maintenance window, but none are expected in normal feature work).

---

## Cleanup checklist (nothing else to remove)

- `.google-tokens/` — gone (step 0). ✓
- `NOTES_FOLDER_ID`, `NOTES_DOC_ID`, `EXTRA_CALENDAR_IDS` — gone from `.env`. ✓
- `app.google.bootstrap` CLI — deleted in goal-8 (replaced by the settings service). ✓
- The old `python -m app.google.auth` auth flow — gone; sign in through the browser. ✓
- Pre-goal-8 overlay rows — dropped by the migration. ✓
- The `ROUTER_SCHEDULER_INTERVAL` default stretched to ~15 min (inline routing is the
  fast path now; the scheduler is just a retry backstop). No action needed.
