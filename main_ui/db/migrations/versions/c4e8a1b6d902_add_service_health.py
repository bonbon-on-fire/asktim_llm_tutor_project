"""add service_health singleton for automatic outage detection

Revision ID: c4e8a1b6d902
Revises: b3d9f1a4c027
Create Date: 2026-08-25 00:00:00.000000

Phase 2 of automatic outage detection: a single shared row that live
``/api/chat`` outcomes fold into, so the "AskTIM is down" banner can engage
across the 4 gunicorn workers without Redis. See
``main_ui/services/service_health.py`` and the design spec
``docs/superpowers/specs/2026-08-25-auto-outage-detection-server-design.md``.
The migration seeds the single id=1 row so the service never depends on
create_all in production.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8a1b6d902'
down_revision: Union[str, Sequence[str], None] = 'b3d9f1a4c027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the service_health table and seed the singleton row."""
    op.create_table(
        "service_health",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column(
            "degraded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("degraded_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Seed the single coordination row. id is always 1; the service reads/writes
    # only this row. server_defaults cover the rest.
    op.execute("INSERT INTO service_health (id) VALUES (1)")


def downgrade() -> None:
    """Drop the service_health table."""
    op.drop_table("service_health")
