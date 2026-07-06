"""reconcile identity schema (idempotent)

Belt-and-suspenders convergence of the ``email`` -> ``username`` rename on
long-lived databases whose real schema drifted out of step with
``alembic_version`` — e.g. a DB created by an early ``create_all`` and then
``stamp``ed to head, on which the pure-rename migration
(``c1d2e3f4a5b6``) never actually executed. Because this is a brand-new
revision, ``alembic upgrade head`` is guaranteed to run it regardless of what
the deployed ``alembic_version`` claims, and every step is guarded by an
inspector check so it is a no-op once the schema already matches the models
(the normal case on a fresh migration chain or SQLite dev DB).

Converges, for whatever state each table is actually in:
- ``conversations``: ensure a nullable ``username`` column + its index exist,
  backfilled from and superseding the legacy ``email`` column/index.
- ``students``: ensure ``username`` is the primary key, superseding ``email``.
- ``messages``: ensure the ``pedagogical_reasoning`` column exists.

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(insp: sa.Inspector, table: str) -> set[str]:
    """Current column names of *table* (empty set if the table is absent)."""
    return {c["name"] for c in insp.get_columns(table)}


def _index_names(insp: sa.Inspector, table: str) -> set[str]:
    """Current index names of *table* (empty set if the table is absent)."""
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    is_postgres = bind.dialect.name == "postgresql"

    # ---- conversations: converge email -> username (+ index) ----
    if "conversations" in tables:
        cols = _cols(insp, "conversations")
        idx = _index_names(insp, "conversations")
        if "email" in cols and "username" not in cols:
            # Pure rename: drop the old index first (it references the old name).
            if "idx_conversations_email" in idx:
                op.drop_index("idx_conversations_email", table_name="conversations")
            with op.batch_alter_table("conversations", schema=None) as batch_op:
                batch_op.alter_column("email", new_column_name="username")
        elif "email" in cols and "username" in cols:
            # Both present (partially migrated): backfill then drop the legacy column.
            op.execute(
                "UPDATE conversations SET username = email "
                "WHERE username IS NULL AND email IS NOT NULL"
            )
            if "idx_conversations_email" in idx:
                op.drop_index("idx_conversations_email", table_name="conversations")
            with op.batch_alter_table("conversations", schema=None) as batch_op:
                batch_op.drop_column("email")
        elif "username" not in cols:
            # Neither present: add the column the models expect.
            op.add_column(
                "conversations", sa.Column("username", sa.Text(), nullable=True)
            )
        # Ensure the username index exists (re-inspect after any DDL above).
        if "idx_conversations_username" not in _index_names(
            sa.inspect(bind), "conversations"
        ):
            op.create_index(
                "idx_conversations_username", "conversations", ["username"]
            )

    # ---- students: converge email -> username as the primary key ----
    if "students" in tables:
        cols = _cols(insp, "students")
        if "email" in cols and "username" not in cols:
            # email was the NOT NULL primary key; renaming carries the PK over.
            with op.batch_alter_table("students", schema=None) as batch_op:
                batch_op.alter_column("email", new_column_name="username")
        elif "email" in cols and "username" in cols:
            op.execute("UPDATE students SET username = email WHERE username IS NULL")
            if is_postgres:
                # Move the primary key onto username, then drop the dead column.
                op.execute("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_pkey")
                op.execute("ALTER TABLE students ALTER COLUMN username SET NOT NULL")
                op.execute("ALTER TABLE students ADD PRIMARY KEY (username)")
                op.execute("ALTER TABLE students DROP COLUMN email")
            else:
                # SQLite: batch rebuilds the table; declare username as the new PK.
                with op.batch_alter_table("students", schema=None) as batch_op:
                    batch_op.alter_column(
                        "username", existing_type=sa.Text(), nullable=False
                    )
                    batch_op.drop_column("email")

    # ---- messages: ensure the reasoning column exists ----
    if "messages" in tables and "pedagogical_reasoning" not in _cols(insp, "messages"):
        op.add_column(
            "messages", sa.Column("pedagogical_reasoning", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    # Reconciliation only ever converges the schema forward toward the models;
    # there is no meaningful, safe inverse, so downgrade is a deliberate no-op.
    pass
