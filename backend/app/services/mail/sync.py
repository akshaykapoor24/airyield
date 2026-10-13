"""Reading new mail from onboarded senders (architecture/05 S1–S3, notifications from 07 §7.11).

For one connected mailbox:
  1. build the sender registry from the owner's Agency / Corporate / Employee Master;
  2. ask the mail server for new messages FROM those addresses and company domains only
     (strict mode — registry.py says which domains count);
  3. re-check the exact sender (IMAP's FROM is a substring match) — From, or Reply-To /
     Sender when accounting software sent it on the supplier's behalf;
  4. store the raw mail and attachments privately, write mail_messages / mail_attachments;
  5. raise a bell notification for the user whose master the sender is in.

ONE SYNC PER MAILBOX AT A TIME — a Redis lock, because beat and "Check now" can overlap and
both would otherwise download the same messages. A second caller is told one is running.

FIRST IMPORT, ONE NOTIFICATION. A folder's first check imports up to the backfill window
(30 days by default); a bell entry per historic message would bury the bell, so that import
raises a single summary. After it, every new message gets its own notification.

COMMITTED PER MESSAGE, CURSOR LAST. A crash part-way keeps what was stored; the unique key
on (connection, provider id) means the next run simply skips those and carries on.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mail import MailAttachment, MailConnection, MailMessage
from app.models.user import User
from app.services import notifications
import httpx

from app.services.mail import classify, cloud_readers, crypto, imap_client, mime, oauth, registry, storage

logger = logging.getLogger(__name__)

_LOCK_TTL_S = 15 * 60
READABLE_PROVIDERS = ("imap", "gmail", "microsoft")
# Every check also re-searches this many days back. Servers index a new message's From for
# SEARCH a little after delivery, so a check right after a mail lands can miss it; the
# lookback finds it next time (see imap_client._read_sync). Already-stored mail is skipped.
LOOKBACK_DAYS = 3


@dataclass
class SyncResult:
    status: str = "ok"                  # ok | busy | skipped | error
    message: str = ""
    new_messages: int = 0
    senders: int = 0
    more_waiting: bool = False
    errors: list[str] = field(default_factory=list)


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)


async def _owner_ids(db: AsyncSession, conn: MailConnection) -> list[int]:
    if conn.visibility != "workspace":
        return [conn.owner_user_id]
    rows = await db.execute(select(User.id).where(User.tenant_id == conn.tenant_id, User.is_active.is_(True)))
    return [r[0] for r in rows]


def _match(parsed: mime.ParsedMail, reg: registry.Registry) -> tuple[str | None, str | None, list[registry.Party]]:
    """(address that matched, how — "address" or "domain" — and the parties). From first;
    Reply-To / Sender only when From is not a registered party — the "sent via Zoho Books on
    behalf of the supplier" case."""
    for addr in [parsed.from_address, *parsed.reply_to, parsed.sender_address]:
        via, parties = reg.match(addr)
        if parties:
            return addr, via, parties
    return None, None, []


def _message_owner(conn: MailConnection, parties: list[registry.Party]) -> int:
    owners = {p.owner_user_id for p in parties}
    if conn.visibility == "workspace" and len(owners) == 1:
        return owners.pop()
    return conn.owner_user_id


