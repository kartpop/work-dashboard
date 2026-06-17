"""Write orchestration: reschedule (due-date) and move (cross-list).

Owns sequencing of Google API calls and overlay-row updates, input validation,
and the decision of what (if anything) to write. The thin one-call wrappers live
in `app.google.tasks`; merge/group helpers live in `app.overlay.service`. See
`.claude/rules/writes.md` for the safety invariants enforced here.
"""

from __future__ import annotations

from sqlmodel import Session

from app.errors import ApiError
from app.google import tasks as tasks_client
from app.overlay import service as overlay_svc
from app.overlay.models import TaskOverlay

_NO_DATE = "NO_DATE"


async def reschedule(
    session: Session,
    tasklist_id: str,
    task_id: str,
    due_date: str | None,
    rank: float | None,
    group_id: int | None,
) -> dict:
    """Reschedule a task across date-buckets (due-date write + overlay update).

    Idempotent: skips the Google write when the destination bucket already
    matches the task's current bucket. `group_id` must reference a group in the
    destination bucket (422 otherwise); it is always set explicitly on the
    overlay (None ungroups).
    """
    current = await tasks_client.get_task(tasklist_id, task_id)
    if current is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    target_bucket = due_date or _NO_DATE

    if group_id is not None:
        grp = overlay_svc.get_group(session, group_id, tasklist_id)
        if grp is None or grp.bucket_key != target_bucket:
            raise ApiError(
                422,
                "group_wrong_bucket",
                "group_id must reference a group in the destination bucket.",
            )

    current_bucket = overlay_svc._bucket_key(current.get("due"))
    if target_bucket != current_bucket:
        new_due = f"{due_date}T00:00:00.000Z" if due_date is not None else None
        try:
            await tasks_client.update_due_date(tasklist_id, task_id, new_due)
        except Exception as exc:
            raise ApiError(
                502, "google_write_failed", "Could not update the task due date."
            ) from exc
        due_out: str | None = new_due
    else:
        # Idempotent no-op: bucket unchanged, so the stored due date stands.
        due_out = current.get("due")

    row = overlay_svc.upsert_overlay(
        session, tasklist_id, task_id, rank=rank, group_id=group_id
    )

    return {
        "tasklist_id": tasklist_id,
        "task_id": task_id,
        "due": due_out,
        "rank": row.rank,
        "group_id": row.group_id,
    }


async def move(
    session: Session,
    tasklist_id: str,
    task_id: str,
    target_list_id: str,
    rank: float | None,
) -> dict:
    """Move a task to another list via insert-before-delete.

    Inserts a copy into the target list, then (only on confirmed insert success)
    deletes the original and migrates the overlay row. A delete failure after a
    successful insert surfaces the duplicate rather than retrying or losing data.
    """
    if target_list_id == tasklist_id:
        raise ApiError(400, "same_list", "Task is already in that list.")

    src = await tasks_client.get_task(tasklist_id, task_id)
    if src is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    body: dict = {
        "title": src.get("title", ""),
        "status": src.get("status", "needsAction"),
    }
    if src.get("notes") is not None:
        body["notes"] = src["notes"]
    if src.get("due") is not None:
        body["due"] = src["due"]

    # Insert first — nothing is deleted yet, so a failure leaves no partial state.
    try:
        new = await tasks_client.insert_task(target_list_id, body)
    except Exception as exc:
        raise ApiError(
            502, "google_insert_failed", "Could not copy the task to the target list."
        ) from exc

    new_id = new["id"]

    # Delete the original only after the insert succeeded. If THIS fails, the task
    # now exists in both lists — surface the duplicate rather than retry-delete.
    try:
        await tasks_client.delete_task(tasklist_id, task_id)
    except Exception as exc:
        raise ApiError(
            502,
            "move_delete_failed",
            "Copied to the target list but could not remove the original — "
            "you now have a duplicate; delete one manually.",
        ) from exc

    # Migrate the overlay row to the new key, then drop the old one.
    row = overlay_svc.upsert_overlay(
        session, target_list_id, new_id, rank=rank, group_id=None
    )
    old = session.get(TaskOverlay, (tasklist_id, task_id))
    if old is not None:
        session.delete(old)
        session.commit()

    return {
        "target_list_id": target_list_id,
        "new_task_id": new_id,
        "rank": row.rank,
        "group_id": None,
    }
