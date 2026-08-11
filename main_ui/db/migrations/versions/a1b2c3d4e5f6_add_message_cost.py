"""add cost_usd + usage_json columns to messages

Estimated USD cost of producing a tutor turn (tutor tokens + prompt cache + RAG
query embedding), plus a JSON breakdown so the figure stays auditable. Both are
nullable — student rows and rows created before this feature stay NULL. main_ui
persists these but does not render them; sandbox_ui renders them.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the messages cost_usd/usage_json migration."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cost_usd', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('usage_json', sa.Text(), nullable=True))


def downgrade() -> None:
    """Revert the messages cost_usd/usage_json migration."""
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('usage_json')
        batch_op.drop_column('cost_usd')
