"""Email intake — received mail: checking for new mail, the inbox, content, attachments.

    POST /mail/connections/{id}/sync     check one mailbox now
    POST /mail/sync                      "Check for new mail": every active mailbox I manage
    GET  /mail/messages                  inbox list — filter b2b | b2e | b2c, search, unread
    GET  /mail/messages/unread-count     sidebar badge
    GET  /mail/messages/{id}             headers, text, parties, attachments (marks read)
    POST /mail/messages/{id}/unread
    GET  /mail/messages/{id}/html        sanitised HTML body with its inline images embedded
    GET  /mail/attachments/{id}/download ?inline=1 shows PDFs and images in the browser

WHO SEES A MESSAGE: the user whose master the sender is in (`owner_user_id`), and the Super
Admin. Everyone else gets 404 — the same answer as for a message that does not exist.

Mounted under /mail beside api/v1/mail.py (connections); split only to keep each file to one job.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.mail import _is_super_admin, _limit, _load_owned, _require_enabled
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.mail import MailAttachment, MailConnection, MailMessage
from app.models.user import User
from app.schemas.mail import (
    AttachmentOut, DocTag, MailboxCount, MarkProcessedIn, MessageDetailOut, MessageHtmlOut, MessageListItem,
    MessageListOut, PartyOut, ProcessPlanOut, SyncOut,
)
from app.services.mail import body as mail_body
from app.services.mail import html as mail_html
from app.services.mail import process as mail_process
from app.services.mail import providers
from app.services.mail import text_deals as mail_text_deals
from app.services.mail import storage as mail_storage
from app.services.mail import sync as mail_sync

router = APIRouter()

_PREVIEW_TYPES = ("application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp")
_SEGMENT_TO_TYPE = {"b2b": "agency", "b2e": "corporate", "b2c": "customer"}
_MAX_INLINE_IMAGE = 3 * 1024 * 1024


def sniff(data: bytes) -> str | None:
    """The real type of a file from its first bytes — never the sender's claim."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _visible(user: User) -> list:
    conds = [MailMessage.tenant_id == user.tenant_id]
    if not _is_super_admin(user):
        conds.append(MailMessage.owner_user_id == user.id)
    return conds


def _party(p: dict | None) -> PartyOut | None:
    if not p:
        return None
    return PartyOut(party_type=p.get("party_type", ""), party_id=int(p.get("party_id", 0)),
                    label=p.get("label", ""), segment=p.get("segment", ""))


def _list_item(m: MailMessage, mailbox: str, statements: list[DocTag] | None = None) -> MessageListItem:
    return MessageListItem(
        id=m.id, subject=m.subject, from_name=m.from_name, from_address=m.from_address,
        party=_party((m.parties or [None])[0]), snippet=m.snippet, received_at=m.received_at,
        attachment_count=m.attachment_count, is_read=m.read_at is not None, mailbox=mailbox,
        connection_id=m.connection_id, statements=statements or [],
    )


def _has_statement(family: str | None = None):
    """EXISTS: the message carries at least one attachment classified as a statement."""
    conds = [MailAttachment.message_id == MailMessage.id, MailAttachment.doc_kind == "statement"]
    if family:
        conds.append(MailAttachment.doc_family == family)
    return exists(select(MailAttachment.id).where(*conds))


async def _statement_tags(db: AsyncSession, message_ids: list[int]) -> dict[int, list[DocTag]]:
    out: dict[int, list[DocTag]] = {}
    if not message_ids:
        return out
    rows = (await db.execute(
        select(MailAttachment.message_id, MailAttachment.doc_type, MailAttachment.doc_family, MailAttachment.doc_label)
        .where(MailAttachment.message_id.in_(message_ids), MailAttachment.doc_kind == "statement")
        .order_by(MailAttachment.part_index)
    )).all()
    for mid, dtype, fam, label in rows:
        tags = out.setdefault(mid, [])
        if not any(t.doc_type == dtype for t in tags):
            tags.append(DocTag(doc_type=dtype or "unknown", family=fam or "unknown", label=label or "Statement"))
    return out


