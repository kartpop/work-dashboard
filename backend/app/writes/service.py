"""Write orchestration: reschedule (due-date) and move (cross-list).

Owns sequencing of Google API calls and overlay-row updates, input validation,
and the decision of what (if anything) to write. The thin one-call wrappers live
in `app.google.tasks`; merge/group helpers live in `app.overlay.service`. See
`.claude/rules/writes.md` for the safety invariants enforced here.
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlmodel import Session

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

from app.errors import ApiError
from app.google import docs as docs_client
from app.google import tasks as tasks_client
from app.overlay import service as overlay_svc
from app.overlay.models import TaskOverlay

_NO_DATE = "NO_DATE"
_UNSET: Any = object()

_log = logging.getLogger("writes.service")
_IST = zoneinfo.ZoneInfo("Asia/Kolkata")

# Docs whose folder-ancestry has been verified once — the gate is idempotent and a
# doc can't leave its folder mid-process, so we cache the confirmation per doc id.
_ancestry_ok: set[str] = set()


async def reschedule(
    session: Session,
    creds: "Credentials",
    user_id: int,
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
    current = await tasks_client.get_task(creds, tasklist_id, task_id)
    if current is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    target_bucket = due_date or _NO_DATE

    if group_id is not None:
        grp = overlay_svc.get_group(session, user_id, group_id, tasklist_id)
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
            await tasks_client.update_due_date(creds, tasklist_id, task_id, new_due)
        except Exception as exc:
            raise ApiError(
                502, "google_write_failed", "Could not update the task due date."
            ) from exc
        due_out: str | None = new_due
    else:
        # Idempotent no-op: bucket unchanged, so the stored due date stands.
        due_out = current.get("due")

    row = overlay_svc.upsert_overlay(
        session, user_id, tasklist_id, task_id, rank=rank, group_id=group_id
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
    creds: "Credentials",
    user_id: int,
    tasklist_id: str,
    task_id: str,
    target_list_id: str,
    rank: float | None,
    due_date: Any = _UNSET,
    group_id: int | None = None,
) -> dict:
    """Move a task to another list via insert-before-delete.

    Inserts a copy into the target list, then (only on confirmed insert success)
    deletes the original and migrates the overlay row. A delete failure after a
    successful insert surfaces the duplicate rather than retrying or losing data.

    Goal 6 (cross-list drag): the drop may also change the date bucket and land in
    a destination group, so `move` optionally reschedules on the **insert leg** —
    one orchestrated write, not two chained calls.
      - `due_date is _UNSET` → preserve the source task's due (menu/same-bucket drop);
        an explicit value (a "YYYY-MM-DD" str, or None to clear → NO_DATE) overrides it.
      - `group_id` must reference a group in the destination `(target_list, bucket)`
        (422 otherwise); it is set on the migrated overlay row (None = ungrouped).
    """
    if target_list_id == tasklist_id:
        raise ApiError(400, "same_list", "Task is already in that list.")

    src = await tasks_client.get_task(creds, tasklist_id, task_id)
    if src is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    # The destination bucket governs both group-scope validation and the insert's
    # due. Preserve the source bucket when due_date is _UNSET; otherwise the
    # explicit value (or NO_DATE for None) is the target.
    if due_date is _UNSET:
        target_bucket = overlay_svc._bucket_key(src.get("due"))
    else:
        target_bucket = due_date or _NO_DATE

    if group_id is not None:
        grp = overlay_svc.get_group(session, user_id, group_id, target_list_id)
        if grp is None or grp.bucket_key != target_bucket:
            raise ApiError(
                422,
                "group_wrong_bucket",
                "group_id must reference a group in the destination bucket.",
            )

    body: dict = {
        "title": src.get("title", ""),
        "status": src.get("status", "needsAction"),
    }
    if src.get("notes") is not None:
        body["notes"] = src["notes"]
    if due_date is _UNSET:
        if src.get("due") is not None:
            body["due"] = src["due"]
    elif due_date is not None:
        body["due"] = f"{due_date}T00:00:00.000Z"
    # else (explicit None): omit `due` → the copy lands in NO_DATE.

    # Insert first — nothing is deleted yet, so a failure leaves no partial state.
    try:
        new = await tasks_client.insert_task(creds, target_list_id, body)
    except Exception as exc:
        raise ApiError(
            502, "google_insert_failed", "Could not copy the task to the target list."
        ) from exc

    new_id = new["id"]

    # Delete the original only after the insert succeeded. If THIS fails, the task
    # now exists in both lists — surface the duplicate rather than retry-delete.
    try:
        await tasks_client.delete_task(creds, tasklist_id, task_id)
    except Exception as exc:
        raise ApiError(
            502,
            "move_delete_failed",
            "Copied to the target list but could not remove the original — "
            "you now have a duplicate; delete one manually.",
        ) from exc

    # Migrate the overlay row to the new key, then drop the old one.
    row = overlay_svc.upsert_overlay(
        session, user_id, target_list_id, new_id, rank=rank, group_id=group_id
    )
    old = session.get(TaskOverlay, (user_id, tasklist_id, task_id))
    if old is not None:
        session.delete(old)
        session.commit()

    return {
        "target_list_id": target_list_id,
        "new_task_id": new_id,
        "rank": row.rank,
        "group_id": row.group_id,
    }


# ── Content CRUD (goal 4a) ─────────────────────────────────────────────────────


async def create_task(
    session: Session,
    creds: "Credentials",
    user_id: int,
    tasklist_id: str,
    title: str,
    rank: float | None,
    notes: str | None = None,
    due_date: str | None = None,
) -> dict:
    """Create a task and seed its overlay row.

    Returns the merged task shape so the client can insert-from-response (no
    refetch). Optional notes and due_date ("YYYY-MM-DD") are set on insert.
    """
    if not title.strip():
        raise ApiError(400, "empty_title", "Task title must not be empty.")

    body: dict = {"title": title, "status": "needsAction"}
    if notes:
        body["notes"] = notes
    if due_date:
        body["due"] = f"{due_date}T00:00:00.000Z"

    try:
        new = await tasks_client.insert_task(creds, tasklist_id, body)
    except Exception as exc:
        raise ApiError(
            502, "google_insert_failed", "Could not create the task."
        ) from exc

    row = overlay_svc.upsert_overlay(
        session, user_id, tasklist_id, new["id"], rank=rank, group_id=None
    )
    return {**new, "type": "task", "rank": row.rank, "group_id": row.group_id}


async def update_content(
    session: Session,
    creds: "Credentials",
    user_id: int,
    tasklist_id: str,
    task_id: str,
    title: Any = _UNSET,
    notes: Any = _UNSET,
    status: Any = _UNSET,
) -> dict:
    """Patch a task's Google content fields (title / notes / status).

    Only fields explicitly provided are written. Completion/uncompletion rides
    the `status` field (completion writes immediately — see writes.md). The
    overlay row is untouched (rank/group are not Google content).
    """
    if title is not _UNSET and not str(title).strip():
        raise ApiError(400, "empty_title", "Task title must not be empty.")

    current = await tasks_client.get_task(creds, tasklist_id, task_id)
    if current is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    # Forward only the fields the caller actually set, so the thin wrapper's own
    # _UNSET default governs what reaches the Google patch body (the sentinels in
    # this module and the client module are intentionally separate objects).
    fields: dict[str, Any] = {}
    if title is not _UNSET:
        fields["title"] = title
    if notes is not _UNSET:
        fields["notes"] = notes
    if status is not _UNSET:
        fields["status"] = status

    try:
        updated = await tasks_client.update_task_content(
            creds, tasklist_id, task_id, **fields
        )
    except Exception as exc:
        raise ApiError(
            502, "google_write_failed", "Could not update the task."
        ) from exc

    overlay = session.get(TaskOverlay, (user_id, tasklist_id, task_id))
    return {
        **updated,
        "type": "task",
        "rank": overlay.rank if overlay else None,
        "group_id": overlay.group_id if overlay else None,
    }


async def delete(
    session: Session,
    creds: "Credentials",
    user_id: int,
    tasklist_id: str,
    task_id: str,
) -> dict:
    """Delete a task from Google and drop its overlay row.

    Immediate on the backend — the ~5s deferral + undo is entirely a frontend
    concern (an undo means this endpoint is never called → zero Google writes).
    This is the second sanctioned `delete_task` caller (the first is `move`).
    """
    current = await tasks_client.get_task(creds, tasklist_id, task_id)
    if current is None:
        raise ApiError(404, "task_not_found", "Task not found.")

    try:
        await tasks_client.delete_task(creds, tasklist_id, task_id)
    except Exception as exc:
        raise ApiError(
            502, "google_delete_failed", "Could not delete the task."
        ) from exc

    row = session.get(TaskOverlay, (user_id, tasklist_id, task_id))
    if row is not None:
        session.delete(row)
        session.commit()
    return {"tasklist_id": tasklist_id, "task_id": task_id, "deleted": True}


async def rename_list(creds: "Credentials", tasklist_id: str, title: str) -> dict:
    """Rename a task list (write to the tasklists resource, not a task)."""
    if not title.strip():
        raise ApiError(400, "empty_title", "List title must not be empty.")
    try:
        return await tasks_client.update_tasklist(creds, tasklist_id, title)
    except Exception as exc:
        raise ApiError(
            502, "google_write_failed", "Could not rename the list."
        ) from exc


# ── Notes writer (goal 7) ──────────────────────────────────────────────────────
#
# The second live Google surface: the auto-router appends a captured note VERBATIM
# to the top of one configured Doc. Insert-only — no delete, no overwrite, no status
# write. `append_note` is a **router-only** caller (writes.md); doc/folder ids come
# from config, never from LLM output. See docs/goals/architecture/drive-access-scoping.md.


def format_note_heading(dt: datetime) -> str:
    """The locked timestamp format, e.g. `6-July-2026, 8:41 PM IST`.

    Built from date/time components (not `%-d`/`%-I`) so it is identical on macOS
    and Linux. `dt` is expected in IST; its wall-clock components are used as-is.
    """
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.day}-{dt.strftime('%B')}-{dt.year}, {hour}:{dt.minute:02d} {ampm} IST"


async def _assert_in_notes_folder(
    creds: "Credentials", doc_id: str, folder_id: str | None
) -> None:
    """Folder-ancestry gate: verify `doc_id`'s parent chain reaches `folder_id`.

    Fail-closed — a missing folder id, an unreachable doc, or an error anywhere in
    the walk means we do NOT write (the caller leaves the entry re-routable). Cached
    per doc id after the first success (a doc can't leave its folder mid-process).
    """
    if not folder_id:
        raise ApiError(
            500, "notes_folder_unset", "The user's notes folder is not configured."
        )
    if doc_id in _ancestry_ok:
        return
    try:
        reached = await _walk_to_folder(creds, doc_id, folder_id)
    except Exception as exc:
        raise ApiError(
            502,
            "notes_ancestry_check_failed",
            "Could not verify the notes Doc's folder.",
        ) from exc
    if not reached:
        raise ApiError(
            422,
            "notes_doc_outside_folder",
            "The configured notes Doc is not inside the user's notes folder.",
        )
    _ancestry_ok.add(doc_id)


async def _walk_to_folder(
    creds: "Credentials", file_id: str, folder_id: str, max_depth: int = 10
) -> bool:
    """Walk up `file_id`'s parents (bounded) looking for `folder_id`.

    The common case — a bootstrap-created doc sitting directly in the folder —
    resolves on the first hop. Deeper nesting relies on the intermediate folders
    being app-visible; if a hand-made ancestor is unreadable the walk raises and
    the gate fails closed (correct: we couldn't prove containment)."""
    seen: set[str] = set()
    frontier = [file_id]
    for _ in range(max_depth):
        parents: list[str] = []
        for fid in frontier:
            if fid in seen:
                continue
            seen.add(fid)
            parents.extend(await docs_client.get_parents(creds, fid))
        if folder_id in parents:
            return True
        if not parents:
            return False
        frontier = parents
    return False


async def append_note(
    creds: "Credentials",
    doc_id: str,
    folder_id: str | None,
    body_text: str,
    summary: str | None = None,
) -> dict:
    """Append a verbatim note to the top of the configured Doc under an H3 timestamp.

    Router-only write. Insert-only — never deletes or overwrites the Doc. The
    ancestry gate runs first (fail-closed); a Docs error is surfaced as an ApiError
    so the entry stays re-routable (route-once marks routed only on success).

    `summary` (goal 7c) is the one LLM-authored line — a bold one-liner inserted
    between the timestamp and the verbatim `body_text`. The raw text stays verbatim;
    an empty/missing summary degrades to the goal-7 shape.
    """
    await _assert_in_notes_folder(creds, doc_id, folder_id)
    heading = format_note_heading(datetime.now(_IST))
    try:
        await docs_client.insert_note(creds, doc_id, heading, body_text, summary)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            502, "google_docs_write_failed", "Could not append the note to the Doc."
        ) from exc
    _log.info("appended note to Doc %s under heading %r", doc_id, heading)
    return {"doc_id": doc_id, "heading": heading}
