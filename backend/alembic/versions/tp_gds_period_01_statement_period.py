"""Third Party GDS: the statement period, and the cross-upload duplicate screen removed

* third_party_statements.period_from / period_to — the days a statement covers, as the
  uploader declared them (services/statement_period.py). Both or neither, never backwards
  (ck_third_party_statements_period). third_party_gds.period_from / period_to — the same,
  copied onto each line, indexed with the tenant.
  Backfilled best-effort for Third Party GDS: from the file name, else from the span of the
  Week values on the upload's lines ("01-07TH AUG 26"), the year read relative to when it
  was uploaded. Left NULL when neither says — such an upload shows no period and is never
  compared with.
* Removed: the screen that compared every upload with ALL of a consolidator's earlier ones
  gave way to the period rule (services/tp_gds_reupload.py) — third_party_gds.near_match_id
  and dedup_group with their indexes, the dedup_key index (lines are now read by statement,
  not looked up by key) and the third_party_gds_duplicates table. dedup_key itself stays: it
  is the line's key, and the keys already stored keep matching.

Revision ID: tp_gds_period_01
Revises: tp_gds_duplicates_01
Create Date: 2026-10-17 00:00:00.000000
"""
import re
from datetime import date, datetime, timedelta
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'tp_gds_period_01'
down_revision: Union[str, None] = 'tp_gds_duplicates_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_H = 'third_party_statements'
_G = 'third_party_gds'
_D = 'third_party_gds_duplicates'
_PERIOD_CHECK = ("(period_from IS NULL AND period_to IS NULL) OR "
                 "(period_from IS NOT NULL AND period_to IS NOT NULL AND period_from <= period_to)")


# ── the period reader, frozen as services/statement_period.py reads one today ──────────
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
        r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])")
_SEP = r"\s*(?:-|–|—|~|_|\bto\b|\btill\b|\buntil\b|\bupto\b|\bup\s+to\b)\s*"
_ORD = r"(?:st|nd|rd|th)?"
_DAY = r"(?<!\d)(\d{1,2})" + _ORD
_YEAR = r"(?:[\s\-./,'’]*(\d{4}|\d{2})(?!\d))?"
_GLUE = r"[\s\-./]*"
_ISO = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)" + _SEP + r"(\d{4})-(\d{2})-(\d{2})(?!\d)", re.I)
_DMY_NUMERIC = re.compile(
    r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)" + _SEP
    + r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)", re.I)
_BOTH_MONTHS = re.compile(_DAY + _GLUE + _MON + _YEAR + _SEP + _DAY + _GLUE + _MON + _YEAR, re.I)
_SAME_MONTH = re.compile(_DAY + rf"(?:{_SEP}|\s+)" + r"(\d{1,2})" + _ORD + _GLUE + _MON + _YEAR, re.I)
_MONTH_FIRST = re.compile(r"(?<![a-z])" + _MON + _GLUE + _DAY + _SEP + r"(\d{1,2})" + _ORD + _YEAR, re.I)
_EXTENSION = re.compile(r"\.(xlsx|xlsm|xlsb|xls|csv|tsv|txt|pdf|zip)$", re.I)
_COPY_SUFFIX = re.compile(r"(\s*\(\d+\)|\s*-\s*copy(\s*\(\d+\))?)+$", re.I)


def _year(y):
    if not y:
        return None
    n = int(y)
    return 2000 + n if len(y) == 2 else n


def _period(d1, m1, y1, d2, m2, y2, today):
    try:
        d1, m1, d2, m2 = int(d1), int(m1), int(d2), int(m2)
        wraps = (m1, d1) > (m2, d2)
        if y2 is None and y1 is not None:
            y2 = y1 + 1 if wraps else y1
        if y2 is None:
            y2 = today.year
            if date(y2, m2, d2) > today + timedelta(days=31):
                y2 -= 1
        if y1 is None:
            y1 = y2 - 1 if wraps else y2
        start, end = date(y1, m1, d1), date(y2, m2, d2)
    except (ValueError, TypeError):
        return None
    if start > end or (end - start).days > 366:
        return None
    return start, end


def find_period(text, today):
    if not text:
        return None
    for m in _ISO.finditer(text):
        y1, m1, d1, y2, m2, d2 = m.groups()
        if (p := _period(d1, m1, int(y1), d2, m2, int(y2), today)):
            return p
    for m in _DMY_NUMERIC.finditer(text):
        d1, m1, y1, d2, m2, y2 = m.groups()
        if (p := _period(d1, m1, _year(y1), d2, m2, _year(y2), today)):
            return p
    for m in _BOTH_MONTHS.finditer(text):
        d1, mon1, y1, d2, mon2, y2 = m.groups()
        if (p := _period(d1, _MONTHS[mon1[:3].lower()], _year(y1), d2, _MONTHS[mon2[:3].lower()], _year(y2), today)):
            return p
    for m in _SAME_MONTH.finditer(text):
        d1, d2, mon, y = m.groups()
        if (p := _period(d1, _MONTHS[mon[:3].lower()], _year(y), d2, _MONTHS[mon[:3].lower()], _year(y), today)):
            return p
    for m in _MONTH_FIRST.finditer(text):
        mon, d1, d2, y = m.groups()
        if (p := _period(d1, _MONTHS[mon[:3].lower()], _year(y), d2, _MONTHS[mon[:3].lower()], _year(y), today)):
            return p
    return None


