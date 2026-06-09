"""Overlay service: merges Google Tasks data with local overlay rows.

This is the ONLY place where merge, sort, and group logic lives.
app/google/tasks.py does fetch+reshape only; routers stay thin.
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from sqlmodel import Session, select

from app.overlay.models import TaskOverlay

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _today_ist() -> date:
    return datetime.now(_IST).date()


def _date_label(due_str: str | None) -> str:
    """Return the bucket label for a task's due date, in IST."""
    if not due_str:
        return "No date"
    # Google Tasks `due` is always midnight UTC representing a calendar date.
    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
    due_date = due_dt.astimezone(_IST).date()
    today = _today_ist()
    if due_date == today:
        return "Today"
    if due_date == today + timedelta(days=1):
        return "Tomorrow"
    return due_date.strftime("%a, %b %-d")


def _date_sort_key(due_str: str | None) -> tuple:
    """Sort key for date buckets: (is_no_date, date)."""
    if not due_str:
        return (1, date.max)
    due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
    return (0, due_dt.astimezone(_IST).date())


def _merge_task(task: dict, overlay: TaskOverlay | None) -> dict:
    return {
        **task,
        "rank": overlay.rank if overlay else None,
        "priority": overlay.priority if overlay else None,
    }


def get_merged_task_lists(
    session: Session,
    raw_lists: list[dict],
    view: Literal["grouped", "flat"] = "grouped",
    show_completed: bool = False,
) -> list[dict]:
    """Left-join overlay rows onto raw Google Tasks, then sort/group."""
    # load all overlay rows for efficiency
    overlays: dict[tuple[str, str], TaskOverlay] = {
        (row.tasklist_id, row.task_id): row
        for row in session.exec(select(TaskOverlay)).all()
    }

    result = []
    for task_list in raw_lists:
        list_id: str = task_list["id"]
        tasks: list[dict] = task_list["tasks"]

        if not show_completed:
            tasks = [t for t in tasks if t.get("status") != "completed"]

        merged = [
            _merge_task(t, overlays.get((list_id, t["id"])))
            for t in tasks
        ]

        base = {k: v for k, v in task_list.items() if k != "tasks"}
        if view == "flat":
            # rank-ordered; unranked fall to end in original Google order
            ranked = [t for t in merged if t["rank"] is not None]
            unranked = [t for t in merged if t["rank"] is None]
            ranked.sort(key=lambda t: t["rank"])
            result.append({**base, "tasks": ranked + unranked})
        else:
            result.append({**base, "groups": _group_by_date(merged)})

    return result


def _group_by_date(tasks: list[dict]) -> list[dict[str, Any]]:
    """Bucket tasks by due date, rank-ordered within each bucket."""
    buckets: dict[str, list[dict]] = {}
    bucket_sort_key: dict[str, tuple] = {}

    for task in tasks:
        label = _date_label(task.get("due"))
        sk = _date_sort_key(task.get("due"))
        if label not in buckets:
            buckets[label] = []
            bucket_sort_key[label] = sk
        buckets[label].append(task)

    # sort tasks within each bucket: ranked first by rank, then unranked in original order
    for label in buckets:
        ranked = [t for t in buckets[label] if t["rank"] is not None]
        unranked = [t for t in buckets[label] if t["rank"] is None]
        ranked.sort(key=lambda t: t["rank"])
        buckets[label] = ranked + unranked

    # sort buckets: overdue/past first, then today/tomorrow/future, no-date last
    sorted_labels = sorted(bucket_sort_key, key=lambda lbl: bucket_sort_key[lbl])
    return [{"label": lbl, "tasks": buckets[lbl]} for lbl in sorted_labels]


def upsert_overlay(
    session: Session,
    tasklist_id: str,
    task_id: str,
    rank: float | None = None,
    priority: int | None = None,
) -> TaskOverlay:
    """Upsert rank and/or priority for a task. Returns the updated row."""
    row = session.get(TaskOverlay, (tasklist_id, task_id))
    now = datetime.now(timezone.utc)
    if row is None:
        row = TaskOverlay(
            tasklist_id=tasklist_id,
            task_id=task_id,
            rank=rank,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        if rank is not None:
            row.rank = rank
        if priority is not None:
            row.priority = priority
        row.updated_at = now
    session.commit()
    session.refresh(row)
    return row
