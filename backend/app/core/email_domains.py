"""Free / public email providers.

Corporate signups must use a real company (work) email, so we reject these
domains for the corporate flow and steer such users to the Individual flow.
This list is the single source of truth — the frontend mirrors a subset only
for UX hints; the backend is authoritative.
"""

PUBLIC_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.co.in", "yahoo.in", "ymail.com", "rocketmail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "proton.me", "protonmail.com", "pm.me",
    "rediffmail.com", "rediff.com",
    "zoho.com", "zohomail.com",
    "gmx.com", "gmx.net", "mail.com", "yandex.com",
})


def extract_domain(email: str) -> str:
    """Return the lowercased domain part of an email address."""
    return email.rsplit("@", 1)[-1].strip().lower()


def is_public_domain(email: str) -> bool:
    """True if the email belongs to a known free/public provider."""
    return extract_domain(email) in PUBLIC_EMAIL_DOMAINS
