"""RFC 5322 bytes → the parts the inbox needs: headers, text, HTML, attachments.

One parser for every provider (architecture/02 D3): IMAP, Gmail and Graph all hand over the
same raw bytes. Pure — no database, no storage — so it is unit-tested on fixture mails.

What it copes with, because supplier mail is rarely tidy:
  * encoded subjects and filenames (RFC 2047 / 2231) — policy.default decodes them;
  * charsets that lie — a part that will not decode as declared is retried as cp1252, then
    replaced, rather than failing the whole message;
  * a nameless attachment — named attachment-<n>.<ext> from its type;
  * a forwarded mail attached as a message (.eml) — its attachments are surfaced too, since
    the statement a colleague forwards is usually inside it;
  * inline images (cid:) — kept apart from attachments, so a pasted deal flyer shows in the
    message and a signature logo does not clutter the attachment list.
"""
from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

_MAX_SNIPPET = 280
_WS = re.compile(r"\s+")


@dataclass
class Part:
    index: int
    filename: str
    content_type: str
    data: bytes
    is_inline: bool = False
    content_id: str | None = None


@dataclass
class ParsedMail:
    subject: str | None
    from_name: str | None
    from_address: str | None
    sender_address: str | None
    reply_to: list[str]
    to: list[str]
    cc: list[str]
    sent_at: datetime | None
    message_id: str | None
    in_reply_to: str | None
    text: str | None
    html: str | None
    parts: list[Part] = field(default_factory=list)

    @property
    def attachments(self) -> list[Part]:
        return [p for p in self.parts if not p.is_inline]

    @property
    def snippet(self) -> str:
        source = self.text or html_to_text(self.html or "")
        return _WS.sub(" ", source).strip()[:_MAX_SNIPPET]


def _addresses(msg: EmailMessage, header: str) -> list[tuple[str, str]]:
    values = msg.get_all(header, [])
    return [(name.strip(), addr.strip().lower()) for name, addr in getaddresses([str(v) for v in values]) if "@" in addr]


def _content(part: EmailMessage) -> str | None:
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        for enc in ("cp1252", "latin-1"):
            try:
                return payload.decode(enc)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")


def _filename(part: EmailMessage, index: int) -> str:
    name = part.get_filename()
    if name:
        return name.strip().replace("\r", "").replace("\n", "")[:480]
    ext = mimetypes.guess_extension(part.get_content_type()) or ".bin"
    return f"attachment-{index}{ext}"


def _sent_at(msg: EmailMessage) -> datetime | None:
    try:
        dt = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def html_to_text(html: str) -> str:
    import nh3
    without_tags = nh3.clean(re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", html), tags=set())
    return re.sub(r"&nbsp;|&#160;", " ", without_tags)


def parse(raw: bytes) -> ParsedMail:
    msg: EmailMessage = message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    frm = _addresses(msg, "From")
    sender = _addresses(msg, "Sender")
    mail = ParsedMail(
        subject=(str(msg["Subject"]).strip() if msg["Subject"] else None),
        from_name=(frm[0][0] or None) if frm else None,
        from_address=frm[0][1] if frm else None,
        sender_address=sender[0][1] if sender else None,
        reply_to=[a for _, a in _addresses(msg, "Reply-To")],
        to=[a for _, a in _addresses(msg, "To")],
        cc=[a for _, a in _addresses(msg, "Cc")],
        sent_at=_sent_at(msg),
        message_id=(str(msg["Message-ID"]).strip() or None) if msg["Message-ID"] else None,
        in_reply_to=(str(msg["In-Reply-To"]).strip() or None) if msg["In-Reply-To"] else None,
        text=None, html=None,
    )
    _walk(msg, mail)
    return mail


def _walk(msg: EmailMessage, mail: ParsedMail) -> None:
    body = msg.get_body(preferencelist=("related", "html", "plain"))
    text_part = msg.get_body(preferencelist=("plain",))
    if text_part is not None:
        mail.text = _content(text_part)
    if body is not None:
        html_part = body.get_body(preferencelist=("html",)) if body.get_content_type() == "multipart/related" else body
        if html_part is not None and html_part.get_content_type() == "text/html":
            mail.html = _content(html_part)
        elif mail.text is None and html_part is not None and html_part.get_content_type() == "text/plain":
            mail.text = _content(html_part)

    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            # A forwarded mail as an attachment: keep the .eml. walk() then descends into it,
            # so the statement inside the forward surfaces as an attachment of its own.
            inner = part.get_payload(0) if isinstance(part.get_payload(), list) else None
            data = inner.as_bytes() if inner is not None else (part.get_payload(decode=True) or b"")
            name = part.get_filename() or f"forwarded-message-{len(mail.parts)}.eml"
            mail.parts.append(Part(len(mail.parts), name, "message/rfc822", data))
            continue
        if part.is_multipart():
            continue
        if part is text_part or (mail.html is not None and ctype == "text/html" and _content(part) == mail.html):
            continue
        disposition = (part.get_content_disposition() or "").lower()
        cid = (part.get("Content-ID") or "").strip().strip("<>") or None
        if disposition != "attachment" and ctype in ("text/plain", "text/html") and not part.get_filename():
            continue          # an alternative rendering of the body, not a file
        data = part.get_payload(decode=True)
        if data is None:
            continue
        inline = disposition == "inline" or (disposition == "" and cid is not None and ctype.startswith("image/"))
        mail.parts.append(Part(len(mail.parts), _filename(part, len(mail.parts)), ctype, data,
                               is_inline=inline and cid is not None, content_id=cid))
