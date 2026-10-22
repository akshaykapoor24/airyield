"""Third Party GDS: keep the lines an upload leaves out as already sent, and tally them

* third_party_statements.total_entries / duplicate_entries / new_entries — each upload's
  entries in the file, those left out as sent before, and those saved. Backfilled: new =
  the entry lines it holds; duplicate = statement_batch_controls.duplicate_rows (Third
  Party GDS only — LCC and API are never screened); total = new + duplicate.
* third_party_gds_duplicates — one row per line left out, under its own statement,
  pointing at the saved line it repeats. Uploads made BEFORE this migration kept only
  the count, so they show their duplicates as a number with no lines behind it.
* third_party_gds.near_match_id — a saved line that looks like an earlier one (same
  document, event and passenger; different date or amount). Backfilled from dedup_group
  against each consolidator's earlier uploads, the way services/tp_gds_dedup.screen
  matches at upload.

Revision ID: tp_gds_duplicates_01
Revises: tenant_airline_02
Create Date: 2026-10-16 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'tp_gds_duplicates_01'
down_revision: Union[str, None] = 'tenant_airline_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_H = 'third_party_statements'
_G = 'third_party_gds'
_D = 'third_party_gds_duplicates'

# line table → its slug, and whether it carries balance lines (which are not entries)
_LINE_TABLES = {
    'third_party_gds': ('tp-gds', 'row_kind IS NULL'),
    'third_party_lcc': ('tp-lcc', 'TRUE'),
    'third_party_api': ('tp-api', 'TRUE'),
}


def upgrade() -> None:
    op.add_column(_H, sa.Column('total_entries', sa.Integer(), nullable=False, server_default='0'))
    op.add_column(_H, sa.Column('duplicate_entries', sa.Integer(), nullable=False, server_default='0'))
    op.add_column(_H, sa.Column('new_entries', sa.Integer(), nullable=False, server_default='0'))

    conn = op.get_bind()
    for table, (slug, is_entry) in _LINE_TABLES.items():
        conn.execute(sa.text(
            f"UPDATE {_H} AS h SET new_entries = c.n "
            f"FROM (SELECT batch_id, COUNT(*) FILTER (WHERE {is_entry}) AS n "
            f"      FROM {table} GROUP BY batch_id) AS c "
            f"WHERE c.batch_id = h.batch_id AND h.slug = :slug"
        ), {"slug": slug})
    conn.execute(sa.text(
        f"UPDATE {_H} AS h SET duplicate_entries = COALESCE(c.duplicate_rows, 0) "
        f"FROM statement_batch_controls AS c "
        f"WHERE c.slug = 'tp-gds' AND c.batch_id = h.batch_id AND h.slug = 'tp-gds'"
    ))
    conn.execute(sa.text(f"UPDATE {_H} SET total_entries = new_entries + duplicate_entries"))

    op.add_column(_G, sa.Column('near_match_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_third_party_gds_near_match', _G, _G,
                          ['near_match_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_third_party_gds_near_match_id', _G, ['near_match_id'])
    # The earliest line of an earlier upload — same user, same consolidator (by supplier or
    # by agency, as `_vendor` matches) — sharing the line's dedup_group.
    conn.execute(sa.text(
        f"UPDATE {_G} AS g SET near_match_id = m.earlier_id "
        f"FROM ("
        f"  SELECT DISTINCT ON (t.id) t.id AS line_id, e.id AS earlier_id "
        f"  FROM {_G} AS t "
        f"  JOIN {_H} AS th ON th.batch_id = t.batch_id "
        f"  JOIN statement_batch_suppliers AS tl "
        f"    ON tl.batch_id = t.batch_id AND tl.slug = 'tp-gds' AND tl.tenant_id = t.tenant_id "
        f"  JOIN {_G} AS e "
        f"    ON e.tenant_id = t.tenant_id AND e.created_by_id = t.created_by_id "
        f"   AND e.dedup_group = t.dedup_group AND e.batch_id <> t.batch_id "
        f"  JOIN {_H} AS eh ON eh.batch_id = e.batch_id AND eh.uploaded_at < th.uploaded_at "
        f"  JOIN statement_batch_suppliers AS el "
        f"    ON el.batch_id = e.batch_id AND el.slug = 'tp-gds' AND el.tenant_id = e.tenant_id "
        f"   AND (el.supplier_id = tl.supplier_id OR el.agency_id = tl.agency_id) "
        f"  WHERE t.dedup_group IS NOT NULL "
        f"  ORDER BY t.id, eh.uploaded_at, e.id"
        f") AS m "
        f"WHERE g.id = m.line_id"
    ))

    op.create_table(
        _D,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('batch_id', sa.String(100),
                  sa.ForeignKey('third_party_statements.batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_id', sa.Integer(),
                  sa.ForeignKey('third_party_gds.id', ondelete='SET NULL'), nullable=True),
        sa.Column('original_batch_id', sa.String(100),
                  sa.ForeignKey('third_party_statements.batch_id', ondelete='SET NULL'), nullable=True),
        sa.Column('dedup_key', sa.String(64), nullable=True),
        sa.Column('dedup_group', sa.String(64), nullable=True),
        sa.Column('data', JSONB(), nullable=False),
    )
    for col in ('tenant_id', 'created_by_id', 'batch_id', 'original_id'):
        op.create_index(f'ix_{_D}_{col}', _D, [col])


def downgrade() -> None:
    for col in ('original_id', 'batch_id', 'created_by_id', 'tenant_id'):
        op.drop_index(f'ix_{_D}_{col}', table_name=_D)
    op.drop_table(_D)
    op.drop_index('ix_third_party_gds_near_match_id', table_name=_G)
    op.drop_constraint('fk_third_party_gds_near_match', _G, type_='foreignkey')
    op.drop_column(_G, 'near_match_id')
    for col in ('new_entries', 'duplicate_entries', 'total_entries'):
        op.drop_column(_H, col)
