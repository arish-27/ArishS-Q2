"""add_session_error_tracking

Revision ID: e4f6a8b0c234
Revises: d3e5f7a9b123
Create Date: 2026-11-27 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4f6a8b0c234'
down_revision: Union[str, Sequence[str], None] = 'd3e5f7a9b123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('call_sessions', sa.Column('error_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('call_sessions', sa.Column('last_error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('call_sessions', 'last_error')
    op.drop_column('call_sessions', 'error_count')
