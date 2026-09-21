"""Deleting a My Profile entity deletes its login IDs / IATA numbers too

`user_login_ids.entity_id` was ON DELETE SET NULL, from when a login ID could stand on its
own. Since profile_entity_login_01 it cannot: every login ID belongs to an entity, takes
its state from it and (unless overridden) its city, and the API refuses one without an
entity. SET NULL therefore turned every deleted entity's login IDs into orphans the owner
then had to find and clean up by hand — rows that show "No entity", have no state, and can
no longer be saved without being reassigned.

CASCADE makes the rule a database fact: an entity's login IDs go with it, whoever deletes
it. The Delete popup on My Profile → Entities lists them first, so it is never a surprise.

Revision ID: profile_login_cascade_01
Revises: profile_entity_login_01
Create Date: 2026-09-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "profile_login_cascade_01"
down_revision: Union[str, None] = "profile_entity_login_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "user_login_ids_entity_id_fkey"   # Postgres' default name for it


def _repoint(ondelete: str) -> None:
    op.drop_constraint(_FK, "user_login_ids", type_="foreignkey")
    op.create_foreign_key(
        _FK, "user_login_ids", "user_entities", ["entity_id"], ["id"], ondelete=ondelete,
    )


def upgrade() -> None:
    _repoint("CASCADE")


def downgrade() -> None:
    _repoint("SET NULL")
