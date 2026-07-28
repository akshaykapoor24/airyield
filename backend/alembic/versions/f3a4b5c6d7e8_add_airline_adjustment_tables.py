"""add airline adjustment upload tables (ADM / ACM / RA)

One table per IATA BSPlink document type for the Airline Adjustments feature.
Each row is a line from an uploaded ADM/ACM/RA export; every export column is
stored as text plus per-upload provenance (batch_id, source_file, uploaded_at)
and tenant/user scoping. Additive — touches nothing else.

Revision ID: f3a4b5c6d7e8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _scope_columns() -> list[sa.Column]:
    """id / scoping / provenance columns shared by all three tables."""
    return [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    ]


def _indexes(table: str) -> None:
    op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
    op.create_index(f'ix_{table}_created_by_id', table, ['created_by_id'])
    op.create_index(f'ix_{table}_batch_id', table, ['batch_id'])
    op.create_index(f'ix_{table}_uploaded_at', table, ['uploaded_at'])


def upgrade() -> None:
    op.create_table(
        'airline_adm',
        *_scope_columns(),
        sa.Column('iso_country_code', sa.Text(), nullable=True),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('country_territory', sa.Text(), nullable=True),
        sa.Column('issue_date', sa.Text(), nullable=True),
        sa.Column('reason_for_issue', sa.Text(), nullable=True),
        sa.Column('document_number', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('date_of_ticket_issue', sa.Text(), nullable=True),
        sa.Column('airline_code', sa.Text(), nullable=True),
        sa.Column('agent_code', sa.Text(), nullable=True),
        sa.Column('airlines_fare', sa.Text(), nullable=True),
        sa.Column('agents_fare', sa.Text(), nullable=True),
        sa.Column('airlines_tax', sa.Text(), nullable=True),
        sa.Column('agents_tax', sa.Text(), nullable=True),
        sa.Column('airlines_commission', sa.Text(), nullable=True),
        sa.Column('agents_commission', sa.Text(), nullable=True),
        sa.Column('airlines_supplementary_commission', sa.Text(), nullable=True),
        sa.Column('agents_supplementary_commission', sa.Text(), nullable=True),
        sa.Column('airlines_tax_on_commission', sa.Text(), nullable=True),
        sa.Column('agents_tax_on_commission', sa.Text(), nullable=True),
        sa.Column('airlines_cancellation_penalty', sa.Text(), nullable=True),
        sa.Column('agents_cancellation_penalty', sa.Text(), nullable=True),
        sa.Column('airlines_miscellaneous_fee', sa.Text(), nullable=True),
        sa.Column('agents_miscellaneous_fee', sa.Text(), nullable=True),
        sa.Column('amount', sa.Text(), nullable=True),
        sa.Column('currency', sa.Text(), nullable=True),
        sa.Column('statistical_code', sa.Text(), nullable=True),
        sa.Column('rtdn_type', sa.Text(), nullable=True),
        sa.Column('issue_reason', sa.Text(), nullable=True),
        sa.Column('primary_reason', sa.Text(), nullable=True),
        sa.Column('reporting_date', sa.Text(), nullable=True),
        sa.Column('period', sa.Text(), nullable=True),
        sa.Column('dispute_date', sa.Text(), nullable=True),
        sa.Column('forward_to_gds', sa.Text(), nullable=True),
        sa.Column('forward_to_gds_date', sa.Text(), nullable=True),
        sa.Column('contact_name', sa.Text(), nullable=True),
        sa.Column('contact_email', sa.Text(), nullable=True),
        sa.Column('contact_phone', sa.Text(), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.Column('forward_to_gds_reason', sa.Text(), nullable=True),
        sa.Column('related_document', sa.Text(), nullable=True),
        sa.Column('dispute_rejection_reason', sa.Text(), nullable=True),
        sa.Column('dispute_approval_remark', sa.Text(), nullable=True),
        sa.Column('sent_to_dpc', sa.Text(), nullable=True),
    )
    _indexes('airline_adm')

    op.create_table(
        'airline_acm',
        *_scope_columns(),
        sa.Column('iso_country_code', sa.Text(), nullable=True),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('country_territory', sa.Text(), nullable=True),
        sa.Column('issue_date', sa.Text(), nullable=True),
        sa.Column('reason_for_issue', sa.Text(), nullable=True),
        sa.Column('document_number', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('date_of_ticket_issue', sa.Text(), nullable=True),
        sa.Column('airline_code', sa.Text(), nullable=True),
        sa.Column('agent_code', sa.Text(), nullable=True),
        sa.Column('airlines_fare', sa.Text(), nullable=True),
        sa.Column('agents_fare', sa.Text(), nullable=True),
        sa.Column('airlines_tax', sa.Text(), nullable=True),
        sa.Column('agents_tax', sa.Text(), nullable=True),
        sa.Column('airlines_commission', sa.Text(), nullable=True),
        sa.Column('agents_commission', sa.Text(), nullable=True),
        sa.Column('airlines_supplementary_commission', sa.Text(), nullable=True),
        sa.Column('agents_supplementary_commission', sa.Text(), nullable=True),
        sa.Column('airlines_tax_on_commission', sa.Text(), nullable=True),
        sa.Column('agents_tax_on_commission', sa.Text(), nullable=True),
        sa.Column('airlines_cancellation_penalty', sa.Text(), nullable=True),
        sa.Column('agents_cancellation_penalty', sa.Text(), nullable=True),
        sa.Column('airlines_miscellaneous_fee', sa.Text(), nullable=True),
        sa.Column('agents_miscellaneous_fee', sa.Text(), nullable=True),
        sa.Column('amount', sa.Text(), nullable=True),
        sa.Column('currency', sa.Text(), nullable=True),
        sa.Column('statistical_code', sa.Text(), nullable=True),
        sa.Column('rtdn_type', sa.Text(), nullable=True),
        sa.Column('issue_reason', sa.Text(), nullable=True),
        sa.Column('reporting_date', sa.Text(), nullable=True),
        sa.Column('period', sa.Text(), nullable=True),
        sa.Column('dispute_date', sa.Text(), nullable=True),
        sa.Column('contact_name', sa.Text(), nullable=True),
        sa.Column('contact_email', sa.Text(), nullable=True),
        sa.Column('contact_phone', sa.Text(), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.Column('related_document', sa.Text(), nullable=True),
        sa.Column('dispute_rejection_reason', sa.Text(), nullable=True),
        sa.Column('dispute_approval_remark', sa.Text(), nullable=True),
        sa.Column('sent_to_dpc', sa.Text(), nullable=True),
    )
    _indexes('airline_acm')

    op.create_table(
        'airline_ra',
        *_scope_columns(),
        sa.Column('iso_country_code', sa.Text(), nullable=True),
        sa.Column('country_territory', sa.Text(), nullable=True),
        sa.Column('document_number', sa.Text(), nullable=True),
        sa.Column('rtdn_number', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('airline_code', sa.Text(), nullable=True),
        sa.Column('agent_code', sa.Text(), nullable=True),
        sa.Column('application_date', sa.Text(), nullable=True),
        sa.Column('authorization_date', sa.Text(), nullable=True),
        sa.Column('rejection_date', sa.Text(), nullable=True),
        sa.Column('reporting_date', sa.Text(), nullable=True),
        sa.Column('period', sa.Text(), nullable=True),
        sa.Column('currency', sa.Text(), nullable=True),
        sa.Column('forms_of_payment', sa.Text(), nullable=True),
        sa.Column('amount', sa.Text(), nullable=True),
        sa.Column('passenger', sa.Text(), nullable=True),
        sa.Column('et', sa.Text(), nullable=True),
        sa.Column('sent_to_dpc', sa.Text(), nullable=True),
        sa.Column('airline_remark', sa.Text(), nullable=True),
        sa.Column('reason_for_refund', sa.Text(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('deletion_reason', sa.Text(), nullable=True),
        sa.Column('final', sa.Text(), nullable=True),
        sa.Column('days_left', sa.Text(), nullable=True),
        sa.Column('process_stopped', sa.Text(), nullable=True),
    )
    _indexes('airline_ra')


def downgrade() -> None:
    for table in ('airline_ra', 'airline_acm', 'airline_adm'):
        op.drop_index(f'ix_{table}_uploaded_at', table_name=table)
        op.drop_index(f'ix_{table}_batch_id', table_name=table)
        op.drop_index(f'ix_{table}_created_by_id', table_name=table)
        op.drop_index(f'ix_{table}_tenant_id', table_name=table)
        op.drop_table(table)
