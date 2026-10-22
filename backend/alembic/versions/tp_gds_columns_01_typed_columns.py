"""Third Party GDS: a column per field instead of JSONB

* third_party_gds gains one typed column per field of the Third Party GDS statement (DATE
  for dates, NUMERIC for amounts, INTEGER for the pax count, TEXT otherwise) plus the
  values ingest sets on a line (balance-line kind, resolved airline, edited cells, …).
* Every existing line is copied out of `data` into those columns. A value that does not
  fit its column's type stores as NULL and its field is listed in `unparsed_fields`.
* data, raw_data, taxes, segments and ssr are dropped.

STOPS, CHANGING NOTHING, if any line carries a `data` key with no column, or a non-empty
taxes / segments / ssr array: either would be data this migration silently throws away.

`raw_data` — each line exactly as the vendor's spreadsheet had it — is NOT recoverable
after this; the uploaded file in storage is the original from here on. A downgrade puts
`data` back from the columns and leaves `raw_data` NULL.

Revision ID: tp_gds_columns_01
Revises: tp_statements_01
Create Date: 2026-10-14 00:00:00.000000
"""
import re
from datetime import date
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'tp_gds_columns_01'
down_revision: Union[str, None] = 'tp_statements_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'third_party_gds'

# (column, `data` key, type) — kept in step with models/statement_row.ThirdPartyGds.
_COLUMNS = [
    ('week', 'week', sa.Text()),
    ('booking_date', 'booking_date', sa.Date()),
    ('transaction_date', 'transaction_date', sa.Date()),
    ('issue_date', 'issue_date', sa.Date()),
    ('travel_date', 'travel_date', sa.Date()),
    ('customer_name', 'customer_name', sa.Text()),
    ('customer_id', 'customer_id', sa.Text()),
    ('airline_name', 'airline_name', sa.Text()),
    ('airline_code', 'airline_code', sa.Text()),
    ('ticket_prefix', 'ticket_prefix', sa.Text()),
    ('segment_type', 'segment_type', sa.Text()),
    ('pnr', 'pnr', sa.Text()),
    ('airline_pnr', 'airline_pnr', sa.Text()),
    ('gds_pnr', 'gds_pnr', sa.Text()),
    ('ticket_number', 'ticket_number', sa.Text()),
    ('ticket_status', 'ticket_status', sa.Text()),
    ('transaction_type', 'transaction_type', sa.Text()),
    ('booking_type', 'booking_type', sa.Text()),
    ('username', 'username', sa.Text()),
    ('issuing_office', 'issuing_office', sa.Text()),
    ('pax_type', 'pax_type', sa.Text()),
    ('first_name', 'first_name', sa.Text()),
    ('last_name', 'last_name', sa.Text()),
    ('passenger_name', 'passenger_name', sa.Text()),
    ('passenger_count', 'passenger_count', sa.Integer()),
    ('sector', 'sector', sa.Text()),
    ('flight_number', 'flight_number', sa.Text()),
    ('trip_type', 'trip_type', sa.Text()),
    ('travel_type', 'travel_type', sa.Text()),
    ('booking_class', 'booking_class', sa.Text()),
    ('payment_method', 'payment_method', sa.Text()),
    ('currency', 'currency', sa.Text()),
    ('base_fare', 'base_fare', sa.Numeric()),
    ('yq', 'yq', sa.Numeric()),
    ('other_taxes', 'other_taxes', sa.Numeric()),
    ('total_tax', 'taxes', sa.Numeric()),
    ('ssr_amount', 'ssr_amount', sa.Numeric()),
    ('reschedule_charges', 'reschedule_charges', sa.Numeric()),
    ('total_fare', 'total_fare', sa.Numeric()),
    ('commission_amount', 'commission_amount', sa.Numeric()),
    ('commission_rate', 'commission_rate', sa.Numeric()),
    ('incentive_amount', 'incentive_amount', sa.Numeric()),
    ('tds', 'tds', sa.Numeric()),
    ('service_charge', 'service_charge', sa.Numeric()),
    ('service_fee', 'service_fee', sa.Numeric()),
    ('gst_on_sf', 'gst_on_sf', sa.Numeric()),
    ('markup', 'markup', sa.Numeric()),
    ('agent_penalty', 'agent_penalty', sa.Numeric()),
    ('cancellation_markup', 'cancellation_markup', sa.Numeric()),
    ('net_amount', 'net_amount', sa.Numeric()),
    ('invoice_number', 'invoice_number', sa.Text()),
    ('agency_code', 'agency_code', sa.Text()),
    ('consolidator_name', 'consolidator_name', sa.Text()),
    ('gds', 'gds', sa.Text()),
    ('payment_status', 'payment_status', sa.Text()),
    ('remarks', 'remarks', sa.Text()),
    ('issue_date_source', 'issue_date_source', sa.String(20)),
    ('total_fare_source', 'total_fare_source', sa.String(20)),
    ('date_parse_failed', 'date_parse_failed', sa.String(40)),
    ('row_kind', 'row_kind', sa.String(20)),
    ('row_label', 'row_label', sa.Text()),
    ('airline_id', 'airline_id', sa.Integer()),
    ('airline_master_name', 'airline_master_name', sa.Text()),
    ('airline_conflict', 'airline_conflict', sa.Text()),
    ('edited_fields', '__edited__', sa.Text()),
    ('unparsed_fields', 'unparsed_fields', sa.Text()),
]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d*\.?\d+$")


