"""Email intake: mail_messages.processed — what has been imported from each email

Revision ID: mail_intake_04
Revises: mail_intake_03
Create Date: 2026-10-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'mail_intake_04'
down_revision: Union[str, None] = 'mail_intake_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mail_messages', sa.Column('processed', postgresql.JSONB(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('mail_messages', 'processed')
