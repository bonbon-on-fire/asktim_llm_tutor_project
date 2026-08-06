"""add focus_problem

Revision ID: b3d9f1a4c027
Revises: d2e724232980
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d9f1a4c027'
down_revision: Union[str, Sequence[str], None] = 'd2e724232980'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("focus_problem", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "focus_problem")
