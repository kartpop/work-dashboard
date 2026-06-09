from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class TaskGroup(SQLModel, table=True):
    __tablename__ = "task_group"
    __table_args__ = (UniqueConstraint("tasklist_id", "bucket_key", "name"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    tasklist_id: str = Field(max_length=100, index=True)
    bucket_key: str = Field(max_length=20)  # YYYY-MM-DD (IST) or NO_DATE
    name: str = Field(max_length=200)
    rank: Optional[float] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TaskOverlay(SQLModel, table=True):
    __tablename__ = "task_overlay"

    tasklist_id: str = Field(primary_key=True, max_length=100)
    task_id: str = Field(primary_key=True, max_length=100)
    rank: Optional[float] = Field(default=None, index=True)
    group_id: Optional[int] = Field(default=None, foreign_key="task_group.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
