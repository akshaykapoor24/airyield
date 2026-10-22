"""Third-party statements: a header row per upload, and the lines linked to it

* third_party_statements — one row per Third Party GDS / LCC / API upload: who uploaded it,
  the file name, the stored copy and when. Keyed by the existing batch_id uuid.
* Backfilled from the lines already in third_party_gds / third_party_lcc / third_party_api,
  one header per distinct batch_id.
* Each of those tables' batch_id becomes a foreign key to the header, ON DELETE CASCADE.

The lines keep their own source_file / file_url / uploaded_at columns for now — see
models/third_party_statement.py for why, and for what drops them.

Revision ID: tp_statements_01
Revises: vendor_internal_01
Create Date: 2026-10-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_statements_01'
down_revision: Union[str, None] = 'vendor_internal_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# line table → the slug its uploads are filed under
_LINE_TABLES = {
    'third_party_gds': 'tp-gds',
    'third_party_lcc': 'tp-lcc',
    'third_party_api': 'tp-api',
}


def upgrade() -> None:
    op.create_table(
        'third_party_statements',
        sa.Column('batch_id', sa.String(100), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('slug', sa.String(20), nullable=False),
        sa.Column('source_file', sa.String(255), nullable=True),
        sa.Column('file_url', sa.String(1000), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("slug IN ('tp-api', 'tp-gds', 'tp-lcc')", name='ck_third_party_statements_slug'),
    )
    op.create_index('ix_third_party_statements_created_by_id', 'third_party_statements', ['created_by_id'])
    op.create_index('ix_third_party_statements_list', 'third_party_statements',
                    ['tenant_id', 'created_by_id', 'slug', 'uploaded_at'])

    conn = op.get_bind()
    for table, slug in _LINE_TABLES.items():
        # A batch is one user's one upload. Lines of one batch_id under two tenants or two
        # uploaders cannot be given one header without handing some of them to the wrong
        # owner — stop and say so rather than pick one.
        mixed = conn.execute(sa.text(
            f"SELECT batch_id FROM {table} GROUP BY batch_id "
            f"HAVING COUNT(DISTINCT tenant_id) > 1 OR COUNT(DISTINCT created_by_id) > 1 LIMIT 5"
        )).scalars().all()
        if mixed:
            raise RuntimeError(
                f"{table}: these batch_ids have lines under more than one tenant or uploader, "
                f"so no single header can own them: {', '.join(mixed)}")
        # MAX(file_url): a batch whose file failed to store has NULL on every line, and
        # MAX keeps a stored copy over a NULL had the two ever been mixed.
        conn.execute(sa.text(
            f"INSERT INTO third_party_statements "
            f"  (batch_id, tenant_id, created_by_id, slug, source_file, file_url, uploaded_at) "
            f"SELECT batch_id, MIN(tenant_id), MIN(created_by_id), :slug, MAX(source_file), "
            f"       MAX(file_url), COALESCE(MIN(uploaded_at), now() AT TIME ZONE 'utc') "
            f"FROM {table} GROUP BY batch_id"
        ), {"slug": slug})
        op.create_foreign_key(
            f'fk_{table}_statement', table, 'third_party_statements',
            ['batch_id'], ['batch_id'], ondelete='CASCADE',
        )


def downgrade() -> None:
    for table in _LINE_TABLES:
        op.drop_constraint(f'fk_{table}_statement', table, type_='foreignkey')
    op.drop_index('ix_third_party_statements_list', table_name='third_party_statements')
    op.drop_index('ix_third_party_statements_created_by_id', table_name='third_party_statements')
    op.drop_table('third_party_statements')
