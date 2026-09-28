"""Invoices the platform raises to a workspace: numbering, tax, and the form's defaults.

The table and why it is shaped the way it is: app/models/platform_invoice.py.
The printed document: services/platform_invoice_pdf.py.

THE ARITHMETIC IS DECIMAL, AND DONE ONCE
    Every line is quantity × rate rounded half-up to the paisa; tax is charged on the
    subtotal, not per line, so an invoice of forty ₹1.10 lines does not drift by a rupee
    of rounding. CGST and SGST are each half the rate rounded separately — the way the
    return files them, and so the two heads are always equal on paper. The results are
    stored; nothing downstream (PDF, email, list) recomputes them.

WHO MAY CHARGE GST
    Only a registered supplier. An issuer with no GSTIN raises a plain INVOICE with no
    tax heads at all rather than a TAX INVOICE with GST it has no right to collect.
    With a GSTIN, the heads follow place of supply exactly as billings do — core/india_tax
    decides, the GSTIN winning over a typed state — and an undecidable pair is refused
    rather than defaulted: silently choosing CGST+SGST for what is really an inter-state
    supply is the one mistake a tax invoice must not make.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.india_tax import (
    GST_STATE_CODES, canonical_state, gstin_error, is_interstate, normalise, pan_error,
    place_of_supply_code,
)
from app.models.platform_invoice import (
    STATUS_CANCELLED, STATUS_ISSUED, TREATMENT_INTER, TREATMENT_INTRA, TREATMENT_NONE,
    PlatformInvoice,
)

_PAISA = Decimal("0.01")
_PARTY_FIELDS = ("name", "address", "city", "state", "pincode", "country", "gstin", "pan", "email", "phone")
_BANK_FIELDS = ("account_name", "account_number", "ifsc", "bank_name", "branch", "upi_id")


class InvoiceError(ValueError):
    """A problem with what the admin entered, worded for them. The router answers 400."""


def q2(value: Any) -> Decimal:
    return Decimal(value).quantize(_PAISA, rounding=ROUND_HALF_UP)


# ── numbering ────────────────────────────────────────────────────────────────

def financial_year(d: date) -> str:
    """The Indian financial year a date falls in: 28 Sep 2026 → '26-27', 2 Feb 2027 → '26-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def format_number(fy: str, serial: int, prefix: Optional[str] = None) -> str:
    return f"{(prefix or settings.PLATFORM_INVOICE_PREFIX).strip().upper()}/{fy}/{serial:04d}"


async def _last_serial(db: AsyncSession, fy: str) -> int:
    return (await db.execute(
        select(func.max(PlatformInvoice.serial)).where(PlatformInvoice.financial_year == fy)
    )).scalar() or 0