def _kind(type_) -> str:
    if isinstance(type_, sa.Date):
        return 'date'
    if isinstance(type_, sa.Numeric):
        return 'number'
    if isinstance(type_, sa.Integer):
        return 'int'
    return 'text'


def _coerce(value, kind):
    """(stored, fitted) — the same rule as models/typed_statement._coerce, frozen here so a
    later change to the model cannot change what this migration did."""
    if value is None:
        return None, True
    if kind == 'text':
        s = str(value)
        return (s if s.strip() else None), True
    s = str(value).strip().replace(',', '')
    if not s:
        return None, True
    if kind == 'date':
        if _ISO_DATE.match(s):
            try:
                return date.fromisoformat(s[:10]), True
            except ValueError:
                pass
        return None, False
    if not _PLAIN_NUMBER.match(s):
        return None, False
    n = Decimal(s)
    if kind == 'int':
        return (int(n), True) if n == n.to_integral_value() else (None, False)
    return n, True


def upgrade() -> None:
    conn = op.get_bind()
    known = {key for _c, key, _t in _COLUMNS}

    unknown = sorted(set(conn.execute(sa.text(
        f"SELECT DISTINCT k FROM {_T}, jsonb_object_keys("
        f"  CASE WHEN jsonb_typeof(data) = 'object' THEN data ELSE '{{}}'::jsonb END) AS k"
    )).scalars().all()) - known)
    if unknown:
        raise RuntimeError(
            f"{_T}.data carries keys with no column: {', '.join(unknown)}. Add a column for "
            f"each (model and this migration) before converting, or they are lost.")
    folded = conn.execute(sa.text(
        f"SELECT count(*) FROM {_T} WHERE "
        + " OR ".join(f"(jsonb_typeof({c}) = 'array' AND jsonb_array_length({c}) > 0)"
                      for c in ('taxes', 'segments', 'ssr'))
    )).scalar()
    if folded:
        raise RuntimeError(
            f"{folded} {_T} line(s) carry taxes / segments / ssr entries, which have no column.")

    for column, _key, type_ in _COLUMNS:
        op.add_column(_T, sa.Column(column, type_, nullable=True))
    op.create_index('ix_third_party_gds_ticket_number', _T, ['ticket_number'])

    sets = ", ".join(f"{c} = :{c}" for c, _k, _t in _COLUMNS)
    update = sa.text(f"UPDATE {_T} SET {sets} WHERE id = :id")
    batch = []
    for row_id, data in conn.execute(sa.text(f"SELECT id, data FROM {_T} ORDER BY id")).all():
        data = data if isinstance(data, dict) else {}
        values, failed = {"id": row_id}, []
        for column, key, type_ in _COLUMNS:
            if column == 'unparsed_fields':
                continue
            stored, fits = _coerce(data.get(key), _kind(type_))
            if not fits:
                failed.append(key)
            values[column] = stored
        values['unparsed_fields'] = ",".join(sorted(failed)) or None
        batch.append(values)
        if len(batch) >= 500:
            conn.execute(update, batch)
            batch = []
    if batch:
        conn.execute(update, batch)

    for column in ('data', 'raw_data', 'taxes', 'segments', 'ssr'):
        op.drop_column(_T, column)


def downgrade() -> None:
    op.add_column(_T, sa.Column('data', JSONB(), nullable=True))
    op.add_column(_T, sa.Column('taxes', JSONB(), nullable=True))
    op.add_column(_T, sa.Column('segments', JSONB(), nullable=True))
    op.add_column(_T, sa.Column('ssr', JSONB(), nullable=True))
    op.add_column(_T, sa.Column('raw_data', JSONB(), nullable=True))

    pairs = [f"'{key}', {column}::text" for column, key, _t in _COLUMNS]
    # jsonb_build_object takes at most 100 arguments, so 50 pairs per call.
    calls = [f"jsonb_build_object({', '.join(pairs[i:i + 50])})" for i in range(0, len(pairs), 50)]
    op.execute(
        f"UPDATE {_T} SET data = jsonb_strip_nulls({' || '.join(calls)}), "
        f"taxes = '[]'::jsonb, segments = '[]'::jsonb, ssr = '[]'::jsonb"
    )

    op.drop_index('ix_third_party_gds_ticket_number', table_name=_T)
    for column, _key, _t in _COLUMNS:
        op.drop_column(_T, column)
