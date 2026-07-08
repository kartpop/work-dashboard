"""Deterministic route/dispose step — code disposes what the LLM proposes (goal 5).

The classifier returns a `RouterClassification`; THIS module decides what happens
and performs (or withholds) the write. The safety contract lives in router.md:

- **LLM-proposes-code-disposes:** no write lives in the classifier; every write is here.
- **Insert-only blast radius:** the only Google writes reachable from routing are
  `create_task` (content) + `reschedule` (the g4a date path) for tasks, and
  `append_note` (goal 7, insert-only into the notes Doc) for notes. The router NEVER
  calls `delete_task`, the complete/uncomplete status write, `update_content`, or any
  Docs delete/overwrite — it is *not* a sanctioned `delete_task` caller (writes.md).
- **Confidence gate / schema gate / allowed-destination gate:** below threshold, or
  `unknown`/`event`, never auto-writes — it goes to the review queue.
- **Route-once:** routing flips `routing_state` off `UNROUTED`, so a re-run no-ops.

Goal 8: routing is per-user. `route_entry` takes the current `user` + their live
`creds`; every Google call uses those creds, the notes Doc is the user's own
(auto-bootstrapped via `settings_svc`), and every scratch/review row is user-scoped.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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
from app.settings import service as settings_svc
from app.writes import service as writes_svc

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

    from app.auth.models import User


_log = logging.getLogger("router.service")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _dispose_note(
    session: Session,
    creds: "Credentials",
    user_id: int,
    entry: ScratchEntry,
    text: str | None = None,
    summary: str | None = None,
) -> str:
    """Dispose a `note`: write it VERBATIM to the top of the user's notes Doc.

    Goal 8: the notes folder + Doc are app-created on first need (`ensure_notes_target`),
    so a note always has a home in the user's own Drive — no env config, no kept-local
    default. `text` overrides the raw body (a review edit); `summary` (goal 7c) is the
    LLM one-liner rendered bold above the raw text. Returns KEPT_NOTE.

    A Drive/Docs failure raises (entry left re-routable, rollback) so route-once only
    marks the entry routed after a successful append — same contract as the task path.
    """
    body_text = text if text is not None else entry.text
    doc_id, folder_id = await settings_svc.ensure_notes_target(session, creds, user_id)
    try:
        await writes_svc.append_note(
            creds, doc_id, folder_id, body_text, summary=summary
        )
    except ApiError:
        session.rollback()
        raise
    return KEPT_NOTE


async def _resolve_list_id(creds: "Credentials", list_hint: str | None) -> str:
    """Map an optional list-hint to a real Google task-list id (deterministic).

    Case-insensitive match on list title; falls back to the first (default) list.
    Raises if Google has no lists or is unreachable (caller leaves entry re-routable).
    """
    raw_lists = await tasks_client.get_task_lists(creds)
    if not raw_lists:
        raise ApiError(502, "no_lists", "No Google task lists are available.")
    if list_hint:
        needle = list_hint.strip().lstrip("#").lower()
        for tl in raw_lists:
            title = (tl.get("title") or "").lower()
            if needle and (needle == title or needle in title):
                return tl["id"]
    return raw_lists[0]["id"]


async def _create_task_from_fields(
    session: Session, creds: "Credentials", user_id: int, fields: RouterFields
) -> dict:
    """Create a Google task from extracted fields, applying list-hint + due date.

    Two sanctioned writes only: `create_task` (always) and `reschedule` (only when a
    due date was extracted — the g4a date path). Nothing destructive is reachable.
    """
    title = (fields.title or "").strip()
    if not title:
        raise ApiError(422, "empty_title", "Router produced no task title.")
    list_id = await _resolve_list_id(creds, fields.list_hint)

    # 1) create (lands undated in NO_DATE) — the router's primary write. Notes are
    #    intentionally dropped: writing them would need `update_content`, which is NOT
    #    a sanctioned router write (create-only). A reviewer can add notes by hand.
    created = await writes_svc.create_task(
        session, creds, user_id, list_id, title, rank=None
    )

    # 2) set the due date via the g4a reschedule path (metadata write, non-destructive).
    if fields.due_date:
        await writes_svc.reschedule(
            session,
            creds,
            user_id,
            tasklist_id=list_id,
            task_id=created["id"],
            due_date=fields.due_date,
            rank=created.get("rank"),
            group_id=None,
        )
    return {"list_id": list_id, "task_id": created["id"]}


def _new_review_item(
    entry: ScratchEntry,
    user_id: int,
    destination: str,
    fields: RouterFields,
    confidence: float,
    reason: str,
) -> ReviewItem:
    return ReviewItem(
        user_id=user_id,
        entry_id=entry.id,  # type: ignore[arg-type]
        destination=destination,
        fields_json=fields.model_dump_json(),
        confidence=confidence,
        reason=reason,
        status=PENDING,
    )


async def route_entry(
    session: Session, user: "User", creds: "Credentials", entry: ScratchEntry
) -> str:
    """Classify + dispose one entry for `user`. Returns the resulting routing_state.

    Idempotent: if the entry is already routed it is left untouched. A Google-write
    failure in the deterministic step leaves the entry `UNROUTED` (re-routable) and
    raises an `ApiError` — nothing is half-written, the error is never swallowed.
    """
    if entry.routing_state != UNROUTED:
        return entry.routing_state

    user_id = user.id
    classification = await classify(entry.text)
    entry.route_result = classification.model_dump_json()
    dest = classification.destination
    conf = classification.confidence
    fields = classification.fields
    above = conf >= config.CONFIDENCE_THRESHOLD

    if dest == "task" and above:
        try:
            await _create_task_from_fields(session, creds, user_id, fields)
        except ApiError:
            # Re-routable: do not persist a routed state; surface the error.
            session.rollback()
            raise
        entry.routing_state = ROUTED_TASK
    elif dest == "note" and above:
        entry.routing_state = await _dispose_note(
            session, creds, user_id, entry, summary=fields.summary
        )
    else:
        if dest in ("task", "note"):
            reason = f"low confidence ({conf:.2f}) for {dest}"
        elif dest == "event":
            reason = "events need a manual calendar add (read-only v1)"
        else:
            reason = "unclassifiable"
        session.add(_new_review_item(entry, user_id, dest, fields, conf, reason))
        entry.routing_state = IN_REVIEW

    entry.routed_at = _now()
    session.add(entry)
    session.commit()
    return entry.routing_state


async def route_unrouted(session: Session, user: "User", creds: "Credentials") -> dict:
    """Route every `UNROUTED` entry for `user` exactly once. Per-entry write failures
    are tallied and skipped (entry left re-routable) so one bad entry can't stall the
    batch. Returns a summary tally."""
    entries = session.exec(
        select(ScratchEntry)
        .where(ScratchEntry.user_id == user.id)
        .where(ScratchEntry.routing_state == UNROUTED)
    ).all()
    tally = {"routed_task": 0, "kept_note": 0, "in_review": 0, "failed": 0}
    for entry in entries:
        try:
            state = await route_entry(session, user, creds, entry)
            tally[state] = tally.get(state, 0) + 1
        except ApiError:
            tally["failed"] += 1
    return tally


# ── Review-queue dispositions ─────────────────────────────────────────────────


def _get_scoped_review(session: Session, user_id: int, item_id: int) -> ReviewItem:
    """Fetch a PENDING review item that belongs to `user_id` (404 otherwise —
    no cross-tenant read by id)."""
    item = session.get(ReviewItem, item_id)
    if item is None or item.user_id != user_id or item.status != PENDING:
        raise ApiError(404, "review_not_found", "No pending review item with that id.")
    return item


async def confirm_review(
    session: Session,
    user: "User",
    creds: "Credentials",
    item_id: int,
    destination: str | None = None,
    fields: RouterFields | None = None,
) -> dict:
    """Confirm a pending review item (optionally edit-then-confirm).

    A `task` confirmation fires exactly one `create_task` (+ date). `note` keeps it
    in the user's Doc. `event`/`unknown` are acknowledged with NO write (manual-add).
    """
    item = _get_scoped_review(session, user.id, item_id)
    entry = session.get(ScratchEntry, item.entry_id)
    if entry is None:
        raise ApiError(404, "entry_not_found", "Source entry missing.")

    dest = destination or item.destination
    eff_fields = fields or RouterFields(**json.loads(item.fields_json or "{}"))

    if dest == "task":
        try:
            await _create_task_from_fields(session, creds, user.id, eff_fields)
        except ApiError:
            session.rollback()
            raise
        entry.routing_state = ROUTED_TASK
    elif dest == "note":
        # Review edits win: a user-edited note body / one-liner is what lands
        # (goal 7c). An empty note_text falls back to the verbatim entry text.
        edited = (eff_fields.note_text or "").strip()
        entry.routing_state = await _dispose_note(
            session,
            creds,
            user.id,
            entry,
            text=edited or None,
            summary=eff_fields.summary,
        )
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


async def dismiss_review(session: Session, user: "User", item_id: int) -> dict:
    """Dismiss a pending review item — writes nothing; the entry is resolved."""
    item = _get_scoped_review(session, user.id, item_id)
    entry = session.get(ScratchEntry, item.entry_id)
    item.status = DISMISSED
    if entry is not None:
        entry.routing_state = RESOLVED
        entry.routed_at = _now()
        session.add(entry)
    session.add(item)
    session.commit()
    return {"item_id": item.id, "status": item.status}
