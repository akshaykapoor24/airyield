"""Build a GST tax invoice PDF for a saved billing.

THE LAYOUT, and why it is this one
──────────────────────────────────
Modelled on a real invoice the business issues, so the document a customer
receives from this system looks like the one they already receive:

    ┌──────────────────────────────────────────────────────────────────┐
    │ [logo]            COMPANY NAME                    Tel : …        │
    │              address · email · GSTIN                             │
    │                     ┌─────────────┐                              │
    │                     │ TAX INVOICE │                              │
    ├───────────────────────────────────┬──────────────────────────────┤
    │ Invoice No. / Invoice Date        │  Place of Supply : 07-Delhi  │
    │ Bill To: name, address, Party GST │                              │
    ├──────┬────────────┬──────┬────────┼────────┬────────┬──────┬─────┤
    │Hs/Sac│Description │Amount│Taxable │  CGST  │  SGST  │ IGST │Total│
    │ Code │            │      │ Value  │ %  Amt │ %  Amt │% Amt │     │
    └──────┴────────────┴──────┴────────┴────────┴────────┴──────┴─────┘
            Add GST Tax · Nett Bill Amount · amount in words

WHAT "AMOUNT" AND "TAXABLE VALUE" MEAN, because they are not the same number
───────────────────────────────────────────────────────────────────────────
`Amount` is what the line costs before tax — fare plus markup less discount.
`Taxable Value` is only the slice of that which GST is charged on, which for an
agency sale is the markup alone: the airline has already taxed the fare, and
taxing it again would be charging tax on tax. On a real sale those differ by
more than an order of magnitude (the reference invoice: 26,53,226 against
95,700), so printing one where the other belongs would misstate the tax base on
a document a tax authority reads. It is taken from the same `gst_taxable` the
tax itself was computed from, never re-derived here.

WHO IS BILLED is decided by the billing's own foreign key, not by inspecting the
party object: `corporate_id` means the company is the recipient and its
registered address and GSTIN head the block; `customer_id` means the person is,
and they are billed under their own name. That is the business's rule — a
corporate is billed as the corporate, a direct sale is billed to the traveller.

EVERY FIGURE IS READ, NEVER RECOMPUTED. The billing is a snapshot: its heads,
its state codes and its line items were fixed when it was raised. A reprint next
year has to produce the same paper, so nothing here recalculates tax.
"""
import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.services.billing_calc import GST_RATE, HALF_GST_RATE, gst_taxable

_GREY = colors.HexColor("#666666")
_LINE = colors.HexColor("#999999")
_BLACK = colors.black

# SAC 998551 — "Reservation services for transportation". The service code an
# air-ticket agent's invoice carries, and the one on the reference invoice. A
# constant rather than a column because every line this system bills is that one
# service; give it a home in the GST master if a workspace ever sells another.
SAC_CODE = "998551"

# The printed page, minus its margins. Every table below is sized against this,
# so the widths cannot silently overflow when one is edited.
_MARGIN = 12 * mm
_CONTENT_W = A4[0] - 2 * _MARGIN


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


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ── amount in words ────────────────────────────────────────────────────────
# The Indian system, which groups as crore / lakh / thousand rather than in
# thousands throughout: 2670452 reads "Twenty Six Lakh Seventy Thousand Four
# Hundred Fifty Two", not "Two Million …". A western grouping here would be
# wrong on every invoice over a lakh, which is most of them.
_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _under_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _under_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_under_hundred(rest))
    return " ".join(parts)


