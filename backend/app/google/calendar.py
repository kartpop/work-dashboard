"""Read-only access to the account's Google Calendar events.

This is the only module that talks to the Google Calendar API directly (see
CLAUDE.md hard constraint: read paths call the Google API client directly,
never via MCP/LLM). Fetch + reshape only — no sorting/merging with overlay data
beyond the multi-calendar merge/dedupe the strip needs.
"""

from __future__ import annotations

import asyncio
import logging
import zoneinfo
from datetime import date as date_cls
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from googleapiclient.discovery import build

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def today_ist() -> date_cls:
    """The current calendar date in IST (the strip's default day)."""
    return datetime.now(_IST).date()


def _ist_day_bounds(day: date_cls) -> tuple[str, str]:
    """RFC3339 `timeMin`/`timeMax` spanning `day` in IST (start inclusive, next
    midnight exclusive). Pure — the unit tests pin this for an arbitrary date."""
    start = datetime.combine(day, time.min, tzinfo=_IST)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _extract_meet_link(event: dict) -> str | None:
    """`hangoutLink`, falling back to the `video` conferenceData entry point; else
    None. Pure — unit-tested for all three shapes."""
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    for entry in event.get("conferenceData", {}).get("entryPoints", []):
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def _my_response(event: dict) -> str | None:
    """The owner's own RSVP (`responseStatus` of the `self: true` attendee).
    None when the event has no attendee entry for the owner (solo/own events) —
    the strip treats that as accepted."""
    for a in event.get("attendees", []):
        if a.get("self"):
            return a.get("responseStatus")
    return None


def _reshape_event(event: dict) -> dict:
    """Map a raw Google Calendar event to our small, stable strip shape."""
    start = event.get("start", {})
    end = event.get("end", {})
    all_day = "date" in start
    organizer = event.get("organizer") or {}
    return {
        "id": event["id"],
        "title": event.get("summary"),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": all_day,
        "meet_link": _extract_meet_link(event),
        "location": event.get("location"),
        "organizer": organizer.get("displayName") or organizer.get("email"),
        "my_response": _my_response(event),
        "attendees": [
            {
                "name": a.get("displayName"),
                "email": a.get("email"),
                "response_status": a.get("responseStatus"),
            }
            for a in event.get("attendees", [])
        ],
    }


def _event_sort_key(event: dict) -> str:
    """Sort raw events by start. `dateTime` (timed) or `date` (all-day → treated as
    that day's start). RFC3339 strings sort chronologically as-is for one day."""
    start = event.get("start", {})
    return start.get("dateTime") or f"{start.get('date', '')}T00:00:00"


def _merge_events(raw_lists: list[list[dict]]) -> list[dict]:
    """Merge per-calendar raw event lists, dedupe by `iCalUID` (first wins — pass
    primary first so an invited-attendee duplicate keeps the primary copy), and
    sort by start. Pure — unit-tested."""
    seen: set[str] = set()
    merged: list[dict] = []
    for raw in raw_lists:
        for event in raw:
            uid = event.get("iCalUID")
            if uid is not None:
                if uid in seen:
                    continue
                seen.add(uid)
            merged.append(event)
    merged.sort(key=_event_sort_key)
    return merged


def _fetch_calendar_day(
    service, calendar_id: str, time_min: str, time_max: str
) -> list[dict]:
    return (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
        .get("items", [])
    )


def _fetch_day_events(
    creds: "Credentials", day: date_cls, extra_calendar_ids: list[str]
) -> list[dict]:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    time_min, time_max = _ist_day_bounds(day)

    # Primary first (so its copy wins dedupe); a primary failure is a real error.
    raw_lists = [_fetch_calendar_day(service, "primary", time_min, time_max)]

    # Shared / toggled-on calendars are their own entities — not visible under
    # `primary`. Each extra is best-effort: a revoked share / bad id logs a warning;
    # the strip still renders from the rest. Ids come from the user's settings
    # (goal 8 — replaces the EXTRA_CALENDAR_IDS env var).
    for calendar_id in extra_calendar_ids:
        try:
            raw_lists.append(
                _fetch_calendar_day(service, calendar_id, time_min, time_max)
            )
        except Exception as exc:  # noqa: BLE001 — best-effort per calendar
            logger.warning("Extra calendar %s fetch failed: %s", calendar_id, exc)

    return [_reshape_event(event) for event in _merge_events(raw_lists)]


async def get_day_events(
    creds: "Credentials",
    extra_calendar_ids: list[str] | None = None,
    day: date_cls | None = None,
) -> list[dict]:
    """Return one IST day's events (default today) merged across `primary` + the
    user's toggled-on `extra_calendar_ids`, deduped by `iCalUID`, sorted by start."""
    return await asyncio.to_thread(
        _fetch_day_events, creds, day or today_ist(), extra_calendar_ids or []
    )


# ── Calendar list (settings toggle source, goal 8) ────────────────────────────


def _reshape_calendar(entry: dict) -> dict:
    """Map a raw calendarList entry to the small shape the settings toggle needs."""
    return {
        "id": entry["id"],
        "summary": entry.get("summaryOverride") or entry.get("summary") or entry["id"],
        "primary": bool(entry.get("primary")),
        "background_color": entry.get("backgroundColor"),
    }


def _fetch_calendar_list(creds: "Credentials") -> list[dict]:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    entries: list[dict] = []
    page_token = None
    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        entries.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return [_reshape_calendar(e) for e in entries]


async def get_calendar_list(creds: "Credentials") -> list[dict]:
    """List the calendars this account can see (`calendarList.list`) — the source
    for the settings toggle (within `calendar.readonly`, no scope change)."""
    return await asyncio.to_thread(_fetch_calendar_list, creds)
