"""Tests for overlay merge/bucket logic that needs no Google access.

Covers the goal-4a Overdue rollup: past-due tasks collapse into a single
synthetic "Overdue" bucket at the top instead of scattering across past dates.

Goal 8: merge/upsert are per-user — `get_merged_task_lists` and `upsert_overlay`
take a `user_id` and only ever see that user's rows.
"""

from __future__ import annotations

from app.overlay import service as overlay_svc
from app.overlay.models import TaskOverlay

# A safely-past date and a safely-future date relative to any real run date.
PAST_1 = "2020-01-01T00:00:00.000Z"
PAST_2 = "2020-02-01T00:00:00.000Z"
FUTURE = "2099-12-31T00:00:00.000Z"


def _task(task_id, due):
    return {
        "id": task_id,
        "title": task_id,
        "status": "needsAction",
        "due": due,
        "notes": None,
    }


def test_overdue_rollup_at_top(session, user_a):
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
    merged = overlay_svc.get_merged_task_lists(session, user_a.id, raw, view="grouped")
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


def test_no_overdue_bucket_when_nothing_past(session, user_a):
    raw = [
        {
            "id": "L1",
            "title": "My Tasks",
            "tasks": [_task("future", FUTURE), _task("nodate", None)],
        }
    ]
    merged = overlay_svc.get_merged_task_lists(session, user_a.id, raw, view="grouped")
    keys = [b["key"] for b in merged[0]["buckets"]]
    assert "OVERDUE" not in keys


# ── Per-user isolation (goal 8) ─────────────────────────────────────────────────


def test_upsert_overlay_is_user_scoped(session, user_a, user_b):
    """Same (tasklist, task) key for two users → two independent rows; a write by
    one user never mutates the other's."""
    overlay_svc.upsert_overlay(session, user_a.id, "L1", "T1", rank=1.0)
    overlay_svc.upsert_overlay(session, user_b.id, "L1", "T1", rank=99.0)

    row_a = session.get(TaskOverlay, (user_a.id, "L1", "T1"))
    row_b = session.get(TaskOverlay, (user_b.id, "L1", "T1"))
    assert row_a.rank == 1.0
    assert row_b.rank == 99.0

    # A follow-up write for A leaves B untouched.
    overlay_svc.upsert_overlay(session, user_a.id, "L1", "T1", rank=2.0)
    session.expire_all()
    assert session.get(TaskOverlay, (user_a.id, "L1", "T1")).rank == 2.0
    assert session.get(TaskOverlay, (user_b.id, "L1", "T1")).rank == 99.0


def test_get_merged_task_lists_filters_by_user(session, user_a, user_b):
    """B's merge sees only B's overlay ranks — A's rank on the same task is invisible."""
    overlay_svc.upsert_overlay(session, user_a.id, "L1", "T1", rank=5.0)

    raw = [{"id": "L1", "title": "My Tasks", "tasks": [_task("T1", None)]}]
    merged_b = overlay_svc.get_merged_task_lists(session, user_b.id, raw, view="flat")
    # B has no overlay row for T1 → its rank is None (A's 5.0 does not leak in).
    assert merged_b[0]["tasks"][0]["rank"] is None

    merged_a = overlay_svc.get_merged_task_lists(session, user_a.id, raw, view="flat")
    assert merged_a[0]["tasks"][0]["rank"] == 5.0
