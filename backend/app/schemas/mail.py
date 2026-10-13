"""Email intake — request / response shapes for /mail/*.

Credentials are write-only: no response model here has a field that could carry a token or a
password, so one cannot leak through a careless `**row.__dict__`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Visibility = Literal["personal", "workspace"]
BACKFILL_CHOICES = (7, 30, 90, 180)


class ProviderAvailability(BaseModel):
    available: bool
    reason: str | None = None          # why not, in a sentence, when unavailable


class MailConfigOut(BaseModel):
    enabled: bool
    encryption_ready: bool
    can_connect: bool
    can_connect_workspace: bool
    providers: dict[str, ProviderAvailability]
    inbound_domain: str | None = None


class DetectOut(BaseModel):
    email_address: str
    provider: str | None
    imap_host: str | None = None
    imap_port: int | None = None
    label: str
    note: str | None = None
    provider_key: str | None = None


class ProviderOut(BaseModel):
    key: str
    name: str
    connector: str
    blurb: str
    imap_host: str | None
    imap_port: int
    password_label: str
    steps: list[str]
    help_url: str | None
    popular: bool
    regions: list[dict]
    available: bool
    reason: str | None = None
    # Sign-in providers: is the sign-in app configured here? When it is not, `imap_alternative`
    # (Google: app password over IMAP) is how the tile connects instead.
    oauth_available: bool = False
    imap_alternative: dict | None = None


class OwnerOut(BaseModel):
    id: int
    name: str


class ConnectionOut(BaseModel):
    id: int
    provider: str
    email_address: str
    visibility: str
    status: str
    status_reason: str | None
    screening_mode: str
    settings: dict
    owner: OwnerOut
    is_mine: bool
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    forwarding_address: str | None = None
    granted_scopes: str | None = None
    last_tested_at: datetime | None = None
    last_synced_at: datetime | None = None
    created_at: datetime


class StartOAuthIn(BaseModel):
    login_hint: str | None = Field(default=None, max_length=320)
    visibility: Visibility = "personal"


class StartOAuthOut(BaseModel):
    url: str


class ImapConnectIn(BaseModel):
    email_address: str = Field(max_length=320)
    host: str = Field(max_length=255)
    port: int = 993
    username: str | None = Field(default=None, max_length=320)    # defaults to the address
    password: str = Field(min_length=1, max_length=500)
    visibility: Visibility = "personal"
    include_spam: bool = True
    provider_key: str | None = Field(default=None, max_length=20)   # the tile picked: zoho, godaddy, yahoo…


class RelayConnectIn(BaseModel):
    email_address: str = Field(max_length=320)                    # the mailbox that will forward
    visibility: Visibility = "personal"


class FolderOut(BaseModel):
    name: str
    display: str
    special_use: str | None = None


class TestOut(BaseModel):
    ok: bool
    message: str
    status: str
    folders: list[FolderOut] | None = None


class ConnectResultOut(BaseModel):
    connection: ConnectionOut
    test: TestOut


class ConnectionSettingsIn(BaseModel):
    folders: list[str] | None = Field(default=None, max_length=20)
    include_spam: bool | None = None
    backfill_days: int | None = None

    @field_validator("backfill_days")
    @classmethod
    def _backfill(cls, v: int | None) -> int | None:
        if v is not None and v not in BACKFILL_CHOICES:
            raise ValueError(f"backfill_days must be one of {BACKFILL_CHOICES}")
        return v

    @field_validator("folders")
    @classmethod
    def _folders(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = [f.strip() for f in v if f and f.strip()]
        if not cleaned:
            raise ValueError("Pick at least one folder.")
        return cleaned


# ── received mail ───────────────────────────────────────────────────────────

class SyncOut(BaseModel):
    status: str
    message: str
    new_messages: int
    senders: int
    more_waiting: bool = False


class PartyOut(BaseModel):
    party_type: str        # agency | corporate | customer
    party_id: int
    label: str
    segment: str           # B2B | B2E | B2C
    via: str | None = None  # address | domain — the sender's exact address, or someone else at its domain


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    is_inline: bool
    previewable: bool      # PDF or image — can open in the browser
    # What the file is (services/mail/classify.py); None until it has been analysed.
    doc_kind: str | None = None          # statement | other
    doc_type: str | None = None          # tp-gds, lcc-detailed, bsp …
    doc_family: str | None = None        # bsp | lcc | third_party | ndc | tgq | mo | bank | unknown
    doc_label: str | None = None
    doc_confidence: float | None = None
    doc_reason: str | None = None
    doc_rows: int | None = None


class DocTag(BaseModel):
    doc_type: str
    family: str
    label: str


class MessageListItem(BaseModel):
    id: int
    subject: str | None
    from_name: str | None
    from_address: str
    party: PartyOut | None
    snippet: str | None
    received_at: datetime
    attachment_count: int
    is_read: bool
    mailbox: str
    connection_id: int
    statements: list[DocTag] = []       # statement attachments, for the row badges


class MailboxCount(BaseModel):
    id: int
    email_address: str
    provider: str
    provider_key: str | None
    status: str
    total: int
    unread: int
    statements: int


class MessageListOut(BaseModel):
    items: list[MessageListItem]
    total: int
    unread: int
    statements: int                     # messages carrying at least one statement (current mailbox scope)
    mailboxes: list[MailboxCount]


class MessageDetailOut(MessageListItem):
    to_addresses: list[str]
    cc_addresses: list[str]
    sent_at: datetime | None
    parties: list[PartyOut]
    body_text: str | None
    has_html: bool
    note: str | None
    attachments: list[AttachmentOut]


class MessageHtmlOut(BaseModel):
    html: str


# ── processing an email ─────────────────────────────────────────────────────

class ProcessPlanOut(BaseModel):
    message_id: int
    subject: str | None
    sender: dict              # party_type, label, segment, agency_id, agency_ids
    facts: dict               # period_from/to, effective_from, valid_to, expected_count, expected_amount
    items: list[dict]         # see services/mail/process.py — key, source, kind, doc_type, label, imported…


class MarkProcessedIn(BaseModel):
    key: str = Field(max_length=40)              # att:<id> | table:<n> | text:deals
    destination: str = Field(max_length=60)      # statements:tp-gds | lcc-detailed | bsp | deals …
    ref: str | None = Field(default=None, max_length=100)
