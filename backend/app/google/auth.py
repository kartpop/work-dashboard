"""Per-user Google credentials + the web OAuth flow (goal 8).

Before goal 8 this module held a single shared token file. It now backs a
multi-user web sign-in: Google Sign-In doubles as the OAuth grant, each user's
**refresh token is stored Fernet-encrypted in the `user` row**, and
`load_credentials(user)` mints a fresh access token per request from that token.

The scope allowlist assertion moved from a single startup check to a **per-token**
check (`assert_scopes_within_allowlist`) run at credential-load time: a grant that
carries any scope beyond the allowlist (e.g. a broad `documents`/`drive` leak)
refuses to serve that user — fail-closed, same rule as before, now per user.

Drive access is `drive.file` ONLY — never `documents` or `drive` (ADR:
docs/goals/architecture/drive-access-scoping.md). Adding `documents`/`drive` here
is a hard NO.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

if TYPE_CHECKING:
    from app.auth.models import User
    from sqlmodel import Session

# Identity scopes (Google Sign-In) + the three API scopes. "exactly the three
# scopes + identity" per the goal-8 acceptance bar.
IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
API_SCOPES = [
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
SCOPES = IDENTITY_SCOPES + API_SCOPES

# The per-token assertion refuses to serve any granted scope outside this set — it
# catches a broad `documents`/`drive` grant leaking onto a user's token. A token
# MISSING a scope is fine (that feature degrades); a token BROADER than this is not.
ALLOWED_SCOPES = frozenset(SCOPES)

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
CLIENT_SECRET_PATH = Path(
    os.environ.get("CLIENT_SECRET_PATH", _BACKEND_ROOT.parent / "client_secret.json")
)


class CredentialsError(RuntimeError):
    """Credential load failed — the user must (re-)authorize. Mapped to 401."""


class ScopeError(RuntimeError):
    """A token carries scopes beyond the allowlist — refuse to serve. Mapped to 403."""


# ── Refresh-token encryption at rest (Fernet) ─────────────────────────────────


def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise CredentialsError("TOKEN_ENCRYPTION_KEY is not configured.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt_token(enc: str) -> str:
    return _fernet().decrypt(enc.encode()).decode()


# ── OAuth client config (web or installed client_secret.json) ─────────────────


def _client_config() -> dict:
    data = json.loads(CLIENT_SECRET_PATH.read_text())
    # A web client nests config under "web"; a desktop/dev one under "installed".
    return data.get("web") or data["installed"]


def client_id() -> str:
    return _client_config()["client_id"]


def _redirect_uri() -> str:
    return os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8010/auth/callback")


# ── Web sign-in flow ──────────────────────────────────────────────────────────


def build_flow(state: str | None = None) -> Flow:
    """Build the OAuth Flow bound to our client + redirect URI (identity + 3 scopes)."""
    return Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
        state=state,
    )


def authorization_url() -> tuple[str, str]:
    """Return (url, state) for the consent redirect. `access_type=offline` +
    `prompt=consent` guarantees a refresh token even on repeat sign-ins."""
    flow = build_flow()
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, state


def exchange_code(code: str, state: str | None = None) -> Credentials:
    """Exchange an authorization code for credentials (access + refresh token)."""
    flow = build_flow(state=state)
    flow.fetch_token(code=code)
    return flow.credentials


def verify_id_token(raw_id_token: str) -> dict:
    """Verify the Google-issued ID token and return its claims (sub/email/...)."""
    return google_id_token.verify_oauth2_token(raw_id_token, Request(), client_id())


# ── Scope assertion (per-token, fail-closed) ──────────────────────────────────


def assert_scopes_within_allowlist(scopes: Iterable[str] | None) -> None:
    """Refuse to serve a token whose grant carries any scope outside the allowlist.

    Called at credential-load time (per user). Missing scopes are allowed (feature
    degradation); a *broader* grant than we ever request is the drift we block."""
    extra = set(scopes or ()) - ALLOWED_SCOPES
    if extra:
        raise ScopeError(
            "Google token carries scopes outside the allowlist: "
            f"{sorted(extra)}. Never grant `documents`/`drive` "
            "(ADR: docs/goals/architecture/drive-access-scoping.md)."
        )


# ── Per-user credential load (from the DB, refresh, persist back) ──────────────


def load_credentials(session: "Session", user: "User") -> Credentials:
    """Build a live `Credentials` for `user` from their encrypted refresh token.

    Fail-closed on the scope allowlist (per token). Always refreshes to mint a fresh
    access token (only the refresh token is persisted); if Google rotates the refresh
    token, the new one is re-encrypted and saved back.
    """
    if not user.refresh_token_encrypted:
        raise CredentialsError("No stored Google credentials — sign in again.")

    assert_scopes_within_allowlist(
        user.granted_scopes.split() if user.granted_scopes else None
    )

    refresh = decrypt_token(user.refresh_token_encrypted)
    cfg = _client_config()
    creds = Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri=cfg["token_uri"],
        scopes=user.granted_scopes.split() if user.granted_scopes else SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception as exc:  # refresh token revoked/expired → re-auth required
        raise CredentialsError(f"Could not refresh Google credentials: {exc}") from exc

    if creds.refresh_token and creds.refresh_token != refresh:
        from datetime import datetime, timezone

        user.refresh_token_encrypted = encrypt_token(creds.refresh_token)
        user.updated_at = datetime.now(timezone.utc)
        session.add(user)
        session.commit()

    return creds
