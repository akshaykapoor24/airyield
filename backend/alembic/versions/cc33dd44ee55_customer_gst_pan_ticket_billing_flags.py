"""Customer GST registration + PAN, and ticket billed flags

Adds:
  - customers.gst_registered (bool) + customers.pan_no
    (backfills gst_registered = true for existing rows that already have a gst_no)
  - uploaded_tickets.is_billed + uploaded_tickets.billing_id (FK -> billings,
    ON DELETE SET NULL) so a ticket can be locked to at most one customer billing.

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'cc33dd44ee55'
down_revision: Union[str, None] = 'bb22cc33dd44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── customers: GST registration + PAN ──
    op.add_column('customers', sa.Column('gst_registered', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('customers', sa.Column('pan_no', sa.String(20), nullable=True))
    # Existing customers that already have a GST number are, by definition, registered.
    op.execute("UPDATE customers SET gst_registered = true WHERE gst_no IS NOT NULL AND gst_no <> ''")

    # ── uploaded_tickets: billed status ──
    op.add_column('uploaded_tickets', sa.Column('is_billed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('uploaded_tickets', sa.Column('billing_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_uploaded_tickets_billing_id', 'uploaded_tickets', 'billings',
        ['billing_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_uploaded_tickets_billing_id', 'uploaded_tickets', ['billing_id'])


def downgrade() -> None:
    op.drop_index('ix_uploaded_tickets_billing_id', table_name='uploaded_tickets')
    op.drop_constraint('fk_uploaded_tickets_billing_id', 'uploaded_tickets', type_='foreignkey')
    op.drop_column('uploaded_tickets', 'billing_id')
    op.drop_column('uploaded_tickets', 'is_billed')
    op.drop_column('customers', 'pan_no')
    op.drop_column('customers', 'gst_registered')
