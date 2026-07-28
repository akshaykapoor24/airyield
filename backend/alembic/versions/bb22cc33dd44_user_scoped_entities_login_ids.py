"""user-scoped entities + login ids (My Profile)

Introduces per-user (private) master tables for the My Profile / onboarding
module, distinct from the tenant-shared entities / login_ids used by User Master:
  - user_entities:   a user's own billing/legal entities
  - user_login_ids:  a user's own airline login ids / IATA codes (each optionally
                     linked to one of the user's own entities)

Also drops the short-lived login_ids.entity_id column added in aa11bb22cc33 — the
entity link now lives on user_login_ids instead.

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-07-01 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb22cc33dd44'
down_revision: Union[str, None] = 'aa11bb22cc33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # entity link moves off the shared login_ids table onto user_login_ids
    op.drop_index('ix_login_ids_entity_id', table_name='login_ids')
    op.drop_constraint('fk_login_ids_entity_id', 'login_ids', type_='foreignkey')
    op.drop_column('login_ids', 'entity_id')

    op.create_table(
        'user_entities',
        sa.Column('id',         sa.Integer(),   nullable=False),
        sa.Column('user_id',    sa.Integer(),   nullable=False),
        sa.Column('tenant_id',  sa.Integer(),   nullable=True),
        sa.Column('name',       sa.String(255), nullable=False),
        sa.Column('code',       sa.String(50),  nullable=False),
        sa.Column('address',    sa.String(500), nullable=True),
        sa.Column('state',      sa.String(100), nullable=True),
        sa.Column('city',       sa.String(100), nullable=True),
        sa.Column('is_active',  sa.Boolean(),   nullable=True),
        sa.Column('created_at', sa.DateTime(),  nullable=True),
        sa.Column('updated_at', sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'code', name='uq_user_entities_user_code'),
    )
    op.create_index('ix_user_entities_user_id',   'user_entities', ['user_id'])
    op.create_index('ix_user_entities_tenant_id', 'user_entities', ['tenant_id'])

    op.create_table(
        'user_login_ids',
        sa.Column('id',           sa.Integer(),   nullable=False),
        sa.Column('user_id',      sa.Integer(),   nullable=False),
        sa.Column('tenant_id',    sa.Integer(),   nullable=True),
        sa.Column('login_id',     sa.String(100), nullable=False),
        sa.Column('airline_name', sa.String(255), nullable=True),
        sa.Column('airline_code', sa.String(20),  nullable=True),
        sa.Column('lob',          sa.String(100), nullable=True),
        sa.Column('vendor_id',    sa.Integer(),   nullable=True),
        sa.Column('entity_id',    sa.Integer(),   nullable=True),
        sa.Column('is_active',    sa.Boolean(),   nullable=True),
        sa.Column('created_at',   sa.DateTime(),  nullable=True),
        sa.Column('updated_at',   sa.DateTime(),  nullable=True),
        sa.ForeignKeyConstraint(['user_id'],   ['users.id'],         ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'],       ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['vendor_id'], ['suppliers.id'],     ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['entity_id'], ['user_entities.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_login_ids_user_id',   'user_login_ids', ['user_id'])
    op.create_index('ix_user_login_ids_tenant_id', 'user_login_ids', ['tenant_id'])
    op.create_index('ix_user_login_ids_login_id',  'user_login_ids', ['login_id'])
    op.create_index('ix_user_login_ids_vendor_id', 'user_login_ids', ['vendor_id'])
    op.create_index('ix_user_login_ids_entity_id', 'user_login_ids', ['entity_id'])


def downgrade() -> None:
    op.drop_index('ix_user_login_ids_entity_id', table_name='user_login_ids')
    op.drop_index('ix_user_login_ids_vendor_id', table_name='user_login_ids')
    op.drop_index('ix_user_login_ids_login_id',  table_name='user_login_ids')
    op.drop_index('ix_user_login_ids_tenant_id', table_name='user_login_ids')
    op.drop_index('ix_user_login_ids_user_id',   table_name='user_login_ids')
    op.drop_table('user_login_ids')

    op.drop_index('ix_user_entities_tenant_id', table_name='user_entities')
    op.drop_index('ix_user_entities_user_id',   table_name='user_entities')
    op.drop_table('user_entities')

    # restore login_ids.entity_id (referring to tenant-shared entities)
    op.add_column('login_ids', sa.Column('entity_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_login_ids_entity_id', 'login_ids', 'entities',
        ['entity_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_login_ids_entity_id', 'login_ids', ['entity_id'])
