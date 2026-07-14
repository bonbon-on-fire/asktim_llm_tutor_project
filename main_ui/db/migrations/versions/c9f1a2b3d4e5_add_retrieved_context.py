"""add retrieved_context (messages)

Nullable; pre-feature rows stay NULL.

Revision ID: c9f1a2b3d4e5
Revises: a1b2c3d4e5f6
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c9f1a2b3d4e5'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'  # use the real current head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retrieved_context', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('retrieved_context')
