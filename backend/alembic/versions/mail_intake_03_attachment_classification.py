"""Email intake: what each attachment is (statement type, family, confidence)

Written by services/mail/classify.py when mail is stored, and for mail stored before this
revision on the next check. Hand-written, like every revision in this repo.

Revision ID: mail_intake_03
Revises: mail_intake_02
Create Date: 2026-10-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'mail_intake_03'
down_revision: Union[str, None] = 'mail_intake_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('mail_attachments', sa.Column('doc_kind', sa.String(20), nullable=True))
    op.add_column('mail_attachments', sa.Column('doc_type', sa.String(40), nullable=True))
    op.add_column('mail_attachments', sa.Column('doc_family', sa.String(20), nullable=True))
    op.add_column('mail_attachments', sa.Column('doc_label', sa.String(80), nullable=True))
    op.add_column('mail_attachments', sa.Column('doc_confidence', sa.Float(), nullable=True))
    op.add_column('mail_attachments', sa.Column('doc_meta', postgresql.JSONB(), nullable=True))
    op.add_column('mail_attachments', sa.Column('classified_at', sa.DateTime(), nullable=True))
    op.create_index('ix_mail_attachments_doc', 'mail_attachments', ['message_id', 'doc_kind'])


def downgrade() -> None:
    op.drop_index('ix_mail_attachments_doc', table_name='mail_attachments')
    for col in ('classified_at', 'doc_meta', 'doc_confidence', 'doc_label', 'doc_family', 'doc_type', 'doc_kind'):
        op.drop_column('mail_attachments', col)
