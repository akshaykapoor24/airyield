"""Internal Statement: one check per upload — a ticket already loaded is a duplicate

The period-based re-upload check is retired; an upload of any period, at any time, now
leaves out the tickets already loaded — the same Booked Date, Ticket No, Pax Name, Amount and
Travel Date (services/ticket_duplicates.py). The declared date format (ticket_date_formats_01)
stays.

* internal_uploaded_tickets.dedup_key — rebuilt for every ticket from its columns with the new
  key (internal_reupload_01's key was the period check's), and indexed with the tenant for the
  lookup each upload makes. A line with neither a ticket number nor a passenger gets NULL: it
  is never a duplicate. uploaded_tickets.dedup_key (Customer data) is untouched — never set.

A downgrade drops the index; the keys stay as rebuilt — the period check's keys cannot be
recovered, and a ticket without its old key had it worked out from its columns.

Revision ID: internal_dupes_01
Revises: tp_gds_dupes_02
Create Date: 2026-10-22 00:00:00.000000
"""
import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'internal_dupes_01'
down_revision: Union[str, None] = 'tp_gds_dupes_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'internal_uploaded_tickets'
_INDEX = 'ix_internal_uploaded_tickets_dedup_key'


# ── the key, frozen as services/ticket_duplicates.py computes it today ───────────────────
def _text(value) -> str:
    return " ".join(str(value or "").upper().split())


def _amount(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except InvalidOperation:
        return _text(value)


def _day(value) -> str:
    return str(value or "")[:10]


def _serial(value) -> str:
    s = re.sub(r"[^0-9A-Z]", "", str(value or "").upper())
    return s[-10:] if s.isdigit() else s


def _kind(d) -> str:
    doc = re.sub(r"\s+", "", str(d.get("doc_no") or "")).upper()
    if doc.startswith("IR"):
        return "R"
    if doc.startswith("IS"):
        return "S"
    it = str(d.get("invoice_type") or "").lower()
    if "credit" in it or "refund" in it:
        return "R"
    try:
        total = Decimal(str(d.get("total_amt")).replace(",", "")) if d.get("total_amt") not in (None, "") else None
    except InvalidOperation:
        total = None
    return "R" if total is not None and total < 0 else "S"


def ticket_key(d):
    ticket = _serial(d.get("ticket_number"))
    pax = _text(d.get("pax_name") or " ".join(str(p) for p in (d.get("last_name"), d.get("first_name")) if p))
    if not ticket and not pax:
        return None
    parts = (_day(d.get("ticket_date") or d.get("doc_date")), ticket, pax, _amount(d.get("total_amt")),
             _day(d.get("departure_datetime")), _kind(d))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


_COLUMNS = ("id", "ticket_number", "pax_name", "last_name", "first_name", "ticket_date", "doc_date",
            "total_amt", "departure_datetime", "doc_no", "invoice_type")


def upgrade() -> None:
    conn = op.get_bind()
    update = sa.text(f"UPDATE {_T} SET dedup_key = :k WHERE id = :id")
    batch = []
    # Keyed before the index exists: one pass of updates, not one index write per row.
    for row in conn.execute(sa.text(f"SELECT {', '.join(_COLUMNS)} FROM {_T} ORDER BY id")).mappings():
        batch.append({"id": row["id"], "k": ticket_key(row)})
        if len(batch) >= 500:
            conn.execute(update, batch)
            batch = []
    if batch:
        conn.execute(update, batch)
    op.create_index(_INDEX, _T, ['tenant_id', 'dedup_key'])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_T)
