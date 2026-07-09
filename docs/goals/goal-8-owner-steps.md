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
      - `https://dashboard.<yourdomain>.com/auth/callback` (prod)
      - `http://localhost:8010/auth/callback` (local dev)
      Download the JSON as **`client_secret.json`** (it will have a `"web"` key).
      > ⚠️ **Never replace this OAuth client id later.** Under `drive.file`, Google keys
      > per-file access to the client id that *created* a file — a new client id (or a new
      > GCP project) is a different app and gets 404 on every user's existing notes
      > folder/Doc. Rotating the client **secret** is fine; changing the client **id** is
      > not. (The app self-heals into a *fresh* Doc if this ever happens — goal 8a — but
      > that orphans the old notes; don't rely on it.)

## B. EC2 host

### B1. Launch the instance

- [ ] EC2 console → **Launch instance**. Name it `dashboard`.
- [ ] **AMI:** Ubuntu Server LTS (24.04 or 22.04), 64-bit (x86 — `t3` is Intel; if you
      pick a `t4g`/Graviton size choose the ARM AMI to match).
- [ ] **Instance type:** `t3.small` (2 vCPU / 2 GB) is the floor — the build compiles the
      Vite SPA and `uv sync`s the backend, which 1 GB can OOM. `t3.medium` (4 GB) if you
      want headroom.
- [ ] **Key pair:** *Create a new key pair* → type **RSA**, format **.pem** → download it.
      Save as e.g. `~/.ssh/dashboard.pem`. You cannot re-download it later; without it you
      can't `ssh` in (step E `scp`s `client_secret.json` over this same key).
- [ ] **Network → Auto-assign public IP: Enable.** (Or attach an Elastic IP after launch so
      the address survives a stop/start — the DNS A record in step D points at this IP.)
- [ ] **Storage:** bump the root volume to **20 GB** gp3 (the 8 GB default fills up with
      Docker images/layers).
- [ ] Launch, then on your laptop lock down the key's permissions or `ssh` will refuse it:

      ```sh
      chmod 400 ~/.ssh/dashboard.pem
      ```

### B2. Security group (inbound rules)

Edit the instance's security group → **Inbound rules**:

- [ ] **SSH** — port **22**, source **My IP** (not `0.0.0.0/0`; re-edit if your ISP IP changes).
- [ ] **HTTP** — port **80**, source **0.0.0.0/0** (Caddy's Let's Encrypt HTTP-01 challenge + redirect to 443).
- [ ] **HTTPS** — port **443**, source **0.0.0.0/0** (the app).

  Leave all outbound rules at the default allow-all (needed to pull images, reach Google, Anthropic, Let's Encrypt).

### B3. First SSH in

- [ ] Grab the instance's **Public IPv4 address** from the console, then:

      ```sh
      ssh -i ~/.ssh/dashboard.pem ubuntu@<EC2_IP>
      ```

  (Accept the host-key fingerprint on first connect. `ubuntu` is the default user on the
  Ubuntu AMI.) Optionally add a `~/.ssh/config` block so later `ssh`/`scp` is just `ssh dashboard`:

      ```
      Host dashboard
          HostName <EC2_IP>
          User ubuntu
          IdentityFile ~/.ssh/dashboard.pem
      ```

### B4. Install Docker Engine + compose plugin (on the host)

- [ ] Update and install from Docker's official apt repo (Ubuntu's `docker.io` package is
      fine too, but this gets you the current Engine + the `docker compose` v2 plugin):

      ```sh
      sudo apt-get update
      sudo apt-get install -y ca-certificates curl
      sudo install -m 0755 -d /etc/apt/keyrings
      sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      sudo chmod a+r /etc/apt/keyrings/docker.asc
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
      sudo apt-get update
      sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
      ```

- [ ] Run Docker without `sudo`, then **re-login** so the new group membership takes effect:

      ```sh
      sudo usermod -aG docker ubuntu
      exit            # drop the SSH session
      ```
      ```sh
      ssh -i ~/.ssh/dashboard.pem ubuntu@<EC2_IP>   # back in with the docker group
      docker run --rm hello-world                    # verify: pulls + prints, no sudo
      docker compose version                         # verify the compose plugin
      ```

### B5. Clone the repo to `~/dashboard`

- [ ] If the repo is **public**:

      ```sh
      git clone https://github.com/<owner>/<repo>.git ~/dashboard
      cd ~/dashboard
      ```

- [ ] If the repo is **private**, the fresh box has no GitHub credentials. Easiest is a
      short-lived **HTTPS [PAT](https://github.com/settings/tokens)** (fine-grained, *Contents:
      read* on this repo):

      ```sh
      git clone https://<PAT>@github.com/<owner>/<repo>.git ~/dashboard
      ```

      The token gets written into `~/dashboard/.git/config`. Scrub it after cloning so it
      doesn't linger on disk:

      ```sh
      cd ~/dashboard
      git remote set-url origin https://github.com/<owner>/<repo>.git
      ```

      (Alternative: generate an SSH key on the host with `ssh-keygen -t ed25519`, add the
      `.pub` as a repo **deploy key** on GitHub, then `git clone git@github.com:<owner>/<repo>.git`.)

  Continue with step C (secrets) and step D (DNS). Nothing gets built until the deploy step.

## C. Secrets

Generate these on the EC2 host (they go into `.env.prod` in step E).

Python 3 is pre-installed on Ubuntu 24.04 so `SESSION_SECRET` works immediately. For
`TOKEN_ENCRYPTION_KEY` you need the `cryptography` package — install it via apt (simplest)
or use the `docker` command that's now available from B4:

```sh
# Option 1 — apt (installs system-wide, no venv needed)
sudo apt-get install -y python3-cryptography

# Option 2 — Docker (no extra apt package)
docker run --rm python:3.12-slim python -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

- [ ] `SESSION_SECRET`:
      `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] `TOKEN_ENCRYPTION_KEY` (use one of the options above, e.g.):
      `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
      **Keep this stable** — rotating it makes every stored refresh token undecryptable
      (users must re-sign-in).
- [ ] `SUPERUSER_EMAIL`: your @gmail address (bootstraps the admin + is always allowed).
- [ ] `ANTHROPIC_API_KEY`: the one app-level key (owner pays for everyone's routing).

## D. DNS (Cloudflare)

- [ ] Add an **A record** `dashboard` → the EC2 public IP.
- [ ] Set it **DNS only (grey cloud)** — not proxied — so Caddy can complete the
      Let's Encrypt HTTP-01 challenge directly (locked: Cloudflare proxy/Tunnel skipped).
- [ ] **Verify it resolves before deploying:** `dig +short dashboard.<yourdomain>.com` should
      return the EC2 IP. If you run step E before this propagates, Caddy's first
      cert attempt fails and retries — harmless, but alarming in the logs.

## E. Deploy

- [ ] On the host: `cp .env.prod.example .env.prod` and fill every value (domain,
      redirect URI, `FRONTEND_ORIGIN=https://dashboard.<yourdomain>.com`, the three
      secrets, API key).
- [ ] Copy `client_secret.json` (the **web** client from step A) to the repo root
      (`~/dashboard/client_secret.json`) — compose mounts it read-only. It's gitignored,
      so `git clone` does **not** bring it; `scp` it from your laptop (where you tested
      local): `scp -i <key.pem> client_secret.json ubuntu@<EC2_IP>:~/dashboard/`.
- [ ] `docker compose --env-file .env.prod up -d --build`
- [ ] Watch `docker compose logs -f app` for `alembic upgrade head` + uvicorn start,
      and `docker compose logs -f caddy` for a successful certificate.

## F. First sign-in + invites

- [ ] Visit `https://dashboard.<yourdomain>.com`, click **Sign in with Google**, accept the
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
