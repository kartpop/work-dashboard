"""Auth service: user upsert, the email allowlist, and superuser bootstrap (goal 8).

Deterministic DB logic only — the OAuth dance lives in `app.google.auth`, the HTTP
routes in `app.auth.router`. The allowlist is a DB table the superuser edits;
`SUPERUSER_EMAIL` (env) is always allowed and flags its user row `is_superuser`.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.auth.models import AllowedEmail, User
from app.google import auth as google_auth


def _now() -> datetime:
    return datetime.now(timezone.utc)


def superuser_email() -> str | None:
    email = os.environ.get("SUPERUSER_EMAIL")
    return email.strip().lower() if email else None


def is_email_allowed(session: Session, email: str) -> bool:
    """True if `email` is the superuser or appears in the allowlist table."""
    e = email.strip().lower()
    if e == superuser_email():
        return True
    return (
        session.exec(select(AllowedEmail).where(AllowedEmail.email == e)).first()
        is not None
    )


def get_or_create_user(
    session: Session,
    claims: dict,
    refresh_token: str | None,
    granted_scopes: list[str],
) -> User:
    """Upsert the `user` row from verified ID-token claims + a fresh grant.

    Stores the refresh token **encrypted** (only when Google returned one — a repeat
    sign-in without `prompt=consent` may omit it, so we keep the existing token).
    Flags `is_superuser` when the email matches `SUPERUSER_EMAIL`.
    """
    sub = claims["sub"]
    email = (claims.get("email") or "").strip().lower()
    user = session.exec(select(User).where(User.google_sub == sub)).first()
    if user is None:
        user = User(google_sub=sub, email=email)

    user.email = email
    user.name = claims.get("name")
    user.picture = claims.get("picture")
    user.is_superuser = email == superuser_email()
    user.granted_scopes = " ".join(granted_scopes)
    if refresh_token:
        user.refresh_token_encrypted = google_auth.encrypt_token(refresh_token)
    user.updated_at = _now()

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ── Allowed-email CRUD (superuser only — enforced at the router) ──────────────


def list_allowed(session: Session) -> list[AllowedEmail]:
    return list(session.exec(select(AllowedEmail).order_by(AllowedEmail.email)).all())


def add_allowed(session: Session, email: str, added_by: str) -> AllowedEmail:
    e = email.strip().lower()
    existing = session.exec(select(AllowedEmail).where(AllowedEmail.email == e)).first()
    if existing:
        return existing
    row = AllowedEmail(email=e, added_by=added_by)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def remove_allowed(session: Session, email: str) -> bool:
    """Remove an allowlist entry. The superuser's own email can never be removed
    (returns False without deleting). Removal blocks future sign-ins only."""
    e = email.strip().lower()
    if e == superuser_email():
        return False
    row = session.exec(select(AllowedEmail).where(AllowedEmail.email == e)).first()
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
