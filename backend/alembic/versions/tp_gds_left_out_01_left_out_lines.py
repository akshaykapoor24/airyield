"""Third Party GDS: keep the lines an upload left out as repeats

* third_party_gds_left_out — one row per line of a statement's file that its upload did not
  save because it repeats a line already saved (already uploaded, a partial duplicate or a
  repeat within the file, left out by the user's choice): the line exactly as the file had
  it, in the same typed columns as third_party_gds, plus the statement it was on (CASCADE),
  its file row, why it was left out, the saved line it repeats (SET NULL) and what differs.
  Read by Vendor Reconciliation, which shows each with the reconciliation of the line it
  repeats (models/statement_row.ThirdPartyGdsLeftOut).

Nothing is backfilled: the lines left out before this were never stored — only counted, in
third_party_statements.duplicate_entries. Uploading such a statement again keeps them.

Revision ID: tp_gds_left_out_01
Revises: internal_dupes_01
Create Date: 2026-10-23 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_left_out_01'
down_revision: Union[str, None] = 'internal_dupes_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'third_party_gds_left_out'

# (column, `data` key, type) — the field columns of models/statement_row._GdsLineFields,
# frozen here as tp_gds_columns_01 froze them for third_party_gds.
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


def upgrade() -> None:
    op.create_table(
        _T,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('batch_id', sa.String(100),
                  sa.ForeignKey('third_party_statements.batch_id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_row', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('repeat_of_id', sa.Integer(),
                  sa.ForeignKey('third_party_gds.id', ondelete='SET NULL'), nullable=True),
        sa.Column('differs', sa.Text(), nullable=True),
        sa.Column('dedup_key', sa.String(64), nullable=True),
        sa.Column('match_key', sa.String(64), nullable=True),
        *[sa.Column(name, type_, nullable=True) for name, _key, type_ in _COLUMNS],
        sa.CheckConstraint("kind IN ('exact', 'partial', 'in_file')", name='ck_third_party_gds_left_out_kind'),
    )
    for col in ('tenant_id', 'created_by_id', 'batch_id', 'repeat_of_id'):
        op.create_index(f'ix_{_T}_{col}', _T, [col])


def downgrade() -> None:
    for col in ('tenant_id', 'created_by_id', 'batch_id', 'repeat_of_id'):
        op.drop_index(f'ix_{_T}_{col}', table_name=_T)
    op.drop_table(_T)
