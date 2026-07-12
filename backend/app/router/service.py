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
from app.settings import notes_index
from app.settings import service as settings_svc
from app.writes import service as writes_svc

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

    from app.auth.models import User


_log = logging.getLogger("router.service")

# The router is opinionated: every routed task is filed into one of exactly these
# two lists — the same lists the dashboard renders (frontend `PINNED_LIST_TITLES`
# in TasksPanel.tsx) — and NEVER into any other Google list the user may have. A
# task filed into an unrendered list is created successfully but never shown.
# DEFAULT_LIST_TITLE is where an unclassified task lands. Keep both in sync with
# the frontend constant and `schema.TargetList`.
PINNED_LIST_TITLES = ("My Tasks", "Follow-ups")
DEFAULT_LIST_TITLE = "My Tasks"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _guarded_note_body(raw: str, note_text: str | None) -> str:
    """The body to write: the prefix-stripped `note_text`, guarded (goal 9).

    Truncation guard — a mangled extraction must never silently lose words: if
    `note_text` is missing, empty, or suspiciously short (< 50% of the raw text's
    length), fall back to the **raw text verbatim**. Otherwise the stripped text
    (prefix removed, rest verbatim) wins."""
    candidate = note_text or ""
    if not candidate.strip() or len(candidate.strip()) < 0.5 * len(raw.strip()):
        return raw
    return candidate


async def _dispose_note(
    session: Session,
    creds: "Credentials",
    user_id: int,
    entry: ScratchEntry,
    fields: RouterFields,
    body_override: str | None = None,
) -> str:
    """Dispose a `note`: route it to the best-matching hierarchy Doc (goal 9).

    The body is the prefix-stripped `note_text` under the truncation guard
    (`_guarded_note_body`); `body_override` (a review edit) wins verbatim. The Doc is
    resolved deterministically from `fields.target_doc_path` (path → stored id;
    unknown/null → default Doc), self-healing a 404'd hierarchy Doc at the same path.
    `entry.routed_doc_path` records where it landed (null = default). `summary` +
    optional `keywords` are the only LLM-authored lines. Returns KEPT_NOTE.

    A Drive/Docs failure raises (entry left re-routable, rollback) so route-once only
    marks the entry routed after a successful append — same contract as the task path.
    """
    body_text = (
        body_override
        if body_override is not None
        else _guarded_note_body(entry.text, fields.note_text)
    )
    doc_id, folder_id, canonical = await settings_svc.resolve_note_target(
        session, creds, user_id, fields.target_doc_path
    )
    try:
        await writes_svc.append_note(
            creds,
            doc_id,
            folder_id,
            body_text,
            summary=fields.summary,
            keywords=fields.keywords,
        )
    except ApiError:
        session.rollback()
        raise
    entry.routed_doc_path = canonical
    entry.routed_doc_id = doc_id
    return KEPT_NOTE


async def _resolve_list_id(creds: "Credentials", target_list: str | None) -> str:
    """Resolve the classifier's `target_list` to a real Google task-list id.

    Opinionated: routing files ONLY into the two pinned lists (`PINNED_LIST_TITLES`)
    the dashboard renders — never into any other Google list. Matches the requested
    list by title (case-insensitive); an unset/unknown target defaults to "My Tasks".
    If the requested pinned list is missing but the other exists, falls back to the
    other pinned list (never a third list). Raises if NEITHER pinned list exists
    (the two-list prerequisite is unmet) or Google is unreachable — the caller then
    leaves the entry re-routable.
    """
    raw_lists = await tasks_client.get_task_lists(creds)
    # title(lower) → id, restricted to the two pinned lists we are willing to write.
    pinned = {t.lower(): None for t in PINNED_LIST_TITLES}
    for tl in raw_lists:
        title = (tl.get("title") or "").strip().lower()
        if title in pinned and pinned[title] is None:
            pinned[title] = tl["id"]

    requested = (target_list or DEFAULT_LIST_TITLE).strip().lstrip("#").lower()
    if requested not in pinned:
        requested = DEFAULT_LIST_TITLE.lower()

    # Prefer the requested list, then the primary default, then the other pinned list.
    for title in (requested, DEFAULT_LIST_TITLE.lower(), *pinned):
        if pinned.get(title) is not None:
            return pinned[title]

    raise ApiError(
        502,
        "no_pinned_lists",
        "This account has neither 'My Tasks' nor 'Follow-ups'. Create both task "
        "lists in Google Tasks — the dashboard requires them.",
    )


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
    list_id = await _resolve_list_id(creds, fields.target_list)

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


async def classify_text(
    session: Session, user_id: int, text: str
) -> RouterClassification:
    """Classify a capture WITHOUT disposing it — a pure, side-effect-free LLM call.

    Split out from `route_entry` so the capture UI can run the (slow) classifier
    during its undo window (the deferred-write toast) and then commit the already-
    computed classification when the window lapses — the LLM latency hides behind the
    toast instead of adding to it. No DB write, no Google write; safe to discard on
    undo. The user's notes hierarchy is injected so the LLM can propose a doc path.
    """
    doc_paths = notes_index.leaf_paths(settings_svc.get_notes_index(session, user_id))
    return await classify(text, doc_paths)


async def route_entry(
    session: Session,
    user: "User",
    creds: "Credentials",
    entry: ScratchEntry,
    classification: RouterClassification | None = None,
) -> str:
    """Classify + dispose one entry for `user`. Returns the resulting routing_state.

    Idempotent: if the entry is already routed it is left untouched. A Google-write
    failure in the deterministic step leaves the entry `UNROUTED` (re-routable) and
    raises an `ApiError` — nothing is half-written, the error is never swallowed.

    `classification` lets a caller inject a pre-computed classification (from
    `classify_text`, run during the capture undo window) so the LLM call is not
    repeated inline; when omitted the classifier runs here as before. Dispose is
    deterministic either way — the confidence/schema/destination gates still apply,
    and a note's Doc still comes from path→id resolution, never from the payload.
    """
    if entry.routing_state != UNROUTED:
        return entry.routing_state

    user_id = user.id
    if classification is None:
        classification = await classify_text(session, user_id, entry.text)
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
            session, creds, user_id, entry, fields
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
        # The review dropdown only offers real leaves, so a non-null path that
        # doesn't validate means a stale tree → 422 (goal 9, item 7). Null = default.
        if eff_fields.target_doc_path:
            forest = settings_svc.get_notes_index(session, user.id)
            if notes_index.resolve_path(forest, eff_fields.target_doc_path) is None:
                raise ApiError(
                    422, "unknown_doc_path", "That notes Doc no longer exists."
                )
        # Review edits win: a user-edited note body / one-liner is what lands. An
        # empty note_text falls back to the verbatim entry text (bypasses the guard).
        edited = (eff_fields.note_text or "").strip()
        entry.routing_state = await _dispose_note(
            session,
            creds,
            user.id,
            entry,
            eff_fields,
            body_override=edited or entry.text,
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
