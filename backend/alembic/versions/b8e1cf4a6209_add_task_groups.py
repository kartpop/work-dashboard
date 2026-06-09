"""add task groups

Revision ID: b8e1cf4a6209
Revises: 7173ec284d38
Create Date: 2026-06-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b8e1cf4a6209'
down_revision: Union[str, Sequence[str], None] = '7173ec284d38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'task_group',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tasklist_id', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column('bucket_key', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=False),
        sa.Column('rank', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tasklist_id', 'bucket_key', 'name', name='uq_task_group_list_bucket_name'),
    )
    op.create_index('ix_task_group_tasklist_id', 'task_group', ['tasklist_id'])

    with op.batch_alter_table('task_overlay', schema=None) as batch_op:
        batch_op.drop_column('priority')
        batch_op.add_column(sa.Column('group_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_task_overlay_group_id',
            'task_group',
            ['group_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('task_overlay', schema=None) as batch_op:
        batch_op.drop_constraint('fk_task_overlay_group_id', type_='foreignkey')
        batch_op.drop_column('group_id')
        batch_op.add_column(sa.Column('priority', sa.Integer(), nullable=True))

    op.drop_index('ix_task_group_tasklist_id', table_name='task_group')
    op.drop_table('task_group')
