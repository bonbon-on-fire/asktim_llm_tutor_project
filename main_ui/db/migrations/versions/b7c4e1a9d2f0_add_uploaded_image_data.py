"""add data column to uploaded_images

Stores raw image bytes in-DB (BYTEA on Postgres) so student-uploaded images
survive Railway redeploys (the filesystem is ephemeral). The table was created
empty as a Step 10 placeholder and has never held rows, so adding a NOT NULL
column without a server default is safe.

Revision ID: b7c4e1a9d2f0
Revises: e63318c3bfed
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4e1a9d2f0'
down_revision: Union[str, Sequence[str], None] = 'e63318c3bfed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('uploaded_images', schema=None) as batch_op:
        batch_op.add_column(sa.Column('data', sa.LargeBinary(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('uploaded_images', schema=None) as batch_op:
        batch_op.drop_column('data')
