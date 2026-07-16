"""Scratchpad + review-queue persistence (goal 5).

Two append-friendly tables backing the capture box and the human-in-the-loop
review surface. Reuses the existing SQLModel + Alembic setup (see backend.md).
Routing state lives on `scratch_entry` and is the route-once idempotency guard —
the scheduled job only picks up `UNROUTED` rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

# ── Routing states (scratch_entry.routing_state) ──────────────────────────────
UNROUTED = "unrouted"
# In-flight claim (goal 10a): exactly one router owns this entry right now. Route-once
# used to be a check-then-act — read UNROUTED, then write the final state ~20s later,
# after the LLM call and the Docs append. Anything that read the row inside that window
# (the scheduler backstop, a "Route now" click, a retried POST) routed it a second time
# and appended the note TWICE. `service._claim_for_routing` makes the flip atomic, so
# the losers see a non-UNROUTED row and no-op. Transient: released back to UNROUTED on
# failure, and reclaimed by the backstop if the process dies mid-route.
ROUTING = "routing"
ROUTED_TASK = "routed_task"
KEPT_NOTE = "kept_note"
IN_REVIEW = "in_review"
# Terminal state for a review item resolved without a live write — a dismissed
# item or a confirmed event (calendar is read-only v1; the user added it manually).
RESOLVED = "resolved"

# ── Review-item statuses (review_item.status) ─────────────────────────────────
PENDING = "pending"
CONFIRMED = "confirmed"
DISMISSED = "dismissed"


class ScratchEntry(SQLModel, table=True):
    __tablename__ = "scratch_entry"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # row-scoping (goal 8)
    text: str = Field()
    routing_state: str = Field(default=UNROUTED, max_length=20, index=True)
    # Raw classification JSON (destination/confidence/fields) for display + debug.
    # Never re-read for control flow — the routing_state is the source of truth.
    route_result: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    routed_at: Optional[datetime] = Field(default=None)
    # The hierarchy Doc path a `kept_note` was actually disposed to (goal 9),
    # e.g. "conversations/john/growth". Null = the default Doc. Set on kept_note
    # (auto-route + confirm-as-note). Drives the RECENT chip's hover tooltip.
    routed_doc_path: Optional[str] = Field(default=None)
    # The Drive id of the Doc the note actually landed in (captured at dispose
    # time — robust to later renames/deletes). Lets the RECENT chip link straight
    # to the Doc (its newest entry is at the top, so no per-entry anchor needed).
    routed_doc_id: Optional[str] = Field(default=None)


class ReviewItem(SQLModel, table=True):
    __tablename__ = "review_item"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)  # row-scoping (goal 8)
    entry_id: int = Field(foreign_key="scratch_entry.id", index=True)
    destination: str = Field(max_length=20)  # proposed: task | note | event | unknown
    fields_json: str = Field(default="{}")  # extracted fields the human can edit
    confidence: float = Field(default=0.0)
    reason: Optional[str] = Field(default=None)  # why it landed in review
    status: str = Field(default=PENDING, max_length=20, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
