import logging
from datetime import date as date_cls

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from sqlmodel import Session

from app.auth.deps import get_current_credentials, get_current_user
from app.auth.models import User
from app.db import get_session
from app.errors import ApiError
from app.google import calendar as calendar_client
from app.settings import service as settings_svc

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/calendar/day")
async def day_events(
    date: str | None = None,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_current_credentials),
    session: Session = Depends(get_session),
):
    """Today's (IST) events for the header strip, or `?date=YYYY-MM-DD` for the
    day-navigation pills. Merges primary + the user's toggled-on extra calendars."""
    day = None
    if date is not None:
        try:
            day = date_cls.fromisoformat(date)
        except ValueError as exc:
            raise ApiError(400, "invalid_date", "date must be YYYY-MM-DD.") from exc

    extra_ids = settings_svc.get_enabled_calendar_ids(session, user.id)
    try:
        events = await calendar_client.get_day_events(creds, extra_ids, day)
    except Exception as exc:
        logger.exception("Google Calendar fetch failed: %s", exc)
        raise ApiError(
            502,
            "google_calendar_unavailable",
            "Could not fetch calendar events.",
        ) from exc

    return {"date": (day or calendar_client.today_ist()).isoformat(), "events": events}
