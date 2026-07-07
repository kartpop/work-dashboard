import logging
from datetime import date as date_cls

from fastapi import APIRouter

from app.errors import ApiError
from app.google import calendar as calendar_client

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/calendar/day")
async def day_events(date: str | None = None):
    """Today's (IST) events for the header strip, or `?date=YYYY-MM-DD` for the
    day-navigation pills. Merges primary + EXTRA_CALENDAR_IDS."""
    day = None
    if date is not None:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError as exc:
            raise ApiError(400, "invalid_date", "date must be YYYY-MM-DD.") from exc

    try:
        events = await calendar_client.get_day_events(day)
    except Exception as exc:
        logger.exception("Google Calendar fetch failed: %s", exc)
        raise ApiError(
            502,
            "google_calendar_unavailable",
            "Could not fetch calendar events.",
        ) from exc

    return {"date": (day or calendar_client.today_ist()).isoformat(), "events": events}
