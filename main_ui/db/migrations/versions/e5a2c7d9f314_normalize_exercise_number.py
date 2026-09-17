"""normalize conversations.exercise_number

Rewrites existing ``conversations.exercise_number`` values to their non-padded
canonical form ('01' -> '1'). A padded assignment link once recorded a second,
duplicate conversation for the same exercise, which showed up as two options
("Exercise 1" / "Exercise 01") in the database_ui export picker. The write path
now normalizes on the way in, so new records can't split; this one-time
migration collapses the records that were written before that fix.

Data-only: no schema change. The normalization is inlined (not imported from
utils.curriculum) so this migration stays a fixed historical snapshot even if
that helper is later refactored. It is dialect-agnostic — it reads the distinct
values, normalizes them in Python, and issues an UPDATE only for the ones that
actually change — so it runs the same on the SQLite test DB and Postgres prod.

Revision ID: e5a2c7d9f314
Revises: a1c3e5f7b209
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a2c7d9f314'
down_revision: Union[str, Sequence[str], None] = 'a1c3e5f7b209'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize(num):
    """Non-padded canonical form of an item number ('01' -> '1').

    Mirrors utils.curriculum.normalize_item_number, inlined so this migration is
    frozen against future changes to that helper. Numeric strings collapse to
    their integer form; None and non-numeric values pass through unchanged.
    """
    if num is None:
        return num
    s = str(num).strip()
    return str(int(s)) if s.isdigit() else s


def upgrade() -> None:
    """Normalize existing exercise_number values to their non-padded form."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT DISTINCT exercise_number FROM conversations")
    ).all()
    update = sa.text(
        "UPDATE conversations SET exercise_number = :new "
        "WHERE exercise_number = :old"
    )
    for (old,) in rows:
        new = _normalize(old)
        if new != old:
            bind.execute(update, {"new": new, "old": old})


def downgrade() -> None:
    """No-op: normalization is not reversible (the original padding is lost)."""
    pass
