"""add feedback table

Stores student tutor-ratings (1..5) scoped to a conversation. New table with no
existing rows, so the additive create is safe.

Revision ID: a7f3c1e9b204
Revises: eb96d85f90cf
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3c1e9b204'
down_revision: Union[str, Sequence[str], None] = 'eb96d85f90cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the add-feedback-table migration."""
    op.create_table(
        'feedback',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('turn', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_feedback_rating'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.create_index('idx_feedback_conversation', ['conversation_id'], unique=False)


def downgrade() -> None:
    """Revert the add-feedback-table migration."""
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.drop_index('idx_feedback_conversation')
    op.drop_table('feedback')
