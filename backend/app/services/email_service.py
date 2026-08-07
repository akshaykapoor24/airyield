"""Email delivery for account verification.

Always sends over SMTP — there is no log-only dev path, so a verification link
created on localhost still lands in the recipient's real mailbox. Configure the
SMTP_* settings in .env; if they are wrong the send fails and is logged, but
signup itself still succeeds.

Headers here are set with deliverability in mind: a real display name, a
Reply-To, and an explicit Date/Message-ID stamped with the sending domain.
Mailbox providers penalise mail that is missing these.
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from app.config import settings

logger = logging.getLogger(__name__)

BRAND = settings.APP_NAME


# Fire-and-forget sends. Awaiting an SMTP round trip inside a request makes the
# response time depend on whether an email was sent, which on forgot-password
# and resend-verification is a user-enumeration oracle.
_background_tasks: set[asyncio.Task] = set()


def send_in_background(coro) -> None:
    """Schedule a send without blocking the response.

    The strong reference is not optional: asyncio only holds a weak one, so
    without keeping the task in a set it can be garbage-collected mid-flight and
    the email silently never goes out.
    """
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _from_domain() -> str:
    """Domain of the sending address — used to stamp the Message-ID."""
    _, _, domain = settings.SMTP_FROM.rpartition("@")
    return domain or "localhost"


def _send_sync(to_email: str, subject: str, html_body: str, text_body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM))
    msg["To"] = to_email
    if settings.SMTP_REPLY_TO:
        msg["Reply-To"] = settings.SMTP_REPLY_TO
    # Spam filters expect both; some SMTP relays omit them if we don't set them.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=_from_domain())
    msg["Auto-Submitted"] = "auto-generated"

    # Plain text first, then HTML as the alternative — mail with no text part
    # scores worse. set_content/add_alternative produces that order.
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


async def send_verification_email(to_email: str, link: str) -> None:
    """Send the account verification link."""
    subject = f"Confirm your email address for {BRAND}"

    text_body = (
        f"Welcome to {BRAND}.\n\n"
        f"Please confirm your email address to activate your account:\n"
        f"{link}\n\n"
        f"This link expires in {settings.EMAIL_TOKEN_EXPIRE_HOURS} hours.\n\n"
        f"If you did not create a {BRAND} account, no action is needed — "
        f"you can safely ignore this message.\n\n"
        f"— The {BRAND} Team"
    )

    html_body = f"""\
<div style="background:#f4f6f8;padding:32px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,Helvetica,sans-serif">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e5e9ef">
    <tr>
      <td style="padding:28px 32px 0 32px">
        <div style="font-size:19px;font-weight:700;color:#1e3a5f;letter-spacing:-0.2px">{BRAND}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:20px 32px 0 32px">
        <h1 style="margin:0 0 12px 0;font-size:20px;font-weight:600;color:#111827">Confirm your email address</h1>
        <p style="margin:0;font-size:14px;line-height:22px;color:#4b5563">
          Welcome to {BRAND}. Please confirm this email address to activate your account.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:24px 32px">
        <a href="{link}"
           style="display:inline-block;background:#1e3a5f;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600">
          Confirm email address
        </a>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 24px 32px">
        <p style="margin:0 0 6px 0;font-size:12px;line-height:18px;color:#6b7280">
          Or copy this link into your browser:
        </p>
        <p style="margin:0;font-size:12px;line-height:18px;word-break:break-all">
          <a href="{link}" style="color:#1e3a5f">{link}</a>
        </p>
        <p style="margin:14px 0 0 0;font-size:12px;color:#6b7280">
          This link expires in {settings.EMAIL_TOKEN_EXPIRE_HOURS} hours.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:16px 32px 24px 32px;border-top:1px solid #eef1f5">
        <p style="margin:0;font-size:11px;line-height:17px;color:#9ca3af">
          If you did not create a {BRAND} account, no action is needed — you can safely ignore this message.
        </p>
        <p style="margin:10px 0 0 0;font-size:11px;color:#9ca3af">— The {BRAND} Team</p>
      </td>
    </tr>
  </table>
</div>"""

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html_body, text_body)
        logger.info("[email] Verification email sent to %s", to_email)
    except Exception as exc:  # don't fail signup because SMTP is down
        logger.error("[email] Failed to send verification email to %s: %s", to_email, exc)


async def send_password_reset_email(to_email: str, link: str) -> None:
    """Send a password reset link.

    NEVER log `link` — it is a bearer credential, and anyone reading the logs
    could use it to take the account over. Log the recipient only, including in
    the failure branch.
    """
    minutes = settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    subject = f"Reset your {BRAND} password"

    text_body = (
        f"We received a request to reset the password for the {BRAND} account "
        f"associated with this email address.\n\n"
        f"Choose a new password here:\n{link}\n\n"
        f"This link expires in {minutes} minutes and can only be used once.\n\n"
        f"If you didn't request a password reset, you can safely ignore this email — "
        f"your password will not change and no action is needed.\n\n"
        f"— The {BRAND} Team"
    )

    html_body = f"""\
<div style="background:#f4f6f8;padding:32px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,Helvetica,sans-serif">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e5e9ef">
    <tr>
      <td style="padding:28px 32px 0 32px">
        <div style="font-size:19px;font-weight:700;color:#1e3a5f;letter-spacing:-0.2px">{BRAND}</div>
      </td>
    </tr>
    <tr>
      <td style="padding:20px 32px 0 32px">
        <h1 style="margin:0 0 12px 0;font-size:20px;font-weight:600;color:#111827">Reset your password</h1>
        <p style="margin:0;font-size:14px;line-height:22px;color:#4b5563">
          We received a request to reset the password for the {BRAND} account associated
          with this email address. Choose a new password using the button below.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:24px 32px">
        <a href="{link}"
           style="display:inline-block;background:#1e3a5f;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600">
          Reset password
        </a>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 24px 32px">
        <p style="margin:0 0 6px 0;font-size:12px;line-height:18px;color:#6b7280">
          Or copy this link into your browser:
        </p>
        <p style="margin:0;font-size:12px;line-height:18px;word-break:break-all">
          <a href="{link}" style="color:#1e3a5f">{link}</a>
        </p>
        <p style="margin:14px 0 0 0;font-size:12px;color:#6b7280">
          This link expires in {minutes} minutes and can only be used once.
        </p>
      </td>
    </tr>
    <tr>
      <td style="padding:16px 32px 24px 32px;border-top:1px solid #eef1f5">
        <p style="margin:0;font-size:11px;line-height:17px;color:#9ca3af">
          If you didn't request a password reset, you can safely ignore this email —
          your password will not change and no action is needed. If you keep receiving
          these messages, contact us at {settings.SMTP_REPLY_TO}.
        </p>
        <p style="margin:10px 0 0 0;font-size:11px;color:#9ca3af">— The {BRAND} Team</p>
      </td>
    </tr>
  </table>
</div>"""

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html_body, text_body)
        # Recipient only — never the link.
        logger.info("[email] Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("[email] Failed to send password reset email to %s: %s", to_email, exc)
