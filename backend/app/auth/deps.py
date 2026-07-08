"""Auth dependencies — the ONE `current_user` resolution every router shares (goal 8).

`get_current_user` reads the signed session cookie → the `user` row (401 if absent).
`get_current_credentials` mints that user's live Google credentials (per-token scope
assertion inside; 403 on a broader-than-allowlist grant, 401 if re-auth is needed).
`require_superuser` gates the allowed-email admin surface.

Row-scoping rule (see .claude/rules/backend.md): every user-owned query filters by
`current_user.id`. Handlers take `user: User = Depends(get_current_user)` and pass
`user.id` into the service layer — never trust an id from the request body/path.
"""

from __future__ import annotations

from fastapi import Depends, Request
from google.oauth2.credentials import Credentials
from sqlmodel import Session

from app.auth.models import User
from app.db import get_session
from app.errors import ApiError
from app.google import auth as google_auth


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise ApiError(401, "unauthenticated", "Sign in required.")
    user = session.get(User, user_id)
    if user is None:
        request.session.clear()
        raise ApiError(401, "unauthenticated", "Sign in required.")
    return user


def get_current_credentials(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Credentials:
    try:
        return google_auth.load_credentials(session, user)
    except google_auth.ScopeError as exc:
        raise ApiError(403, "scope_exceeded", str(exc)) from exc
    except google_auth.CredentialsError as exc:
        raise ApiError(401, "reauth_required", str(exc)) from exc


def require_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise ApiError(403, "forbidden", "Superuser only.")
    return user
