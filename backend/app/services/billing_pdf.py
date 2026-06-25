"""Build a customer billing invoice PDF (black & white).

Layout: agency (FROM) on the left, customer (BILL TO) on the right, then a
ticket line-item table and totals. Plain black/white styling, no fill colors.
"""
import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable

_GREY = colors.HexColor("#666666")
_LINE = colors.HexColor("#cccccc")
_BLACK = colors.black


def _money(v) -> str:
    try:
        return f"INR {float(v):,.2f}"
    except (TypeError, ValueError):
        return "INR 0.00"


def _num(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def build_billing_pdf(billing, customer, agency: dict | None = None) -> io.BytesIO:
    agency = agency or {}
    items = billing.line_items or []

    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, textColor=_BLACK, leading=24)
    invoice_word = ParagraphStyle("invw", fontName="Helvetica-Bold", fontSize=22, textColor=_BLACK, alignment=TA_RIGHT, leading=26)
    small_r = ParagraphStyle("smallr", fontName="Helvetica", fontSize=9, textColor=_GREY, alignment=TA_RIGHT, leading=13)
    label = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8, textColor=_GREY, leading=12, spaceAfter=2)
    name_b = ParagraphStyle("nameb", fontName="Helvetica-Bold", fontSize=11, textColor=_BLACK, leading=15)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=_BLACK, leading=13)

    invoice_no = f"BILL-{billing.created_at:%Y}-{billing.id:04d}"
    inv_date = f"{billing.created_at:%d/%m/%Y}"
    period = f"{billing.period_from:%d %b %Y} - {billing.period_to:%d %b %Y}"

    cust_org = (customer.company or f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer")
    cust_contact = f"{customer.first_name or ''} {customer.last_name or ''}".strip()

    # ── Header: agency name (left) + INVOICE block (right) ──
    header = Table(
        [[
            Paragraph(agency.get("name") or "Agency", title),
            [
                Paragraph("Billing", invoice_word),
                Paragraph(f"Billing #: {invoice_no}", small_r),
                Paragraph(f"Date: {inv_date}", small_r),
            ],
        ]],
        colWidths=[95 * mm, 80 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    # ── FROM / BILL TO ──
    from_cell = [Paragraph("FROM", label), Paragraph(agency.get("name") or "Agency", name_b)]
    if agency.get("domain"):
        from_cell.append(Paragraph(agency["domain"], body))
    if agency.get("email"):
        from_cell.append(Paragraph(agency["email"], body))

    to_cell = [Paragraph("BILL TO", label), Paragraph(cust_org, name_b)]
    if customer.company and cust_contact:
        to_cell.append(Paragraph(cust_contact, body))
    if customer.title:
        to_cell.append(Paragraph(customer.title, body))
    if customer.email:
        to_cell.append(Paragraph(customer.email, body))
    if customer.phone:
        to_cell.append(Paragraph(customer.phone, body))
    if getattr(customer, "gst_no", None):
        to_cell.append(Paragraph(f"GST No: {customer.gst_no}", body))
    to_cell.append(Paragraph(f"Billing period: {period}", body))

    parties = Table([[from_cell, to_cell]], colWidths=[95 * mm, 80 * mm])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    # ── Ticket table (markup column merges markup + additional markup) ──
    rows: list[list[str]] = [
        ["Ticket #", "Passenger", "Airline", "Sector", "Date", "Base", "Markup", "GST", "Total"]
    ]
    for it in items:
        markup = float(it.get("markup_amount") or 0) + float(it.get("additional_markup") or 0)
        rows.append([
            it.get("ticket_number") or "-",
            it.get("passenger") or "-",
            it.get("airline_name") or it.get("airlines_code") or "-",
            it.get("sector") or "-",
            it.get("ticket_date") or "-",
            _num(it.get("base_amount")),
            _num(markup),
            _num(it.get("gst_amount")),
            _num(it.get("total")),
        ])

    table = Table(rows, repeatRows=1, colWidths=[24 * mm, 30 * mm, 24 * mm, 18 * mm, 20 * mm, 16 * mm, 16 * mm, 14 * mm, 18 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 0), (-1, -1), _BLACK),
        ("ALIGN",         (5, 0), (-1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.75, _BLACK),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.25, _LINE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
    ]))

    # ── Totals (right-aligned) ──
    subtotal = float(billing.total_base or 0) + float(billing.total_markup or 0) + float(billing.total_additional_markup or 0)
    totals = Table(
        [
            ["Subtotal:", _money(subtotal)],
            ["GST (18%):", _money(billing.total_gst)],
            ["TOTAL:", _money(billing.grand_total)],
        ],
        colWidths=[35 * mm, 35 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, 1), "Helvetica"),
        ("FONTNAME",      (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (0, -1), "RIGHT"),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("TEXTCOLOR",     (0, 0), (-1, -1), _BLACK),
        ("LINEABOVE",     (0, 2), (-1, 2), 0.75, _BLACK),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )
    elements = [
        header,
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=0.5, color=_LINE),
        Spacer(1, 6 * mm),
        parties,
        Spacer(1, 8 * mm),
        table,
        Spacer(1, 4 * mm),
        totals,
    ]
    doc.build(elements)
    buf.seek(0)
    return buf