async def allocate_number(db: AsyncSession, invoice_date: date) -> tuple[str, str, int]:
    """(invoice_number, financial_year, serial) for a new invoice. Call inside the
    transaction that inserts it.

    The advisory lock is transaction-scoped: held until that insert commits or rolls
    back, so concurrent generators queue here instead of both reading the same max, and a
    rolled-back insert releases its number for the next one — the series stays gapless.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('platform_invoice_number'))"))
    fy = financial_year(invoice_date)
    serial = await _last_serial(db, fy) + 1
    return format_number(fy, serial), fy, serial


async def preview_number(db: AsyncSession, invoice_date: date) -> str:
    """What the next number will PROBABLY be — for the form, not a reservation."""
    fy = financial_year(invoice_date)
    return format_number(fy, await _last_serial(db, fy) + 1)


# ── parties ──────────────────────────────────────────────────────────────────

def _clean(value: Any, limit: int = 255) -> Optional[str]:
    text_value = " ".join(str(value).split()) if value is not None else ""
    return text_value[:limit] or None


def clean_party(raw: dict, role: str, *, bank: bool = False) -> dict:
    """A party as it will be stored: trimmed, GSTIN/PAN upper-cased, state canonical.
    Raises InvoiceError with the field and the reason."""
    party = {k: _clean(raw.get(k), 500 if k == "address" else 255) for k in _PARTY_FIELDS}
    if not party["name"]:
        raise InvoiceError(f"{role}: a name is required.")
    party["gstin"] = normalise(party["gstin"])
    party["pan"] = normalise(party["pan"])
    if party["state"]:
        state = canonical_state(party["state"])
        if state is None:
            raise InvoiceError(f"{role}: '{party['state']}' is not an Indian state — pick one from the list.")
        party["state"] = state
    problem = pan_error(party["pan"]) or gstin_error(party["gstin"], pan=party["pan"], state=party["state"])
    if problem:
        raise InvoiceError(f"{role}: {problem}")
    if bank:
        details = raw.get("bank") or {}
        party["bank"] = {k: _clean(details.get(k), 120) for k in _BANK_FIELDS}
        if party["bank"]["ifsc"]:
            party["bank"]["ifsc"] = party["bank"]["ifsc"].upper()
    return party


def state_label(code: Optional[str]) -> str:
    """'07' → '07 - Delhi', as place of supply is printed."""
    return f"{code} - {GST_STATE_CODES[code]}" if code in GST_STATE_CODES else ""


# ── lines and tax ────────────────────────────────────────────────────────────

@dataclass
class Totals:
    lines: list[dict] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    cgst: Decimal = Decimal("0.00")
    sgst: Decimal = Decimal("0.00")
    igst: Decimal = Decimal("0.00")
    treatment: str = TREATMENT_NONE
    place_of_supply_code: Optional[str] = None

    @property
    def total_tax(self) -> Decimal:
        return self.cgst + self.sgst + self.igst

    @property
    def grand_total(self) -> Decimal:
        return self.subtotal + self.total_tax


def _decimal(value: Any, what: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise InvoiceError(f"{what} must be a number.")


def clean_lines(lines: Iterable[dict]) -> list[dict]:
    """Stored lines. Quantities keep what was typed (1.5 months stays 1.5); money is to the
    paisa. A negative rate is allowed — that is how a discount line is written."""
    out = []
    for i, raw in enumerate(lines, start=1):
        description = _clean(raw.get("description"), 300)
        if not description:
            raise InvoiceError(f"Line {i}: a description is required.")
        qty = _decimal(raw.get("quantity", 1), f"Line {i} quantity")
        if qty <= 0:
            raise InvoiceError(f"Line {i}: quantity must be more than zero.")
        rate = q2(_decimal(raw.get("unit_price", 0), f"Line {i} rate"))
        out.append({
            "description": description,
            "sac": _clean(raw.get("sac"), 10),
            "quantity": format(qty.normalize(), "f"),
            "unit_price": str(rate),
            "amount": str(q2(qty * rate)),
        })
    if not out:
        raise InvoiceError("Add at least one line.")
    return out


def compute(lines: list[dict], gst_rate: Any, issuer: dict, bill_to: dict) -> Totals:
    """Tax for cleaned lines between cleaned parties. See the module docstring."""
    rate = _decimal(gst_rate, "GST rate")
    if rate < 0 or rate > 28:
        raise InvoiceError("GST rate must be between 0 and 28%.")
    totals = Totals(lines=lines, subtotal=sum((Decimal(l["amount"]) for l in lines), Decimal("0.00")))
    if totals.subtotal <= 0:
        raise InvoiceError("The invoice total must be more than zero.")
    totals.place_of_supply_code = place_of_supply_code(bill_to.get("gstin"), bill_to.get("state"))

    if not issuer.get("gstin") or rate == 0:
        return totals

    interstate = is_interstate(issuer.get("gstin"), issuer.get("state"),
                               bill_to.get("gstin"), bill_to.get("state"))
    if interstate is None:
        raise InvoiceError(
            "Can't tell whether to charge CGST + SGST or IGST — choose the customer's state "
            "(or enter their GSTIN)."
        )
    if interstate:
        totals.treatment = TREATMENT_INTER
        totals.igst = q2(totals.subtotal * rate / 100)
    else:
        totals.treatment = TREATMENT_INTRA
        totals.cgst = totals.sgst = q2(totals.subtotal * rate / 200)
    return totals


# ── the form's defaults ──────────────────────────────────────────────────────

def month_period(today: date) -> tuple[date, date]:
    return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])


def _month_label(d: Optional[date]) -> Optional[str]:
    return d.strftime("%B %Y") if d else None


def default_issuer() -> dict:
    return {
        **{k: None for k in _PARTY_FIELDS},
        "name": settings.APP_NAME,
        "email": settings.SMTP_REPLY_TO or None,
        "country": "India",
        "bank": {k: None for k in _BANK_FIELDS},
    }


def bill_to_from_tenant(tenant, owner) -> dict:
    return {
        "name": tenant.name or tenant.domain or (owner.full_name if owner else None),
        "address": tenant.address,
        "city": tenant.city,
        "state": canonical_state(tenant.state) or tenant.state,
        "pincode": tenant.pincode,
        "country": tenant.country or "India",
        "gstin": tenant.gst_number,
        "pan": tenant.pan_number,
        "email": owner.email if owner else None,
        "phone": tenant.phone,
    }


def carry_lines(previous: Optional[PlatformInvoice], period_from: date) -> list[dict]:
    """This workspace's last invoice's lines, with its month renamed to this one — so a
    monthly invoice is the same as last month's unless someone changes it. A first
    invoice gets one subscription line with no price."""
    if previous is None or not previous.line_items:
        return [{
            "description": f"{settings.APP_NAME} subscription — {_month_label(period_from)}",
            "sac": settings.PLATFORM_INVOICE_SAC,
            "quantity": "1",
            "unit_price": "0.00",
        }]
    old, new = _month_label(previous.period_from), _month_label(period_from)
    return [
        {
            "description": (line.get("description") or "").replace(old, new) if old else line.get("description"),
            "sac": line.get("sac"),
            "quantity": line.get("quantity", "1"),
            "unit_price": line.get("unit_price", "0.00"),
        }
        for line in previous.line_items
    ]


async def draft(db: AsyncSession, tenant, owner, today: Optional[date] = None) -> dict:
    """Everything the Generate form opens with."""
    today = today or date.today()
    period_from, period_to = month_period(today)

    # The issuer is the platform, the same on every invoice: whatever the last one said.
    last_any = (await db.execute(
        select(PlatformInvoice).order_by(PlatformInvoice.id.desc()).limit(1)
    )).scalar_one_or_none()
    # The lines are per workspace: whatever this one was billed last, cancelled aside.
    last_here = (await db.execute(
        select(PlatformInvoice)
        .where(PlatformInvoice.billed_tenant_id == tenant.id, PlatformInvoice.status != STATUS_CANCELLED)
        .order_by(PlatformInvoice.invoice_date.desc(), PlatformInvoice.id.desc()).limit(1)
    )).scalar_one_or_none()

    issuer = default_issuer()
    if last_any is not None:
        issuer.update({k: v for k, v in last_any.issuer.items() if k != "bank"})
        issuer["bank"] = {**issuer["bank"], **(last_any.issuer.get("bank") or {})}

    return {
        "tenant_id": tenant.id,
        "next_number": await preview_number(db, today),
        "invoice_date": today,
        "due_date": today + timedelta(days=settings.PLATFORM_INVOICE_DUE_DAYS),
        "period_from": period_from,
        "period_to": period_to,
        "gst_rate": float(last_here.gst_rate) if last_here else settings.PLATFORM_INVOICE_GST_RATE,
        "issuer": issuer,
        "bill_to": bill_to_from_tenant(tenant, owner),
        "lines": carry_lines(last_here, period_from),
        "notes": last_here.notes if last_here else None,
    }


# ── the console's column ─────────────────────────────────────────────────────

async def summaries(db: AsyncSession, tenant_ids: list[int], today: Optional[date] = None) -> dict[int, dict]:
    """{tenant_id: {count, unpaid_count, unpaid_total, overdue_count, last_number,
    last_status, last_date}} — two grouped queries, whatever the page size."""
    if not tenant_ids:
        return {}
    today = today or date.today()
    P = PlatformInvoice
    unpaid = P.status == STATUS_ISSUED
    rows = (await db.execute(
        select(
            P.billed_tenant_id,
            func.count().filter(P.status != STATUS_CANCELLED),
            func.count().filter(unpaid),
            func.coalesce(func.sum(P.grand_total).filter(unpaid), 0),
            func.count().filter(unpaid, P.due_date < today),
        )
        .where(P.billed_tenant_id.in_(tenant_ids))
        .group_by(P.billed_tenant_id)
    )).all()
    out = {
        tid: {"count": n, "unpaid_count": n_unpaid, "unpaid_total": float(unpaid_total),
              "overdue_count": n_overdue}
        for tid, n, n_unpaid, unpaid_total, n_overdue in rows
    }
    latest = (await db.execute(
        select(P.billed_tenant_id, P.invoice_number, P.status, P.invoice_date)
        .where(P.billed_tenant_id.in_(tenant_ids))
        .distinct(P.billed_tenant_id)
        .order_by(P.billed_tenant_id, P.invoice_date.desc(), P.id.desc())
    )).all()
    for tid, number, status, on in latest:
        out.setdefault(tid, {"count": 0, "unpaid_count": 0, "unpaid_total": 0.0, "overdue_count": 0})
        out[tid].update(last_number=number, last_status=status, last_date=on)
    return out