async def _mailbox_counts(db: AsyncSession, user: User) -> list[MailboxCount]:
    """Every mailbox the user can see, with how much mail it brought in — for the picker."""
    q = select(MailConnection).where(MailConnection.tenant_id == user.tenant_id)
    if not _is_super_admin(user):
        q = q.where(MailConnection.owner_user_id == user.id)
    conns = (await db.execute(q.order_by(MailConnection.created_at))).scalars().all()
    stats = {cid: (total, unread, stmts) for cid, total, unread, stmts in (await db.execute(
        select(MailMessage.connection_id, func.count(),
               func.count().filter(MailMessage.read_at.is_(None)),
               func.count().filter(_has_statement()))
        .where(*_visible(user)).group_by(MailMessage.connection_id)
    )).all()}
    out = []
    for c in conns:
        total, unread, stmts = stats.get(c.id, (0, 0, 0))
        if c.status == "disconnected" and not total:
            continue
        key = (c.settings or {}).get("provider_key") or providers.key_for_host(c.imap_host) or \
            {"gmail": "google", "microsoft": "microsoft", "relay": "relay"}.get(c.provider)
        out.append(MailboxCount(id=c.id, email_address=c.email_address, provider=c.provider, provider_key=key,
                                status=c.status, total=total, unread=unread, statements=stmts))
    return out


async def _load_message(db: AsyncSession, user: User, message_id: int) -> MailMessage:
    m = (await db.execute(select(MailMessage).where(MailMessage.id == message_id, *_visible(user)))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="Email not found.")
    return m


async def _unread(db: AsyncSession, user: User) -> int:
    return await db.scalar(select(func.count()).select_from(MailMessage)
                           .where(*_visible(user), MailMessage.read_at.is_(None))) or 0


# ── checking for new mail ───────────────────────────────────────────────────

