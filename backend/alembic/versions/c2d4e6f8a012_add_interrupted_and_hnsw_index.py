"""add_interrupted_and_hnsw_index

Revision ID: c2d4e6f8a012
Revises: af6963a6310d
Create Date: 2026-11-26 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d4e6f8a012'
down_revision: Union[str, Sequence[str], None] = 'af6963a6310d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with conversation_messages.interrupted and pgvector HNSW cosine index."""
    op.add_column(
        'conversation_messages',
        sa.Column('interrupted', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops);"
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw;")
    op.drop_column('conversation_messages', 'interrupted')
