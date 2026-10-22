"""Tickets: Payable To — who a ticket was bought from

* uploaded_tickets.payable_type — "airline" (bought direct from the carrier) or "b2b"
  (bought through a consolidator).
* uploaded_tickets.payable_airline_id — the airline, when bought direct: any carrier in
  the platform's airline master (airlines.id).
* uploaded_tickets.payable_agency_id — the consolidator, when bought B2B: one of the user's
  User master → Agency Master rows (agencies.id).
* uploaded_tickets.payable_to — the name as picked, so a list reads it without a join.

Set per ticket by Internal Statement → Create Ticket, the purchase side of its Sold To. All
NULL on every ticket before this, and on uploaded statements, which do not say.

Added to BOTH ticket tables — uploaded_tickets and internal_uploaded_tickets — because the
internal model is mapped from the customer table's own metadata (models/internal_ticket.py)
and so expects every column the customer model has.

Revision ID: ticket_payable_01
Revises: internal_reupload_01
Create Date: 2026-10-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'ticket_payable_01'
down_revision: Union[str, None] = 'internal_reupload_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TICKETS = ('uploaded_tickets', 'internal_uploaded_tickets')


def upgrade() -> None:
    for table in _TICKETS:
        op.add_column(table, sa.Column('payable_type', sa.String(10), nullable=True))
        op.add_column(table, sa.Column('payable_airline_id', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('payable_agency_id', sa.Integer(), nullable=True))
        op.add_column(table, sa.Column('payable_to', sa.String(200), nullable=True))
        op.create_foreign_key(f'fk_{table}_payable_airline_id', table, 'airlines',
                              ['payable_airline_id'], ['id'], ondelete='SET NULL')
        op.create_foreign_key(f'fk_{table}_payable_agency_id', table, 'agencies',
                              ['payable_agency_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    for table in _TICKETS:
        op.drop_constraint(f'fk_{table}_payable_agency_id', table, type_='foreignkey')
        op.drop_constraint(f'fk_{table}_payable_airline_id', table, type_='foreignkey')
        op.drop_column(table, 'payable_to')
        op.drop_column(table, 'payable_agency_id')
        op.drop_column(table, 'payable_airline_id')
        op.drop_column(table, 'payable_type')
