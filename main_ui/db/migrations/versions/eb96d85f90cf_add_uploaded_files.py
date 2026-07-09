"""add uploaded_files

Adds the ``uploaded_files`` table for non-image student attachments (csv, tsv,
xlsx, pdf, docx, txt). Mirrors ``uploaded_images``: raw bytes stored in-DB
(Railway's filesystem is ephemeral) plus the text extracted at upload time
(``extracted_text``), which is what actually reaches the tutor and is
re-injected into history every turn.

Revision ID: eb96d85f90cf
Revises: d4e5f6a7b8c9
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb96d85f90cf'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'uploaded_files',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('uploaded_files', schema=None) as batch_op:
        batch_op.create_index('idx_uploaded_files_message', ['message_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('uploaded_files', schema=None) as batch_op:
        batch_op.drop_index('idx_uploaded_files_message')
    op.drop_table('uploaded_files')
