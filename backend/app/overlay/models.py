from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class TaskOverlay(SQLModel, table=True):
    __tablename__ = "task_overlay"

    tasklist_id: str = Field(primary_key=True, max_length=100)
    task_id: str = Field(primary_key=True, max_length=100)
    rank: Optional[float] = Field(default=None, index=True)
    priority: Optional[int] = Field(default=None)  # 0=none 1=low 2=medium 3=high
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
