from fastapi import APIRouter

from app.errors import ApiError
from app.google import calendar as calendar_client

router = APIRouter()


@router.get("/calendar/upcoming")
async def upcoming_events(limit: int = 10):
    try:
        events = await calendar_client.get_upcoming_events(max_results=limit)
    except Exception as exc:
        raise ApiError(
            502, "google_calendar_unavailable", "Could not fetch upcoming calendar events."
        ) from exc
    return {"events": events}