@router.post("/connections/{connection_id}/sync", response_model=SyncOut)
async def sync_now(connection_id: int, db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    """Check this mailbox now instead of waiting for the next scheduled check."""
    _require_enabled()
    conn = await _load_owned(db, current_user, connection_id)
    await _limit("mail-sync", current_user, 20, 600)
    r = await mail_sync.sync_connection(db, conn)
    return SyncOut(status=r.status, message=r.message, new_messages=r.new_messages,
                   senders=r.senders, more_waiting=r.more_waiting)


@router.post("/sync", response_model=SyncOut)
async def sync_mine(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The inbox's "Check for new mail": every active mailbox this user may manage."""
    _require_enabled()
    await _limit("mail-sync", current_user, 20, 600)
    q = select(MailConnection).where(MailConnection.tenant_id == current_user.tenant_id,
                                     MailConnection.status == "active")
    if not _is_super_admin(current_user):
        q = q.where(MailConnection.owner_user_id == current_user.id)
    conns = (await db.execute(q)).scalars().all()
    if not conns:
        return SyncOut(status="skipped", message="No connected mailbox to check. Connect one in Mailboxes.",
                       new_messages=0, senders=0)

    out = SyncOut(status="ok", message="", new_messages=0, senders=0)
    problems: list[str] = []
    for conn in conns:
        r = await mail_sync.sync_connection(db, conn)
        out.new_messages += r.new_messages
        out.senders = max(out.senders, r.senders)
        out.more_waiting |= r.more_waiting
        if r.status in ("error", "busy"):
            out.status = r.status
            problems.append(f"{conn.email_address}: {r.message}")
    if problems:
        out.message = " ".join(problems)
    elif out.senders == 0:
        out.message = "No sender emails in Agency, Corporate or Employee Master yet — add them to start receiving mail."
    else:
        out.message = (f"{out.new_messages} new email(s)." if out.new_messages else "You're up to date.") + \
                      (" More are on the way." if out.more_waiting else "")
    return out


# ── the inbox ───────────────────────────────────────────────────────────────

@router.get("/messages", response_model=MessageListOut)
async def list_messages(
    segment: str | None = Query(default=None, description="b2b | b2e | b2c"),
    mailbox: int | None = Query(default=None, description="one connected mailbox (its id)"),
    kind: str | None = Query(default=None, description="statement"),
    family: str | None = Query(default=None, description="bsp | lcc | third_party | ndc | tgq | mo | bank | unknown"),
    q: str | None = Query(default=None, max_length=200),
    unread: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_enabled()
    conds = _visible(current_user)
    if mailbox is not None:
        conds.append(MailMessage.connection_id == mailbox)
    scope = list(conds)                     # mailbox scope, before the content filters
    if kind == "statement" or family:
        conds.append(_has_statement(family))
    elif kind:
        raise HTTPException(status_code=400, detail="kind must be 'statement'.")
    if segment:
        ptype = _SEGMENT_TO_TYPE.get(segment.lower())
        if not ptype:
            raise HTTPException(status_code=400, detail="segment must be b2b, b2e or b2c.")
        conds.append(MailMessage.party_type == ptype)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(MailMessage.subject.ilike(like), MailMessage.from_address.ilike(like),
                         MailMessage.from_name.ilike(like), MailMessage.snippet.ilike(like)))
    if unread:
        conds.append(MailMessage.read_at.is_(None))

    total = await db.scalar(select(func.count()).select_from(MailMessage).where(*conds)) or 0
    rows = (await db.execute(
        select(MailMessage, MailConnection.email_address)
        .join(MailConnection, MailConnection.id == MailMessage.connection_id)
        .where(*conds).order_by(MailMessage.received_at.desc(), MailMessage.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    tags = await _statement_tags(db, [m.id for m, _ in rows])
    statements = await db.scalar(select(func.count()).select_from(MailMessage).where(*scope, _has_statement())) or 0
    return MessageListOut(items=[_list_item(m, box, tags.get(m.id)) for m, box in rows], total=total,
                          unread=await _unread(db, current_user), statements=statements,
                          mailboxes=await _mailbox_counts(db, current_user))


@router.get("/messages/unread-count")
async def unread_count(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not settings.MAIL_INTAKE_ENABLED or current_user.tenant_id is None:
        return {"unread": 0}
    return {"unread": await _unread(db, current_user)}


@router.get("/messages/{message_id}", response_model=MessageDetailOut)
async def get_message(message_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    """Opening a message marks it read."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    box = await db.scalar(select(MailConnection.email_address).where(MailConnection.id == m.connection_id)) or ""
    atts = (await db.execute(select(MailAttachment).where(MailAttachment.message_id == m.id)
                             .order_by(MailAttachment.part_index))).scalars().all()
    if m.read_at is None:
        m.read_at = datetime.utcnow()
        await db.commit()
    tags = await _statement_tags(db, [m.id])
    base = _list_item(m, box, tags.get(m.id))
    return MessageDetailOut(
        **base.model_dump(), to_addresses=m.to_addresses or [], cc_addresses=m.cc_addresses or [],
        sent_at=m.sent_at, parties=[p for p in (_party(x) for x in (m.parties or [])) if p],
        body_text=m.body_text, has_html=bool(m.body_html), note=m.note,
        attachments=[AttachmentOut(id=a.id, filename=a.filename, content_type=a.content_type,
                                   size_bytes=a.size_bytes, is_inline=a.is_inline,
                                   previewable=a.content_type in _PREVIEW_TYPES,
                                   doc_kind=a.doc_kind, doc_type=a.doc_type, doc_family=a.doc_family,
                                   doc_label=a.doc_label, doc_confidence=a.doc_confidence,
                                   doc_reason=(a.doc_meta or {}).get("reason"),
                                   doc_rows=(a.doc_meta or {}).get("rows")) for a in atts],
    )


@router.post("/messages/{message_id}/unread", status_code=204)
async def mark_unread(message_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    m.read_at = None
    await db.commit()
    return Response(status_code=204)


@router.get("/messages/{message_id}/html", response_model=MessageHtmlOut)
async def get_message_html(message_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """The HTML body, sanitised, with the mail's own inline images embedded. The frontend
    still renders it inside a sandboxed iframe with no scripts — two walls, not one."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    if not m.body_html:
        return MessageHtmlOut(html="")
    images: dict[str, tuple[str, bytes]] = {}
    inline = (await db.execute(select(MailAttachment).where(
        MailAttachment.message_id == m.id, MailAttachment.content_id.is_not(None)))).scalars().all()
    for a in inline:
        if not a.content_type.startswith("image/") or a.size_bytes > _MAX_INLINE_IMAGE:
            continue
        try:
            data = await mail_storage.load(a.locator)
        except Exception:  # noqa: BLE001 — a missing image must not hide the message
            continue
        real = sniff(data)
        if real and real.startswith("image/"):
            images[a.content_id or ""] = (real, data)
    return MessageHtmlOut(html=mail_html.sanitise(m.body_html, images))


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: int, inline: bool = False, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """The file. Shown in the browser only when its bytes really are a PDF or an image;
    spreadsheets, archives and anything unknown always download."""
    _require_enabled()
    att = await db.get(MailAttachment, attachment_id)
    if att is None or att.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    await _load_message(db, current_user, att.message_id)      # same visibility as the message
    try:
        data = await mail_storage.load(att.locator)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="This attachment is no longer stored.")
    real = sniff(data)
    show_inline = inline and real in _PREVIEW_TYPES
    headers = {
        "Content-Disposition": f"{'inline' if show_inline else 'attachment'}; filename*=UTF-8''{quote(att.filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if show_inline:
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self' data: blob:; style-src 'unsafe-inline'; sandbox"
    return Response(content=data, media_type=real if show_inline else (att.content_type or "application/octet-stream"),
                    headers=headers)


# ══════════════════════════════════════════════════════════════════════════════
# PROCESSING AN EMAIL — what can be imported, and the files the module wizards need
# ══════════════════════════════════════════════════════════════════════════════
#
# The import itself is the module's own wizard (statement upload, deals upload), opened by the
# inbox with these files pre-loaded: same validation, duplicate checks and approvals as a
# manual upload. These endpoints only plan, hand over files, and remember what was imported.

def _safe_name(text: str | None, fallback: str) -> str:
    import re as _re
    name = _re.sub(r"[^A-Za-z0-9 ._-]+", " ", text or "").strip()[:60]
    return name or fallback


def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(content=data, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    }, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/messages/{message_id}/process", response_model=ProcessPlanOut)
async def get_process_plan(message_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    return ProcessPlanOut(**await mail_process.plan(db, m))


@router.get("/messages/{message_id}/tables/{index}/file")
async def get_table_file(message_id: int, index: int, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """The n-th table in the email body as a real .xlsx, for the module's upload wizard.
    Every cell stays text, so a 13-digit ticket number is never turned into 9.81E+12."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    tables = mail_body.tables(m.body_html)
    if index < 0 or index >= len(tables):
        raise HTTPException(status_code=404, detail="That table is not in this email.")
    name = f"{_safe_name(m.subject, 'email')} - table {index + 1}.xlsx"
    return _xlsx_response(mail_body.to_xlsx(tables[index]), name)


@router.get("/messages/{message_id}/text-deals/file")
async def get_text_deals_file(message_id: int, refresh: bool = False, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(get_current_user)):
    """A deal written as text, read by AI into the deals import's own sheet layout. The result
    is cached on the message, so re-opening the import does not pay for the AI twice."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    text = mail_body.deal_text(mail_process.body_text(m))
    if not text:
        raise HTTPException(status_code=404, detail="This email's text does not read like a deal.")
    cached = (m.processed or {}).get("text_deals") or {}
    rows = cached.get("rows") if not refresh else None
    if rows is None:
        await _limit("mail-text-deals", current_user, 20, 3600)
        try:
            deals = await mail_text_deals.extract(text, subject=m.subject,
                                                  facts=mail_body.facts(m.subject, text))
        except mail_text_deals.TextDealsUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not deals:
            raise HTTPException(status_code=422, detail="No airline and rate could be read from this email's text. "
                                                        "Create the deal by hand from the deal form.")
        rows = mail_text_deals.to_sheet_rows(deals)
        m.processed = {**(m.processed or {}), "text_deals": {"rows": rows, "at": datetime.utcnow().isoformat(timespec="seconds")}}
        await db.commit()
    return _xlsx_response(mail_body.to_xlsx(rows, "Deals"), f"{_safe_name(m.subject, 'email')} - deals.xlsx")


@router.post("/messages/{message_id}/processed", status_code=204)
async def mark_processed(message_id: int, body_in: MarkProcessedIn, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    """Record that an item of this email was imported (called when the module's wizard saved)."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    mail_process.mark(m, body_in.key, destination=body_in.destination, ref=body_in.ref, user_id=current_user.id)
    await db.commit()
    return Response(status_code=204)


@router.delete("/messages/{message_id}/processed/{key}", status_code=204)
async def unmark_processed(message_id: int, key: str, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    """Clear the "imported" mark — e.g. the batch was deleted and should be imported again."""
    _require_enabled()
    m = await _load_message(db, current_user, message_id)
    mail_process.unmark(m, key)
    await db.commit()
    return Response(status_code=204)
