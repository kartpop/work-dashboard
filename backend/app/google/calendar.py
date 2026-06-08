"""Read-only access to the account's upcoming Google Calendar events.

This is the only module that talks to the Google Calendar API directly (see
CLAUDE.md hard constraint: read paths call the Google API client directly,
never via MCP/LLM).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from googleapiclient.discovery import build

from app.google.auth import load_credentials


def _fetch_upcoming_events(max_results: int) -> list[dict]:
    service = build("calendar", "v3", credentials=load_credentials(), cache_discovery=False)

    response = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=datetime.now(timezone.utc).isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for event in response.get("items", []):
        start = event.get("start", {})
        events.append(
            {
                "id": event["id"],
                "title": event.get("summary"),
                "start": start.get("dateTime") or start.get("date"),
            }
        )
    return events


async def get_upcoming_events(max_results: int = 10) -> list[dict]:
    """Return the next `max_results` upcoming events on the primary calendar."""
    return await asyncio.to_thread(_fetch_upcoming_events, max_results)
