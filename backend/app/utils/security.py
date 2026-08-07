import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from app.config import settings
from app.core.password_policy import MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    # bcrypt 5.x raises above 72 bytes rather than truncating. Fail here with a
    # message a caller can show, instead of letting the library's own exception
    # surface as a 500.
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # bcrypt raises above 72 bytes. Returning False rather than propagating
        # is what closes a user-enumeration oracle on login: `if not user or not
        # verify_password(...)` short-circuits, so the exception only fired when
        # the email existed — giving 500 for a real account and 401 for a fake
        # one. An over-long password must now fail identically either way.
        return False


# ── Access tokens ───────────────────────────────────────────────────────────
# Access tokens carry purpose="access". Every other token minted in this module
# carries its own purpose, and get_current_user rejects anything that is not an
# access token — without that gate an email-verification link doubles as a full
# API session.
ACCESS_PURPOSE = "access"


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = datetime.utcnow()
    # `iat` is what lets a password change revoke tokens issued before it. jose
    # encodes it via timegm(utctimetuple()), i.e. floored to whole seconds —
    # see the comment on User.password_changed_at, which is floored to match.
    to_encode["iat"] = now
    to_encode.setdefault("purpose", ACCESS_PURPOSE)
    to_encode["exp"] = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
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


# ── Password reset tokens ───────────────────────────────────────────────────
# Stateless, like the two above, but with one extra claim that does the work of
# a whole database table: a fingerprint of the user's CURRENT password hash.
#
# Redeeming the link rewrites hashed_password, so the fingerprint stops matching
# and the same link cannot be used twice. The same thing happens if the password
# changes by any other route (change-password today, an admin reset tomorrow),
# so cross-channel invalidation is a property of the data model rather than a
# line of code someone has to remember to write. bcrypt re-salts on every hash,
# so even re-setting the SAME password rotates the fingerprint.
PASSWORD_RESET_PURPOSE = "password_reset"


def _password_fingerprint(user_id: int, hashed_password: str) -> str:
    """Truncated HMAC of the user's current bcrypt hash, keyed by SECRET_KEY.

    Reveals nothing about the hash: HMAC-SHA256 under a secret key is a PRF, and
    anyone who could invert it already holds the key that signs every token. The
    16-hex truncation is a URL-length choice, not a security parameter — the
    value sits inside a signed envelope, so it cannot be tampered with.
    """
    msg = f"{user_id}:{hashed_password}".encode("utf-8")
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]


def create_password_reset_token(user_id: int, hashed_password: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {
            "sub": str(user_id),
            "purpose": PASSWORD_RESET_PURPOSE,
            "fp": _password_fingerprint(user_id, hashed_password),
            "exp": expire,
        },
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


def read_password_reset_token(token: str) -> Optional[tuple[int, str]]:
    """(user_id, fingerprint) if the signature, purpose and expiry are good.

    Deliberately does not touch the database — the caller loads the user and
    compares the fingerprint with hmac.compare_digest, keeping this module free
    of model imports like the rest of the file.
    """
    payload = verify_token(token)
    if not payload or payload.get("purpose") != PASSWORD_RESET_PURPOSE:
        return None
    fingerprint = payload.get("fp")
    if not isinstance(fingerprint, str):
        return None
    try:
        return int(payload["sub"]), fingerprint
    except (KeyError, ValueError, TypeError):
        return None


def password_fingerprint_matches(user_id: int, hashed_password: str, fingerprint: str) -> bool:
    """Constant-time check that a reset token was minted for this exact hash."""
    return hmac.compare_digest(_password_fingerprint(user_id, hashed_password), fingerprint)
