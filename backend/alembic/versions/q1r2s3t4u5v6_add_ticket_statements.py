"""Add ticket_statements table

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'q1r2s3t4u5v6'
down_revision: Union[str, None] = 'p0q1r2s3t4u5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ticket_statements',
        sa.Column('batch_id',       sa.String(100),  nullable=False),
        sa.Column('tenant_id',      sa.Integer(),    nullable=False),
        sa.Column('statement_name', sa.String(500),  nullable=False),
        sa.Column('agency',         sa.String(200),  nullable=False),
        sa.Column('valid_from',     sa.Date(),       nullable=False),
        sa.Column('valid_to',       sa.Date(),       nullable=False),
        sa.Column('file_name',      sa.String(500),  nullable=False),
        sa.Column('created_by_id',  sa.Integer(),    nullable=False),
        sa.Column('created_at',     sa.DateTime(),   nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'],     ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('batch_id'),
    )
    op.create_index('ix_ticket_statements_tenant_id', 'ticket_statements', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_ticket_statements_tenant_id', table_name='ticket_statements')
    op.drop_table('ticket_statements')
