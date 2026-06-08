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

SCOPES = [
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SECRET_PATH = _BACKEND_ROOT.parent / "client_secret.json"
TOKEN_PATH = _BACKEND_ROOT / ".google-tokens" / "token.json"


def load_credentials() -> Credentials:
    """Load the persisted token, refreshing it if it has expired."""
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Google OAuth token at {TOKEN_PATH}. "
            "Run `uv run python -m app.google.auth` once to authorize this app."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persist(creds)
    return creds


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