async def _store_message(db: AsyncSession, conn: MailConnection, fetched: imap_client.FetchedMessage,
                         reg: registry.Registry) -> MailMessage | None:
    raw = fetched.raw or b""
    parsed = mime.parse(raw)
    matched, via, parties = _match(parsed, reg)
    if not parties:
        return None          # FROM matched a substring only; not an onboarded sender — keep nothing

    if parsed.message_id:    # the same mail already arrived through another folder or mailbox
        dup = await db.scalar(select(MailMessage.id).where(
            MailMessage.tenant_id == conn.tenant_id, MailMessage.internet_message_id == parsed.message_id))
        if dup:
            return None

    received = fetched.internaldate or parsed.sent_at or datetime.utcnow()
    raw_locator, raw_sha = await storage.store_raw(conn.tenant_id, conn.id, raw, received)
    owner = _message_owner(conn, parties)
    msg = MailMessage(
        tenant_id=conn.tenant_id, connection_id=conn.id, owner_user_id=owner,
        provider_message_id=fetched.provider_id, folder=fetched.folder,
        internet_message_id=(parsed.message_id or "")[:998] or None,
        in_reply_to=(parsed.in_reply_to or "")[:998] or None,
        subject=parsed.subject, from_address=parsed.from_address or matched or "",
        from_name=(parsed.from_name or "")[:320] or None, matched_address=matched or "",
        to_addresses=parsed.to, cc_addresses=parsed.cc, sent_at=parsed.sent_at, received_at=received,
        parties=[p.as_dict(via) for p in parties], party_type=parties[0].party_type,
        body_text=parsed.text, body_html=parsed.html, snippet=parsed.snippet or None,
        size_bytes=fetched.size or len(raw), raw_locator=raw_locator, raw_sha256=raw_sha,
        attachment_count=len(parsed.attachments),
        note="too_large" if fetched.too_large else None,
    )
    db.add(msg)
    await db.flush()
    for part in parsed.parts:
        locator, digest = await storage.store_attachment(conn.tenant_id, part.data, part.content_type)
        att = MailAttachment(
            tenant_id=conn.tenant_id, message_id=msg.id, part_index=part.index, filename=part.filename,
            content_type=part.content_type, size_bytes=len(part.data), sha256=digest, locator=locator,
            is_inline=part.is_inline, content_id=part.content_id,
        )
        await _apply_class(att, part.data, parties[0].party_type, context=parsed.subject or "")
        db.add(att)
    return msg


async def _apply_class(att: MailAttachment, data: bytes, sender_hint: str | None, *, context: str = "") -> None:
    """What the file is — statement, deal or other (services/mail/classify.py). Never fails the
    store: an attachment that cannot be classified is simply 'other'. The email subject is
    context ("Fwd: Vendor deal sheet") for files whose own content is ambiguous."""
    if att.is_inline:
        doc = classify.DocClass("other", meta={"reason": "image shown inside the email"})
    else:
        try:
            doc = await asyncio.to_thread(classify.classify, data, att.filename, att.content_type,
                                          sender_hint=sender_hint, context=context)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[mail.classify] %s failed: %s", att.filename, exc)
            doc = classify.DocClass("other", meta={"reason": "could not be analysed"})
    att.doc_kind, att.doc_type, att.doc_family = doc.kind, doc.doc_type, doc.family
    att.doc_label, att.doc_confidence = doc.label, doc.confidence
    att.doc_meta = {**(doc.meta or {}), "v": classify.CLASSIFIER_VERSION}
    att.classified_at = datetime.utcnow()


async def classify_pending(db: AsyncSession, *, tenant_id: int, connection_id: int | None = None,
                           limit: int = 200) -> int:
    """Classify attachments stored before classification existed (or whose run failed).
    Called at the end of every check, so existing mail is caught up without a manual step."""
    # Not yet classified, or classified by an older rule set (e.g. before deals were
    # recognised) — so improving the classifier relabels existing mail on the next check.
    stale = func.coalesce(MailAttachment.doc_meta["v"].astext, "") != str(classify.CLASSIFIER_VERSION)
    q = (select(MailAttachment, MailMessage.party_type, MailMessage.subject)
         .join(MailMessage, MailMessage.id == MailAttachment.message_id)
         .where(MailAttachment.tenant_id == tenant_id,
                or_(MailAttachment.classified_at.is_(None), stale)))
    if connection_id is not None:
        q = q.where(MailMessage.connection_id == connection_id)
    done = 0
    for att, party_type, subject in (await db.execute(q.limit(limit))).all():
        try:
            data = await storage.load(att.locator)
        except Exception:  # noqa: BLE001 — file gone: record that rather than retry forever
            att.doc_kind, att.classified_at = "other", datetime.utcnow()
            att.doc_meta = {"reason": "file not found in storage", "v": classify.CLASSIFIER_VERSION}
            continue
        await _apply_class(att, data, party_type, context=subject or "")
        done += 1
    await db.commit()
    return done


