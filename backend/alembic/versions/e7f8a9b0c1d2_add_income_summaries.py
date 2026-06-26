"""Add income_summaries table

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'income_summaries',
        sa.Column('id',               sa.Integer(),      nullable=False),
        sa.Column('tenant_id',        sa.Integer(),      nullable=False),
        sa.Column('created_by_id',    sa.Integer(),      nullable=False),
        sa.Column('batch_id',         sa.String(100),    nullable=False),
        sa.Column('name',             sa.String(500),    nullable=False),
        sa.Column('statement_name',   sa.String(500),    nullable=True),
        sa.Column('statement_type',   sa.String(10),     nullable=False, server_default='B2B'),
        sa.Column('agency',           sa.String(200),    nullable=False),
        sa.Column('valid_from',       sa.Date(),         nullable=False),
        sa.Column('valid_to',         sa.Date(),         nullable=False),
        sa.Column('ticket_count',     sa.Integer(),      nullable=False, server_default='0'),
        sa.Column('incentive_totals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('total_income',     sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('created_at',       sa.DateTime(),     nullable=True),
        sa.Column('updated_at',       sa.DateTime(),     nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'],                 ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['batch_id'],      ['ticket_statements.batch_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'created_by_id', 'batch_id',
                            name='uq_income_summaries_tenant_user_batch'),
    )
    op.create_index('ix_income_summaries_tenant_id', 'income_summaries', ['tenant_id'])
    op.create_index('ix_income_summaries_created_by_id', 'income_summaries', ['created_by_id'])
    op.create_index('ix_income_summaries_batch_id', 'income_summaries', ['batch_id'])


def downgrade() -> None:
    op.drop_index('ix_income_summaries_batch_id', table_name='income_summaries')
    op.drop_index('ix_income_summaries_created_by_id', table_name='income_summaries')
    op.drop_index('ix_income_summaries_tenant_id', table_name='income_summaries')
    op.drop_table('income_summaries')
