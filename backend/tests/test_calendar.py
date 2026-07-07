"""Unit tests for the goal-7b calendar day-window read path.

The pure helpers (IST day bounds, meet-link extraction, reshape, multi-calendar
merge/dedupe, env parsing) are tested directly — no Google API contact.
"""

from __future__ import annotations

from datetime import date

from app.google import calendar as cal


def test_ist_day_bounds_arbitrary_date():
    time_min, time_max = cal._ist_day_bounds(date(2026, 3, 15))
    # IST is +05:30; the window is that day's midnight to the next, inclusive/exclusive.
    assert time_min == "2026-03-15T00:00:00+05:30"
    assert time_max == "2026-03-16T00:00:00+05:30"


def test_extract_meet_link_hangout():
    assert cal._extract_meet_link({"hangoutLink": "https://meet.google.com/abc"}) == (
        "https://meet.google.com/abc"
    )


def test_extract_meet_link_conference_data_fallback():
    event = {
        "conferenceData": {
            "entryPoints": [
                {"entryPointType": "phone", "uri": "tel:+1"},
                {"entryPointType": "video", "uri": "https://meet.google.com/xyz"},
            ]
        }
    }
    assert cal._extract_meet_link(event) == "https://meet.google.com/xyz"


def test_extract_meet_link_none():
    assert cal._extract_meet_link({"summary": "no video"}) is None


def test_reshape_timed_event_with_attendees():
    raw = {
        "id": "e1",
        "summary": "1:1",
        "start": {"dateTime": "2026-07-07T15:00:00+05:30"},
        "end": {"dateTime": "2026-07-07T15:30:00+05:30"},
        "location": "Room 4",
        "hangoutLink": "https://meet.google.com/abc",
        "attendees": [
            {"displayName": "Ada", "email": "ada@x.com", "responseStatus": "accepted"},
            {"email": "b@x.com", "responseStatus": "needsAction"},
        ],
    }
    shaped = cal._reshape_event(raw)
    assert shaped == {
        "id": "e1",
        "title": "1:1",
        "start": "2026-07-07T15:00:00+05:30",
        "end": "2026-07-07T15:30:00+05:30",
        "all_day": False,
        "meet_link": "https://meet.google.com/abc",
        "location": "Room 4",
        "attendees": [
            {"name": "Ada", "email": "ada@x.com", "response_status": "accepted"},
            {"name": None, "email": "b@x.com", "response_status": "needsAction"},
        ],
    }


def test_reshape_all_day_event():
    raw = {
        "id": "e2",
        "summary": "Holiday",
        "start": {"date": "2026-07-07"},
        "end": {"date": "2026-07-08"},
    }
    shaped = cal._reshape_event(raw)
    assert shaped["all_day"] is True
    assert shaped["start"] == "2026-07-07"
    assert shaped["meet_link"] is None
    assert shaped["attendees"] == []


def test_merge_sorts_by_start_and_dedupes_ical_uid():
    primary = [
        {
            "id": "p1",
            "iCalUID": "shared@g",
            "start": {"dateTime": "2026-07-07T10:00:00+05:30"},
        },
        {
            "id": "p2",
            "iCalUID": "only-primary@g",
            "start": {"dateTime": "2026-07-07T09:00:00+05:30"},
        },
    ]
    work = [
        # Same iCalUID as p1 (invited-attendee duplicate) — the primary copy wins.
        {
            "id": "w1",
            "iCalUID": "shared@g",
            "start": {"dateTime": "2026-07-07T10:00:00+05:30"},
        },
        {
            "id": "w2",
            "iCalUID": "work-only@g",
            "start": {"dateTime": "2026-07-07T08:00:00+05:30"},
        },
    ]
    merged = cal._merge_events([primary, work])
    ids = [e["id"] for e in merged]
    # Sorted by start; the duplicated event appears once as the primary copy (p1).
    assert ids == ["w2", "p2", "p1"]
    assert "w1" not in ids


def test_merge_all_day_sorts_before_timed_same_day():
    raw = [
        [{"id": "timed", "start": {"dateTime": "2026-07-07T09:00:00+05:30"}}],
        [{"id": "allday", "start": {"date": "2026-07-07"}}],
    ]
    merged = cal._merge_events(raw)
    assert [e["id"] for e in merged] == ["allday", "timed"]


def test_extra_calendar_ids_unset(monkeypatch):
    monkeypatch.delenv("EXTRA_CALENDAR_IDS", raising=False)
    assert cal._extra_calendar_ids() == []


def test_extra_calendar_ids_parsed(monkeypatch):
    monkeypatch.setenv("EXTRA_CALENDAR_IDS", " work@x.com , , team@x.com ")
    assert cal._extra_calendar_ids() == ["work@x.com", "team@x.com"]


def test_fetch_day_events_extra_best_effort(monkeypatch):
    """A failing extra calendar degrades to a logged warning; primary still returns."""
    monkeypatch.setattr(cal, "build", lambda *a, **k: object())
    monkeypatch.setattr(cal, "load_credentials", lambda: None)
    monkeypatch.setenv("EXTRA_CALENDAR_IDS", "good@x.com,bad@x.com")

    def fake_fetch(service, calendar_id, time_min, time_max):
        if calendar_id == "bad@x.com":
            raise RuntimeError("share revoked")
        return [{"id": calendar_id, "start": {"dateTime": "2026-07-07T09:00:00+05:30"}}]

    monkeypatch.setattr(cal, "_fetch_calendar_day", fake_fetch)
    events = cal._fetch_day_events(date(2026, 7, 7))
    ids = {e["id"] for e in events}
    assert "primary" in ids and "good@x.com" in ids and "bad@x.com" not in ids


def test_fetch_day_events_primary_only_when_unset(monkeypatch):
    monkeypatch.setattr(cal, "build", lambda *a, **k: object())
    monkeypatch.setattr(cal, "load_credentials", lambda: None)
    monkeypatch.delenv("EXTRA_CALENDAR_IDS", raising=False)
    monkeypatch.setattr(
        cal,
        "_fetch_calendar_day",
        lambda service, cid, tmin, tmax: [
            {"id": cid, "start": {"dateTime": "2026-07-07T09:00:00+05:30"}}
        ],
    )
    events = cal._fetch_day_events(date(2026, 7, 7))
    assert [e["id"] for e in events] == ["primary"]


def test_day_endpoint_invalid_date_returns_400():
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/calendar/day?date=not-a-date")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_date"
