from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.utils.security import verify_token, ACCESS_PURPOSE
from app.models.user import User, UserRole

security = HTTPBearer()


async def get_current_user(
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
    return user


def require_role(*roles: UserRole):
    allowed_tokens = set()
    for role in roles:
        allowed_tokens.update({
            role,
            role.name,
            role.value,
            role.name.lower(),
            role.value.lower(),
            role.name.upper(),
            role.value.upper(),
        })

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        user_tokens = {current_user.role}
        if isinstance(current_user.role, UserRole):
            user_tokens.update({
                current_user.role.name,
                current_user.role.value,
                current_user.role.name.lower(),
                current_user.role.value.lower(),
                current_user.role.name.upper(),
                current_user.role.value.upper(),
            })
        else:
            role_str = str(current_user.role)
            user_tokens.update({role_str, role_str.lower(), role_str.upper()})

        if user_tokens.isdisjoint(allowed_tokens):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return checker
