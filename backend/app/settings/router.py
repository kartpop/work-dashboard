"""Settings HTTP surface (goal 8).

Per-user calendar toggles + the read-only notes folder/Doc ids, plus the
superuser-only allowed-email admin. Everything is scoped to `current_user`; the
allowed-email endpoints additionally require `is_superuser` (403 otherwise) and are
hidden entirely from the non-superuser UI.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import service as auth_svc
from app.auth.deps import (
    get_current_credentials,
    get_current_user,
    require_superuser,
)
from app.auth.models import User
from app.db import get_session
from app.errors import ApiError
from app.google import calendar as calendar_client
from app.settings import service as settings_svc

router = APIRouter(prefix="/settings", tags=["settings"])


def _folder_url(fid: str | None) -> str | None:
    return f"https://drive.google.com/drive/folders/{fid}" if fid else None


def _doc_url(did: str | None) -> str | None:
    return f"https://docs.google.com/document/d/{did}/edit" if did else None


@router.get("")
async def get_settings(
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_current_credentials),
    session: Session = Depends(get_session),
):
    """Return the user's settings: which calendars they can see (with the toggle
    state), and their notes folder/Doc ids (bootstrapped here on first visit)."""
    enabled = set(settings_svc.get_enabled_calendar_ids(session, user.id))
    try:
        calendars = await calendar_client.get_calendar_list(creds)
    except Exception as exc:
        raise ApiError(
            502, "google_calendar_unavailable", "Could not list your calendars."
        ) from exc
    calendars_out = [
        {**c, "enabled": c["primary"] or c["id"] in enabled} for c in calendars
    ]
    # Include any toggled-on id the calendarList didn't return (add-by-id calendars).
    known = {c["id"] for c in calendars}
    for cid in enabled - known:
        calendars_out.append(
            {
                "id": cid,
                "summary": cid,
                "primary": False,
                "background_color": None,
                "enabled": True,
            }
        )

    # "settings visit" bootstraps the notes folder/Doc if they don't exist yet.
    doc_id, folder_id = await settings_svc.ensure_notes_target(session, creds, user.id)
    return {
        "calendars": calendars_out,
        "enabled_calendar_ids": sorted(enabled),
        "notes_folder_id": folder_id,
        "notes_doc_id": doc_id,
        "notes_folder_url": _folder_url(folder_id),
        "notes_doc_url": _doc_url(doc_id),
    }


class CalendarsUpdate(BaseModel):
    # The full set of extra (non-primary) calendar ids to merge into the day strip.
    # Free-text ids not in calendarList are accepted (add-by-id, goal 8).
    calendar_ids: list[str]


@router.put("/calendars")
async def set_calendars(
    body: CalendarsUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    settings_svc.set_enabled_calendars(session, user.id, body.calendar_ids)
    return {
        "enabled_calendar_ids": settings_svc.get_enabled_calendar_ids(session, user.id)
    }


# ── Allowed emails (superuser only) ───────────────────────────────────────────


def _allowed_out(row) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "added_by": row.added_by,
        "created_at": row.created_at.isoformat(),
    }


class AllowedEmailCreate(BaseModel):
    email: str


@router.get("/allowed-emails")
async def list_allowed(
    superuser: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    return {"allowed": [_allowed_out(r) for r in auth_svc.list_allowed(session)]}


@router.post("/allowed-emails", status_code=201)
async def add_allowed(
    body: AllowedEmailCreate,
    superuser: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    email = body.email.strip().lower()
    if "@" not in email:
        raise ApiError(400, "invalid_email", "Enter a valid email address.")
    row = auth_svc.add_allowed(session, email, added_by=superuser.email)
    return _allowed_out(row)


@router.delete("/allowed-emails/{email}")
async def remove_allowed(
    email: str,
    superuser: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    ok = auth_svc.remove_allowed(session, email)
    if not ok:
        raise ApiError(
            400,
            "cannot_remove",
            "That email is not removable (unknown, or the superuser's own).",
        )
    return {"ok": True}
