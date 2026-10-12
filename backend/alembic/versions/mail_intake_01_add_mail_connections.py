"""Email intake: mail_connections (connected mailboxes)

One row per mailbox a user connects — Gmail, Microsoft 365, IMAP or a forwarding address.
See app/models/mail.py for why each column exists, and architecture/08-data-model.md for
the tables that follow it (messages, attachments, drafts …), which arrive in later revisions.

Hand-written: autogenerate on this repo proposes hundreds of unrelated drops.

Revision ID: mail_intake_01
Revises: payment_module_02
Create Date: 2026-10-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'mail_intake_01'
down_revision: Union[str, None] = 'payment_module_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'mail_connections',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('visibility', sa.String(10), nullable=False, server_default='personal'),
        sa.Column('provider', sa.String(10), nullable=False),
        sa.Column('email_address', sa.String(320), nullable=False),
        sa.Column('provider_account_id', sa.String(255), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending_auth'),
        sa.Column('status_reason', sa.String(500), nullable=True),
        sa.Column('screening_mode', sa.String(10), nullable=False, server_default='strict'),
        sa.Column('credentials_enc', sa.LargeBinary(), nullable=True),
        sa.Column('credentials_dek_enc', sa.LargeBinary(), nullable=True),
        sa.Column('credentials_key_ref', sa.String(255), nullable=True),
        sa.Column('granted_scopes', sa.Text(), nullable=True),
        sa.Column('imap_host', sa.String(255), nullable=True),
        sa.Column('imap_port', sa.Integer(), nullable=True),
        sa.Column('imap_username', sa.String(320), nullable=True),
        sa.Column('imap_security', sa.String(10), nullable=True),
        sa.Column('relay_token', sa.String(40), nullable=True),
        sa.Column('settings', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('sync_cursor', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('watch_ref', sa.String(255), nullable=True),
        sa.Column('watch_secret_hash', sa.String(128), nullable=True),
        sa.Column('watch_expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.Column('last_tested_at', sa.DateTime(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('backfill_state', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('tenant_id', 'provider', 'email_address', name='uq_mail_connections_mailbox'),
        sa.UniqueConstraint('relay_token', name='uq_mail_connections_relay_token'),
        sa.CheckConstraint("provider IN ('gmail', 'microsoft', 'imap', 'relay')", name='ck_mail_connections_provider'),
        sa.CheckConstraint(
            "status IN ('pending_auth', 'active', 'needs_reauth', 'paused', 'error', 'disconnected')",
            name='ck_mail_connections_status',
        ),
        sa.CheckConstraint("screening_mode IN ('strict', 'extended')", name='ck_mail_connections_mode'),
        sa.CheckConstraint("visibility IN ('personal', 'workspace')", name='ck_mail_connections_visibility'),
    )
    op.create_index('ix_mail_connections_tenant_id', 'mail_connections', ['tenant_id'])
    op.create_index('ix_mail_connections_owner_user_id', 'mail_connections', ['owner_user_id'])
    op.create_index('ix_mail_connections_due', 'mail_connections', ['status', 'provider', 'last_synced_at'])


def downgrade() -> None:
    op.drop_index('ix_mail_connections_due', table_name='mail_connections')
    op.drop_index('ix_mail_connections_owner_user_id', table_name='mail_connections')
    op.drop_index('ix_mail_connections_tenant_id', table_name='mail_connections')
    op.drop_table('mail_connections')
