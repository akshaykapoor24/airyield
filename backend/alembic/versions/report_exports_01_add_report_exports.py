"""Workspace → Report download: report_exports job table + two BSP lookup indexes

  report_exports   One generated workbook per row: request params, resolved selection,
                   progress, fenced attempt counter, stored-file locator and expiry.
                   See app/models/report_export.py for why each field exists.

  ix_bsp_rows_owner_document  (tenant_id, created_by_id, document_number)
  ix_bsp_rows_owner_rtdn      (tenant_id, created_by_id, rtdn)
                   The report's owner lookup ("is this TGQ ticket / memo in ANOTHER of the
                   user's BSP uploads?") probes document_number and rtdn, and neither column
                   is indexed today, so every probe batch would scan the user's BSP rows.

THE TWO BSP INDEXES ARE BUILT CONCURRENTLY. bsp_statement_rows is the largest table in the
schema and a plain CREATE INDEX holds a SHARE lock that blocks every BSP upload and commission
run for the whole build. CREATE INDEX CONCURRENTLY cannot run inside a transaction, hence the
autocommit block — the report_exports DDL above it is committed first, on purpose.

A concurrent build that fails (a deadlock, a cancelled deploy) leaves an INVALID index behind
under the real name. IF NOT EXISTS would then happily skip it forever and the planner would
never use it, so an invalid leftover is dropped and rebuilt rather than trusted.

Hand-written: autogenerate on this repo proposes ~240 unrelated drops (see memory notes).

Revision ID: report_exports_01
Revises: lcc_pax_01
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'report_exports_01'
down_revision: Union[str, None] = 'lcc_pax_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUS_CHECK = "status IN ('queued', 'processing', 'completed', 'failed', 'expired', 'deleted')"

_BSP_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ('ix_bsp_rows_owner_document', ['tenant_id', 'created_by_id', 'document_number']),
    ('ix_bsp_rows_owner_rtdn', ['tenant_id', 'created_by_id', 'rtdn']),
)


def _index_is_valid(name: str) -> bool | None:
    """True/False for an existing index, None when there is none.

    to_regclass resolves the name through search_path, so an unrelated index of the same
    name in another schema can neither be mistaken for ours nor dropped.
    """
    return op.get_bind().execute(
        sa.text("SELECT i.indisvalid FROM pg_index i WHERE i.indexrelid = to_regclass(:name)"),
        {"name": name},
    ).scalar()


def upgrade() -> None:
    op.create_table(
        'report_exports',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('status', sa.String(length=12), server_default='queued', nullable=False),
        sa.Column('stage', sa.String(length=120), nullable=True),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('selection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('engine_version', sa.String(length=20), nullable=False),
        sa.Column('celery_task_id', sa.String(length=64), nullable=True),
        sa.Column('attempt', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('estimated_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('processed_rows', sa.Integer(), server_default='0', nullable=False),
        sa.Column('combined_rows', sa.Integer(), nullable=True),
        sa.Column('sheet_row_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('storage_key', sa.String(length=40), nullable=False),
        sa.Column('storage_bucket', sa.String(length=200), nullable=True),
        sa.Column('file_locator', sa.String(length=1000), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('stored_remotely', sa.Boolean(), nullable=True),
        sa.Column('error_code', sa.String(length=40), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(_STATUS_CHECK, name='ck_report_exports_status'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_report_exports_tenant_id', 'report_exports', ['tenant_id'])
    op.create_index('ix_report_exports_created_by_id', 'report_exports', ['created_by_id'])
    op.create_index('ix_report_exports_owner_created', 'report_exports',
                    ['tenant_id', 'created_by_id', 'created_at'])
    op.create_index('ix_report_exports_status_heartbeat', 'report_exports', ['status', 'heartbeat_at'])
    op.create_index('ix_report_exports_status_expires', 'report_exports', ['status', 'expires_at'])

    offline = op.get_context().as_sql
    with op.get_context().autocommit_block():
        for name, columns in _BSP_INDEXES:
            # --sql (offline) has no connection to ask; it emits the create only.
            if not offline and _index_is_valid(name) is False:
                op.drop_index(name, table_name='bsp_statement_rows',
                              postgresql_concurrently=True, if_exists=True)
            op.create_index(name, 'bsp_statement_rows', columns,
                            postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _columns in reversed(_BSP_INDEXES):
            op.drop_index(name, table_name='bsp_statement_rows',
                          postgresql_concurrently=True, if_exists=True)

    op.drop_index('ix_report_exports_status_expires', table_name='report_exports')
    op.drop_index('ix_report_exports_status_heartbeat', table_name='report_exports')
    op.drop_index('ix_report_exports_owner_created', table_name='report_exports')
    op.drop_index('ix_report_exports_created_by_id', table_name='report_exports')
    op.drop_index('ix_report_exports_tenant_id', table_name='report_exports')
    op.drop_table('report_exports')
