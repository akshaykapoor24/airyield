"""Password rules — the single source of truth for what we will accept.

Deliberately dependency-free (no imports from app.models / app.schemas) so both
the Pydantic schemas and the auth service can use it without an import cycle,
mirroring how core/email_domains.py is shared.

MAX_PASSWORD_BYTES is not a style choice. bcrypt refuses anything longer than 72
bytes — bcrypt 5.x *raises* rather than truncating — so a longer password is a
crash, not a weak password. It has to be caught before the hash function is ever
reached. See verify_password in app/utils/security.py for the other half of that
fix: the login path has no policy (by design), so the primitive itself must also
be safe.
"""
import re
import unicodedata

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72     # bcrypt's hard limit, measured in UTF-8 bytes

# Small, high-frequency blocklist. Not a substitute for a real breach corpus —
# it just stops the passwords that show up first in every credential-stuffing
# list, plus the ones specific to this product.
_COMMON_PASSWORDS: frozenset[str] = frozenset({
    "password", "password1", "password123", "passw0rd", "p@ssw0rd", "p@ssword",
    "12345678", "123456789", "1234567890", "123123123", "111111111", "987654321",
    "qwertyui", "qwerty123", "qwertyuiop", "asdfghjkl", "zxcvbnm1", "1qaz2wsx",
    "iloveyou", "sunshine", "princess", "football", "baseball", "superman",
    "trustno1", "letmein1", "welcome1", "welcome123", "admin123", "administrator",
    "abc12345", "abcd1234", "a1b2c3d4", "changeme", "change_me", "secret123",
    "monkey123", "dragon123", "master123", "shadow123", "michael1", "jennifer1",
    "fareqube", "fareqube1", "fareqube123", "airyield", "airyield1", "airyield123",
    "india123", "mumbai123", "delhi123", "company1", "corporate1",
})


def _has_class(password: str) -> int:
    """How many of {lower, upper, digit, other} the password uses."""
    return sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(not c.isalnum() for c in password),
    ))


def _name_fragments(full_name: str) -> list[str]:
    """Name parts long enough to be worth checking (>= 4 chars)."""
    return [p.lower() for p in re.split(r"\W+", full_name or "") if len(p) >= 4]


def password_problem(
    password: str,
    *,
    email: str | None = None,
    full_name: str | None = None,
) -> str | None:
    """None if the password is acceptable, else a user-facing sentence saying why not.

    Leading/trailing whitespace is neither stripped nor rejected: NIST SP 800-63B
    says accept all printable characters, and silently trimming would change what
    the user typed — which then fails at login for reasons they cannot see.
    """
    if not password:
        return "Password is required."

    # Normalise only for the *comparisons* below, never for storage — the raw
    # string is what gets hashed.
    lowered = unicodedata.normalize("NFKC", password).casefold()

    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."

    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return (
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes — about "
            f"{MAX_PASSWORD_BYTES} characters, fewer if you use emoji or accented letters."
        )

    if _has_class(password) < 3:
        return (
            "Password must use at least three of: lowercase letters, uppercase "
            "letters, numbers, and symbols."
        )

    if lowered in _COMMON_PASSWORDS:
        return "That password is too common. Please choose something less predictable."

    if email:
        local_part = email.split("@", 1)[0].strip().casefold()
        if len(local_part) >= 4 and local_part in lowered:
            return "Password must not contain your email address."

    for fragment in _name_fragments(full_name or ""):
        if fragment in lowered:
            return "Password must not contain your name."

    return None


def validate_password(
    password: str,
    *,
    email: str | None = None,
    full_name: str | None = None,
) -> str:
    """Return the password unchanged, or raise ValueError with the reason.

    Used as a Pydantic AfterValidator (yields 422) and called directly from the
    auth service (where the caller converts it to a 400 with a clean message —
    Pydantic prefixes validator errors with "Value error, ", which is not
    something we want to show a user mid-flow).
    """
    problem = password_problem(password, email=email, full_name=full_name)
    if problem:
        raise ValueError(problem)
    return password
