"""Tests for overlay merge/bucket logic that needs no Google access.

Covers the goal-4a Overdue rollup: past-due tasks collapse into a single
synthetic "Overdue" bucket at the top instead of scattering across past dates.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.overlay import service as overlay_svc

# A safely-past date and a safely-future date relative to any real run date.
PAST_1 = "2020-01-01T00:00:00.000Z"
PAST_2 = "2020-02-01T00:00:00.000Z"
FUTURE = "2099-12-31T00:00:00.000Z"


@pytest.fixture
def session():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    SQLModel.metadata.drop_all(eng)


def _task(task_id, due):
    return {
        "id": task_id,
        "title": task_id,
        "status": "needsAction",
        "due": due,
        "notes": None,
    }


def test_overdue_rollup_at_top(session):
    raw = [
        {
            "id": "L1",
            "title": "My Tasks",
            "tasks": [
                _task("past-a", PAST_1),
                _task("past-b", PAST_2),
                _task("future", FUTURE),
                _task("nodate", None),
            ],
        }
    ]
    merged = overlay_svc.get_merged_task_lists(session, raw, view="grouped")
    buckets = merged[0]["buckets"]

    # First bucket is the rollup, holding both past tasks (oldest first).
    assert buckets[0]["key"] == "OVERDUE"
    assert buckets[0]["label"] == "Overdue"
    overdue_ids = [it["id"] for it in buckets[0]["items"]]
    assert overdue_ids == ["past-a", "past-b"]

    # No separate past-date buckets remain; future + NO_DATE still present.
    keys = [b["key"] for b in buckets]
    assert "2020-01-01" not in keys and "2020-02-01" not in keys
    assert "NO_DATE" in keys


def test_no_overdue_bucket_when_nothing_past(session):
    raw = [
        {
            "id": "L1",
            "title": "My Tasks",
            "tasks": [_task("future", FUTURE), _task("nodate", None)],
        }
    ]
    merged = overlay_svc.get_merged_task_lists(session, raw, view="grouped")
    keys = [b["key"] for b in merged[0]["buckets"]]
    assert "OVERDUE" not in keys