def from_file_name(name, today):
    if not name:
        return None
    stem = _EXTENSION.sub("", name.replace("\\", "/").rsplit("/", 1)[-1].strip())
    return find_period(_COPY_SUFFIX.sub("", stem), today)


def _backfill(conn) -> None:
    """Each Third Party GDS upload's period: its file name's, else the span of its lines'
    Week values. Then copied onto its lines."""
    weeks: dict[str, list[str]] = {}
    for batch_id, week in conn.execute(sa.text(
        f"SELECT DISTINCT batch_id, week FROM {_G} WHERE week IS NOT NULL AND row_kind IS NULL"
    )):
        weeks.setdefault(batch_id, []).append(week)
    found = []
    for batch_id, source_file, uploaded_at in conn.execute(sa.text(
        f"SELECT batch_id, source_file, uploaded_at FROM {_H} "
        f"WHERE slug = 'tp-gds' AND period_from IS NULL"
    )):
        today = (uploaded_at or datetime.utcnow()).date()
        period = from_file_name(source_file, today)
        if period is None:
            spans = [p for w in weeks.get(batch_id, []) if (p := find_period(w, today))]
            if spans:
                start, end = min(p[0] for p in spans), max(p[1] for p in spans)
                if (end - start).days <= 366:
                    period = start, end
        if period is not None:
            found.append({"b": batch_id, "f": period[0], "t": period[1]})
    if not found:
        return
    conn.execute(sa.text(f"UPDATE {_H} SET period_from = :f, period_to = :t WHERE batch_id = :b"), found)
    conn.execute(sa.text(
        f"UPDATE {_G} AS g SET period_from = h.period_from, period_to = h.period_to "
        f"FROM {_H} AS h WHERE h.batch_id = g.batch_id AND h.period_from IS NOT NULL"
    ))


def upgrade() -> None:
    op.add_column(_H, sa.Column('period_from', sa.Date(), nullable=True))
    op.add_column(_H, sa.Column('period_to', sa.Date(), nullable=True))
    op.create_check_constraint('ck_third_party_statements_period', _H, _PERIOD_CHECK)
    op.add_column(_G, sa.Column('period_from', sa.Date(), nullable=True))
    op.add_column(_G, sa.Column('period_to', sa.Date(), nullable=True))
    op.create_index('ix_third_party_gds_period', _G, ['tenant_id', 'period_from', 'period_to'])

    _backfill(op.get_bind())

    # IF EXISTS throughout: a database built from the models (create_tables.py) names the
    # near-match foreign key third_party_gds_near_match_id_fkey rather than as
    # tp_gds_duplicates_01 created it. Dropping a column drops its foreign key and indexes.
    op.execute("DROP INDEX IF EXISTS ix_third_party_gds_near_match_id")
    op.execute(f"ALTER TABLE {_G} DROP CONSTRAINT IF EXISTS fk_third_party_gds_near_match")
    op.execute(f"ALTER TABLE {_G} DROP COLUMN IF EXISTS near_match_id")
    op.execute("DROP INDEX IF EXISTS ix_third_party_gds_dedup_group")
    op.execute(f"ALTER TABLE {_G} DROP COLUMN IF EXISTS dedup_group")
    op.execute("DROP INDEX IF EXISTS ix_third_party_gds_dedup_key")
    op.execute(f"DROP TABLE IF EXISTS {_D}")


def downgrade() -> None:
    # Recreated empty, under the exact names the earlier downgrades drop them by.
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
    op.add_column(_G, sa.Column('dedup_group', sa.String(64), nullable=True))
    op.create_index('ix_third_party_gds_dedup_key', _G, ['tenant_id', 'created_by_id', 'dedup_key'])
    op.create_index('ix_third_party_gds_dedup_group', _G, ['tenant_id', 'created_by_id', 'dedup_group'])
    op.add_column(_G, sa.Column('near_match_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_third_party_gds_near_match', _G, _G,
                          ['near_match_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_third_party_gds_near_match_id', _G, ['near_match_id'])

    op.drop_index('ix_third_party_gds_period', table_name=_G)
    op.drop_column(_G, 'period_to')
    op.drop_column(_G, 'period_from')
    op.drop_constraint('ck_third_party_statements_period', _H, type_='check')
    op.drop_column(_H, 'period_to')
    op.drop_column(_H, 'period_from')
