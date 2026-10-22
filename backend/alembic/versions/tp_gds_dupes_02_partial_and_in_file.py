"""Third Party GDS: every upload screened against the agency's saved lines — exact, partial
and in-file duplicates

* third_party_gds.match_key — which entry a line is (its ticket and event; the passenger too
  when the document is a PNR), so a line re-sent with its amount, date or passenger changed
  is recognised as the same entry (services/tp_gds_reupload.py). Backfilled from the columns.
* third_party_gds.dedup_key now counts the Booked Date as well. Each stored key is EXTENDED
  with its line's Booked Date — not rebuilt from the columns — so it stays the key of the
  line as the vendor sent it, however it was corrected since. A line with no key gets one
  from its columns.
* third_party_gds.duplicate_kind / duplicate_of_id / duplicate_fields — a line saved although
  it repeats one: "exact" (saved again by choice), "partial" or "in_file", the saved line it
  repeats (ON DELETE SET NULL) and what differs. NULL on every line saved before this.
* The two keys indexed with the tenant and uploader, for the lookup each upload makes —
  under ix_third_party_gds_dedup_key, the name and columns tp_gds_period_01's downgrade uses.

A downgrade rebuilds each dedup_key from its line's columns without the Booked Date (the
as-sent reading of a corrected line cannot be recovered) and drops the rest.

Revision ID: tp_gds_dupes_02
Revises: ticket_date_formats_01
Create Date: 2026-10-21 00:00:00.000000
"""
import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'tp_gds_dupes_02'
down_revision: Union[str, None] = 'ticket_date_formats_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T = 'third_party_gds'
_KIND_CHECK = "duplicate_kind IS NULL OR duplicate_kind IN ('exact', 'partial', 'in_file')"


# ── the line keys, frozen as services/tp_gds_reupload.py computes them today ─────────────
def _text(value) -> str:
    return " ".join(str(value or "").upper().split())


def _document(d: dict):
    digits = re.sub(r"\D", "", str(d.get("ticket_number") or ""))
    if digits:
        return "T" + (digits[-10:] if len(digits) > 10 else digits)
    for key in ("pnr", "airline_pnr", "gds_pnr"):
        pnr = re.sub(r"[^A-Z0-9]", "", str(d.get(key) or "").upper())
        if pnr:
            return "P" + pnr
    return None


def _event(d: dict) -> str:
    return f"{_text(d.get('ticket_status'))}/{_text(d.get('transaction_type'))}"


def _passenger(d: dict) -> str:
    return _text(d.get("passenger_name") or " ".join(
        p for p in (d.get("first_name"), d.get("last_name")) if p))


def _amount(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except InvalidOperation:
        return _text(value)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


_NOT_IDENTITY = frozenset({"week", "invoice_number", "username", "__edited__", "unparsed_fields",
                           "airline_id", "airline_master_name", "airline_conflict"})


def base_key(d: dict):
    """tp_gds_dedup_01's exact key — everything but the Booked Date."""
    if d.get("row_kind"):
        return None
    doc = _document(d)
    if doc is None:
        body = "|".join(f"{k}={_text(v)}" for k, v in sorted(d.items())
                        if k not in _NOT_IDENTITY and v not in (None, ""))
        return _hash("X|" + body)
    return _hash("|".join((doc, _event(d), _passenger(d), str(d.get("issue_date") or ""),
                           _amount(d.get("base_fare")), _amount(d.get("net_amount")))))


def extend_key(base, booking_date):
    if base is None:
        return None
    return _hash(f"{base}|B{str(booking_date or '')[:10]}")


def match_key(d: dict):
    if d.get("row_kind"):
        return None
    doc = _document(d)
    if doc is None:
        return None
    parts = [doc, _event(d)]
    if doc.startswith("P"):
        parts.append(_passenger(d))
    return _hash("M|" + "|".join(parts))


# A line's `data` as models/typed_statement.TypedData rebuilds it — the shape the keys are
# computed from at upload: every field column, renamed where its key differs, as a string.
_NOT_DATA = frozenset({"id", "tenant_id", "created_by_id", "batch_id", "source_file", "file_url",
                       "uploaded_at", "source_format", "dedup_key", "period_from", "period_to",
                       "match_key", "duplicate_kind", "duplicate_of_id", "duplicate_fields"})
_RENAMED = {"total_tax": "taxes", "edited_fields": "__edited__"}


def _as_data(row) -> dict:
    out = {}
    for column, value in row.items():
        if column in _NOT_DATA or value is None:
            continue
        if isinstance(value, Decimal):
            value = format(value, "f")
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        out[_RENAMED.get(column, column)] = str(value)
    return out


def _rekey(conn, keys_for) -> None:
    """Set every line's keys to `keys_for(row, data)` → (dedup_key, match_key | None)."""
    update = sa.text(f"UPDATE {_T} SET dedup_key = :k, match_key = :m WHERE id = :id")
    batch = []
    for row in conn.execute(sa.text(f"SELECT * FROM {_T} ORDER BY id")).mappings():
        k, m = keys_for(row, _as_data(row))
        batch.append({"id": row["id"], "k": k, "m": m})
        if len(batch) >= 500:
            conn.execute(update, batch)
            batch = []
    if batch:
        conn.execute(update, batch)


def upgrade() -> None:
    op.add_column(_T, sa.Column('match_key', sa.String(64), nullable=True))
    op.add_column(_T, sa.Column('duplicate_kind', sa.String(20), nullable=True))
    op.add_column(_T, sa.Column('duplicate_of_id', sa.Integer(), nullable=True))
    op.add_column(_T, sa.Column('duplicate_fields', sa.Text(), nullable=True))
    op.create_foreign_key('fk_third_party_gds_duplicate_of', _T, _T,
                          ['duplicate_of_id'], ['id'], ondelete='SET NULL')
    op.create_check_constraint('ck_third_party_gds_duplicate_kind', _T, _KIND_CHECK)

    def keys(row, data):
        if data.get("row_kind"):
            return None, None
        base = row["dedup_key"] or base_key(data)     # as sent; from the columns when never keyed
        return extend_key(base, data.get("booking_date")), match_key(data)

    # Keyed before the indexes exist: one pass of updates, not one index write per row twice.
    _rekey(op.get_bind(), keys)

    op.create_index('ix_third_party_gds_dedup_key', _T, ['tenant_id', 'created_by_id', 'dedup_key'])
    op.create_index('ix_third_party_gds_match_key', _T, ['tenant_id', 'created_by_id', 'match_key'])
    op.create_index('ix_third_party_gds_duplicate_of_id', _T, ['duplicate_of_id'])


def downgrade() -> None:
    op.drop_index('ix_third_party_gds_duplicate_of_id', table_name=_T)
    op.drop_index('ix_third_party_gds_match_key', table_name=_T)
    op.drop_index('ix_third_party_gds_dedup_key', table_name=_T)
    _rekey(op.get_bind(), lambda row, data: (base_key(data), None))
    op.drop_constraint('ck_third_party_gds_duplicate_kind', _T, type_='check')
    op.drop_constraint('fk_third_party_gds_duplicate_of', _T, type_='foreignkey')
    op.drop_column(_T, 'duplicate_fields')
    op.drop_column(_T, 'duplicate_of_id')
    op.drop_column(_T, 'duplicate_kind')
    op.drop_column(_T, 'match_key')
