from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.user import UserCreate, UserRead, Token, SignupPayload, LoginPayload, TokenWithUser
from app.services.auth_service import AuthService

router = APIRouter()


@router.post("/signup", response_model=TokenWithUser, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupPayload, db: AsyncSession = Depends(get_db)):
    """
    Public signup. First user from a domain becomes company_admin.
    If that domain already has an admin, returns 409 with a message.
    """
    return await AuthService.signup(db, payload)


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
async def refresh(refresh_token: str, db: AsyncSession = Depends(get_db)):
    return await AuthService.refresh(db, refresh_token)
