"""Email intake: mail_messages + mail_attachments (mail received from onboarded senders)

Only mail whose sender is in Agency / Corporate / Employee Master becomes a row — see
app/models/mail.py. Hand-written, like every revision in this repo.

Revision ID: mail_intake_02
Revises: mail_intake_01
Create Date: 2026-10-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'mail_intake_02'
down_revision: Union[str, None] = 'mail_intake_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mail_messages',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('connection_id', sa.Integer(), sa.ForeignKey('mail_connections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider_message_id', sa.String(255), nullable=False),
        sa.Column('folder', sa.String(255), nullable=True),
        sa.Column('internet_message_id', sa.String(998), nullable=True),
        sa.Column('in_reply_to', sa.String(998), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('from_address', sa.String(320), nullable=False),
        sa.Column('from_name', sa.String(320), nullable=True),
        sa.Column('matched_address', sa.String(320), nullable=False),
        sa.Column('to_addresses', postgresql.JSONB(), nullable=True),
        sa.Column('cc_addresses', postgresql.JSONB(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('parties', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('party_type', sa.String(12), nullable=True),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('snippet', sa.String(300), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=True),
        sa.Column('raw_locator', sa.String(1024), nullable=True),
        sa.Column('raw_sha256', sa.String(64), nullable=True),
        sa.Column('attachment_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.String(40), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('connection_id', 'provider_message_id', name='uq_mail_messages_provider'),
    )
    op.create_index('ix_mail_messages_connection_id', 'mail_messages', ['connection_id'])
    op.create_index('ix_mail_messages_imid', 'mail_messages', ['tenant_id', 'internet_message_id'])
    op.create_index('ix_mail_messages_inbox', 'mail_messages', ['tenant_id', 'owner_user_id', 'received_at'])

    op.create_table(
        'mail_attachments',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message_id', sa.BigInteger(), sa.ForeignKey('mail_messages.id', ondelete='CASCADE'), nullable=False),
        sa.Column('part_index', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('locator', sa.String(1024), nullable=False),
        sa.Column('is_inline', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('content_id', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('message_id', 'part_index', name='uq_mail_attachments_part'),
    )
    op.create_index('ix_mail_attachments_message_id', 'mail_attachments', ['message_id'])
    op.create_index('ix_mail_attachments_sha', 'mail_attachments', ['tenant_id', 'sha256'])


def downgrade() -> None:
    op.drop_index('ix_mail_attachments_sha', table_name='mail_attachments')
    op.drop_index('ix_mail_attachments_message_id', table_name='mail_attachments')
    op.drop_table('mail_attachments')
    op.drop_index('ix_mail_messages_inbox', table_name='mail_messages')
    op.drop_index('ix_mail_messages_imid', table_name='mail_messages')
    op.drop_index('ix_mail_messages_connection_id', table_name='mail_messages')
    op.drop_table('mail_messages')
