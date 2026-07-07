"""Shared OAuth credentials for the Google API client modules.

Run once, interactively, to grant access and persist a token:

    uv run python -m app.google.auth

Routers and the other `app.google.*` modules call `load_credentials()`, which
reuses and refreshes that persisted token. It never launches the consent flow
itself — a web server process must not block a request on a browser prompt.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Changing these scopes requires re-running `uv run python -m app.google.auth`.
#
# Drive access is `drive.file` ONLY — never `documents` or `drive` (ADR:
# docs/goals/architecture/drive-access-scoping.md). Google itself then guarantees the
# token can touch only files the app created; app-code gates are defence-in-depth on
# top of that wall. Adding `documents`/`drive` here is a hard NO — do Option B instead.
SCOPES = [
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

# The startup assertion refuses to boot on any granted scope outside this set — it
# catches "re-authed broad while debugging" drift (a scoped design's classic rot).
# A token MISSING drive.file is fine (the notes writer just degrades to kept-local);
# a token with `documents`/`drive` is not (it can rewrite the whole account).
ALLOWED_SCOPES = frozenset(SCOPES)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SECRET_PATH = _BACKEND_ROOT.parent / "client_secret.json"
TOKEN_PATH = _BACKEND_ROOT / ".google-tokens" / "token.json"


def load_credentials() -> Credentials:
    """Load the persisted token, refreshing it if it has expired.

    Scopes are read from the token file itself (not forced to `SCOPES`) so an old,
    narrower token still loads and refreshes cleanly after `SCOPES` grows — the
    drive.file features degrade to kept-local until the owner re-auths.
    """
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Google OAuth token at {TOKEN_PATH}. "
            "Run `uv run python -m app.google.auth` once to authorize this app."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persist(creds)
    return creds


def granted_scopes() -> list[str]:
    """Read the scopes actually granted on the persisted token (empty if no token)."""
    if not TOKEN_PATH.exists():
        return []
    return Credentials.from_authorized_user_file(str(TOKEN_PATH)).scopes or []


def assert_scopes_within_allowlist() -> None:
    """Fail-closed startup guard: refuse to boot if the token carries any scope
    outside `ALLOWED_SCOPES`. Missing scopes are allowed (feature degradation);
    a *broader* grant than we ever request is the drift we block."""
    extra = set(granted_scopes()) - ALLOWED_SCOPES
    if extra:
        raise RuntimeError(
            "Google token carries scopes outside the allowlist: "
            f"{sorted(extra)}. Re-auth narrower — never grant `documents`/`drive` "
            "(ADR: docs/goals/architecture/drive-access-scoping.md). "
            "Delete backend/.google-tokens/token.json and re-run "
            "`uv run python -m app.google.auth`."
        )


def authorize() -> Credentials:
    """Run the interactive consent flow and persist the resulting token."""
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    _persist(creds)
    return creds


def _persist(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())


if __name__ == "__main__":
    authorize()
    print(f"Token persisted to {TOKEN_PATH}")
