"""Deterministic route/dispose step — code disposes what the LLM proposes (goal 5).

The classifier returns a `RouterClassification`; THIS module decides what happens
and performs (or withholds) the write. The safety contract lives in router.md:

- **LLM-proposes-code-disposes:** no write lives in the classifier; every write is here.
- **Create-only blast radius:** the only Google task writes reachable from routing are
  `create_task` (content) and `reschedule` (the g4a date path for the new task's due
  date). The router NEVER calls `delete_task`, the complete/uncomplete status write, or
  `update_content` — it is *not* a sanctioned `delete_task` caller (writes.md).
- **Confidence gate / schema gate / allowed-destination gate:** below threshold, or
  `unknown`/`event`, never auto-writes — it goes to the review queue.
- **Route-once:** routing flips `routing_state` off `UNROUTED`, so a re-run no-ops.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.errors import ApiError
from app.google import tasks as tasks_client
from app.router import config
from app.router.classifier import classify
from app.router.models import (
    CONFIRMED,
    DISMISSED,
    IN_REVIEW,
    KEPT_NOTE,
    PENDING,
    RESOLVED,
    ROUTED_TASK,
    UNROUTED,
    ReviewItem,
    ScratchEntry,
)
from app.router.schema import RouterFields
from app.writes import service as writes_svc


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _resolve_list_id(list_hint: str | None) -> str:
    """Map an optional list-hint to a real Google task-list id (deterministic).

    Case-insensitive match on list title; falls back to the first (default) list.
    Raises if Google has no lists or is unreachable (caller leaves entry re-routable).
    """
    raw_lists = await tasks_client.get_task_lists()
    if not raw_lists:
        raise ApiError(502, "no_lists", "No Google task lists are available.")
    if list_hint:
        needle = list_hint.strip().lstrip("#").lower()
        for tl in raw_lists:
            title = (tl.get("title") or "").lower()
            if needle and (needle == title or needle in title):
                return tl["id"]
    return raw_lists[0]["id"]


async def _create_task_from_fields(session: Session, fields: RouterFields) -> dict:
    """Create a Google task from extracted fields, applying list-hint + due date.

    Two sanctioned writes only: `create_task` (always) and `reschedule` (only when a
    due date was extracted — the g4a date path). Nothing destructive is reachable.
    """
    title = (fields.title or "").strip()
    if not title:
        raise ApiError(422, "empty_title", "Router produced no task title.")
    list_id = await _resolve_list_id(fields.list_hint)

    # 1) create (lands undated in NO_DATE) — the router's primary write. Notes are
    #    intentionally dropped: writing them would need `update_content`, which is NOT
    #    a sanctioned router write (create-only). A reviewer can add notes by hand.
    created = await writes_svc.create_task(session, list_id, title, rank=None)

    # 2) set the due date via the g4a reschedule path (metadata write, non-destructive).
    if fields.due_date:
        await writes_svc.reschedule(
            session,
            tasklist_id=list_id,
            task_id=created["id"],
            due_date=fields.due_date,
            rank=created.get("rank"),
            group_id=None,
        )
    return {"list_id": list_id, "task_id": created["id"]}


def _new_review_item(
    entry: ScratchEntry,
    destination: str,
    fields: RouterFields,
    confidence: float,
    reason: str,
) -> ReviewItem:
    return ReviewItem(
        entry_id=entry.id,  # type: ignore[arg-type]
        destination=destination,
        fields_json=fields.model_dump_json(),
        confidence=confidence,
        reason=reason,
        status=PENDING,
    )


async def route_entry(session: Session, entry: ScratchEntry) -> str:
    """Classify + dispose one entry. Returns the resulting routing_state.

    Idempotent: if the entry is already routed it is left untouched. A Google-write
    failure in the deterministic step leaves the entry `UNROUTED` (re-routable) and
    raises an `ApiError` — nothing is half-written, the error is never swallowed.
    """
    if entry.routing_state != UNROUTED:
        return entry.routing_state

    classification = await classify(entry.text)
    entry.route_result = classification.model_dump_json()
    dest = classification.destination
    conf = classification.confidence
    fields = classification.fields
    above = conf >= config.CONFIDENCE_THRESHOLD

    if dest == "task" and above:
        try:
            await _create_task_from_fields(session, fields)
        except ApiError:
            # Re-routable: do not persist a routed state; surface the error.
            session.rollback()
            raise
        entry.routing_state = ROUTED_TASK
    elif dest == "note" and above:
        entry.routing_state = KEPT_NOTE
    else:
        if dest in ("task", "note"):
            reason = f"low confidence ({conf:.2f}) for {dest}"
        elif dest == "event":
            reason = "events need a manual calendar add (read-only v1)"
        else:
            reason = "unclassifiable"
        session.add(_new_review_item(entry, dest, fields, conf, reason))
        entry.routing_state = IN_REVIEW

    entry.routed_at = _now()
    session.add(entry)
    session.commit()
    return entry.routing_state


async def route_unrouted(session: Session) -> dict:
    """Route every `UNROUTED` entry exactly once. Per-entry write failures are
    tallied and skipped (entry left re-routable) so one bad entry can't stall the
    batch. Returns a summary tally."""
    entries = session.exec(
        select(ScratchEntry).where(ScratchEntry.routing_state == UNROUTED)
    ).all()
    tally = {"routed_task": 0, "kept_note": 0, "in_review": 0, "failed": 0}
    for entry in entries:
        try:
            state = await route_entry(session, entry)
            tally[state] = tally.get(state, 0) + 1
        except ApiError:
            tally["failed"] += 1
    return tally


# ── Review-queue dispositions ─────────────────────────────────────────────────


async def confirm_review(
    session: Session,
    item_id: int,
    destination: str | None = None,
    fields: RouterFields | None = None,
) -> dict:
    """Confirm a pending review item (optionally edit-then-confirm).

    A `task` confirmation fires exactly one `create_task` (+ date). `note` keeps it
    locally. `event`/`unknown` are acknowledged with NO write (manual-add affordance).
    """
    item = session.get(ReviewItem, item_id)
    if item is None or item.status != PENDING:
        raise ApiError(404, "review_not_found", "No pending review item with that id.")
    entry = session.get(ScratchEntry, item.entry_id)
    if entry is None:
        raise ApiError(404, "entry_not_found", "Source entry missing.")

    dest = destination or item.destination
    eff_fields = fields or RouterFields(**json.loads(item.fields_json or "{}"))

    if dest == "task":
        try:
            await _create_task_from_fields(session, eff_fields)
        except ApiError:
            session.rollback()
            raise
        entry.routing_state = ROUTED_TASK
    elif dest == "note":
        entry.routing_state = KEPT_NOTE
    else:
        # event / unknown: acknowledged, no write (calendar read-only v1).
        entry.routing_state = RESOLVED

    item.status = CONFIRMED
    item.destination = dest
    item.fields_json = eff_fields.model_dump_json()
    entry.routed_at = _now()
    session.add(item)
    session.add(entry)
    session.commit()
    return {
        "item_id": item.id,
        "status": item.status,
        "entry_state": entry.routing_state,
    }


async def dismiss_review(session: Session, item_id: int) -> dict:
    """Dismiss a pending review item — writes nothing; the entry is resolved."""
    item = session.get(ReviewItem, item_id)
    if item is None or item.status != PENDING:
        raise ApiError(404, "review_not_found", "No pending review item with that id.")
    entry = session.get(ScratchEntry, item.entry_id)
    item.status = DISMISSED
    if entry is not None:
        entry.routing_state = RESOLVED
        entry.routed_at = _now()
        session.add(entry)
    session.add(item)
    session.commit()
    return {"item_id": item.id, "status": item.status}
