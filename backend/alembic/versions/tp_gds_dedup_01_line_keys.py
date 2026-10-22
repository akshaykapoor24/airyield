"""Third Party GDS: recognise lines a consolidator sends twice

* third_party_gds.dedup_key / dedup_group — which entry a line is, exactly and less its
  date and amounts (services/tp_gds_dedup.py), indexed for the lookup an upload makes.
  Backfilled for every existing line from its columns.
* statement_batch_controls.duplicate_rows / duplicate_net / duplicate_of — the entries of
  a file left out at upload as already sent, their net and the upload they were in, so
  the completeness checks still add the file up.

Revision ID: tp_gds_dedup_01
Revises: tp_gds_columns_01
Create Date: 2026-10-14 00:00:00.000000
"""
import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_dedup_01'
down_revision: Union[str, None] = 'tp_gds_columns_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'third_party_gds'
_C = 'statement_batch_controls'


# ── the line keys, frozen as services/tp_gds_dedup.entry_keys computes them today ──────
def _text(value) -> str:
    return " ".join(str(value or "").upper().split())


def _document(d: dict):
    digits = re.sub(r"\D", "", str(d.get("ticket_number") or ""))
    if digits:
        return "T" + (digits[-10:] if len(digits) > 10 else digits)
    for key in ("pnr", "airline_pnr", "gds_pnr"):
        pnr = re.sub(r"[^A-Z0-9]", "", str(d.get(key) or "").upper())
        if pnr:
            return "P" + pnr
    return None


def _amount(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except InvalidOperation:
        return _text(value)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


_NOT_IDENTITY = frozenset({"week", "invoice_number", "username", "__edited__", "unparsed_fields",
                           "airline_id", "airline_master_name", "airline_conflict"})


def entry_keys(d: dict):
    if d.get("row_kind"):
        return None, None
    doc = _document(d)
    if doc is None:
        body = "|".join(f"{k}={_text(v)}" for k, v in sorted(d.items())
                        if k not in _NOT_IDENTITY and v not in (None, ""))
        return _hash("X|" + body), None
    name = d.get("passenger_name") or " ".join(p for p in (d.get("first_name"), d.get("last_name")) if p)
    near = "|".join((doc, f"{_text(d.get('ticket_status'))}/{_text(d.get('transaction_type'))}", _text(name)))
    exact = "|".join((near, str(d.get("issue_date") or ""),
                      _amount(d.get("base_fare")), _amount(d.get("net_amount"))))
    return _hash(exact), _hash(near)


# A line's `data` as models/typed_statement.TypedData rebuilds it — the shape the keys are
# computed from at upload: every field column, renamed where its key differs, as a string.
_NOT_DATA = frozenset({"id", "tenant_id", "created_by_id", "batch_id", "source_file", "file_url",
                       "uploaded_at", "source_format", "dedup_key", "dedup_group"})
_RENAMED = {"total_tax": "taxes", "edited_fields": "__edited__"}


def _as_data(row) -> dict:
    out = {}
    for column, value in row.items():
        if column in _NOT_DATA or value is None:
            continue
        if isinstance(value, Decimal):
            value = format(value, "f")
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        out[_RENAMED.get(column, column)] = str(value)
    return out


def upgrade() -> None:
    op.add_column(_T, sa.Column('dedup_key', sa.String(64), nullable=True))
    op.add_column(_T, sa.Column('dedup_group', sa.String(64), nullable=True))
    op.create_index('ix_third_party_gds_dedup_key', _T, ['tenant_id', 'created_by_id', 'dedup_key'])
    op.create_index('ix_third_party_gds_dedup_group', _T, ['tenant_id', 'created_by_id', 'dedup_group'])

    op.add_column(_C, sa.Column('duplicate_rows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column(_C, sa.Column('duplicate_net', sa.Numeric(20, 4), nullable=True))
    op.add_column(_C, sa.Column('duplicate_of', sa.String(100), nullable=True))

    conn = op.get_bind()
    update = sa.text(f"UPDATE {_T} SET dedup_key = :k, dedup_group = :g WHERE id = :id")
    batch = []
    for row in conn.execute(sa.text(f"SELECT * FROM {_T} ORDER BY id")).mappings():
        k, g = entry_keys(_as_data(row))
        if k is not None:
            batch.append({"id": row["id"], "k": k, "g": g})
        if len(batch) >= 500:
            conn.execute(update, batch)
            batch = []
    if batch:
        conn.execute(update, batch)


def downgrade() -> None:
    op.drop_column(_C, 'duplicate_of')
    op.drop_column(_C, 'duplicate_net')
    op.drop_column(_C, 'duplicate_rows')
    op.drop_index('ix_third_party_gds_dedup_group', table_name=_T)
    op.drop_index('ix_third_party_gds_dedup_key', table_name=_T)
    op.drop_column(_T, 'dedup_group')
    op.drop_column(_T, 'dedup_key')
