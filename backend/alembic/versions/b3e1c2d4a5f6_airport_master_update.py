"""airport master update - new fields + approval table

Revision ID: b3e1c2d4a5f6
Revises: 0174f8762ca2
Create Date: 2026-04-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b3e1c2d4a5f6'
down_revision: Union[str, None] = '0174f8762ca2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── airports table: drop old columns, add new ones ─────────────────────
    op.drop_column('airports', 'name')
    op.drop_column('airports', 'city')

    op.add_column('airports', sa.Column('apt_id',            sa.String(20),  nullable=True))
    op.add_column('airports', sa.Column('categorization',    sa.String(50),  nullable=True))
    op.add_column('airports', sa.Column('continent',         sa.String(50),  nullable=True))
    op.add_column('airports', sa.Column('city_airport_name', sa.String(255), nullable=True))
    op.add_column('airports', sa.Column('created_by_id',     sa.Integer(),   nullable=True))

    op.create_unique_constraint('uq_airports_apt_id', 'airports', ['apt_id'])
    op.create_foreign_key(
        'fk_airports_created_by', 'airports', 'users',
        ['created_by_id'], ['id'], ondelete='SET NULL'
    )

    # ── airport_approvals table ────────────────────────────────────────────
    op.create_table(
        'airport_approvals',
        sa.Column('id',               sa.Integer(),     nullable=False),
        sa.Column('iata_code',        sa.String(3),     nullable=False),
        sa.Column('country',          sa.String(100),   nullable=False),
        sa.Column('categorization',   sa.String(50),    nullable=True),
        sa.Column('continent',        sa.String(50),    nullable=True),
        sa.Column('city_airport_name',sa.String(255),   nullable=False),
        sa.Column('status',           sa.String(20),    nullable=False, server_default='pending'),
        sa.Column('submitted_by_id',  sa.Integer(),     nullable=False),
        sa.Column('tenant_id',        sa.Integer(),     nullable=True),
        sa.Column('submitted_at',     sa.DateTime(),    nullable=False),
        sa.Column('reviewed_by_id',   sa.Integer(),     nullable=True),
        sa.Column('reviewed_at',      sa.DateTime(),    nullable=True),
        sa.Column('rejection_reason', sa.Text(),        nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['submitted_by_id'], ['users.id'],  ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by_id'],  ['users.id'],  ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'],       ['tenants.id'],ondelete='SET NULL'),
    )

    # ── userrole enum: add PLATFORM_ADMIN value ────────────────────────────
    # Since the column uses native_enum=False (VARCHAR), just update any
    # existing rows if needed — no DDL change required for VARCHAR columns.


def downgrade() -> None:
    op.drop_table('airport_approvals')

    op.drop_constraint('fk_airports_created_by', 'airports', type_='foreignkey')
    op.drop_constraint('uq_airports_apt_id', 'airports', type_='unique')
    op.drop_column('airports', 'created_by_id')
    op.drop_column('airports', 'city_airport_name')
    op.drop_column('airports', 'continent')
    op.drop_column('airports', 'categorization')
    op.drop_column('airports', 'apt_id')

    op.add_column('airports', sa.Column('name', sa.String(255), nullable=False, server_default=''))
    op.add_column('airports', sa.Column('city', sa.String(100), nullable=False, server_default=''))