def amount_in_words(value) -> str:
    """'2670452' -> 'Twenty Six Lakh Seventy Thousand Four Hundred Fifty Two Only.'

    Rupees only. Paise are dropped rather than spelled: the reference invoice
    words whole rupees, and a credit note (a negative total) is worded as its
    magnitude with the sign left to the figures, which is how they are read.
    """
    rupees = int(abs(_f(value)))
    if rupees == 0:
        return "Zero Only."
    groups = []
    crore, rest = divmod(rupees, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, hundreds = divmod(rest, 1_000)
    if crore:
        groups.append(f"{amount_in_words(crore)[:-6].strip() if crore > 99 else _under_hundred(crore)} Crore")
    if lakh:
        groups.append(f"{_under_hundred(lakh)} Lakh")
    if thousand:
        groups.append(f"{_under_hundred(thousand)} Thousand")
    if hundreds:
        groups.append(_under_thousand(hundreds))
    return " ".join(g for g in groups if g).strip() + " Only."


# ── the supplier side ──────────────────────────────────────────────────────
def supplier_block(tenant, user) -> dict:
    """The FROM party — who is raising this invoice, and under which registration.

    One helper because the customer, corporate and agency PDF endpoints all need
    the identical block; each used to build its own three-key dict, and none of
    them carried a GSTIN. `tenant` may be None (a workspace deleted out from
    under a user), so every read is guarded.

    The logo is NOT loaded here: it is bytes in a blob store and this stays
    synchronous and unit-testable. Endpoints call `load_logo` and add it.
    """
    return {
        "name": (tenant.name if tenant and tenant.name else (tenant.domain if tenant else "")) or user.full_name,
        "domain": tenant.domain if tenant else "",
        "email": user.email,
        "phone": getattr(tenant, "phone", None),
        "gst_number": getattr(tenant, "gst_number", None),
        "pan_number": getattr(tenant, "pan_number", None),
        "address": getattr(tenant, "address", None),
        "city": getattr(tenant, "city", None),
        "state": getattr(tenant, "state", None),
        "pincode": getattr(tenant, "pincode", None),
    }


async def load_logo(tenant) -> bytes | None:
    """The workspace's letterhead image, or None.

    Every failure is swallowed on purpose. A missing blob, an unreachable
    bucket, a row that outlived its file — none of those are a reason to refuse
    a customer their invoice, and the page reads perfectly well without a logo.
    """
    if tenant is None or not getattr(tenant, "logo_path", None):
        return None
    try:
        from app.config import settings
        from app.services import file_store
        return await file_store.load(tenant.logo_path, settings.GCS_LOGOS_BUCKET_NAME)
    except Exception:
        return None


def _logo_flowable(raw: bytes | None, box_w: float, box_h: float):
    """The logo scaled to fit its box, or None if it cannot be drawn.

    Goes through PIL so a WEBP — which the profile accepts and reportlab cannot
    place directly — still prints, and so the aspect ratio is preserved rather
    than the image being squashed into the box.
    """
    if not raw:
        return None
    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        scale = min(box_w / img.width, box_h / img.height)
        return Image(buf, width=img.width * scale, height=img.height * scale)
    except Exception:
        return None


# ── the recipient side ─────────────────────────────────────────────────────
def _bill_to_lines(billing, party) -> tuple[str, list[str]]:
    """(headline, detail lines) for the BILL TO block.

    The billing's own foreign key decides, not the shape of `party`:

      corporate_id  the COMPANY is the recipient. Its registered name heads the
                    block and its address follows — an employee's ticket billed
                    to their employer is a supply to the employer, and the
                    invoice has to be addressed to the entity that will claim
                    the credit.
      customer_id   the PERSON is. They are billed under their own name; their
                    company, if they have one, is context on a later line rather
                    than the addressee, because they are not billing it.
      agency_id     the agency, which arrives already shaped as a party.
    """
    def text(attr):
        value = getattr(party, attr, None)
        return str(value).strip() if value not in (None, "") else None

    person = " ".join(x for x in (text("first_name"), text("last_name")) if x)
    company = text("company")

    if getattr(billing, "corporate_id", None):
        headline = company or person or "Customer"
        lines = []
    elif getattr(billing, "customer_id", None):
        # A direct sale: bill the traveller by name. Their employer's name is
        # still worth showing — it is how the invoice is recognised — but it is
        # not who is being billed.
        headline = person or company or "Customer"
        lines = [company] if company and company != headline else []
    else:
        headline = company or person or "Agency"
        lines = []

    if text("address"):
        lines.extend(str(getattr(party, "address")).splitlines())
    locality = ", ".join(x for x in (text("city"), text("state")) if x)
    pin = text("pincode")
    if locality or pin:
        lines.append(f"{locality}-{pin}" if locality and pin else (locality or pin))
    if text("country"):
        lines.append(text("country"))
    for label, attr in (("", "email"), ("", "phone")):
        if text(attr):
            lines.append(f"{label}{text(attr)}")
    return headline, [ln for ln in lines if ln]


def _place_of_supply(billing) -> str:
    """'07-Delhi' — the code and the state it names, as an invoice prints it.

    Read from the billing's snapshot. A bill raised before the split has no code
    stored, and saying nothing is better than guessing one.
    """
    from app.core.india_tax import GST_STATE_CODES

    code = getattr(billing, "place_of_supply_code", None)
    if not code:
        return "—"
    name = GST_STATE_CODES.get(code)
    return f"{code}-{name}" if name else code


def _invoice_number(billing, agency: dict) -> str:
    """'MY/26-27/0099' — a prefix, the Indian financial year, and the serial.

    The financial year runs April to March, so an invoice dated August 2026 sits
    in 26-27. Derived from the billing rather than stored, exactly as the old
    'BILL-2026-0099' was.
    """
    raised = getattr(billing, "created_at", None) or date.today()
    year = raised.year
    fy_start = year if raised.month >= 4 else year - 1
    fy = f"{fy_start % 100:02d}-{(fy_start + 1) % 100:02d}"

    words = [w for w in (agency.get("name") or "").split() if w]
    if len(words) >= 2:
        prefix = "".join(w[0] for w in words[:3]).upper()
    elif words:
        prefix = words[0][:2].upper()
    else:
        prefix = "INV"
    return f"{prefix}/{fy}/{billing.id:04d}"


# ── the document ───────────────────────────────────────────────────────────
def build_billing_pdf(billing, customer, agency: dict | None = None) -> io.BytesIO:
    agency = agency or {}
    items = billing.line_items or []

    big = ParagraphStyle("big", fontName="Helvetica-Bold", fontSize=20, textColor=_BLACK,
                         leading=23, alignment=TA_CENTER)
    mid_c = ParagraphStyle("midc", fontName="Helvetica-Bold", fontSize=8, textColor=_BLACK,
                           leading=11, alignment=TA_CENTER)
    small_r = ParagraphStyle("smallr", fontName="Helvetica-Bold", fontSize=8.5, textColor=_BLACK,
                             leading=12, alignment=TA_RIGHT)
    banner = ParagraphStyle("banner", fontName="Helvetica-Bold", fontSize=13, textColor=_BLACK,
                            leading=16, alignment=TA_CENTER)
    label = ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8.5, textColor=_BLACK, leading=12)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=8.5, textColor=_BLACK, leading=12)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, textColor=_BLACK, leading=10)
    cell_b = ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=7.5, textColor=_BLACK, leading=10)
    foot = ParagraphStyle("foot", fontName="Helvetica", fontSize=7.5, textColor=_BLACK, leading=11)
    foot_r = ParagraphStyle("footr", fontName="Helvetica", fontSize=7.5, textColor=_BLACK,
                            leading=11, alignment=TA_RIGHT)

    # ── letterhead: logo | company block | phone ──
    head_block = [Paragraph(agency.get("name") or "Agency", big)]
    addr_bits = [agency.get("address")]
    locality = ", ".join(x for x in (agency.get("city"), agency.get("state")) if x)
    if locality or agency.get("pincode"):
        addr_bits.append(
            f"{locality}-{agency['pincode']}" if locality and agency.get("pincode")
            else (locality or agency.get("pincode"))
        )
    line = ", ".join(str(b).replace("\n", ", ") for b in addr_bits if b)
    if line:
        head_block.append(Paragraph(line, mid_c))
    if agency.get("email"):
        head_block.append(Paragraph(f"Email : {agency['email']}", mid_c))
    if agency.get("gst_number"):
        head_block.append(Paragraph(f"GST NO. : {agency['gst_number']}", mid_c))

    phone_cell = ""
    if agency.get("phone"):
        # Two numbers stacked, the way a letterhead carries them.
        nums = [n.strip() for n in str(agency["phone"]).replace(",", "\n").splitlines() if n.strip()]
        phone_cell = Paragraph("Tel : " + "<br/>".join(nums), small_r)

    logo = _logo_flowable(agency.get("logo"), 26 * mm, 18 * mm)
    letterhead = Table(
        [[logo or "", head_block, phone_cell]],
        colWidths=[28 * mm, _CONTENT_W - 28 * mm - 32 * mm, 32 * mm],
    )
    letterhead.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 0), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))

    title = Table([[Paragraph("TAX INVOICE", banner)]], colWidths=[46 * mm], hAlign="CENTER")
    title.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, _BLACK),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eeeeee")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    # ── invoice meta + BILL TO, with place of supply beside them ──
    raised = getattr(billing, "created_at", None)
    meta = [
        Paragraph(f"<b>Invoice No. :</b>&nbsp;&nbsp;&nbsp;{_invoice_number(billing, agency)}", label),
        Paragraph(f"<b>Invoice Date:</b>&nbsp;&nbsp;&nbsp;{raised:%d-%m-%Y}" if raised else "", label),
    ]
    headline, detail = _bill_to_lines(billing, customer)
    bill_to = [Paragraph("<b>Bill To&nbsp;&nbsp;&nbsp;:</b>", label), Paragraph(headline, body)]
    bill_to.extend(Paragraph(ln, body) for ln in detail)
    if getattr(customer, "gst_no", None):
        bill_to.append(Paragraph(f"Party GST No. {customer.gst_no}", body))
    elif getattr(customer, "gst_number", None):
        bill_to.append(Paragraph(f"Party GST No. {customer.gst_number}", body))
    bill_to.append(Paragraph(
        f"Billing period: {billing.period_from:%d %b %Y} - {billing.period_to:%d %b %Y}", body,
    ))

    pos = [
        Paragraph(f"<b>Place of Supply :</b>&nbsp;&nbsp;&nbsp;{_place_of_supply(billing)}", label),
    ]
    meta_w = _CONTENT_W * 0.58
    header_box = Table(
        [[meta, pos], [bill_to, ""]],
        colWidths=[meta_w, _CONTENT_W - meta_w],
    )
    header_box.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("SPAN", (1, 0), (1, 1)),
        ("BOX", (0, 0), (-1, -1), 0.75, _BLACK),
        ("LINEAFTER", (0, 0), (0, -1), 0.75, _BLACK),
        ("LINEBELOW", (0, 0), (0, 0), 0.75, _BLACK),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    # ── line items ──
    # The rates that were charged, from the billing's own treatment. Not derived
    # per line from amount/taxable: that produces rounding noise like 8.99% on
    # small values, and the rate is a property of the supply, not of the line.
    treatment = getattr(billing, "gst_treatment", None)
    pct = {"cgst": 0.0, "sgst": 0.0, "igst": 0.0}
    if treatment == "cgst_sgst":
        pct["cgst"] = pct["sgst"] = HALF_GST_RATE * 100
    elif treatment == "igst":
        pct["igst"] = GST_RATE * 100

    rows = [
        [
            Paragraph("Hs/Sac<br/>Code", cell_b), Paragraph("Description", cell_b),
            Paragraph("Amount", cell_b), Paragraph("Taxable<br/>Value", cell_b),
            Paragraph("CGST", cell_b), "", Paragraph("SGST", cell_b), "",
            Paragraph("IGST", cell_b), "", Paragraph("Total", cell_b),
        ],
        [
            "", Paragraph("Date of Travel&nbsp;&nbsp;&nbsp;Ticket&nbsp;&nbsp;&nbsp;Number", cell_b),
            "", "",
            Paragraph("%", cell_b), Paragraph("Amount", cell_b),
            Paragraph("%", cell_b), Paragraph("Amount", cell_b),
            Paragraph("%", cell_b), Paragraph("Amount", cell_b), "",
        ],
    ]

    total_amount = total_taxable = 0.0
    for it in items:
        base = _f(it.get("base_amount"))
        markup = _f(it.get("markup_amount")) + _f(it.get("additional_markup"))
        disc = _f(it.get("discount"))
        amount = base + markup - disc
        # The same figure the tax was charged on — see the module docstring.
        taxable = gst_taxable(base, markup, getattr(billing, "billing_type", None), disc)
        total_amount += amount
        total_taxable += taxable

        desc = [
            f"{it.get('ticket_date') or '-'}&nbsp;&nbsp;&nbsp;"
            f"{it.get('ticket_number') or '-'}&nbsp;&nbsp;&nbsp;"
            f"{it.get('airline_name') or it.get('airlines_code') or '-'}",
            f"<b>Passenger</b>&nbsp;&nbsp;{it.get('passenger') or '-'}",
            f"<b>Sector</b>&nbsp;&nbsp;{it.get('sector') or '-'}",
        ]
        rows.append([
            Paragraph(SAC_CODE, cell),
            Paragraph("<br/>".join(desc), cell),
            Paragraph(_num(amount), cell), Paragraph(_num(taxable), cell),
            Paragraph(f"{pct['cgst']:.2f}", cell), Paragraph(_num(it.get("cgst")), cell),
            Paragraph(f"{pct['sgst']:.2f}", cell), Paragraph(_num(it.get("sgst")), cell),
            Paragraph(f"{pct['igst']:.2f}", cell), Paragraph(_num(it.get("igst")), cell),
            Paragraph(_num(it.get("total")), cell),
        ])

    rows.append([
        "", Paragraph("<b>Total :</b>", cell_b), "",
        Paragraph(_num(total_taxable), cell_b),
        "", Paragraph(_num(billing.total_cgst), cell_b),
        "", Paragraph(_num(billing.total_sgst), cell_b),
        "", Paragraph(_num(billing.total_igst), cell_b),
        Paragraph(_num(billing.grand_total), cell_b),
    ])

    # 11 columns summing to exactly the content width.
    widths = [13, 48, 19, 18, 8, 14, 8, 14, 8, 14, 22]
    scale = _CONTENT_W / (sum(widths) * mm)
    table = Table(rows, repeatRows=2, colWidths=[w * mm * scale for w in widths])
    last = len(rows) - 1
    table.setStyle(TableStyle([
        # The header's grouped columns: CGST, SGST and IGST each cover a % and an
        # Amount, while the plain columns run down through both header rows.
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (2, 0), (2, 1)),
        ("SPAN", (3, 0), (3, 1)),
        ("SPAN", (4, 0), (5, 0)),
        ("SPAN", (6, 0), (7, 0)),
        ("SPAN", (8, 0), (9, 0)),
        ("SPAN", (10, 0), (10, 1)),
        ("SPAN", (0, last), (1, last)),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (4, 0), (9, 1), "CENTER"),
        ("ALIGN", (0, last), (1, last), "RIGHT"),
        ("VALIGN", (0, 0), (-1, 1), "MIDDLE"),
        ("VALIGN", (0, 2), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, _LINE),
        ("BOX", (0, 0), (-1, -1), 0.75, _BLACK),
        ("LINEBELOW", (0, 1), (-1, 1), 0.75, _BLACK),
        ("LINEABOVE", (0, last), (-1, last), 0.75, _BLACK),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))

    # ── the money that closes the invoice ──
    tax_total = _f(billing.total_cgst) + _f(billing.total_sgst) + _f(billing.total_igst)
    # A pre-split billing has heads of zero but real tax; its stored total is the
    # only truthful figure for the "Add GST Tax" line.
    unsplit_tax = 0.0
    if tax_total == 0:
        tax_total = _f(billing.total_gst)
        unsplit_tax = tax_total

    # A bill raised before the place of supply was recorded carries real tax that
    # belongs under no head. Leaving the three columns at zero would read as "no
    # tax charged" while the Total column plainly includes it, so say what it is.
    unsplit_note = []
    if unsplit_tax:
        unsplit_note = [Paragraph(
            f"GST of {_num(unsplit_tax)} is included in the Total above. This bill was "
            "raised before the place of supply was recorded, so it is not split into "
            "CGST/SGST or IGST.", foot,
        ), Spacer(1, 2 * mm)]

    closing = Table(
        [
            ["", Paragraph("Add GST Tax :", foot_r), Paragraph(_num(tax_total), foot_r)],
            [
                Paragraph("<b>Payment Mode :</b>&nbsp;&nbsp;CHQ/DD/TC", foot),
                Paragraph("<b>Nett Bill Amount :</b>", foot_r),
                Paragraph(f"<b>{_num(billing.grand_total)}</b>", foot_r),
            ],
        ],
        colWidths=[_CONTENT_W - 60 * mm, 35 * mm, 25 * mm],
    )
    closing.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (2, 1), (2, 1), 0.75, _BLACK),
        ("LINEABOVE", (1, 0), (2, 0), 0.5, _LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))

    company = agency.get("name") or "us"
    jurisdiction = agency.get("state") or agency.get("city")
    terms = [
        Paragraph(f"E.&amp; O.E. {amount_in_words(billing.grand_total)}", foot),
        Paragraph(f"Payment if made by crossed Cheque to be in favour of {company}", foot),
    ]
    if jurisdiction:
        terms.append(Paragraph(f"All Disputes are subject to {jurisdiction} Jurisdiction.", foot))
    terms.append(Paragraph(
        "N.B. - Bills not paid within Due Date of date hereof will be charged 18 % over due interest.", foot,
    ))

    signoff = Table(
        [[terms, [
            Paragraph(f"FOR {company.upper()}", foot_r),
            Spacer(1, 10 * mm),
            Paragraph("<b>Computer Generated Bill does not require Signature.</b>", foot_r),
            Paragraph("<b>Authorised Signatory</b>", foot_r),
        ]]],
        colWidths=[_CONTENT_W * 0.58, _CONTENT_W * 0.42],
    )
    signoff.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=f"Tax Invoice {_invoice_number(billing, agency)}",
        leftMargin=_MARGIN, rightMargin=_MARGIN, topMargin=10 * mm, bottomMargin=10 * mm,
    )
    doc.build([
        letterhead,
        Spacer(1, 3 * mm),
        title,
        Spacer(1, 3 * mm),
        header_box,
        table,
        Paragraph("Page No :&nbsp;&nbsp;1", foot),
        Spacer(1, 2 * mm),
        *unsplit_note,
        # Kept together so the closing figures never strand on a page of their own,
        # which on an invoice reads as a second, different bill.
        KeepTogether([closing, Spacer(1, 2 * mm), signoff]),
    ])
    buf.seek(0)
    return buf
