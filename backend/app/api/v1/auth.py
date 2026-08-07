from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.core import rate_limit
from app.schemas.user import (
    UserCreate, UserRead, Token, SignupPayload, LoginPayload, TokenWithUser,
    SignupResult, VerifyEmailPayload, ResendVerificationPayload, SimpleMessage,
    ChangePasswordPayload, ForgotPasswordPayload, ResetPasswordPayload, RefreshPayload,
)
from app.services.auth_service import AuthService

router = APIRouter()


async def _limit(request: Request, scope: str, limit: int, window_s: int, key: str | None = None) -> None:
    """Apply one rate-limit bucket, or 429. Fails open — see core/rate_limit.py."""
    allowed, retry_after = await rate_limit.hit(
        scope, key or rate_limit.client_ip(request), limit, window_s
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please wait a few minutes and try again.",
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/signup", response_model=SignupResult, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupPayload, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Public signup with two flows (the new user is always super_admin of their tenant):

    - corporate:  work email required (public providers rejected). The first
                  person from a company domain creates/owns that tenant; later
                  signups from the same domain get 409 (add them via User Management).
    - individual: any email allowed (incl. Gmail/Yahoo). Each signup gets its own
                  private single-person tenant. PAN required; GST optional.

    No session is issued: the account is created unverified and an email
    verification link is sent. The user must verify before they can sign in.
    """
    await _limit(request, "signup:ip", 5, 3600)
    return await AuthService.signup(db, payload)


@router.post("/verify-email", response_model=TokenWithUser)
async def verify_email(payload: VerifyEmailPayload, db: AsyncSession = Depends(get_db)):
    """Confirm an email verification token and sign the (now verified) user in."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.user import User
    from app.utils.security import create_access_token

    user = await AuthService.verify_email(db, payload.token)
    # reload with tenant eager-loaded for tenant_type serialisation
    result = await db.execute(
        select(User).options(selectinload(User.tenant)).where(User.id == user.id)
    )
    user = result.scalar_one()
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenWithUser(access_token=token, user=user)


@router.post("/resend-verification", response_model=SimpleMessage)
async def resend_verification(
    payload: ResendVerificationPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Resend the verification link. Always returns success (no user enumeration)."""
    await _limit(request, "resend:ip", 5, 3600)
    # Unconditional, before the existence check — same reasoning as forgot-password.
    await _limit(request, "resend:email", 3, 3600, key=rate_limit.email_key(payload.email))
    await AuthService.resend_verification(db, payload.email)
    return SimpleMessage(message="If that account exists and is unverified, a new verification link has been sent.")


@router.post("/login", response_model=TokenWithUser)
async def login_json(payload: LoginPayload, db: AsyncSession = Depends(get_db)):
    """JSON body login — returns token + full user object."""
    return await AuthService.login_json(db, payload)


@router.post("/login-form", response_model=Token)
async def login_form(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """OAuth2 form login — kept for Swagger /api/docs Authorize button."""
    return await AuthService.login(db, form.username, form.password)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """Admin-created user registration (no domain checks)."""
    return await AuthService.register(db, payload)


@router.post("/refresh", response_model=Token)
async def refresh(payload: RefreshPayload, db: AsyncSession = Depends(get_db)):
    """Exchange a live access token for a fresh one.

    The token travels in the BODY. It used to be a bare `str` parameter, which
    FastAPI binds as a query string — putting a live 24-hour credential into
    access logs, proxy logs and the Referer header.
    """
    return await AuthService.refresh(db, payload.refresh_token)


# ── Password management ────────────────────────────────────────────────────

@router.post("/change-password", response_model=TokenWithUser)
async def change_password(
    payload: ChangePasswordPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change your own password. Signs out every other session.

    A wrong `current_password` is a 400, not a 401 — see the comment in
    AuthService.change_password. The response carries a fresh access token so
    the calling tab survives its own change.
    """
    await _limit(request, "change-pw:user", 5, 900, key=str(current_user.id))
    return await AuthService.change_password(
        db, current_user, payload.current_password, payload.new_password
    )


@router.post("/forgot-password", response_model=SimpleMessage)
async def forgot_password(
    payload: ForgotPasswordPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a reset link. Always succeeds, whether or not the account exists."""
    await _limit(request, "forgot-pw:ip", 5, 900)
    # Counted BEFORE the existence check, and unconditionally: if only real
    # accounts were counted, 429-vs-200 would rebuild exactly the enumeration
    # oracle the constant response exists to prevent.
    await _limit(request, "forgot-pw:email", 3, 3600, key=rate_limit.email_key(payload.email))

    await AuthService.forgot_password(db, payload.email)
    return SimpleMessage(
        message=(
            "If an account exists for that email, we've sent a password reset link. "
            "It expires in 30 minutes."
        )
    )


@router.post("/reset-password", response_model=SimpleMessage)
async def reset_password(
    payload: ResetPasswordPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Redeem a reset link. No session is issued — the user signs in again."""
    await _limit(request, "reset-pw:ip", 10, 900)
    await AuthService.reset_password(db, payload.token, payload.new_password)
    return SimpleMessage(
        message="Your password has been updated. Please sign in with your new password."
    )
