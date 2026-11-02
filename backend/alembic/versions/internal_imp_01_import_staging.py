"""Internal Statement: background upload — import jobs and their staging rows

A lakh-line sales report is uploaded once, read into staging rows by a Celery worker, reviewed
page by page on the server and saved by the worker (models/internal_ticket_import.py,
services/internal_import.py):

* internal_ticket_imports — one per uploaded file: where it is stored, how it is read, the
  worker's status and progress, and what Save was asked and did.
* internal_ticket_import_rows — the file's lines as mapped, keyed (import, row number).
* internal_uploaded_tickets.booking_class widened to 100 characters: Yatra's sales report
  writes one class per segment ("J K L M N O P Q R T U V"), which 20 could not hold — and a
  lakh-line file with 195 such lines could not be saved at all. Internal Statement's table
  only; models/internal_ticket.py says why the two tables differ in this one column.

Revision ID: internal_imp_01
Revises: pay_mod_01
Create Date: 2026-10-30 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'internal_imp_01'
down_revision: Union[str, None] = 'pay_mod_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'internal_ticket_imports',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('file_name', sa.String(500), nullable=False),
        sa.Column('file_locator', sa.String(1000), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sheet_name', sa.String(255), nullable=True),
        sa.Column('header_row', sa.Integer(), nullable=True),
        sa.Column('column_map', postgresql.JSONB(), nullable=True),
        sa.Column('date_formats', postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='uploaded'),
        sa.Column('phase', sa.String(16), nullable=True),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('processed_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('read_info', postgresql.JSONB(), nullable=True),
        sa.Column('save_request', postgresql.JSONB(), nullable=True),
        sa.Column('result', postgresql.JSONB(), nullable=True),
        sa.Column('batch_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_internal_ticket_imports_tenant_id', 'internal_ticket_imports', ['tenant_id'])
    op.create_index('ix_internal_ticket_imports_created_by_id', 'internal_ticket_imports', ['created_by_id'])

    op.create_table(
        'internal_ticket_import_rows',
        sa.Column('import_id', sa.String(36),
                  sa.ForeignKey('internal_ticket_imports.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('row_no', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('data', postgresql.JSONB(), nullable=False),
        sa.Column('search_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('dedup_key', sa.String(64), nullable=True),
        sa.Column('duplicate_of', sa.String(100), nullable=True),
        sa.Column('bad_date', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('too_long', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('supplier_group', sa.String(400), nullable=True),
        sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('edited', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.alter_column('internal_uploaded_tickets', 'booking_class',
                    type_=sa.String(100), existing_type=sa.String(20), existing_nullable=True)


def downgrade() -> None:
    op.alter_column('internal_uploaded_tickets', 'booking_class',
                    type_=sa.String(20), existing_type=sa.String(100), existing_nullable=True,
                    postgresql_using='left(booking_class, 20)')
    op.drop_table('internal_ticket_import_rows')
    op.drop_index('ix_internal_ticket_imports_created_by_id', table_name='internal_ticket_imports')
    op.drop_index('ix_internal_ticket_imports_tenant_id', table_name='internal_ticket_imports')
    op.drop_table('internal_ticket_imports')
