"""Per-user settings service (goal 8) — replaces the NOTES_* / EXTRA_CALENDAR_IDS
env vars with a `user_settings` row per user.

Two pieces of per-user config:
- **Calendars:** the extra calendar ids merged into the day strip (primary always on).
- **Notes target:** the app-created notes folder + Doc ids in *this* user's Drive,
  bootstrapped on first need (`ensure_notes_target`). IDs are config-only (DB now),
  never LLM output; under `drive.file` the app can only touch files it created, so
  the folder + Doc must be app-created — never a user-pasted id.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlmodel import Session

from app.auth.models import UserSettings
from app.errors import ApiError
from app.google import docs as docs_client

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

_NOTES_FOLDER_NAME = "Dashboard Notes"
_NOTES_DOC_NAME = "Dashboard — Notes"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create(session: Session, user_id: int) -> UserSettings:
    row = session.get(UserSettings, user_id)
    if row is None:
        row = UserSettings(user_id=user_id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def enabled_calendar_ids(settings: UserSettings) -> list[str]:
    try:
        ids = json.loads(settings.enabled_calendar_ids or "[]")
    except json.JSONDecodeError:
        return []
    return [str(c) for c in ids if isinstance(c, str) and c.strip()]


def get_enabled_calendar_ids(session: Session, user_id: int) -> list[str]:
    return enabled_calendar_ids(get_or_create(session, user_id))


def set_enabled_calendars(
    session: Session, user_id: int, calendar_ids: list[str]
) -> UserSettings:
    """Persist the user's toggled-on extra calendars (dedupe, drop blanks)."""
    seen: list[str] = []
    for cid in calendar_ids:
        c = (cid or "").strip()
        if c and c not in seen:
            seen.append(c)
    row = get_or_create(session, user_id)
    row.enabled_calendar_ids = json.dumps(seen)
    row.updated_at = _now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def ensure_notes_target(
    session: Session, creds: "Credentials", user_id: int
) -> tuple[str, str]:
    """Return (doc_id, folder_id), app-creating the folder + Doc on first need.

    Idempotent: once the ids are stored they are reused. A Drive failure raises
    `ApiError` so the caller (router) leaves the entry re-routable — nothing is
    half-persisted that would block a retry (folder id is saved before the Doc is
    attempted, so a retry reuses the folder)."""
    row = get_or_create(session, user_id)

    try:
        if not row.notes_folder_id:
            row.notes_folder_id = await docs_client.create_folder(
                creds, _NOTES_FOLDER_NAME
            )
            row.updated_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
        if not row.notes_doc_id:
            row.notes_doc_id = await docs_client.create_doc_in_folder(
                creds, _NOTES_DOC_NAME, row.notes_folder_id
            )
            row.updated_at = _now()
            session.add(row)
            session.commit()
            session.refresh(row)
    except ApiError:
        raise
    except Exception as exc:  # noqa: BLE001 — Drive create failed
        raise ApiError(
            502, "notes_bootstrap_failed", "Could not create your notes folder/Doc."
        ) from exc

    return row.notes_doc_id, row.notes_folder_id
