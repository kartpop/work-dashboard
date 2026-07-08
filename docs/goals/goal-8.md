# Goal 8 — Deploy-ready: Google Sign-In, multi-tenancy, EC2

**One line:** The app graduates from "one local process, one token file, four env vars" to a
deployable multi-user service at `dashboard.<owner-domain>.com`: Google Sign-In doubles as the
OAuth grant (tasks + calendar.readonly + drive.file per user), per-user encrypted tokens and
settings live in the DB, every row is user-scoped, and the repo ships the Docker/Caddy/EC2
artifacts to run it on a small instance behind Cloudflare DNS.

## Intent / acceptance bar

The owner's wife and a few close friends can each sign in with Google, grant the three scopes,
and get their *own* dashboard — their tasks, their calendars, their notes Doc — with zero shared
state and zero server-side per-user setup. The bar: a brand-new allowlisted user goes from the
sign-in page to a working dashboard (including their first routed note landing in an
auto-created Doc in *their* Drive) without the owner touching the server. Security posture:
**lightest acceptable for friends-and-family** — allowlist + session cookies + strict row
scoping + encrypted tokens — not enterprise hardening.

## What ships

- **1. Google Sign-In = auth + authorization, one flow.** A web-app OAuth flow replaces the
  `InstalledAppFlow` CLI (`app/google/auth.py` reworked; the CLI path may remain for local dev).
  `GET /auth/login` → Google consent (identity + the three scopes, `access_type=offline`);
  `GET /auth/callback` verifies the ID token, upserts the `user` row, stores the refresh token,
  sets the session. Sign-out clears the session. Unauthenticated API/page access → login.
  - **Email allowlist — DB table + superuser (amended 2026-07-08).** The allowlist is a
    simple `allowed_email` table (email, added_by, created_at) with CRUD exposed **only to
    the superuser** in the settings page; the `ALLOWED_EMAILS` env var dies. **`SUPERUSER_EMAIL`**
    (env) bootstraps it: that address is always allowed and its `user` row is flagged
    `is_superuser` at first sign-in. A non-allowlisted Google account gets a friendly
    "not invited" page — no user row, no token stored. Removing an email blocks *future*
    sign-ins only (no session revocation, no row deletion — fine at this scale); the
    superuser cannot remove their own email.
  - **Sessions:** Starlette `SessionMiddleware` — signed cookie, `HttpOnly`, `Secure`,
    `SameSite=Lax`, secret from `SESSION_SECRET`. No JWT machinery.
- **2. Per-user Google credentials.** `user` table stores the refresh token **encrypted at rest**
  (Fernet, key from `TOKEN_ENCRYPTION_KEY`). `load_credentials()` becomes per-user (loads from
  DB, refreshes, persists back); the **scope allowlist assertion moves from startup to per-token
  load** — same fail-closed rule (a broader-than-allowlist grant refuses to serve that user), a
  *missing* scope degrades that feature for that user only. The token file and its startup
  assertion die (dev fallback aside).
- **3. Row-level multi-tenancy.** `user_id` FK on every user-owned table: `scratch_entry`,
  `review_item`, the task-overlay rows, `task_group` (Alembic migration). Every router resolves
  `current_user` from the session via one dependency; every service query filters by it. The
  scheduler backstop iterates per user with that user's credentials. **Existing local rows are
  lost — no migration (amended 2026-07-08):** the overlay/review data is test-mode and
  recreatable, so the server starts from an empty `overlay.db`. No claim command, no DB-copy
  owner step.
- **4. Per-user settings replace the env vars.** New `user_settings` storage +
  a minimal settings page:
  - **Calendars:** the app lists the calendars the account can already see
    (`calendarList.list` — within `calendar.readonly`; new fetch+reshape fn in
    `app/google/calendar.py`) and the user **toggles** which merge into the day strip. Replaces
    `EXTRA_CALENDAR_IDS`. Primary is always on; same `iCalUID` dedupe and best-effort extras.
    Plus a free-text **add-calendar-by-ID** field (amended 2026-07-08) for calendars the
    account can read but that don't appear in its `calendarList` — same best-effort merge.
  - **Notes Doc — auto-bootstrap:** on first need (first routed note, or settings visit) the app
    creates a **"Dashboard Notes" folder at the user's Drive root and the notes Doc inside it**,
    and stores both IDs in the user's settings. Replaces `NOTES_FOLDER_ID` *and* `NOTES_DOC_ID`;
    the CLI bootstrap command's logic is reused per-user. The folder-ancestry gate reads the
    user's stored folder ID. IDs remain config-only (now DB-config) — never LLM output. The
    settings page shows the folder/Doc IDs **read-only** (with Drive links) — not editable:
    under `drive.file` the app can only write files it created, so a user-pasted ID would be
    unwritable.
  - **Allowed emails (superuser only):** the `allowed_email` CRUD from item 1 lives here;
    hidden entirely for non-superusers (and the endpoints 403).
