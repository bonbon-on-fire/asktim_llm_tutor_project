"""add rating column to messages

Per-message thumb rating from the student: -1 (down), 0 (none), 1 (up). Only
ever set on tutor rows. Added NOT NULL with a server default of 0 so existing
rows backfill cleanly. A CHECK constraint pins it to {-1, 0, 1}.

Revision ID: f1a2b3c4d5e6
Revises: a7f3c1e9b204
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'a7f3c1e9b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the messages rating-column migration."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('rating', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.create_check_constraint(
            'ck_messages_rating', 'rating IN (-1, 0, 1)'
        )


def downgrade() -> None:
    """Revert the messages rating-column migration."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_constraint('ck_messages_rating', type_='check')
        batch_op.drop_column('rating')
