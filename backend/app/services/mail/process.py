"""The processing plan for one email: everything in it that can be imported, and how.

One email can carry several things at once — a consolidator's weekly statement AND next week's
deal sheet attached, a deal grid pasted into the body, or a deal written as plain text. The plan
lists each as an item:

    att:<id>      an attachment the classifier recognised (statement / deal) — or "other",
                  which the user may still import by choosing the type themselves
    table:<n>     the n-th HTML table in the body that reads as a statement or a deal
    text:deals    the body's own words, when they read like a deal circular (AI reads them)

…with the FACTS found in subject, body and file names (period, effective date, totals) and the
SENDER's party, so the module's wizard opens pre-filled: the consolidator for a third-party
statement, the supplier for a B2B deal, the period, the control totals.

Importing itself is the module's own wizard; this module only plans and remembers (in
mail_messages.processed) what was imported where, so nothing is imported twice by accident.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mail import MailAttachment, MailMessage
from app.services.mail import body, mime

TEXT_DEALS_KEY = "text:deals"


def _sender(msg: MailMessage) -> dict:
    parties = msg.parties or []
    first = parties[0] if parties else {}
    agency = next((p for p in parties if p.get("party_type") == "agency"), None)
    return {
        "party_type": first.get("party_type"), "label": first.get("label"), "segment": first.get("segment"),
        # The Agency Master row behind the sender — what a third-party statement is filed
        # against and who a B2B deal is from. A GDS + LCC pair is two rows; the first is offered
        # and the wizard lets the user switch.
        "agency_id": agency.get("party_id") if agency else None,
        "agency_ids": [p.get("party_id") for p in parties if p.get("party_type") == "agency"],
    }


def body_text(msg: MailMessage) -> str:
    return msg.body_text or (mime.html_to_text(msg.body_html) if msg.body_html else "")


async def plan(db: AsyncSession, msg: MailMessage) -> dict:
    done = (msg.processed or {}).get("items", {})
    atts = (await db.execute(
        select(MailAttachment).where(MailAttachment.message_id == msg.id, MailAttachment.is_inline.is_(False))
        .order_by(MailAttachment.part_index)
    )).scalars().all()
    sender = _sender(msg)
    context = msg.subject or ""
    items: list[dict] = []

    for a in atts:
        if a.content_type == "message/rfc822":
            continue                          # the forwarded mail itself; its files are listed on their own
        meta = a.doc_meta or {}
        items.append({
            "key": f"att:{a.id}", "source": "attachment", "attachment_id": a.id, "title": a.filename,
            "content_type": a.content_type, "size_bytes": a.size_bytes,
            "kind": a.doc_kind or "other", "doc_type": a.doc_type, "family": a.doc_family,
            "label": a.doc_label, "confidence": a.doc_confidence, "reason": meta.get("reason"),
            "rows": meta.get("rows"), "imported": done.get(f"att:{a.id}"),
        })

    tables = body.tables(msg.body_html)
    deal_table = False
    for n, t in enumerate(tables):
        c = body.classify_table(t, sender_hint=sender["party_type"], context=context)
        if c.kind not in ("statement", "deal"):
            continue
        deal_table |= c.kind == "deal"
        items.append({
            "key": f"table:{n}", "source": "table", "table_index": n,
            "title": f"Table {n + 1} in the email · {len(t) - 1} row{'s' if len(t) != 2 else ''}",
            "kind": c.kind, "doc_type": c.doc_type, "family": c.family, "label": c.label,
            "confidence": c.confidence, "reason": c.meta.get("reason"), "rows": len(t) - 1,
            "preview": t[:6], "imported": done.get(f"table:{n}"),
        })

    text = body_text(msg)
    # With a deal sheet already attached, the body is usually its covering note — so the bar
    # for "the text is a deal of its own" is higher (two rate lines instead of one).
    deal_attached = any(i["kind"] == "deal" for i in items)
    deal_words = body.deal_text(text, min_lines=2 if deal_attached else 1)
    if deal_words and not deal_table:
        items.append({
            "key": TEXT_DEALS_KEY, "source": "text", "title": "Deal written in the email",
            "kind": "deal", "doc_type": "deal-text", "family": "deal", "label": "Deal in email text",
            "confidence": 0.6, "reason": "deal wording and percentages in the message",
            "preview_text": deal_words[:600], "imported": done.get(TEXT_DEALS_KEY),
        })

    facts = body.facts(msg.subject, body.new_content(text), *[a.filename for a in atts])
    return {"message_id": msg.id, "subject": msg.subject, "sender": sender, "facts": facts, "items": items}


def mark(msg: MailMessage, key: str, *, destination: str, ref: str | None, user_id: int) -> None:
    processed = dict(msg.processed or {})
    items = dict(processed.get("items", {}))
    items[key] = {"destination": destination, "ref": ref, "at": datetime.utcnow().isoformat(timespec="seconds"),
                  "by": user_id}
    processed["items"] = items
    msg.processed = processed           # a new dict, so the JSONB change is saved


def unmark(msg: MailMessage, key: str) -> None:
    processed = dict(msg.processed or {})
    items = dict(processed.get("items", {}))
    items.pop(key, None)
    processed["items"] = items
    msg.processed = processed
