"""Third-party statements: attribute an upload to an Agency Master row

* statement_batch_suppliers.agency_id — the agency the uploader picked (one branch on one
  channel). It carries the vendor service charge the statement's SF columns are checked
  against.
* statement_batch_suppliers.supplier_id becomes NULLABLE — an agency awaiting
  supplier-master approval has no supplier row yet, and its statements must still upload.

Revision ID: tp_agency_01
Revises: employee_codes_01
Create Date: 2026-10-11 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_agency_01'
down_revision: Union[str, None] = 'employee_codes_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('statement_batch_suppliers', sa.Column('agency_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_statement_batch_suppliers_agency', 'statement_batch_suppliers', 'agencies',
        ['agency_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_statement_batch_suppliers_agency_id', 'statement_batch_suppliers', ['agency_id'])
    op.alter_column('statement_batch_suppliers', 'supplier_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM statement_batch_suppliers WHERE supplier_id IS NULL")
    op.alter_column('statement_batch_suppliers', 'supplier_id', existing_type=sa.Integer(), nullable=False)
    op.drop_index('ix_statement_batch_suppliers_agency_id', table_name='statement_batch_suppliers')
    op.drop_constraint('fk_statement_batch_suppliers_agency', 'statement_batch_suppliers', type_='foreignkey')
    op.drop_column('statement_batch_suppliers', 'agency_id')
