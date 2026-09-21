"""Who may see, and who may change, a workspace's entities and login IDs / IATA numbers.

ONE RULE, KEPT HERE so My Profile's two APIs — and anything that reads them later, such
as the deal forms — cannot disagree about it:

    SUPER ADMIN      manages them: adds, edits, deletes, uploads. Sees their own.
                     (Also the only user of an individual account, so a one-person
                     workspace keeps full control.)
    EVERYONE ELSE    sees exactly the entities the Super Admin granted them in
                     Admin → User management (user_entity_access), plus the login IDs
                     under those entities — read-only. Nothing else, and no changes.

The grant is the WHOLE of a team member's view. Entities are owned by the Super Admin who
created them (user_entities.user_id), so "my entities" means something different per
role: the ones I own if I manage them, the ones granted to me if I do not.

Enforced on the server — the UI hiding a button is not a restriction.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException

from sqlalchemy import select

from app.dependencies import get_current_user
from app.models.user import User, UserRole, role_matches
from app.models.user_entity import UserEntity
from app.models.user_entity_access import UserEntityAccess
from app.models.user_login_id import UserLoginId

MANAGED_BY_SUPER_ADMIN = (
    "Entities and login IDs are managed by your Super Admin. Ask them to add or change one."
)


def can_manage_entities(user: User) -> bool:
    """Is this user the one who manages the workspace's entities and login IDs?

    role_matches rather than `==`: the role column persists the enum NAME, and this must
    not depend on which spelling a given code path happens to hold.
    """
    return role_matches(user.role, UserRole.SUPER_ADMIN)


def granted_entity_ids(user: User):
    """The entity ids granted to this user — a subquery, so the filter stays one query."""
    return select(UserEntityAccess.entity_id).where(UserEntityAccess.user_id == user.id)


def entity_scope(user: User):
    """WHERE-clause for the `user_entities` rows this user may see."""
    if can_manage_entities(user):
        return UserEntity.user_id == user.id
    return UserEntity.id.in_(granted_entity_ids(user))


def login_scope(user: User):
    """WHERE-clause for the `user_login_ids` rows this user may see — for a team member,
    every login ID under an entity granted to them, and only those."""
    if can_manage_entities(user):
        return UserLoginId.user_id == user.id
    return UserLoginId.entity_id.in_(granted_entity_ids(user))


def require_entity_manager(current_user: User = Depends(get_current_user)) -> User:
    """Dependency for every endpoint that CHANGES an entity or a login ID."""
    if not can_manage_entities(current_user):
        raise HTTPException(status_code=403, detail=MANAGED_BY_SUPER_ADMIN)
    return current_user
