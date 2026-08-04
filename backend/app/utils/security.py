from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


# ── Email verification tokens ───────────────────────────────────────────────
# Stateless (no DB table): a short-lived JWT carrying the user id and a purpose
# claim so it can't be used as an access token.
EMAIL_VERIFY_PURPOSE = "email_verify"


def create_email_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.EMAIL_TOKEN_EXPIRE_HOURS)
    to_encode = {"sub": str(user_id), "purpose": EMAIL_VERIFY_PURPOSE, "exp": expire}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_email_token(token: str) -> Optional[int]:
    """Return the user id if `token` is a valid, unexpired email-verify token."""
    payload = verify_token(token)
    if not payload or payload.get("purpose") != EMAIL_VERIFY_PURPOSE:
        return None
    try:
        return int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None


# ── Source-file access tokens ───────────────────────────────────────────────
# The local equivalent of a GCS signed URL: a file kept on local disk (because the
# bucket was unreachable at upload time) still has to be openable by a plain
# window.open, which sends no Authorization header. So the capability travels in the
# URL instead — short-lived, scoped to one batch and one file kind, and carrying a
# purpose claim so it can never be replayed as an access token.
FILE_ACCESS_PURPOSE = "file_access"


def create_file_token(batch_id: str, kind: str, expires_minutes: int = 60) -> str:
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    return jwt.encode(
        {"sub": batch_id, "kind": kind, "purpose": FILE_ACCESS_PURPOSE, "exp": expire},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


def verify_file_token(token: str, batch_id: str, kind: str) -> bool:
    """True only for an unexpired file token issued for exactly this batch and kind."""
    payload = verify_token(token)
    return bool(
        payload
        and payload.get("purpose") == FILE_ACCESS_PURPOSE
        and payload.get("sub") == batch_id
        and payload.get("kind") == kind
    )
