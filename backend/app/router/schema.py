"""Structured-output schema for the router classification (goal 5).

The classifier returns exactly this shape — schema-validated. An invalid result
is treated as `unknown` (→ review), never a crash and never an auto-write. This
is the contract the LLM *proposes*; deterministic code in `service.py` disposes.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Destination = Literal["task", "note", "event", "unknown"]

# The dashboard renders exactly two task lists; the router is opinionated and files
# every task into one of them (never a third Google list). Keep in sync with the
# frontend `PINNED_LIST_TITLES` (TasksPanel.tsx) and `service.PINNED_LIST_TITLES`.
TargetList = Literal["My Tasks", "Follow-ups"]


class RouterFields(BaseModel):
    """Extracted fields. Which ones are populated depends on the destination:
    task → title (+ optional target_list, due_date, notes); event → title,
    event_datetime, attendees; note → cleaned note text.
    """

    title: Optional[str] = Field(default=None, description="Task/event title.")
    target_list: Optional[TargetList] = Field(
        default=None,
        description=(
            'Which list a task belongs to: "My Tasks" (default) for the user\'s own '
            'to-dos, or "Follow-ups" for things they are waiting on or need to chase '
            "with someone else. Null for non-task destinations."
        ),
    )
    due_date: Optional[str] = Field(
        default=None,
        description="Resolved due date as YYYY-MM-DD (IST), else null.",
    )
    notes: Optional[str] = Field(
        default=None, description="Extra task notes, else null."
    )
    note_text: Optional[str] = Field(
        default=None, description="Cleaned note body when destination is note."
    )
    summary: Optional[str] = Field(
        default=None,
        description=(
            "For a note: a single short phrase (a few words) capturing the note's "
            "essence — a one-liner headline, NOT a rewrite of the note. Else null."
        ),
    )
    event_datetime: Optional[str] = Field(
        default=None,
        description="Event date/time as free text when destination is event.",
    )
    attendees: Optional[str] = Field(
        default=None, description="Event attendees as free text, else null."
    )


class RouterClassification(BaseModel):
    destination: Destination = Field(description="Where this entry should go.")
    confidence: float = Field(
        description="Confidence in [0,1] that the destination + key fields are correct."
    )
    fields: RouterFields = Field(default_factory=RouterFields)


def unknown_classification(confidence: float = 0.0) -> RouterClassification:
    """The safe fallback: schema-invalid output / model error → unknown → review."""
    return RouterClassification(
        destination="unknown", confidence=confidence, fields=RouterFields()
    )
