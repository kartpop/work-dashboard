"""add scratchpad and review queue

Revision ID: c4d5e6f70812
Revises: b8e1cf4a6209
Create Date: 2026-06-17 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "c4d5e6f70812"
down_revision: Union[str, Sequence[str], None] = "b8e1cf4a6209"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scratch_entry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "routing_state", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column("route_result", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("routed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_scratch_entry_routing_state", "scratch_entry", ["routing_state"]
    )

    op.create_table(
        "review_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column(
            "destination", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column("fields_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["scratch_entry.id"], name="fk_review_item_entry_id"
        ),
    )
    op.create_index("ix_review_item_entry_id", "review_item", ["entry_id"])
    op.create_index("ix_review_item_status", "review_item", ["status"])


def downgrade() -> None:
    op.drop_index("ix_review_item_status", table_name="review_item")
    op.drop_index("ix_review_item_entry_id", table_name="review_item")
    op.drop_table("review_item")

    op.drop_index("ix_scratch_entry_routing_state", table_name="scratch_entry")
    op.drop_table("scratch_entry")
