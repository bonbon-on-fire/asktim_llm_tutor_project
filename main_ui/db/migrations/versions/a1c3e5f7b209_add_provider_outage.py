"""add provider_outage incident log

Append-only history of tutor degraded episodes (see
main_ui/services/service_health.py and the design spec
docs/superpowers/specs/2026-09-03-provider-outage-weekly-report-markers-design.md).
Starts empty; rows are written as outages open and close. The database_ui
weekly report reads this table to mark affected days on the activity chart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5f7b209"
down_revision: Union[str, Sequence[str], None] = "c4e8a1b6d902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_outage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_outage")
