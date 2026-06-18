"""Structured-output schema for the router classification (goal 5).

The classifier returns exactly this shape — schema-validated. An invalid result
is treated as `unknown` (→ review), never a crash and never an auto-write. This
is the contract the LLM *proposes*; deterministic code in `service.py` disposes.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Destination = Literal["task", "note", "event", "unknown"]


class RouterFields(BaseModel):
    """Extracted fields. Which ones are populated depends on the destination:
    task → title (+ optional list_hint, due_date, notes); event → title,
    event_datetime, attendees; note → cleaned note text.
    """

    title: Optional[str] = Field(default=None, description="Task/event title.")
    list_hint: Optional[str] = Field(
        default=None,
        description="Name of the target task list if the user hinted one, else null.",
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
