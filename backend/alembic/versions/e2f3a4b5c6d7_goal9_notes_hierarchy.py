"""goal 9: notes hierarchy (user_settings.notes_index + scratch_entry.routed_doc_path)

Revision ID: e2f3a4b5c6d7
Revises: d1a2b3c4e5f6
Create Date: 2026-07-10 09:00:00.000000

Two additive columns, both nullable-with-default so existing rows migrate to the
current behavior:
- `user_settings.notes_index` — the JSON folder/Doc forest (defaults to "[]", an
  empty tree → routing falls back to the default Doc exactly as today).
- `scratch_entry.routed_doc_path` — the hierarchy path a kept note landed in
  (NULL = default Doc).
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, Sequence[str], None] = "d1a2b3c4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_Str = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("notes_index", _Str(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "scratch_entry",
        sa.Column("routed_doc_path", _Str(), nullable=True),
    )
    op.add_column(
        "scratch_entry",
        sa.Column("routed_doc_id", _Str(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scratch_entry", "routed_doc_id")
    op.drop_column("scratch_entry", "routed_doc_path")
    op.drop_column("user_settings", "notes_index")
