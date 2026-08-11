"""rename email to username

Renames the soft-identity column from ``email`` to ``username`` on the
``students`` primary key and the ``conversations.email`` column (plus its
index). The value is a free-form identifier that is never used to send mail,
so this is a pure column rename with no data transformation — existing values
carry over unchanged.

Revision ID: c1d2e3f4a5b6
Revises: b7c4e1a9d2f0
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7c4e1a9d2f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply the email-to-username rename migration."""
    # Drop the index before renaming the column (it references the old name),
    # rename inside a batch (SQLite recreates the table), then rebuild the
    # index on the new column. Keeping the index ops outside the rename batch
    # avoids the batch copy failing to see the just-renamed column.
    op.drop_index('idx_conversations_email', table_name='conversations')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('email', new_column_name='username')
    op.create_index('idx_conversations_username', 'conversations', ['username'])

    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.alter_column('email', new_column_name='username')


def downgrade() -> None:
    """Revert the email-to-username rename migration."""
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.alter_column('username', new_column_name='email')

    op.drop_index('idx_conversations_username', table_name='conversations')
    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('username', new_column_name='email')
    op.create_index('idx_conversations_email', 'conversations', ['email'])
