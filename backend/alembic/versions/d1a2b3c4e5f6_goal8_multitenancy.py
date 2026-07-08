"""goal 8: auth + multi-tenancy (user/allowed_email/user_settings + user_id scoping)

Revision ID: d1a2b3c4e5f6
Revises: c4d5e6f70812
Create Date: 2026-07-08 09:00:00.000000

Existing overlay/review rows are test-mode and disposable (goal-8 brief item 3:
"the server starts from an empty overlay.db"), so the four user-owned tables are
dropped and recreated with a `user_id` column rather than migrated in place.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "d1a2b3c4e5f6"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f70812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_Str = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    # ── New auth / tenancy tables ─────────────────────────────────────────────
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("google_sub", _Str(length=64), nullable=False),
        sa.Column("email", _Str(length=320), nullable=False),
        sa.Column("name", _Str(length=200), nullable=True),
        sa.Column("picture", _Str(), nullable=True),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("refresh_token_encrypted", _Str(), nullable=True),
        sa.Column("granted_scopes", _Str(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_google_sub", "user", ["google_sub"], unique=True)
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "allowed_email",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", _Str(length=320), nullable=False),
        sa.Column("added_by", _Str(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_allowed_email_email", "allowed_email", ["email"], unique=True)

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("notes_folder_id", _Str(), nullable=True),
        sa.Column("notes_doc_id", _Str(), nullable=True),
        sa.Column("enabled_calendar_ids", _Str(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_user_settings_user_id"
        ),
    )

    # ── Recreate user-owned tables with user_id (children dropped first) ───────
    op.drop_index("ix_review_item_status", table_name="review_item")
    op.drop_index("ix_review_item_entry_id", table_name="review_item")
    op.drop_table("review_item")
    op.drop_index("ix_scratch_entry_routing_state", table_name="scratch_entry")
    op.drop_table("scratch_entry")
    op.drop_table("task_overlay")
    op.drop_index("ix_task_group_tasklist_id", table_name="task_group")
    op.drop_table("task_group")

    op.create_table(
        "task_group",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tasklist_id", _Str(length=100), nullable=False),
        sa.Column("bucket_key", _Str(length=20), nullable=False),
        sa.Column("name", _Str(length=200), nullable=False),
        sa.Column("rank", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_task_group_user_id"),
        sa.UniqueConstraint(
            "user_id", "tasklist_id", "bucket_key", "name", name="uq_task_group_scope"
        ),
    )
    op.create_index("ix_task_group_user_id", "task_group", ["user_id"])
    op.create_index("ix_task_group_tasklist_id", "task_group", ["tasklist_id"])

    op.create_table(
        "task_overlay",
        sa.Column("user_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("tasklist_id", _Str(length=100), primary_key=True, nullable=False),
        sa.Column("task_id", _Str(length=100), primary_key=True, nullable=False),
        sa.Column("rank", sa.Float(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_task_overlay_user"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["task_group.id"], name="fk_task_overlay_group_id"
        ),
    )
    op.create_index("ix_task_overlay_rank", "task_overlay", ["rank"])

    op.create_table(
        "scratch_entry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("text", _Str(), nullable=False),
        sa.Column("routing_state", _Str(length=20), nullable=False),
        sa.Column("route_result", _Str(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("routed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_scratch_entry_user_id"
        ),
    )
    op.create_index("ix_scratch_entry_user_id", "scratch_entry", ["user_id"])
    op.create_index(
        "ix_scratch_entry_routing_state", "scratch_entry", ["routing_state"]
    )

    op.create_table(
        "review_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("destination", _Str(length=20), nullable=False),
        sa.Column("fields_json", _Str(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", _Str(), nullable=True),
        sa.Column("status", _Str(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["scratch_entry.id"], name="fk_review_item_entry_id"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_review_item_user_id"
        ),
    )
    op.create_index("ix_review_item_user_id", "review_item", ["user_id"])
    op.create_index("ix_review_item_entry_id", "review_item", ["entry_id"])
    op.create_index("ix_review_item_status", "review_item", ["status"])


def downgrade() -> None:
    raise NotImplementedError("goal-8 multitenancy migration is forward-only")
