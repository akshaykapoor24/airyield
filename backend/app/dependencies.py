from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.utils.security import verify_token, ACCESS_PURPOSE
from app.models.user import User, UserRole, role_matches

security = HTTPBearer()

# Paths a workspace without an active plan may still reach. Everything else
# answers 402 — see _assert_plan_active.
#   /auth/*      sign in, sign out, change password, refresh. A frozen user must
#                be able to log in, or they get an error instead of the screen
#                telling them who to email.
#   /users/me*   the frozen screen itself reads this to learn it is frozen, and
#                polls it when the user hits "Check again".
_PLAN_EXEMPT_PREFIXES = ("/api/v1/auth/", "/api/v1/users/me")

_NO_PLAN_DETAIL = (
    "Your workspace does not have an active plan. "
    "Please contact info@fareqube.com to activate it."
)


def is_platform_admin(user: User) -> bool:
    """The platform admin owns global master data and belongs to no tenant.

    Previously copy-pasted as a private _is_platform_admin into airlines.py,
    airports.py, suppliers.py and classes.py; it belongs here.
    """
    return role_matches(user.role, UserRole.PLATFORM_ADMIN)


def _assert_plan_active(user: User, path: str) -> None:
    """Refuse the request when the caller's workspace has no active plan.

    Deliberately here rather than as a dependency on each include_router in
    api/v1/__init__.py. Two reasons:

    1. get_current_user already selectinloads User.tenant, so this costs no
       extra query, and every current *and future* router inherits the gate
       without anyone remembering to wire it.
    2. A router-level dependency would force HTTPBearer onto endpoints that
       deliberately do not use it — bsp.stream_bsp_file and
       bsp_summary.stream_bsp_summary_file are opened with window.open (no
       Authorization header) and are authorised by a short-lived token in the
       query string. Gating inside get_current_user leaves them alone, because
       they never call it.
    """
    if any(path.startswith(p) for p in _PLAN_EXEMPT_PREFIXES):
        return
    if is_platform_admin(user):
        return
    # A non-platform-admin with no tenant is only reachable via the FK's
    # ondelete="SET NULL"; that orphaned state is not a licence to use the app.
    if user.tenant is None or not user.tenant.has_active_plan:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=_NO_PLAN_DETAIL)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Only an access token opens a session. Without this gate every token signed
    # with SECRET_KEY works as a Bearer credential — the link in a verification
    # email was a full API session for its whole 48-hour life, and a password
    # reset link would have been the same.
    # Tokens minted before this shipped carry no purpose claim, so None is
    # allowed for one release; tighten to `!= ACCESS_PURPOSE` once they have all
    # expired (ACCESS_TOKEN_EXPIRE_MINUTES, currently 24h).
    if payload.get("purpose") not in (None, ACCESS_PURPOSE):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # A file-access token's `sub` is a batch id, not an int — unguarded this was
    # an unhandled ValueError (500) rather than a 401.
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # eager-load tenant so UserRead.tenant_type is populated without a lazy-load
    result = await db.execute(
        select(User).options(selectinload(User.tenant)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    # A password change revokes every token issued at or before it. Skipped
    # entirely while password_changed_at is NULL, which is every user until they
    # first change their password — so shipping this signs nobody out.
    if user.password_changed_at is not None:
        iat = payload.get("iat")
        if iat is None or datetime.utcfromtimestamp(int(iat)) < user.password_changed_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired. Please sign in again.",
            )

    # Last, so that an expired session or a deactivated account still reports
    # itself as such rather than as a billing problem.
    _assert_plan_active(user, request.url.path)
    return user


def require_role(*roles: UserRole):
    async def checker(current_user: User = Depends(get_current_user)) -> User:
        # role_matches (models/user.py) does the name/value/case collapsing the
        # users.role column's NAME-based storage forces on us.
        if not role_matches(current_user.role, *roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return checker
