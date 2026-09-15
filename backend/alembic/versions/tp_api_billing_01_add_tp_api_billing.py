"""Third Party API billing — party resolution + the projection back-link

Adds `_BillingMixin`'s ten columns to `third_party_api` so an aggregator's FLIGHT rows can be
resolved to a Customer/Corporate and projected into `uploaded_tickets`, exactly as NDC's are.
See services/tp_api_billing_projection.py for what writes each one.

TEN COLUMNS, NOT THIRTEEN. `ndc` also carries `bill_group_key` / `bill_is_anchor` /
`bill_latch_status`, which attach a document-less ancillary line (a paid seat, excess baggage)
to the flight line it belongs to. An aggregator booking IS one line and one ticket, so those
three were split into `_RollUpMixin` and stay on `ndc` alone — here they would be NULL forever
and their CHECK would police a vocabulary this table never uses.

NO `statement_batch_billing` WORK. `ndc_billing_01` created it keyed on `(slug, batch_id)` with
no foreign key, deliberately named for the slug space rather than for NDC — so it already
serves this type with no change.

Revision ID: tp_api_billing_01
Revises: tp_api_01
Create Date: 2026-09-13 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'tp_api_billing_01'
down_revision: Union[str, None] = 'tp_api_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'third_party_api'

# Every one nullable or defaulted, so this is additive over existing rows with no backfill:
# an already-uploaded batch simply reads as "never resolved" until someone opens Billing.
_COLUMNS = (
    sa.Column('bill_kind', sa.String(length=12), nullable=True),
    sa.Column('bill_status', sa.String(length=16), nullable=False,
              server_default='unresolved'),
    sa.Column('bill_customer_type', sa.String(length=12), nullable=True),
    sa.Column('bill_customer_id', sa.Integer(), nullable=True),
    sa.Column('bill_corporate_id', sa.Integer(), nullable=True),
    sa.Column('bill_match_reason', sa.String(length=300), nullable=True),
    sa.Column('bill_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('projected_ticket_id', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.Column('resolved_by_id', sa.Integer(), nullable=True),
)

_FKS = (
    ('fk_third_party_api_bill_customer', 'bill_customer_id', 'customers', 'SET NULL'),
    ('fk_third_party_api_bill_corporate', 'bill_corporate_id', 'corporates', 'SET NULL'),
    ('fk_third_party_api_projected_ticket', 'projected_ticket_id', 'uploaded_tickets', 'SET NULL'),
    ('fk_third_party_api_resolved_by', 'resolved_by_id', 'users', None),
)


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column(_TABLE, col)

    for name, local, remote, ondelete in _FKS:
        op.create_foreign_key(name, _TABLE, remote, [local], ['id'], ondelete=ondelete)

    # The vocabulary, not the type↔id coherence: 'direct' carrying a corporate_id is still
    # legal SQL here, exactly as it is on uploaded_tickets. services/ticket_retag.py owns
    # that rule in code, and this CHECK only stops a fourth spelling appearing.
    op.create_check_constraint(
        'ck_third_party_api_bill_customer_type', _TABLE,
        "bill_customer_type IS NULL OR bill_customer_type IN ('agency', 'corporate', 'direct')",
    )

    # The worklist's every query is (this batch, some bill_status).
    op.create_index('ix_third_party_api_bill', _TABLE, ['batch_id', 'bill_status'])
    # Partial: only projected rows are ever looked up this way, and they are the minority.
    op.create_index('ix_third_party_api_projected', _TABLE, ['projected_ticket_id'],
                    postgresql_where=sa.text('projected_ticket_id IS NOT NULL'))


def downgrade() -> None:
    op.drop_index('ix_third_party_api_projected', table_name=_TABLE)
    op.drop_index('ix_third_party_api_bill', table_name=_TABLE)
    op.drop_constraint('ck_third_party_api_bill_customer_type', _TABLE, type_='check')

    for name, _local, _remote, _ondelete in _FKS:
        op.drop_constraint(name, _TABLE, type_='foreignkey')

    for col in reversed(_COLUMNS):
        op.drop_column(_TABLE, col.name)

    # Deliberately does NOT drop the ix_uploaded_tickets_* partial indexes: they are owned by
    # lcc_billing_01 and are still used by LCC and NDC. Same note as ndc_billing_01.
