"""merge migration heads

Revision ID: 23f7d53e7e14
Revises: r2s3t4u5v6w7, s3t4u5v6w7x8
Create Date: 2026-05-27 12:48:55.721477

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '23f7d53e7e14'
down_revision: Union[str, None] = ('r2s3t4u5v6w7', 's3t4u5v6w7x8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
