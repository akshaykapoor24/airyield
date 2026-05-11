from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.utils.security import verify_token
from app.models.user import User, UserRole
from app import crud

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await crud.user.get(db, id=int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
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
