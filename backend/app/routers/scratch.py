"""Scratchpad capture + review-queue endpoints (goal 5; per-user from goal 8).

Thin router: appends raw captures, triggers routing (manual "route now"), and
disposes review items. All orchestration lives in `app.router.service`; the only
runtime LLM (the classifier) is reached through that service, never here. Every
row is scoped to `current_user` (goal 8) — no capture, entry, or review item is
readable or mutable across tenants.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from google.oauth2.credentials import Credentials
from pydantic import BaseModel
from sqlmodel import Session, desc, select

from app.auth.deps import get_current_credentials, get_current_user
from app.auth.models import User
from app.db import get_session
from app.errors import ApiError
from app.router import service as router_svc
from app.router.models import PENDING, ReviewItem, ScratchEntry
from app.router.schema import RouterFields

logger = logging.getLogger(__name__)

router = APIRouter()


def _entry_out(entry: ScratchEntry) -> dict:
    return {
        "id": entry.id,
        "text": entry.text,
        "routing_state": entry.routing_state,
        "created_at": entry.created_at.isoformat(),
        "routed_at": entry.routed_at.isoformat() if entry.routed_at else None,
        # Where a kept note landed (goal 9): the hierarchy path (null = default Doc)
        # for the RECENT chip's hover, and a direct link to the Doc (its newest
        # entry is at the top, so no per-entry anchor is needed).
        "routed_doc_path": entry.routed_doc_path,
        "routed_doc_url": (
            f"https://docs.google.com/document/d/{entry.routed_doc_id}/edit"
            if entry.routed_doc_id
            else None
        ),
    }


class CaptureRequest(BaseModel):
    text: str


@router.post("/scratch", status_code=201)
async def capture(
    body: CaptureRequest,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_current_credentials),
    session: Session = Depends(get_session),
):
    """Append a raw capture, then route it inline (goal 7c instant routing).

    Capture is persisted FIRST (append-only; never edits or deletes prior entries),
    so it can never be lost. Routing then runs synchronously in the same request and
    the response carries the routed state — RECENT renders it filed immediately, no
    scheduler tick. A classifier/Google failure leaves the entry UNROUTED and still
    returns 2xx (capture succeeded); the scheduler backstop retries the filing.
    """
    text = body.text.strip()
    if not text:
        raise ApiError(400, "empty_capture", "Capture text must not be empty.")
    entry = ScratchEntry(user_id=user.id, text=text)
    session.add(entry)
    session.commit()
    session.refresh(entry)

    try:
        await router_svc.route_entry(session, user, creds, entry)
    except ApiError:
        # A Google/Docs write failed — the entry is already persisted and left
        # UNROUTED (re-routable). Capture is never lost; the backstop retries.
        logger.warning("inline routing failed for entry %s; left unrouted", entry.id)
    session.refresh(entry)
    return _entry_out(entry)


@router.get("/scratch")
async def list_entries(
    limit: int = 100,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List THIS user's recent captures, newest first, with their routing state."""
    entries = session.exec(
        select(ScratchEntry)
        .where(ScratchEntry.user_id == user.id)
        .order_by(desc(ScratchEntry.id))
        .limit(limit)
    ).all()
    return {"entries": [_entry_out(e) for e in entries]}


@router.post("/scratch/route-now")
async def route_now(
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_current_credentials),
    session: Session = Depends(get_session),
):
    """Route every unrouted entry for this user now (the manual trigger; same code
    path as the scheduled job). Idempotent: already-routed entries are skipped."""
    tally = await router_svc.route_unrouted(session, user, creds)
    return {"tally": tally}


# ── Review queue ──────────────────────────────────────────────────────────────


def _review_out(item: ReviewItem, entry: ScratchEntry | None) -> dict:
    return {
        "id": item.id,
        "entry_id": item.entry_id,
        "entry_text": entry.text if entry else None,
        "destination": item.destination,
        "fields": item.fields_json,
        "confidence": item.confidence,
        "reason": item.reason,
        "status": item.status,
    }


@router.get("/review")
async def list_review(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """List this user's pending review items with their source-entry text."""
    items = session.exec(
        select(ReviewItem)
        .where(ReviewItem.user_id == user.id)
        .where(ReviewItem.status == PENDING)
        .order_by(ReviewItem.id)
    ).all()
    out = []
    for item in items:
        entry = session.get(ScratchEntry, item.entry_id)
        out.append(_review_out(item, entry))
    return {"items": out}


class ConfirmRequest(BaseModel):
    # Edit-then-confirm: override the proposed destination and/or fields. Omit to
    # confirm the router's original proposal as-is.
    destination: Optional[str] = None
    fields: Optional[RouterFields] = None


@router.post("/review/{item_id}/confirm")
async def confirm(
    item_id: int,
    body: ConfirmRequest | None = None,
    user: User = Depends(get_current_user),
    creds: Credentials = Depends(get_current_credentials),
    session: Session = Depends(get_session),
):
    """Confirm a review item — fires exactly one `create_task` for a `task` item;
    keeps a `note`; acknowledges an `event`/`unknown` with NO write."""
    body = body or ConfirmRequest()
    return await router_svc.confirm_review(
        session, user, creds, item_id, destination=body.destination, fields=body.fields
    )


@router.post("/review/{item_id}/dismiss")
async def dismiss(
    item_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Dismiss a review item — writes nothing; the source entry is resolved."""
    return await router_svc.dismiss_review(session, user, item_id)
