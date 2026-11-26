"""add_tool_webhook_fields

Revision ID: d3e5f7a9b123
Revises: c2d4e6f8a012
Create Date: 2026-11-26 14:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e5f7a9b123'
down_revision: Union[str, Sequence[str], None] = 'c2d4e6f8a012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tools', sa.Column('webhook_method', sa.String(length=10), nullable=True, server_default='POST'))
    op.add_column('tools', sa.Column('webhook_headers', sa.Text(), nullable=True, server_default='{}'))
    op.add_column('tools', sa.Column('webhook_body_template', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tools', 'webhook_body_template')
    op.drop_column('tools', 'webhook_headers')
    op.drop_column('tools', 'webhook_method')
