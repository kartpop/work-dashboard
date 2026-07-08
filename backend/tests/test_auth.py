"""Goal-8 acceptance-criteria tests: refresh-token encryption at rest, the per-token
scope assertion, and the allowlist + superuser rules (service + endpoint level).

All pure/DB or mocked — no Google network. `load_credentials` never actually refreshes
here: the scope test raises before `.refresh()`, and the within-allowlist test
monkeypatches `Credentials.refresh` to a no-op.
"""

from __future__ import annotations

import pytest

from app.auth import service as auth_svc
from app.auth.models import User
from app.google import auth as google_auth


# ── Refresh token encrypted at rest ─────────────────────────────────────────────


def test_refresh_token_encrypted_at_rest_and_round_trips(session):
    """`get_or_create_user` stores the refresh token Fernet-encrypted (never the
    plaintext); `decrypt_token` recovers it."""
    plaintext = "1//super-secret-refresh-token"
    user = auth_svc.get_or_create_user(
        session,
        claims={"sub": "sub-x", "email": "x@example.com", "name": "X"},
        refresh_token=plaintext,
        granted_scopes=list(google_auth.SCOPES),
    )
    assert user.refresh_token_encrypted is not None
    assert user.refresh_token_encrypted != plaintext  # not stored in the clear
    assert google_auth.decrypt_token(user.refresh_token_encrypted) == plaintext


# ── Per-token scope assertion ───────────────────────────────────────────────────


def test_load_credentials_rejects_scope_outside_allowlist(session):
    """A user whose granted scopes exceed the allowlist (a `drive` leak) makes
    `load_credentials` raise `ScopeError` — before any network refresh."""
    over_broad = list(google_auth.SCOPES) + ["https://www.googleapis.com/auth/drive"]
    user = User(
        google_sub="sub-broad",
        email="broad@example.com",
        refresh_token_encrypted=google_auth.encrypt_token("rt"),
        granted_scopes=" ".join(over_broad),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    with pytest.raises(google_auth.ScopeError):
        google_auth.load_credentials(session, user)


def test_assert_scopes_within_allowlist_passes_for_granted_set():
    # A within-allowlist grant (a subset is fine too) does not raise.
    google_auth.assert_scopes_within_allowlist(list(google_auth.SCOPES))
    google_auth.assert_scopes_within_allowlist(
        ["https://www.googleapis.com/auth/tasks"]
    )


def test_load_credentials_within_allowlist_passes(session, monkeypatch):
    """A within-allowlist user loads credentials; the network refresh is stubbed."""
    from google.oauth2.credentials import Credentials

    def _fake_refresh(self, request):
        self.token = "fresh-access-token"

    monkeypatch.setattr(Credentials, "refresh", _fake_refresh)
    # load_credentials reads a client config off disk; point it at a minimal temp one.
    import json
    import tempfile
    from pathlib import Path

    secret = {
        "installed": {
            "client_id": "cid",
            "client_secret": "csecret",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(secret, f)
        secret_path = f.name
    monkeypatch.setattr(google_auth, "CLIENT_SECRET_PATH", Path(secret_path))

    user = User(
        google_sub="sub-ok",
        email="ok@example.com",
        refresh_token_encrypted=google_auth.encrypt_token("rt"),
        granted_scopes=" ".join(google_auth.SCOPES),
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    creds = google_auth.load_credentials(session, user)
    assert creds.token == "fresh-access-token"


# ── Allowlist + superuser (service level) ───────────────────────────────────────


def test_is_email_allowed_superuser_added_and_denied(session, monkeypatch):
    monkeypatch.setenv("SUPERUSER_EMAIL", "boss@example.com")
    # Superuser is always allowed.
    assert auth_svc.is_email_allowed(session, "boss@example.com") is True
    assert (
        auth_svc.is_email_allowed(session, "BOSS@example.com") is True
    )  # case-insens.
    # Unknown email denied.
    assert auth_svc.is_email_allowed(session, "stranger@example.com") is False
    # Added email allowed.
    auth_svc.add_allowed(session, "friend@example.com", added_by="boss@example.com")
    assert auth_svc.is_email_allowed(session, "friend@example.com") is True


def test_add_and_remove_allowed(session, monkeypatch):
    monkeypatch.setenv("SUPERUSER_EMAIL", "boss@example.com")
    auth_svc.add_allowed(session, "friend@example.com", added_by="boss@example.com")
    assert auth_svc.is_email_allowed(session, "friend@example.com") is True
    assert auth_svc.remove_allowed(session, "friend@example.com") is True
    assert auth_svc.is_email_allowed(session, "friend@example.com") is False
    # Removing an unknown email → False.
    assert auth_svc.remove_allowed(session, "nobody@example.com") is False


def test_remove_allowed_refuses_superuser_own_email(session, monkeypatch):
    monkeypatch.setenv("SUPERUSER_EMAIL", "boss@example.com")
    assert auth_svc.remove_allowed(session, "boss@example.com") is False
    # Still allowed after the refused removal.
    assert auth_svc.is_email_allowed(session, "boss@example.com") is True


# ── Allowed-email endpoints require superuser (endpoint level) ──────────────────


def test_allowed_email_endpoints_403_for_non_superuser(auth, user_a):
    """A non-superuser is 403 on every allowed-email admin endpoint."""
    client = auth.as_user(user_a)  # user_a.is_superuser is False by default
    assert client.get("/settings/allowed-emails").status_code == 403
    assert (
        client.post(
            "/settings/allowed-emails", json={"email": "x@example.com"}
        ).status_code
        == 403
    )
    assert client.delete("/settings/allowed-emails/x@example.com").status_code == 403


def test_allowed_email_endpoints_ok_for_superuser(auth, session, monkeypatch):
    monkeypatch.setenv("SUPERUSER_EMAIL", "boss@example.com")
    su = User(
        google_sub="sub-su",
        email="boss@example.com",
        is_superuser=True,
    )
    session.add(su)
    session.commit()
    session.refresh(su)

    client = auth.as_user(su)
    assert client.get("/settings/allowed-emails").status_code == 200
    r = client.post("/settings/allowed-emails", json={"email": "new@example.com"})
    assert r.status_code == 201
    listing = client.get("/settings/allowed-emails").json()["allowed"]
    assert any(row["email"] == "new@example.com" for row in listing)
