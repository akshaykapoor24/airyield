from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.user import User, UserRole
from app.models.tenant import Tenant, TenantType
from app.schemas.user import UserCreate, SignupPayload, LoginPayload, TokenWithUser, SignupResult
from app.core.email_domains import extract_domain, is_public_domain
from app.services.email_service import send_verification_email
from app.utils.security import (
    hash_password, verify_password, create_access_token,
    create_email_token, verify_email_token,
)


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


async def _needs_onboarding(db: AsyncSession, tenant_id: int | None) -> bool:
    """Whether a new user of this tenant should see the first-login wizard.

    Only CORPORATE workspaces do: entities and airline login IDs are company
    setup. An individual account is a private single-person workspace with
    nothing to configure up front, so it starts already onboarded and adds those
    from My Profile whenever it wants.
    """
    if tenant_id is None:
        return False
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    return bool(tenant and tenant.tenant_type == TenantType.CORPORATE)


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
            # admin-created teammates are trusted (no email verification needed),
            # but still run the first-login onboarding when it applies to them.
            is_verified=True,
            onboarding_complete=not await _needs_onboarding(db, tenant_id),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    # ── Public signup: corporate (domain-based) or individual (private) ────
    @staticmethod
    async def signup(db: AsyncSession, payload: SignupPayload) -> SignupResult:
        # email uniqueness applies to both flows
        existing_email = await db.execute(select(User).where(User.email == payload.email))
        if existing_email.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

        is_corporate = payload.account_type == "corporate"
        if is_corporate:
            tenant = await AuthService._signup_corporate_tenant(db, payload)
        else:
            tenant = await AuthService._signup_individual_tenant(db, payload)

        # the signing-up user is always super_admin of their own tenant. The
        # account starts unverified — no session is issued until the emailed
        # verification link is confirmed.
        user = User(
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=UserRole.SUPER_ADMIN,
            department=payload.company_name or None,
            is_verified=False,
            # Only corporate workspaces run the first-login setup wizard; an
            # individual account is born onboarded (see _needs_onboarding).
            onboarding_complete=not is_corporate,
            tenant=tenant,                      # set relationship so tenant_type serialises
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        link = f"{settings.FRONTEND_URL}/verify-email?token={create_email_token(user.id)}"
        await send_verification_email(user.email, link)

        return SignupResult(
            email=user.email,
            is_verified=False,
            message="Account created. We've emailed you a verification link — "
                    "verify your email, then sign in.",
            verification_url=link if settings.DEBUG else None,   # dev convenience only
        )

    # ── Email verification ─────────────────────────────────────────────────
    @staticmethod
    async def verify_email(db: AsyncSession, token: str) -> User:
        user_id = verify_email_token(token)
        if not user_id:
            raise HTTPException(
                status_code=400,
                detail="This verification link is invalid or has expired. Please request a new one.",
            )
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Account not found.")
        if not user.is_verified:
            user.is_verified = True
            await db.commit()
        return user

    @staticmethod
    async def resend_verification(db: AsyncSession, email: str) -> None:
        """Resend the link if the account exists and is unverified. Always
        succeeds silently to avoid leaking which emails are registered."""
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user and not user.is_verified:
            link = f"{settings.FRONTEND_URL}/verify-email?token={create_email_token(user.id)}"
            await send_verification_email(user.email, link)

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
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email before signing in — check your inbox "
                       "for the verification link.",
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
