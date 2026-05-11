"""Fix deal_approvals unique index — drop ix_deal_approvals_deal_id, add composite unique

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-04-29 00:00:00.000000

Previous migration tried to drop a unique *constraint* named 'deal_approvals_deal_id_key'
but SQLAlchemy created a unique *index* named 'ix_deal_approvals_deal_id' (because the column
had both unique=True and index=True). The wrong name silently did nothing, leaving the old
unique index in place and causing UniqueViolationError when inserting multiple deal_approvals
rows with the same deal_id but different deal_type values.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'k5l6m7n8o9p0'
down_revision: Union[str, None] = 'j4k5l6m7n8o9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the unique index on deal_id alone (idempotent — safe if already dropped)
    op.execute("DROP INDEX IF EXISTS ix_deal_approvals_deal_id")

    # Create composite unique constraint on (deal_type, deal_id) if not already there
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_deal_approvals_type_deal'
            ) THEN
                ALTER TABLE deal_approvals
                ADD CONSTRAINT uq_deal_approvals_type_deal UNIQUE (deal_type, deal_id);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint('uq_deal_approvals_type_deal', 'deal_approvals', type_='unique')
    op.create_index('ix_deal_approvals_deal_id', 'deal_approvals', ['deal_id'], unique=True)
