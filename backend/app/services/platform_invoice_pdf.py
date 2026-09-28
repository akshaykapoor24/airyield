"""The printed platform invoice — what a workspace receives from Subscriptions → Generate.

    ┌──────────────────────────────────────────────────────────────────┐
    │ [fareqube logo]                                     TAX INVOICE  │
    │                                  Invoice No.  FQ/26-27/0001      │
    │                                  Date / Due date                 │
    ├────────────────────────────────┬─────────────────────────────────┤
    │ FROM  issuer, GSTIN, PAN       │ BILL TO  workspace, GSTIN, PAN  │
    ├────────────────────────────────┴─────────────────────────────────┤
    │ Place of supply · Billing period · Reverse charge                │
    ├───┬──────────────────────────┬────────┬──────┬────────┬──────────┤
    │ # │ Description              │  SAC   │ Qty  │  Rate  │  Amount  │
    ├───┴──────────────────────────┴────────┴──────┴────────┴──────────┤
    │ Amount in words / payment details     │ Subtotal, CGST, SGST … │
    │                                       │ Total                  │
    │ Notes                                     For <issuer>, signatory │
    └──────────────────────────────────────────────────────────────────┘

EVERY FIGURE IS READ FROM THE ROW, never recomputed — the row is the invoice
(app/models/platform_invoice.py), and a reprint next year must be the same paper.

A sibling of services/billing_pdf.py rather than a mode of it: that builder's table is an
air ticket (date of travel, passenger, sector, SAC 998551) and its heads are per line. This
one prints generic service lines and tax on the subtotal. The Indian amount-in-words helper
is shared.

Helvetica, the PDF base font, has no ₹ glyph, so amounts say INR — as billing_pdf does.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.models.platform_invoice import (
    STATUS_CANCELLED, STATUS_PAID, TREATMENT_INTER, TREATMENT_INTRA,
)
from app.services.billing_pdf import amount_in_words
from app.services.platform_invoices import state_label

_LOGO = Path(__file__).resolve().parents[1] / "assets" / "fareqube-logo.png"

_NAVY = colors.HexColor("#16304f")
_BLUE = colors.HexColor("#3b82c4")
_GREY = colors.HexColor("#6b7280")
_RULE = colors.HexColor("#d1d5db")
_SHADE = colors.HexColor("#f3f6fa")
_RED = colors.HexColor("#dc2626")
_GREEN = colors.HexColor("#15803d")

_MARGIN = 14 * mm
_W = A4[0] - 2 * _MARGIN


def _style(name: str, **kw) -> ParagraphStyle:
    base = {"fontName": "Helvetica", "fontSize": 8.5, "leading": 11.5, "textColor": colors.black}
    base.update(kw)
    return ParagraphStyle(name, **base)


S_BODY = _style("body")
S_SMALL = _style("small", fontSize=7.5, leading=10, textColor=_GREY)
S_LABEL = _style("label", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=_GREY)
S_NAME = _style("name", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=_NAVY)
S_TITLE = _style("title", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=_NAVY, alignment=TA_RIGHT)
S_RIGHT = _style("right", alignment=TA_RIGHT)
S_RIGHT_B = _style("rightb", fontName="Helvetica-Bold", alignment=TA_RIGHT)
S_TH = _style("th", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=colors.white)
S_TH_R = _style("thr", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_RIGHT)
S_TH_C = _style("thc", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_CENTER)
S_SMALL_R = _style("smallr", fontSize=7.5, leading=10, textColor=_GREY, alignment=TA_RIGHT)
S_CENTER = _style("center", alignment=TA_CENTER)


def _esc(value) -> str:
    return xml_escape(str(value)) if value not in (None, "") else ""


def inr(value) -> str:
    """Indian digit grouping to the paisa: 1234567.5 → '12,34,567.50'."""
    d = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}.{frac}"


def _qty(value) -> str:
    d = Decimal(str(value or 0))
    return format(d.normalize(), "f") if d == d.to_integral() else str(d)


def _pct(rate) -> str:
    d = Decimal(str(rate or 0)).normalize()
    return format(d, "f")


def _date(value) -> str:
    return value.strftime("%d %b %Y") if isinstance(value, date) else ""


def words(total) -> str:
    """'Indian Rupees Eleven Thousand Eight Hundred and Fifty Paise Only.'"""
    d = Decimal(str(total or 0)).quantize(Decimal("0.01"))
    rupees, paise = int(abs(d)), int((abs(d) * 100) % 100)
    text = amount_in_words(rupees)
    if paise:
        text = text[: -len(" Only.")] + f" and {amount_in_words(paise)[: -len(' Only.')]} Paise Only."
    return f"Indian Rupees {text}"


# ── blocks ───────────────────────────────────────────────────────────────────

def _party(label: str, p: dict) -> list:
    out = [Paragraph(label, S_LABEL), Spacer(0, 2), Paragraph(_esc(p.get("name")), S_NAME)]
    if p.get("address"):
        out.append(Paragraph(_esc(p["address"]).replace("\n", "<br/>"), S_BODY))
    place = ", ".join(x for x in (p.get("city"), p.get("state"), p.get("pincode")) if x)
    if place:
        country = p.get("country")
        out.append(Paragraph(_esc(place + (f", {country}" if country and country != "India" else "")), S_BODY))
    ids = " &nbsp;&nbsp; ".join(
        f"<b>{k}</b> {_esc(v)}" for k, v in (("GSTIN", p.get("gstin")), ("PAN", p.get("pan"))) if v
    )
    if ids:
        out.append(Paragraph(ids, S_BODY))
    contact = " &nbsp;·&nbsp; ".join(_esc(v) for v in (p.get("email"), p.get("phone")) if v)
    if contact:
        out.append(Paragraph(contact, S_SMALL))
    return out


def _header(inv, taxed: bool) -> Table:
    logo = Image(str(_LOGO), width=52 * mm, height=52 * mm * 209 / 720) if _LOGO.exists() else Paragraph("", S_BODY)
    meta = [
        [Paragraph("Invoice No.", S_SMALL_R), Paragraph(f"<b>{_esc(inv.invoice_number)}</b>", S_RIGHT)],
        [Paragraph("Invoice date", S_SMALL_R), Paragraph(_date(inv.invoice_date), S_RIGHT)],
    ]
    if inv.due_date:
        meta.append([Paragraph("Due date", S_SMALL_R), Paragraph(_date(inv.due_date), S_RIGHT)])
    # The full width of the half, labels and values both right-aligned, so the block sits
    # flush under the title instead of floating mid-page.
    meta_t = Table(meta, colWidths=[_W * 0.5 - 34 * mm, 34 * mm])
    meta_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    right = [Paragraph("TAX INVOICE" if taxed else "INVOICE", S_TITLE), Spacer(0, 3), meta_t]
    stamp = _stamp(inv)
    if stamp:
        right += [Spacer(0, 3), stamp]
    t = Table([[logo, right]], colWidths=[_W * 0.5, _W * 0.5])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _stamp(inv):
    if inv.status == STATUS_CANCELLED:
        reason = f" — {_esc(inv.cancel_reason)}" if inv.cancel_reason else ""
        return Paragraph(f"<font color='#dc2626'><b>CANCELLED</b>{reason}</font>", S_RIGHT)
    if inv.status == STATUS_PAID:
        ref = f" · Ref {_esc(inv.payment_reference)}" if inv.payment_reference else ""
        return Paragraph(f"<font color='#15803d'><b>PAID</b> on {_date(inv.paid_at)}{ref}</font>", S_RIGHT)
    return None


def _facts(inv, taxed: bool) -> Table:
    cells = []
    if inv.place_of_supply_code:
        cells.append(("PLACE OF SUPPLY", state_label(inv.place_of_supply_code)))
    if inv.period_from and inv.period_to:
        cells.append(("BILLING PERIOD", f"{_date(inv.period_from)} – {_date(inv.period_to)}"))
    if taxed:
        cells.append(("REVERSE CHARGE", "No"))
    cells.append(("CURRENCY", inv.currency or "INR"))
    row = [[Paragraph(k, S_LABEL), Paragraph(_esc(v), S_BODY)] for k, v in cells]
    t = Table([[c for c in row]], colWidths=[_W / len(row)] * len(row))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _SHADE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _items(inv) -> Table:
    head = [Paragraph("#", S_TH_C), Paragraph("Description", S_TH), Paragraph("SAC", S_TH_C),
            Paragraph("Qty", S_TH_R), Paragraph("Rate (INR)", S_TH_R), Paragraph("Amount (INR)", S_TH_R)]
    rows = [head]
    for i, line in enumerate(inv.line_items, start=1):
        rows.append([
            Paragraph(str(i), S_CENTER),
            Paragraph(_esc(line.get("description")), S_BODY),
            Paragraph(_esc(line.get("sac")), S_CENTER),
            Paragraph(_qty(line.get("quantity")), S_RIGHT),
            Paragraph(inr(line.get("unit_price")), S_RIGHT),
            Paragraph(inr(line.get("amount")), S_RIGHT),
        ])
    widths = [8 * mm, None, 20 * mm, 16 * mm, 28 * mm, 30 * mm]
    widths[1] = _W - sum(w for w in widths if w)
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _totals(inv) -> Table:
    rate = Decimal(str(inv.gst_rate or 0))
    rows = [["Subtotal", inr(inv.subtotal)]]
    if inv.gst_treatment == TREATMENT_INTRA:
        half = _pct(rate / 2)
        rows += [[f"CGST @ {half}%", inr(inv.cgst)], [f"SGST @ {half}%", inr(inv.sgst)]]
    elif inv.gst_treatment == TREATMENT_INTER:
        rows.append([f"IGST @ {_pct(rate)}%", inr(inv.igst)])
    rows.append(["Total (INR)", inr(inv.grand_total)])
    t = Table(
        [[Paragraph(_esc(k), S_BODY), Paragraph(v, S_RIGHT)] for k, v in rows[:-1]]
        + [[Paragraph(f"<b>{rows[-1][0]}</b>", _style('tl', textColor=colors.white)),
            Paragraph(f"<b>{rows[-1][1]}</b>", _style('tr', textColor=colors.white, alignment=TA_RIGHT))]],
        colWidths=[38 * mm, 32 * mm],
    )
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _RULE),
        ("BACKGROUND", (0, -1), (-1, -1), _NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _payment(inv) -> list:
    bank = (inv.issuer or {}).get("bank") or {}
    lines = [
        (label, bank.get(key)) for label, key in (
            ("Account name", "account_name"), ("Account number", "account_number"),
            ("IFSC", "ifsc"), ("Bank", "bank_name"), ("Branch", "branch"), ("UPI", "upi_id"),
        ) if bank.get(key)
    ]
    out = [Paragraph("AMOUNT IN WORDS", S_LABEL), Paragraph(_esc(words(inv.grand_total)), S_BODY)]
    if lines and inv.status != STATUS_CANCELLED:
        out += [Spacer(0, 6), Paragraph("PAYMENT DETAILS", S_LABEL)]
        out += [Paragraph(f"{_esc(k)}: <b>{_esc(v)}</b>", S_BODY) for k, v in lines]
        out.append(Paragraph(
            f"Please quote <b>{_esc(inv.invoice_number)}</b> as the payment reference.", S_SMALL))
    return out


def _decorate(inv):
    """Footer on every page, and a watermark on a cancelled invoice."""
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(_GREY)
        canvas.drawString(_MARGIN, 9 * mm, "This is a computer-generated invoice.")
        canvas.drawRightString(A4[0] - _MARGIN, 9 * mm, f"{inv.invoice_number} · Page {doc.page}")
        if inv.status == STATUS_CANCELLED:
            canvas.setFont("Helvetica-Bold", 72)
            canvas.setFillColor(_RED)
            canvas.setFillAlpha(0.08)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "CANCELLED")
        canvas.restoreState()
    return draw


def build_platform_invoice_pdf(inv) -> io.BytesIO:
    """The invoice as an A4 PDF. `inv` is a PlatformInvoice, or anything with its fields."""
    issuer, bill_to = inv.issuer or {}, inv.bill_to or {}
    taxed = bool(issuer.get("gstin"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN, bottomMargin=16 * mm,
        title=f"Invoice {inv.invoice_number}", author=issuer.get("name") or "",
    )

    parties = Table([[_party("FROM", issuer), _party("BILL TO", bill_to)]], colWidths=[_W / 2, _W / 2])
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))

    summary = Table([[_payment(inv), _totals(inv)]], colWidths=[_W - 72 * mm, 72 * mm])
    summary.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 10),
        ("RIGHTPADDING", (1, 0), (1, -1), 0),
    ]))

    closing = []
    if inv.notes:
        notes = Table([[[Paragraph("NOTES", S_LABEL),
                         Paragraph(_esc(inv.notes).replace("\n", "<br/>"), S_BODY)]]], colWidths=[_W])
        notes.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        closing += [notes, Spacer(0, 10)]
    sign = Table([[
        "",
        [Paragraph(f"For <b>{_esc(issuer.get('name'))}</b>", S_RIGHT), Spacer(0, 26),
         Paragraph("Authorised Signatory", _style("sig", alignment=TA_RIGHT, textColor=_GREY))],
    ]], colWidths=[_W - 70 * mm, 70 * mm])
    sign.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    closing.append(sign)

    story = [
        _header(inv, taxed),
        Spacer(0, 6),
        Table([[""]], colWidths=[_W], style=[("LINEBELOW", (0, 0), (-1, -1), 1.2, _BLUE)]),
        Spacer(0, 8),
        parties,
        Spacer(0, 8),
        _facts(inv, taxed),
        Spacer(0, 8),
        _items(inv),
        Spacer(0, 8),
        KeepTogether([summary, Spacer(0, 14), *closing]),
    ]
    decorate = _decorate(inv)
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    buf.seek(0)
    return buf


def pdf_filename(inv) -> str:
    """FQ/26-27/0001 → FQ-26-27-0001.pdf — a slash is a path separator in every OS."""
    return f"{inv.invoice_number.replace('/', '-')}.pdf"
