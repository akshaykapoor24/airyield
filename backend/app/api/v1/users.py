from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.user import UserRead, UserUpdate, UserCreate, UserRoleUpdate

router = APIRouter()

ADMIN_ROLES = [UserRole.SUPER_ADMIN]
ASSIGNABLE_ROLES = {
    UserRole.COMPANY_ADMIN,
    UserRole.OPERATIONS_USER,
    UserRole.FINANCE_USER,
    UserRole.APPROVER,
    UserRole.VIEWER,
}


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Current user ───────────────────────────────────────────────────────────
@router.get("/me", response_model=UserRead)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app import crud
    return await crud.user.update(db, db_obj=current_user, obj_in=payload)


# ── Admin: list users in same tenant ──────────────────────────────────────
@router.get("/", response_model=list[UserRead])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    result = await db.execute(
        select(User)
        .where(User.tenant_id == current_user.tenant_id)
        .offset(skip).limit(limit)
    )
    return result.scalars().all()


# ── Admin: create user in same tenant ─────────────────────────────────────
@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    from app.services.auth_service import AuthService

    # enforce same domain
    admin_domain = current_user.email.split("@")[-1].lower()
    user_domain  = payload.email.split("@")[-1].lower()
    if user_domain != admin_domain:
        raise HTTPException(
            status_code=400,
            detail=f"Users must belong to the same domain (@{admin_domain})."
        )
    # check duplicate
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    if payload.role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Super Admin can assign only company_admin, operations_user, finance_user, approver, viewer roles.",
        )

    return await AuthService.register(db, payload, tenant_id=current_user.tenant_id)


# ── Admin: get single user (same tenant only) ──────────────────────────────
@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ── Admin: update user role (same tenant only) ─────────────────────────────
@router.patch("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own role")
    if payload.role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Super Admin can assign only company_admin, operations_user, finance_user, approver, viewer roles.",
        )
    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user


# ── Admin: toggle active/inactive (same tenant only) ──────────────────────
@router.patch("/{user_id}/toggle-active", response_model=UserRead)
async def toggle_user_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return user


# ── Admin: delete user (same tenant only) ─────────────────────────────────
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_require_admin),
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.delete(user)
    await db.commit()
