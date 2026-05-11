"""Add airline_deals, b2b_deals tables and polymorphic deal_type to deal_approvals

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'j4k5l6m7n8o9'
down_revision: Union[str, None] = 'i3j4k5l6m7n8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── airline_deals table ───────────────────────────────────────────────────
    op.create_table(
        'airline_deals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending_approval'),
        sa.Column('source_agent', sa.String(length=255), nullable=False),
        sa.Column('deal_maker_name', sa.String(length=255), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('airline_type', sa.String(length=20), nullable=True),
        sa.Column('airline_name', sa.String(length=255), nullable=True),
        sa.Column('contract_year', sa.String(length=50), nullable=True),
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('trigger_type', sa.String(length=50), nullable=True),
        sa.Column('payout_type', sa.String(length=50), nullable=True),
        sa.Column('entity', sa.String(length=50), nullable=True),
        sa.Column('iata_number', sa.String(length=50), nullable=True),
        sa.Column('business_type', sa.String(length=50), nullable=True),
        sa.Column('entity_lcc', sa.String(length=50), nullable=True),
        sa.Column('login_id', sa.String(length=100), nullable=True),
        sa.Column('incentive_types', sa.JSON(), nullable=True),
        sa.Column('incentive_data', sa.JSON(), nullable=True),
        sa.Column('incl_excl_types', sa.JSON(), nullable=True),
        sa.Column('incl_excl_data', sa.JSON(), nullable=True),
        sa.Column('vice_versa', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── b2b_deals table ───────────────────────────────────────────────────────
    op.create_table(
        'b2b_deals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), sa.ForeignKey('tenants.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='pending_approval'),
        sa.Column('source_agent', sa.String(length=255), nullable=False),
        sa.Column('deal_maker_name', sa.String(length=255), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('airline_type', sa.String(length=20), nullable=True),
        sa.Column('airline_name', sa.String(length=255), nullable=True),
        # No contract_year, trigger_type, payout_type
        sa.Column('valid_from', sa.Date(), nullable=True),
        sa.Column('valid_to', sa.Date(), nullable=True),
        sa.Column('entity', sa.String(length=50), nullable=True),
        sa.Column('iata_number', sa.String(length=50), nullable=True),
        sa.Column('business_type', sa.String(length=50), nullable=True),
        sa.Column('entity_lcc', sa.String(length=50), nullable=True),
        sa.Column('login_id', sa.String(length=100), nullable=True),
        sa.Column('incentive_types', sa.JSON(), nullable=True),
        sa.Column('incentive_data', sa.JSON(), nullable=True),
        sa.Column('incl_excl_types', sa.JSON(), nullable=True),
        sa.Column('incl_excl_data', sa.JSON(), nullable=True),
        sa.Column('vice_versa', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── deal_approvals: add deal_type, drop old FK + unique, add new unique ──
    op.add_column('deal_approvals', sa.Column('deal_type', sa.String(length=20), nullable=False, server_default='upload'))

    # Drop the old FK constraint on deal_id (points to deals table)
    op.drop_constraint('deal_approvals_deal_id_fkey', 'deal_approvals', type_='foreignkey')

    # Drop the old unique index on deal_id alone.
    # SQLAlchemy named it ix_deal_approvals_deal_id (not a named constraint) because the column
    # had unique=True AND index=True — use drop_index, not drop_constraint.
    op.execute("DROP INDEX IF EXISTS ix_deal_approvals_deal_id")

    # Add new composite unique constraint on (deal_type, deal_id)
    op.create_unique_constraint('uq_deal_approvals_type_deal', 'deal_approvals', ['deal_type', 'deal_id'])


def downgrade() -> None:
    # Remove composite unique, restore original unique + FK
    op.drop_constraint('uq_deal_approvals_type_deal', 'deal_approvals', type_='unique')
    op.create_unique_constraint('deal_approvals_deal_id_key', 'deal_approvals', ['deal_id'])
    op.create_foreign_key(
        'deal_approvals_deal_id_fkey', 'deal_approvals',
        'deals', ['deal_id'], ['id'], ondelete='CASCADE',
    )
    op.drop_column('deal_approvals', 'deal_type')

    op.drop_table('b2b_deals')
    op.drop_table('airline_deals')