- **5. Deployment artifacts.** Multi-stage Dockerfile (build the Vite bundle → FastAPI serves it
  via `StaticFiles`; one container, one process), `docker-compose.yml` (app + Caddy), `Caddyfile`
  (auto-TLS for `dashboard.<domain>`), SQLite in **WAL mode** on a mounted volume, and a nightly
  `sqlite3 .backup` cron to a second on-disk path (off-box backup **explicitly skipped** —
  locked 2026-07-08; the overlay data is recreatable, revisit if that changes).
  `docs/deploy.md` documents the stack; **`goal-8-owner-steps.md`** is the ordered checklist:
  web OAuth client + redirect URIs, consent screen **published unverified**, EC2 instance +
  security group, Cloudflare DNS record, env secrets (incl. `SUPERUSER_EMAIL`). *(No DB-copy
  or row-claim steps — the server starts from an empty `overlay.db`.)*
- **6. Local dev keeps working.** `http://localhost:8010` (or `:5173` proxied) as a second
  redirect URI on the same OAuth client; documented in the README. No separate dev auth system.

## Locked decisions (2026-07-07)

- **Consent screen: published, unverified.** Users click through Google's "unverified app"
  interstitial once; refresh tokens don't expire (testing mode's 7-day expiry is the
  disqualifier); ≤100-user cap is irrelevant here. Full verification is explicitly not pursued.
- **Notes folder is app-created, not user-chosen.** Under `drive.file` the app cannot write into
  an arbitrary user folder (ADR stands — scope is still `drive.file` only, per user). No Google
  Picker. Users may move/rename the folder in Drive afterwards — IDs stay stable.
- **Hosting: one small EC2 instance (~$10/mo class), Cloudflare DNS, Caddy auto-TLS, single
  container.** Reserved instance later if usage sticks. No managed PaaS.
- **SQLite stays** (WAL, single instance, volume + backup cron). Postgres is deferred until it
  actually hurts; the in-process scheduler shares the same single-instance assumption, so they
  move together if that day comes.
- **TLS = Caddy + Let's Encrypt, Cloudflare DNS-only (re-confirmed 2026-07-08).** Cloudflare's
  proxy/Tunnel modes considered and skipped — least ops surface wins. Backup = local-only
  second path, no off-box copy.
- **Pinned lists stay convention-by-title** ("My Tasks" is Google's default list name;
  "Follow-ups" is created once — the empty-column hint guides new users). No per-user pinned
  config in this goal.
- **One app-level `ANTHROPIC_API_KEY`** — the owner pays for everyone's routing (Haiku
  classification ≈ noise). No per-user keys, no rate limiting yet.
- **Security floor:** allowlist + signed `HttpOnly`/`Secure`/`SameSite=Lax` session cookie +
  row scoping via one `current_user` dependency + Fernet-encrypted refresh tokens + HTTPS.
  `SameSite=Lax` + JSON-body mutations is the accepted CSRF stance at this scale.

## Out of scope (do not build)

- Postgres / multi-instance / HA / autoscaling.
- Google app verification, Google Picker, any scope beyond the existing three.
- Per-user pinned-list config or a list-visibility chooser (dropped g9a residue — revisit only
  if a real user hurts).
- Rate limiting, audit logging, per-user API keys/quotas, admin UI beyond the superuser's
  allowed-emails section in settings.
- Any feature work — 7c closed the feature gaps; this goal is auth + tenancy + infra only.

## Acceptance criteria

- Sign-in: allowlisted account → consent (exactly the three scopes + identity) → working
  dashboard; non-allowlisted → refusal page, no user row, no token persisted; sign-out works;
  unauthenticated API calls → 401 envelope.
- Superuser: only the `SUPERUSER_EMAIL` account sees the allowed-emails section; adding an
  email lets that account sign in; removing one blocks its next sign-in; allowlist endpoints
  return 403 for non-superusers; the superuser's own email cannot be removed.
- **Isolation (the headline check):** with two signed-in users, every surface — tasks, overlay
  writes, scratch, review queue, calendar day, settings — returns/mutates only the requesting
  user's rows; user B can neither read nor write user A's data by ID guessing (endpoint tests
  with two seeded users).
- Refresh tokens unreadable in a raw DB dump (encrypted); a token with a broader-than-allowlist
  scope refuses to serve that user (per-token assertion test).
- New-user bootstrap: first routed note auto-creates the Drive folder + Doc in *that user's*
  Drive and persists the IDs; the folder-ancestry gate holds per user.
- Calendar settings: toggling a visible calendar on/off changes the day-strip merge for that
  user only.
- Scheduler backstop routes each user's unrouted entries with that user's credentials.
- `docker compose up` on a clean machine serves the built frontend + API on one port behind
  Caddy TLS; SQLite is in WAL mode on the volume; the backup cron produces a restorable copy.
- Owner-steps checklist exists and is executable top-to-bottom; local dev flow documented and
  working; AST write-dependency test and eval gate unchanged; `tsc`, build, all backend tests
  green.

## Harness upkeep (closing checklist — friction-driven only)

- `backend.md`: the `current_user` dependency + row-scoping convention (every new query filters
  by user — this is now a hard rule worth a rule-file line).
- `writes.md` + `router.md`: per-user credentials/doc-ID resolution notes where they touch the
  write paths.
- `google-api-integration`: web-flow credentials + `calendarList.list` conventions if the module
  shape earns it.
- `verifier-web` / `verifier-writes`: two-user isolation checks; verification against a deployed
  instance is a new mode — document what the verifier can/can't reach.
- `goal-8-owner-steps.md` (mandatory — this goal is full of non-code owner actions).
- Refresh root `README.md` (run/deploy steps changed) + `docs/api-reference.md` (auth endpoints,
  settings endpoints). Wrap-up to the planning chat.
