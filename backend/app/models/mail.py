"""Email intake — connected mailboxes (architecture/08-data-model.md).

ONE ROW IS ONE MAILBOX A USER HAS CONNECTED: a Gmail / Google Workspace account, a
Microsoft 365 / Outlook account, an IMAP mailbox (Zoho, GoDaddy, Rediff, Hostinger…), or a
forwarding address the user's own mail rule sends to. Reading mail is a later step; this
table is what the connect flow writes and what every later stage reads its cursor from.

WHOSE ROW IT IS. `owner_user_id` is the user the mailbox's drafts will be saved as, because
FareQube scopes masters and batches per user (tenant_id + created_by_id). A `workspace`
connection (Super Admin only) is a shared box such as accounts@; its drafts are routed to
whichever user onboarded the sender (architecture/04 §4.7).

CREDENTIALS ARE NEVER STORED IN THE CLEAR. `credentials_enc` holds the OAuth token set or
the IMAP app password, AES-256-GCM encrypted under a per-row data key; `credentials_dek_enc`
is that data key, wrapped by MAIL_ENCRYPTION_KEY (services/mail/crypto.py). Both are bound
to `tenant_id:id`, so ciphertext copied onto another row will not decrypt. No API response
ever carries either column.

ONE ROW PER MAILBOX PER WORKSPACE (`uq_mail_connections_mailbox`). Two colleagues connecting
the same box would read every mail twice; the second one is told who already connected it.
A disconnected row is kept (it explains past imports) and is reused on reconnect.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

PROVIDERS: tuple[str, ...] = ("gmail", "microsoft", "imap", "relay")
STATUSES: tuple[str, ...] = (
    "pending_auth", "active", "needs_reauth", "paused", "error", "disconnected",
)
SCREENING_MODES: tuple[str, ...] = ("strict", "extended")
VISIBILITIES: tuple[str, ...] = ("personal", "workspace")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class MailConnection(Base):
    __tablename__ = "mail_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "email_address", name="uq_mail_connections_mailbox"),
        UniqueConstraint("relay_token", name="uq_mail_connections_relay_token"),
        CheckConstraint(_in("provider", PROVIDERS), name="ck_mail_connections_provider"),
        CheckConstraint(_in("status", STATUSES), name="ck_mail_connections_status"),
        CheckConstraint(_in("screening_mode", SCREENING_MODES), name="ck_mail_connections_mode"),
        CheckConstraint(_in("visibility", VISIBILITIES), name="ck_mail_connections_visibility"),
        # The scheduler's "which mailboxes are due" scan.
        Index("ix_mail_connections_due", "status", "provider", "last_synced_at"),
    )

    id:            Mapped[int] = mapped_column(primary_key=True)
    tenant_id:     Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # No cascade: a user who owns a mailbox is reassigned or disconnected first.
    owner_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    visibility:    Mapped[str] = mapped_column(String(10), nullable=False, default="personal", server_default="personal")
    provider:      Mapped[str] = mapped_column(String(10), nullable=False)
    # The mailbox itself, lowercased. For `relay` it is the mailbox that forwards to us.
    email_address: Mapped[str] = mapped_column(String(320), nullable=False)
    # Google `sub` / Entra "<tid>:<oid>". Lets a reconnect recognise the same account.
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status:        Mapped[str] = mapped_column(String(16), nullable=False, default="pending_auth", server_default="pending_auth")
    # A sentence for the user, never a stack trace or a provider token.
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screening_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="strict", server_default="strict")

    credentials_enc:     Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credentials_dek_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credentials_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    granted_scopes:      Mapped[str | None] = mapped_column(Text, nullable=True)

    imap_host:     Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port:     Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_username: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # "ssl" (993) or "starttls" (143). Plaintext IMAP is refused, so there is no third value.
    imap_security: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Local part of the forwarding address <relay_token>@MAIL_INBOUND_DOMAIN.
    relay_token:   Mapped[str | None] = mapped_column(String(40), nullable=True)

    # {folders: [...], include_spam: bool, backfill_days: int}. Plain JSON on purpose:
    # these grow with the feature and none of them is ever filtered on in SQL.
    settings:      Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Provider sync position — written only by the sync worker (architecture/03 §3.2).
    sync_cursor:   Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    watch_ref:         Mapped[str | None] = mapped_column(String(255), nullable=True)
    watch_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    watch_expires_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    last_synced_at:       Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_message_at:      Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_tested_at:       Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    backfill_state:       Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Naive UTC from Python, like the rest of the schema.
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class MailMessage(Base):
    """One email from an onboarded sender, read from a connected mailbox.

    ONLY ALLOWLISTED MAIL BECOMES A ROW. The sync asks the mail server for messages FROM the
    addresses in Agency / Corporate / Employee Master, and re-checks the exact From address
    after download; anything else is never fetched and never stored (architecture/04).

    WHO SEES IT. `owner_user_id` is the user whose master the sender was found in — FareQube
    scopes masters per user — or the connection owner when several users onboarded the same
    sender. The Super Admin sees every message in the workspace.

    The raw RFC 5322 bytes live in object storage (`raw_locator`); the text and HTML bodies
    are copied here so the inbox renders without re-parsing the .eml on every click.
    """
    __tablename__ = "mail_messages"
    __table_args__ = (
        # Same message, same mailbox: delivered once. provider_message_id for IMAP is
        # "<folder>:<uidvalidity>:<uid>", which survives re-syncs but not a renumbered folder.
        UniqueConstraint("connection_id", "provider_message_id", name="uq_mail_messages_provider"),
        Index("ix_mail_messages_imid", "tenant_id", "internet_message_id"),
        Index("ix_mail_messages_inbox", "tenant_id", "owner_user_id", "received_at"),
    )

    id:                  Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id:           Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    connection_id:       Mapped[int] = mapped_column(Integer, ForeignKey("mail_connections.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id:       Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    folder:              Mapped[str | None] = mapped_column(String(255), nullable=True)
    internet_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    in_reply_to:         Mapped[str | None] = mapped_column(String(998), nullable=True)

    subject:       Mapped[str | None] = mapped_column(Text, nullable=True)
    from_address:  Mapped[str] = mapped_column(String(320), nullable=False)
    from_name:     Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Who matched the registry: From, or Reply-To / Sender when accounting software
    # (Zoho Books, Tally…) sent it on the supplier's behalf.
    matched_address: Mapped[str] = mapped_column(String(320), nullable=False)
    to_addresses:  Mapped[list | None] = mapped_column(JSONB, nullable=True)
    cc_addresses:  Mapped[list | None] = mapped_column(JSONB, nullable=True)
    sent_at:       Mapped[datetime | None] = mapped_column(DateTime, nullable=True)     # Date header, UTC
    received_at:   Mapped[datetime] = mapped_column(DateTime, nullable=False)           # server's INTERNALDATE, UTC

    # [{party_type: agency|corporate|customer, party_id, label, owner_user_id}] — every master
    # row the sender's address appears on. Usually one; a GDS + LCC agency pair is two.
    parties:       Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # The first party's type, denormalised so the inbox can filter B2B / B2E / B2C cheaply.
    party_type:    Mapped[str | None] = mapped_column(String(12), nullable=True)

    body_text:     Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html:     Mapped[str | None] = mapped_column(Text, nullable=True)   # as sent; sanitised on display
    snippet:       Mapped[str | None] = mapped_column(String(300), nullable=True)
    size_bytes:    Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_locator:   Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw_sha256:    Mapped[str | None] = mapped_column(String(64), nullable=True)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # "too_large" when the message was over MAIL_MAX_MESSAGE_MB and only its headers were kept.
    note:          Mapped[str | None] = mapped_column(String(40), nullable=True)

    read_at:       Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # What has been done with this email's contents (services/mail/process.py):
    #   {"items": {"att:12": {"destination": "statements:tp-gds", "ref": "<batch id>", "at": …, "by": 14}},
    #    "text_deals": {"rows": [...], "at": …},       ← AI reading of a deal written as text, cached
    #    "body_items": 1}                               ← statement / deal tables and deal text in the body
    processed:     Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    created_at:    Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class MailAttachment(Base):
    """A file that came with a MailMessage. Bytes are in object storage, content-addressed by
    SHA-256 within the workspace, so the same statement attached to five replies is stored once.

    `is_inline` marks images the HTML body embeds (cid:), e.g. a pasted deal flyer or a logo —
    shown inside the message rather than in the attachment list.
    """
    __tablename__ = "mail_attachments"
    __table_args__ = (
        UniqueConstraint("message_id", "part_index", name="uq_mail_attachments_part"),
        Index("ix_mail_attachments_sha", "tenant_id", "sha256"),
        Index("ix_mail_attachments_doc", "message_id", "doc_kind"),
    )

    id:           Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id:    Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    message_id:   Mapped[int] = mapped_column(BigInteger, ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    part_index:   Mapped[int] = mapped_column(Integer, nullable=False)
    filename:     Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes:   Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256:       Mapped[str] = mapped_column(String(64), nullable=False)
    locator:      Mapped[str] = mapped_column(String(1024), nullable=False)
    is_inline:    Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    content_id:   Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What the file is (services/mail/classify.py) — statements first; deals, contracts and
    # payment advices follow. NULL `classified_at` means "not looked at yet".
    doc_kind:       Mapped[str | None] = mapped_column(String(20), nullable=True)     # statement | other
    doc_type:       Mapped[str | None] = mapped_column(String(40), nullable=True)     # tp-gds, lcc-detailed, bsp …
    doc_family:     Mapped[str | None] = mapped_column(String(20), nullable=True)     # bsp | lcc | third_party | …
    doc_label:      Mapped[str | None] = mapped_column(String(80), nullable=True)
    doc_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    doc_meta:       Mapped[dict | None] = mapped_column(JSONB, nullable=True)       # matched, total, rows, reason
    classified_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at:   Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
