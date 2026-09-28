"""Email verification as the platform admin sees it — Subscriptions → Verified column.

WHO CAN BE UNVERIFIED
    Only a workspace's founding account. Public signup creates the Super Admin unverified
    and emails a link; sign-in is refused until it is clicked (services/auth_service).
    Teammates added from User management are born verified. So in practice the column is
    about the owner — but it is computed over every member, so an unverified account that
    arrives by some future route still shows up here instead of being invisible.

VERIFYING BY HAND BYPASSES A SECURITY CHECK
    The link proves the person controls the mailbox. Verifying without it is sometimes
    right (the link went to spam, the owner called in), so it is allowed — but it is
    recorded: `verified_by_id` names the platform admin and `verified_at` says when, and
    the console shows it. A link verification leaves `verified_by_id` NULL.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.services.email_service import send_verification_email
from app.utils.security import create_email_token

STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"
STATUS_NO_USERS = "no_users"


def state_for(owner: Optional[User], members: Iterable[User], names: dict[int, str]) -> dict:
    """One workspace's verification state. `names` resolves verified_by_id to a person."""
    members = list(members)
    unverified = [u.email for u in sorted(members, key=lambda u: u.id) if not u.is_verified]
    if not members:
        status = STATUS_NO_USERS
    else:
        status = STATUS_UNVERIFIED if unverified else STATUS_VERIFIED
    subject = owner or (members[0] if members else None)
    verified_by = None
    if subject is not None and subject.is_verified and subject.verified_by_id:
        verified_by = names.get(subject.verified_by_id, "a platform admin")
    return {
        "status": status,
        "unverified_emails": unverified,
        "verified_at": subject.verified_at if subject is not None and subject.is_verified else None,
        "verified_by": verified_by,
    }


async def states(db: AsyncSession, tenant_ids: list[int], owners: dict[int, User]) -> dict[int, dict]:
    """``{tenant_id: state}`` in two queries, whatever the page size."""
    if not tenant_ids:
        return {}
    members = (await db.execute(
        select(User).where(User.tenant_id.in_(tenant_ids)).order_by(User.id)
    )).scalars().all()
    by_tenant: dict[int, list[User]] = {tid: [] for tid in tenant_ids}
    for u in members:
        by_tenant[u.tenant_id].append(u)

    verifier_ids = {u.verified_by_id for u in members if u.verified_by_id}
    names: dict[int, str] = {}
    if verifier_ids:
        rows = (await db.execute(select(User.id, User.full_name).where(User.id.in_(verifier_ids)))).all()
        names = {uid: name for uid, name in rows}
    return {tid: state_for(owners.get(tid), by_tenant[tid], names) for tid in tenant_ids}


async def _unverified(db: AsyncSession, tenant_id: int) -> list[User]:
    return list((await db.execute(
        select(User).where(User.tenant_id == tenant_id, User.is_verified.is_(False)).order_by(User.id)
    )).scalars().all())


async def verify_members(db: AsyncSession, tenant_id: int, admin: User) -> list[str]:
    """Mark every unverified member of the workspace verified, on `admin`'s authority.
    Returns the emails verified — empty when there was nothing to do, which is not an
    error: a double-click must not fail."""
    pending = await _unverified(db, tenant_id)
    now = datetime.utcnow()
    for u in pending:
        u.is_verified = True
        u.verified_at = now
        u.verified_by_id = admin.id
    if pending:
        await db.commit()
    return [u.email for u in pending]


async def resend_links(db: AsyncSession, tenant_id: int) -> list[str]:
    """Email a fresh verification link to every unverified member. Raises if a send fails,
    so the admin is not told a link went when it did not."""
    pending = await _unverified(db, tenant_id)
    for u in pending:
        link = f"{settings.FRONTEND_URL}/verify-email?token={create_email_token(u.id)}"
        await send_verification_email(u.email, link, raise_errors=True)
    return [u.email for u in pending]
