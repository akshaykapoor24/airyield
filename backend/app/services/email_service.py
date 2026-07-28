"""Email delivery for account verification.

Dev-friendly by design: when EMAILS_ENABLED is False or SMTP is not configured,
the verification link is written to the log instead of being sent, so local
development works without a mail server. Set EMAILS_ENABLED=true and the SMTP_*
settings in .env to turn on real email delivery — no code change required.
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.EMAILS_ENABLED and settings.SMTP_HOST)


def _send_sync(to_email: str, subject: str, html_body: str, text_body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def send_verification_email(to_email: str, link: str) -> None:
    """Send (or log, in dev) the account verification link."""
    if not _smtp_configured():
        logger.info("[email:dev] Verification link for %s -> %s", to_email, link)
        return

    subject = "Verify your AirYield account"
    text_body = (
        f"Welcome to AirYield!\n\n"
        f"Please verify your email address by opening this link:\n{link}\n\n"
        f"If you didn't create this account, you can ignore this email."
    )
    html_body = f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:auto">
  <h2 style="color:#1e3a5f">Verify your email</h2>
  <p>Welcome to AirYield! Confirm your email address to activate your account.</p>
  <p style="margin:24px 0">
    <a href="{link}"
       style="background:#1e3a5f;color:#fff;text-decoration:none;padding:12px 20px;border-radius:10px;font-weight:600">
      Verify my account
    </a>
  </p>
  <p style="color:#6b7280;font-size:12px">Or paste this link into your browser:<br>{link}</p>
  <p style="color:#9ca3af;font-size:12px">If you didn't create this account, you can ignore this email.</p>
</div>"""

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html_body, text_body)
        logger.info("[email] Verification email sent to %s", to_email)
    except Exception as exc:  # don't fail signup because SMTP is down
        logger.error("[email] Failed to send verification email to %s: %s", to_email, exc)
