"""agency profile tables (agencies + entities + login ids)

Introduces per-user (private) master tables for the Agency Profile module:
  - agencies:          a user's own agencies (details copied from the suppliers
                       master at add-time; name unique per user)
  - agency_entities:   a user's agency entities (one agency -> many entities;
                       code unique per agency)
  - agency_login_ids:  a user's agency login ids / IATA codes (one agency ->
                       many login ids, each optionally linked to one of that
                       agency's entities)

Distinct from the user-scoped My Profile tables (user_entities / user_login_ids)
and the tenant-shared User Master tables (entities / login_ids).

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dd44ee55ff66'
down_revision: Union[str, None] = 'cc33dd44ee55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agencies',
        sa.Column('id',            sa.Integer(),   nullable=False),
        sa.Column('user_id',       sa.Integer(),   nullable=False),
        sa.Column('tenant_id',     sa.Integer(),   nullable=True),
        sa.Column('name',          sa.String(255), nullable=False),
        sa.Column('vendor_type',   sa.String(100), nullable=True),
        sa.Column('gst_number',    sa.String(20),  nullable=True),
        sa.Column('pan_number',    sa.String(20),  nullable=True),
        sa.Column('contact_phone', sa.String(50),  nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('notes',         sa.Text(),      nullable=True),
        sa.Column('is_active',     sa.Boolean(),   nullable=True),
        sa.Column('created_at',    sa.DateTime(),  nullable=True),
        sa.Column('updated_at',    sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_agencies_user_name'),
    )
    op.create_index('ix_agencies_user_id',   'agencies', ['user_id'])
    op.create_index('ix_agencies_tenant_id', 'agencies', ['tenant_id'])

    op.create_table(
        'agency_entities',
        sa.Column('id',         sa.Integer(),   nullable=False),
        sa.Column('user_id',    sa.Integer(),   nullable=False),
        sa.Column('tenant_id',  sa.Integer(),   nullable=True),
        sa.Column('agency_id',  sa.Integer(),   nullable=False),
        sa.Column('name',       sa.String(255), nullable=False),
        sa.Column('code',       sa.String(50),  nullable=False),
        sa.Column('address',    sa.String(500), nullable=True),
        sa.Column('state',      sa.String(100), nullable=True),
        sa.Column('city',       sa.String(100), nullable=True),
        sa.Column('is_active',  sa.Boolean(),   nullable=True),
        sa.Column('created_at', sa.DateTime(),  nullable=True),
        sa.Column('updated_at', sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],    ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],  ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agency_id', 'code', name='uq_agency_entities_agency_code'),
    )
    op.create_index('ix_agency_entities_user_id',   'agency_entities', ['user_id'])
    op.create_index('ix_agency_entities_tenant_id', 'agency_entities', ['tenant_id'])
    op.create_index('ix_agency_entities_agency_id', 'agency_entities', ['agency_id'])

    op.create_table(
        'agency_login_ids',
        sa.Column('id',           sa.Integer(),   nullable=False),
        sa.Column('user_id',      sa.Integer(),   nullable=False),
        sa.Column('tenant_id',    sa.Integer(),   nullable=True),
        sa.Column('agency_id',    sa.Integer(),   nullable=False),
        sa.Column('entity_id',    sa.Integer(),   nullable=True),
        sa.Column('login_id',     sa.String(100), nullable=False),
        sa.Column('airline_name', sa.String(255), nullable=True),
        sa.Column('airline_code', sa.String(20),  nullable=True),
        sa.Column('lob',          sa.String(100), nullable=True),
        sa.Column('vendor_id',    sa.Integer(),   nullable=True),
        sa.Column('is_active',    sa.Boolean(),   nullable=True),
        sa.Column('created_at',   sa.DateTime(),  nullable=True),
        sa.Column('updated_at',   sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],           ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],         ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id'],        ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entity_id'], ['agency_entities.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['vendor_id'], ['suppliers.id'],       ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agency_login_ids_user_id',   'agency_login_ids', ['user_id'])
    op.create_index('ix_agency_login_ids_tenant_id', 'agency_login_ids', ['tenant_id'])
    op.create_index('ix_agency_login_ids_agency_id', 'agency_login_ids', ['agency_id'])
    op.create_index('ix_agency_login_ids_entity_id', 'agency_login_ids', ['entity_id'])
    op.create_index('ix_agency_login_ids_login_id',  'agency_login_ids', ['login_id'])
    op.create_index('ix_agency_login_ids_vendor_id', 'agency_login_ids', ['vendor_id'])


def downgrade() -> None:
    op.drop_index('ix_agency_login_ids_vendor_id', table_name='agency_login_ids')
    op.drop_index('ix_agency_login_ids_login_id',  table_name='agency_login_ids')
    op.drop_index('ix_agency_login_ids_entity_id', table_name='agency_login_ids')
    op.drop_index('ix_agency_login_ids_agency_id', table_name='agency_login_ids')
    op.drop_index('ix_agency_login_ids_tenant_id', table_name='agency_login_ids')
    op.drop_index('ix_agency_login_ids_user_id',   table_name='agency_login_ids')
    op.drop_table('agency_login_ids')

    op.drop_index('ix_agency_entities_agency_id', table_name='agency_entities')
    op.drop_index('ix_agency_entities_tenant_id', table_name='agency_entities')
    op.drop_index('ix_agency_entities_user_id',   table_name='agency_entities')
    op.drop_table('agency_entities')

    op.drop_index('ix_agencies_tenant_id', table_name='agencies')
    op.drop_index('ix_agencies_user_id',   table_name='agencies')
    op.drop_table('agencies')
