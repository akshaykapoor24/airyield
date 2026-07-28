"""add user verification + onboarding flags and login_ids.entity_id

Adds:
  - users.is_verified          (email verification gate for login)
  - users.onboarding_complete  (first-login onboarding wizard state)
  - login_ids.entity_id        (owning entity: one entity -> many login ids)

Existing users are backfilled to verified + onboarded so they are not locked
out or re-prompted by the new flows.

Revision ID: aa11bb22cc33
Revises: m6a7b8c9d0e1
Create Date: 2026-07-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa11bb22cc33'
down_revision: Union[str, None] = 'm6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # user flags — server_default false so the NOT NULL add succeeds on existing rows
    op.add_column('users', sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('users', sa.Column('onboarding_complete', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    # backfill: existing accounts keep working (already using the app)
    op.execute("UPDATE users SET is_verified = true, onboarding_complete = true")

    # login_ids -> owning entity (nullable; SET NULL if entity deleted)
    op.add_column('login_ids', sa.Column('entity_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_login_ids_entity_id', 'login_ids', 'entities',
        ['entity_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_login_ids_entity_id', 'login_ids', ['entity_id'])


def downgrade() -> None:
    op.drop_index('ix_login_ids_entity_id', table_name='login_ids')
    op.drop_constraint('fk_login_ids_entity_id', 'login_ids', type_='foreignkey')
    op.drop_column('login_ids', 'entity_id')
    op.drop_column('users', 'onboarding_complete')
    op.drop_column('users', 'is_verified')
