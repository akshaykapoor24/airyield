"""add iata_commissions (User Master)

Tenant-scoped master table for the "User Master → IATA Commission" tab:
per-airline IATA commission % with a validity window. Airline name / code /
numeric code are copied from the Airline master; %, valid-from, valid-to are
user-filled. Standalone reference master — does not drive calculation.

Revision ID: m6a7b8c9d0e1
Revises: l5f6a7b8c9d0
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm6a7b8c9d0e1'
down_revision: Union[str, None] = 'l5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'iata_commissions',
        sa.Column('id',                  sa.Integer(),      nullable=False),
        sa.Column('tenant_id',           sa.Integer(),      nullable=True),
        sa.Column('created_by_id',       sa.Integer(),      nullable=False),
        sa.Column('airline_name',        sa.String(255),    nullable=False),
        sa.Column('airline_code',        sa.String(20),     nullable=True),
        sa.Column('iata_numeric_code',   sa.String(10),     nullable=True),
        sa.Column('iata_commission_pct', sa.Numeric(6, 2),  nullable=True),
        sa.Column('valid_from',          sa.Date(),         nullable=True),
        sa.Column('valid_to',            sa.Date(),         nullable=True),
        sa.Column('is_active',           sa.Boolean(),      nullable=True),
        sa.Column('created_at',          sa.DateTime(),     nullable=True),
        sa.Column('updated_at',          sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_iata_commissions_tenant_id',     'iata_commissions', ['tenant_id'])
    op.create_index('ix_iata_commissions_created_by_id', 'iata_commissions', ['created_by_id'])
    op.create_index('ix_iata_commissions_airline_name',  'iata_commissions', ['airline_name'])


def downgrade() -> None:
    op.drop_index('ix_iata_commissions_airline_name',  table_name='iata_commissions')
    op.drop_index('ix_iata_commissions_created_by_id', table_name='iata_commissions')
    op.drop_index('ix_iata_commissions_tenant_id',     table_name='iata_commissions')
    op.drop_table('iata_commissions')
