"""add exercise_kind

Revision ID: d2e724232980
Revises: c9f1a2b3d4e5
Create Date: 2026-07-18 11:09:52.972623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e724232980'
down_revision: Union[str, Sequence[str], None] = 'c9f1a2b3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the add-exercise_kind migration."""
    op.add_column(
        "conversations",
        sa.Column(
            "exercise_kind",
            sa.Text(),
            nullable=False,
            server_default="exercise",
        ),
    )


def downgrade() -> None:
    """Revert the add-exercise_kind migration."""
    op.drop_column("conversations", "exercise_kind")