async def _notify_one(db: AsyncSession, msg: MailMessage) -> None:
    party = (msg.parties or [{}])[0]
    segment = party.get("segment", "")
    who = party.get("label") or msg.from_address
    if party.get("via") == "domain":      # someone else at the party's company — say who
        who = f"{msg.from_name or msg.from_address} · {who}"
    await notifications.notify(
        db, tenant_id=msg.tenant_id, user_id=msg.owner_user_id, category="mail", kind="new_mail",
        title=f"New email from {who}" + (f" ({segment})" if segment else ""),
        body=(msg.subject or "(no subject)") + (f" · {msg.attachment_count} attachment(s)" if msg.attachment_count else ""),
        link=f"/email-intake/inbox?m={msg.id}", dedupe_key=f"mail:msg:{msg.id}",
        source_type="mail_message", source_id=msg.id,
    )


async def sync_connection(db: AsyncSession, conn: MailConnection) -> SyncResult:
    """Fetch and store new mail for one mailbox. Safe to call concurrently (locked)."""
    if conn.provider not in READABLE_PROVIDERS:
        # Forwarding addresses receive mail by webhook, not by polling.
        return SyncResult(status="skipped", message="Forwarded mail arrives on its own; there is nothing to check.")
    if conn.status != "active":
        return SyncResult(status="skipped", message=f"Mailbox is {conn.status.replace('_', ' ')}.")

    lock_key = f"mail:lock:sync:{conn.id}"
    try:
        async with _redis() as r:
            if not await r.set(lock_key, "1", nx=True, ex=_LOCK_TTL_S):
                return SyncResult(status="busy", message="A check is already running for this mailbox.")
    except Exception as exc:  # noqa: BLE001 — without Redis there is no safe way to avoid double imports
        logger.warning("[mail.sync] lock unavailable: %s", exc)
        return SyncResult(status="error", message="Could not start the check (Redis unavailable).")

    try:
        return await _sync_locked(db, conn)
    finally:
        try:
            async with _redis() as r:
                await r.delete(lock_key)
        except Exception:  # noqa: BLE001 — the lock expires on its own
            pass


@dataclass
class _Read:
    """What a reader hands back: messages to store, plus the cursor to write afterwards."""
    messages: list
    more_waiting: bool = False
    errors: list[str] = field(default_factory=list)
    cursors: dict | None = None       # IMAP: per-folder UID cursors · cloud: {"__cloud__": {...}}


class _ReadFailed(Exception):
    def __init__(self, message: str, *, reauth: bool = False):
        super().__init__(message)
        self.reauth = reauth


def _credentials(conn: MailConnection) -> dict:
    try:
        return crypto.decrypt(conn.credentials_enc, conn.credentials_dek_enc, crypto.row_aad(conn.tenant_id, conn.id))
    except (crypto.CredentialsUnreadable, crypto.CryptoNotConfigured, TypeError) as exc:
        raise _ReadFailed("The stored access could not be read. Reconnect this mailbox.", reauth=True) from exc


async def _access_token(db: AsyncSession, conn: MailConnection) -> str:
    """A live OAuth access token, refreshing (and re-encrypting a rotated refresh token) when due."""
    tokens = _credentials(conn)
    if tokens.get("access_token") and int(tokens.get("expires_at", 0)) > int(datetime.utcnow().timestamp()) + 60:
        return tokens["access_token"]
    try:
        fresh = await oauth.refresh(conn.provider, tokens)
    except oauth.OAuthError as exc:
        raise _ReadFailed(str(exc), reauth=exc.reauth) from exc
    enc, dek, ref = crypto.encrypt(fresh, crypto.row_aad(conn.tenant_id, conn.id))
    conn.credentials_enc, conn.credentials_dek_enc, conn.credentials_key_ref = enc, dek, ref
    await db.commit()
    return fresh["access_token"]


async def _read_imap(conn: MailConnection, reg: registry.Registry, existing: set[str], settings_: dict) -> _Read:
    password = _credentials(conn).get("password")
    if not password:
        raise _ReadFailed("The stored password could not be read. Reconnect this mailbox.", reauth=True)
    folders = settings_.get("folders") or ["INBOX"]
    if not settings_.get("include_spam", True):
        folders = folders[:1]
    since = (datetime.utcnow() - timedelta(days=int(settings_.get("backfill_days") or 30))).date()
    try:
        read = await imap_client.read_new(
            conn.imap_host or "", conn.imap_port or 993, conn.imap_username or conn.email_address, password,
            folders=folders, cursors=(conn.sync_cursor or {}).get("folders", {}), senders=reg.search_terms,
            since=since, existing=existing, limit=settings.MAIL_SYNC_BATCH,
            max_bytes=settings.MAIL_MAX_MESSAGE_MB * 1024 * 1024,
            lookback=(datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).date(),
        )
    except imap_client.ImapError as exc:
        raise _ReadFailed(str(exc), reauth=exc.code == "auth_failed") from exc
    return _Read(messages=read.messages, more_waiting=read.more_waiting, errors=read.errors, cursors=read.cursors)


