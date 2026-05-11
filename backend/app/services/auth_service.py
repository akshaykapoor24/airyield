from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.schemas.user import UserCreate, SignupPayload, LoginPayload, TokenWithUser
from app.utils.security import hash_password, verify_password, create_access_token


def _extract_domain(email: str) -> str:
    return email.split("@")[-1].lower()


async def _get_or_create_tenant(db: AsyncSession, domain: str, name: str | None = None) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.domain == domain))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(domain=domain, name=name)
        db.add(tenant)
        await db.flush()   # get id without full commit
    return tenant


class AuthService:

    # ── Admin-created user ─────────────────────────────────────────────────
    @staticmethod
    async def register(db: AsyncSession, payload: UserCreate, tenant_id: int | None = None) -> User:
        result = await db.execute(select(User).where(User.email == payload.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        user = User(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=payload.role,
            department=payload.department,
            tenant_id=tenant_id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    # ── Public signup with domain-based tenant + admin logic ───────────────
    @staticmethod
    async def signup(db: AsyncSession, payload: SignupPayload) -> TokenWithUser:
        domain = _extract_domain(payload.email)

        # check email not already taken
        existing_email = await db.execute(select(User).where(User.email == payload.email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

        # check if a super admin already exists for this domain
        existing_admin = await db.execute(
            select(User).where(
                User.email.like(f"%@{domain}"),
                User.role == UserRole.SUPER_ADMIN,
            )
        )
        if existing_admin.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Your domain '{domain}' already has an account. "
                    f"Please contact your Super Admin to be added as a user."
                ),
            )

        # find or create tenant for this domain
        tenant = await _get_or_create_tenant(db, domain=domain, name=payload.company_name)

        # first user from domain → super_admin of their company
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=UserRole.SUPER_ADMIN,
            department=payload.company_name or None,
            tenant_id=tenant.id,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        token = create_access_token({"sub": str(user.id), "role": user.role})
        return TokenWithUser(access_token=token, user=user)

    # ── JSON login ─────────────────────────────────────────────────────────
    @staticmethod
    async def login_json(db: AsyncSession, payload: LoginPayload) -> TokenWithUser:
        result = await db.execute(select(User).where(User.email == payload.email))
        user = result.scalar_one_or_none()

        if not user or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account has been deactivated. Contact your admin.",
            )

        token = create_access_token({"sub": str(user.id), "role": user.role})
        return TokenWithUser(access_token=token, user=user)

    # ── OAuth2 form login ──────────────────────────────────────────────────
    @staticmethod
    async def login(db: AsyncSession, email: str, password: str) -> dict:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
        token = create_access_token({"sub": str(user.id), "role": user.role})
        return {"access_token": token, "token_type": "bearer"}

    @staticmethod
    async def refresh(db: AsyncSession, refresh_token: str) -> dict:
        from app.utils.security import verify_token
        payload = verify_token(refresh_token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        token = create_access_token({"sub": payload["sub"], "role": payload["role"]})
        return {"access_token": token, "token_type": "bearer"}
