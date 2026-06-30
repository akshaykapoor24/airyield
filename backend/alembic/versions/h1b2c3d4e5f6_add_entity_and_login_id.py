"""add entities + login_ids (User Master)

Tenant-scoped master tables for the new "User Master" module:
  - entities: billing/legal entities (name, code, address, state, city)
  - login_ids: airline-portal login id / IATA code, vendor → suppliers master

Revision ID: h1b2c3d4e5f6
Revises: g0a1b2c3d4e5
Create Date: 2026-06-28 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1b2c3d4e5f6'
down_revision: Union[str, None] = 'g0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'entities',
        sa.Column('id',            sa.Integer(),   nullable=False),
        sa.Column('tenant_id',     sa.Integer(),   nullable=True),
        sa.Column('created_by_id', sa.Integer(),   nullable=False),
        sa.Column('name',          sa.String(255), nullable=False),
        sa.Column('code',          sa.String(50),  nullable=False),
        sa.Column('address',       sa.String(500), nullable=True),
        sa.Column('state',         sa.String(100), nullable=True),
        sa.Column('city',          sa.String(100), nullable=True),
        sa.Column('is_active',     sa.Boolean(),   nullable=True),
        sa.Column('created_at',    sa.DateTime(),  nullable=True),
        sa.Column('updated_at',    sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_entities_tenant_code'),
    )
    op.create_index('ix_entities_tenant_id',     'entities', ['tenant_id'])
    op.create_index('ix_entities_created_by_id', 'entities', ['created_by_id'])

    op.create_table(
        'login_ids',
        sa.Column('id',            sa.Integer(),   nullable=False),
        sa.Column('tenant_id',     sa.Integer(),   nullable=True),
        sa.Column('created_by_id', sa.Integer(),   nullable=False),
        sa.Column('login_id',      sa.String(100), nullable=False),
        sa.Column('airline_name',  sa.String(255), nullable=True),
        sa.Column('airline_code',  sa.String(20),  nullable=True),
        sa.Column('lob',           sa.String(100), nullable=True),
        sa.Column('vendor_id',     sa.Integer(),   nullable=True),
        sa.Column('is_active',     sa.Boolean(),   nullable=True),
        sa.Column('created_at',    sa.DateTime(),  nullable=True),
        sa.Column('updated_at',    sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['vendor_id'],     ['suppliers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_ids_tenant_id',     'login_ids', ['tenant_id'])
    op.create_index('ix_login_ids_created_by_id', 'login_ids', ['created_by_id'])
    op.create_index('ix_login_ids_login_id',      'login_ids', ['login_id'])
    op.create_index('ix_login_ids_vendor_id',     'login_ids', ['vendor_id'])


def downgrade() -> None:
    op.drop_index('ix_login_ids_vendor_id',     table_name='login_ids')
    op.drop_index('ix_login_ids_login_id',      table_name='login_ids')
    op.drop_index('ix_login_ids_created_by_id', table_name='login_ids')
    op.drop_index('ix_login_ids_tenant_id',     table_name='login_ids')
    op.drop_table('login_ids')
    op.drop_index('ix_entities_created_by_id', table_name='entities')
    op.drop_index('ix_entities_tenant_id',     table_name='entities')
    op.drop_table('entities')
