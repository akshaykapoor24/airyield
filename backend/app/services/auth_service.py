from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.user import User, UserRole
from app.models.tenant import Tenant, TenantType
from app.schemas.user import UserCreate, SignupPayload, LoginPayload, TokenWithUser
from app.core.email_domains import extract_domain, is_public_domain
from app.utils.security import hash_password, verify_password, create_access_token


async def _get_or_create_tenant(
    db: AsyncSession,
    domain: str,
    name: str | None = None,
    tenant_type: TenantType = TenantType.CORPORATE,
) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.domain == domain))
    tenant = result.scalar_one_or_none()
    if not tenant:
        tenant = Tenant(domain=domain, name=name, tenant_type=tenant_type)
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

    # ── Public signup: corporate (domain-based) or individual (private) ────
    @staticmethod
    async def signup(db: AsyncSession, payload: SignupPayload) -> TokenWithUser:
        # email uniqueness applies to both flows
        existing_email = await db.execute(select(User).where(User.email == payload.email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

        if payload.account_type == "corporate":
            tenant = await AuthService._signup_corporate_tenant(db, payload)
        else:
            tenant = await AuthService._signup_individual_tenant(db, payload)

        # the signing-up user is always super_admin of their own tenant
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=UserRole.SUPER_ADMIN,
            department=payload.company_name or None,
            tenant=tenant,                      # set relationship so tenant_type serialises
        )
        db.add(user)
        await db.commit()

        # reload with tenant eager-loaded for the response (tenant_type)
        result = await db.execute(
            select(User).options(selectinload(User.tenant)).where(User.id == user.id)
        )
        user = result.scalar_one()

        token = create_access_token({"sub": str(user.id), "role": user.role})
        return TokenWithUser(access_token=token, user=user)

    # ── Corporate: discover/create a company tenant by work-email domain ───
    @staticmethod
    async def _signup_corporate_tenant(db: AsyncSession, payload: SignupPayload) -> Tenant:
        domain = extract_domain(payload.email)

        # defense-in-depth: schema already rejects public domains for corporate
        if is_public_domain(payload.email):
            raise HTTPException(
                status_code=422,
                detail="Corporate signup requires a work email. Choose 'Individual' for a personal email.",
            )

        # one super_admin per corporate tenant — keyed on the tenant's domain
        existing_admin = await db.execute(
            select(User)
            .join(Tenant, User.tenant_id == Tenant.id)
            .where(Tenant.domain == domain, User.role == UserRole.SUPER_ADMIN)
        )
        if existing_admin.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Your domain '{domain}' already has an account. "
                    f"Please contact your Super Admin to be added as a user."
                ),
            )

        tenant = await _get_or_create_tenant(
            db, domain=domain, name=payload.company_name, tenant_type=TenantType.CORPORATE,
        )
        tenant.tenant_type = TenantType.CORPORATE
        if payload.pan_number:
            tenant.pan_number = payload.pan_number
        if payload.gst_registered:
            tenant.gst_number = payload.gst_number
        return tenant

    # ── Individual: always a fresh private single-person tenant ────────────
    @staticmethod
    async def _signup_individual_tenant(db: AsyncSession, payload: SignupPayload) -> Tenant:
        tenant = Tenant(
            tenant_type=TenantType.INDIVIDUAL,
            domain=None,                                   # no shared company domain
            name=payload.company_name or payload.full_name,
            pan_number=payload.pan_number,
            gst_number=payload.gst_number if payload.gst_registered else None,
        )
        db.add(tenant)
        await db.flush()   # populate tenant.id
        return tenant

    # ── JSON login ─────────────────────────────────────────────────────────
    @staticmethod
    async def login_json(db: AsyncSession, payload: LoginPayload) -> TokenWithUser:
        result = await db.execute(
            select(User).options(selectinload(User.tenant)).where(User.email == payload.email)
        )
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