async def _read_cloud(db: AsyncSession, conn: MailConnection, reg: registry.Registry, existing: set[str],
                      settings_: dict) -> _Read:
    """Gmail / Microsoft: a time window — since the last check minus LOOKBACK_DAYS, or the
    backfill window on the first check — with stored and ignored ids skipped."""
    cursor = (conn.sync_cursor or {}).get("cloud") or {}
    first = not cursor.get("last_check")
    now = datetime.utcnow()
    backfill_from = now - timedelta(days=int(settings_.get("backfill_days") or 30))
    window = backfill_from if first else \
        datetime.fromisoformat(cursor["last_check"]) - timedelta(days=LOOKBACK_DAYS)
    # A sender added since the last check — a party onboarded, or a company domain now read —
    # has earlier mail the window never covered. Reach back to the backfill window for it, as
    # IMAP does; stored mail is skipped, and that earlier mail is imported without a bell each.
    terms = reg.search_terms
    known = cursor.get("senders")
    widen = not first and (known is None or not set(terms) <= set(known))
    after = min(window, backfill_from) if widen else window
    skip = existing | set(cursor.get("ignored", []))
    common = dict(after=after, include_spam=bool(settings_.get("include_spam", True)), skip=skip,
                  limit=settings.MAIL_SYNC_BATCH, max_bytes=settings.MAIL_MAX_MESSAGE_MB * 1024 * 1024,
                  first_sync=first)
    token = await _access_token(db, conn)
    try:
        if conn.provider == "gmail":
            read = await cloud_readers.gmail_read(token, senders=terms, **common)
        else:
            read = await cloud_readers.graph_read(token, is_sender=lambda a: bool(reg.lookup(a)), **common)
    except oauth.OAuthError as exc:
        raise _ReadFailed(str(exc), reauth=exc.reauth) from exc
    except cloud_readers.CloudError as exc:
        raise _ReadFailed(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise _ReadFailed("The mail provider could not be reached. New mail will be checked again shortly.") from exc
    if widen:
        for m in read.messages:
            if m.internaldate and m.internaldate < window:
                m.first_sync = True
    # More waiting than one check takes: keep the window — and the sender list, so a widened
    # check widens again — where it was, so the next check carries on from the same point
    # (what was stored is skipped). Otherwise move the window to now.
    done = not read.more_waiting
    return _Read(messages=read.messages, more_waiting=read.more_waiting,
                 cursors={"__cloud__": {"last_check": now.isoformat() if done else cursor.get("last_check"),
                                        "senders": terms if done else known,
                                        "ignored": cursor.get("ignored", [])}})


async def _sync_locked(db: AsyncSession, conn: MailConnection) -> SyncResult:
    result = SyncResult()
    reg = await registry.build(db, conn.tenant_id, await _owner_ids(db, conn), mailbox_address=conn.email_address)
    result.senders = len(reg)
    if not reg:
        conn.last_synced_at = datetime.utcnow()
        await db.commit()
        result.status, result.message = "ok", "No sender emails in Agency, Corporate or Employee Master yet."
        return result

    existing = set((await db.execute(
        select(MailMessage.provider_message_id).where(MailMessage.connection_id == conn.id)
    )).scalars().all())
    settings_ = conn.settings or {}

    try:
        if conn.provider == "imap":
            read = await _read_imap(conn, reg, existing, settings_)
        else:
            read = await _read_cloud(db, conn, reg, existing, settings_)
    except _ReadFailed as exc:
        conn.consecutive_failures += 1
        if exc.reauth:
            conn.status = "needs_reauth"
        elif conn.consecutive_failures >= 10:
            conn.status = "error"
        conn.status_reason = str(exc)
        await db.commit()
        return SyncResult(status="error", message=str(exc), senders=len(reg))

    first_import = 0
    # Fetched but deliberately not stored (the provider's sender match was looser than ours, or
    # the same mail is already in the inbox from another folder). Remembered in the cursor so the
    # lookback does not download them again every check. A message that FAILED is not added —
    # it is retried on the next check instead of being lost.
    not_ours: dict[str, set] = {}
    for fetched in read.messages:
        try:
            msg = await _store_message(db, conn, fetched, reg)
            if msg is None:
                key = fetched.uid if fetched.uid is not None else fetched.provider_id
                not_ours.setdefault(fetched.folder, set()).add(key)
            else:
                if fetched.first_sync:
                    first_import += 1
                else:
                    await _notify_one(db, msg)
                result.new_messages += 1
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — one bad message must not stop the rest
            await db.rollback()
            await db.refresh(conn)      # a rollback expires it; async code cannot lazy-load
            logger.exception("[mail.sync] message %s failed", fetched.provider_id)
            result.errors.append(f"{fetched.provider_id}: {exc.__class__.__name__}")

    if first_import:
        await notifications.notify(
            db, tenant_id=conn.tenant_id, user_id=conn.owner_user_id, category="mail", kind="first_import",
            title=f"{first_import} earlier email(s) imported from your onboarded senders",
            body=f"From {conn.email_address}, last {settings_.get('backfill_days') or 30} days.",
            link="/email-intake/inbox", dedupe_key=f"mail:first:{conn.id}:{datetime.utcnow():%Y%m%d%H%M}",
            source_type="mail_connection", source_id=conn.id,
        )

    cursors = read.cursors or {}
    if conn.provider == "imap":
        for folder, uids in not_ours.items():
            cur = cursors.get(folder)
            if cur is not None:
                cur["ignored"] = sorted(set(cur.get("ignored", [])) | uids)[-imap_client._IGNORED_KEEP:]
        conn.sync_cursor = {**(conn.sync_cursor or {}), "folders": cursors}
    else:
        cloud = cursors.get("__cloud__", {})
        ignored = list(dict.fromkeys(list(cloud.get("ignored", [])) + [i for ids in not_ours.values() for i in ids]))
        conn.sync_cursor = {**(conn.sync_cursor or {}),
                            "cloud": {"last_check": cloud.get("last_check"), "senders": cloud.get("senders"),
                                      "ignored": ignored[-imap_client._IGNORED_KEEP:]}}
    try:
        await classify_pending(db, tenant_id=conn.tenant_id, connection_id=conn.id)
    except Exception:  # noqa: BLE001 — classification catches up next time; the sync itself succeeded
        await db.rollback()
        await db.refresh(conn)
        logger.exception("[mail.classify] catch-up failed for connection %s", conn.id)
    conn.last_synced_at = datetime.utcnow()
    if result.new_messages:
        conn.last_message_at = datetime.utcnow()
    conn.consecutive_failures = 0
    if conn.status_reason and conn.status == "active":
        conn.status_reason = None
    await db.commit()

    result.more_waiting = read.more_waiting
    result.errors += read.errors
    result.message = (f"{result.new_messages} new email(s)" if result.new_messages else "No new email") + \
                     (" — more are waiting and will arrive on the next check." if read.more_waiting else ".")
    return result


async def sync_all(db: AsyncSession) -> dict:
    """Every active mailbox (IMAP, Gmail, Microsoft) whose workspace may use the product.
    Called by Celery beat. Forwarding addresses receive by webhook, not by polling."""
    from app.models.tenant import Tenant
    rows = (await db.execute(
        select(MailConnection).join(Tenant, Tenant.id == MailConnection.tenant_id)
        .where(MailConnection.status == "active", MailConnection.provider.in_(READABLE_PROVIDERS))
    )).scalars().all()
    summary = {"mailboxes": 0, "new_messages": 0, "errors": 0}
    for conn in rows:
        tenant = await db.get(Tenant, conn.tenant_id)
        if tenant is None or not tenant.has_active_plan:
            continue
        res = await sync_connection(db, conn)
        summary["mailboxes"] += 1
        summary["new_messages"] += res.new_messages
        summary["errors"] += res.status == "error"
    return summary
