"""LCC Detailed → "entries in system" workbook: what the database holds for one upload.

The uploads list already serves the ORIGINAL file back. This is the other half of the
check a user runs after an import — did every line land, and was it read right — so it is
built from the `lcc_detailed` rows themselves, never from the stored file:

  * Entries — one row per stored record, in import order (which is file order), under
    the upload template's own headers (services/lcc_detailed_spec.py), so it lines up
    against the file it came from. The folded JSONB is unfolded back into the template's
    shape: one column per tax code and three per leg, for only the codes and legs this
    upload actually carries — 87 empty tax columns would bury the ones that matter.
  * Summary — lines read against entries stored, the money totals, and the billing
    counts exactly as the uploads screen shows them.

Pure: the endpoint (api/v1/lcc_detailed.py) queries and hands over rows and facts, so this
is unit-testable without a database. Cell safety (formula injection from uploaded text,
XML-illegal characters, 15-digit ids) is ReportWorkbook's, not re-done here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from app.services import customer_resolver as cres
from app.services import lcc_billing_projection as proj
from app.services import lcc_detailed_spec as spec
from app.services.report_download.workbook import Block, ColSpec, ReportWorkbook
# Shared with the spec-driven statements' export, so both name their file the same way.
from app.services.statement_export import file_name  # noqa: F401  (re-exported for the router)

ENTRIES_TITLE = "Entries"
SUMMARY_TITLE = "Summary"

# Datetimes deliberately take the PLAIN format ("text" kind → openpyxl's own
# yyyy-mm-dd h:mm:ss) rather than ReportWorkbook's "datetime" one, which drops the
# seconds. Matching a transaction against the file is exactly when seconds matter.
_KIND_BY_DTYPE = {"numeric": "money", "int": "int", "datetime": "text", "bool": "text", "str": "text"}
_WIDTH_BY_DTYPE = {"numeric": 12, "int": 9, "datetime": 19, "bool": 8, "str": 16}

_CORE = spec.CORE_COLUMNS
_TAX_ORDER = {c["header"]: i for i, c in enumerate(
    c for c in spec.LCC_STANDARD_COLUMNS if c["role"] == "tax")}
_LEG_SLOTS = ("route", "flight_no", "dep_date")
_LEG_HEADERS = {(c["leg_no"], c["slot"]): c["header"]
                for c in spec.LCC_STANDARD_COLUMNS if c["role"] == "leg"}
_LEG_SLOT_LABEL = {"route": "", "flight_no": " Flight No", "dep_date": " Dep Date"}

# Added by the system, never read from the file — listed on the Summary so nobody goes
# looking for them in their upload.
SYSTEM_COLUMNS = ("Airline", "Departure Date", "Row Type", "Movement", "SSR", "Billing", "System ID")

# The Billing column, in the uploads screen's own terms. Only AG payment lines are billed
# (see lcc_billing_projection.is_ag), which is why "billable" there can be well below the
# entry count — this column is what makes that gap legible row by row.
BILLING_NOT_AG = "Not billed (not an AG line)"
BILLING_PAYMENT = "Not billable (payment movement)"
BILLING_SENT = "Sent to billing"
BILLING_READY = "Customer set, not sent"
BILLING_NO_PARTY = "No customer yet"


@dataclass
class UploadFacts:
    """The batch-level facts the Summary sheet reports. `stored_rows` is a live COUNT of
    the upload's rows, never the batch's counter — the point is to check, not to repeat."""
    source_file: str | None
    stored_rows: int
    source_rows: int | None = None
    expected_rows: int | None = None
    # batch.merge_stats — set when the import's merge pass ran (an account statement and/or
    # a passenger report, e.g. Air India Express). Lines read ≠ entries stored is expected
    # there, and these counters are what account for every line the entries don't.
    merge_stats: dict | None = None
    files: list[tuple[str, str | None, int | None]] = field(default_factory=list)  # (role, name, lines)
    airline: str | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    completed_at: datetime | None = None
    billable_rows: int = 0
    resolved_rows: int = 0
    projected_rows: int = 0
    filters: list[tuple[str, str]] = field(default_factory=list)   # (label, value)
    exported_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @property
    def merged(self) -> bool:
        return self.merge_stats is not None


def billing_label(row) -> str:
    if not proj.is_ag(row):
        return BILLING_NOT_AG
    if row.projected_ticket_id is not None:
        return BILLING_SENT
    if row.bill_status == cres.EXCLUDED:
        return BILLING_PAYMENT
    if row.bill_status in proj.BILLABLE_STATUSES:
        return BILLING_READY
    return BILLING_NO_PARTY


def _source_word(facts: UploadFacts) -> str:
    return "files" if len(facts.files) > 1 else "file"


def line_breakdown(stats: dict) -> list[list[Any]]:
    """Where every line of a merged upload went, from the merge's own counters.

    Without this a merged upload reads "60 lines read, 32 stored" and leaves the user to
    wonder about 28 lines. Every line is accounted for: an account line is either an AG
    transaction (stored) or a balance line (skipped by design); a passenger line is either
    its own entry (passenger file alone), folded into another line's legs, an exact
    duplicate, or — beside an account file — the source of an entry's passenger details.
    """
    def n(key: str) -> int:
        return int(stats.get(key) or 0)

    out: list[list[Any]] = []
    if n("account_source_rows"):
        out.append(["Account statement — lines read", n("account_source_rows")])
        out.append(["   stored as entries (AG transactions)", n("account_rows")])
        if n("skipped_not_ag"):
            out.append(["   skipped — not AG payment lines (balance lines)", n("skipped_not_ag")])
    if n("pax_source_rows"):
        out.append(["Passenger report — lines read", n("pax_source_rows")])
        if n("pax_rows"):
            out.append(["   stored as entries (one per passenger per PNR)", n("pax_rows")])
            folded = n("pax_source_rows") - n("pax_rows") - n("duplicate_pax_lines")
            if folded > 0:
                out.append(["   folded into a passenger's legs (one line per segment)", folded])
        else:
            out.append(["   not stored as entries — used to fill in passenger, fare and legs "
                        "on this many entries", n("enriched_account_rows")])
        if n("duplicate_pax_lines"):
            out.append(["   dropped — exact duplicate lines", n("duplicate_pax_lines")])
    return out


def row_check(facts: UploadFacts) -> str:
    """One sentence: did every line read from the file end up stored?

    Equality is checked BEFORE the merge: a merged upload whose counts happen to agree
    should read as plainly complete, not carry a "counts are not expected to match" caveat.
    """
    stored, read = facts.stored_rows, facts.source_rows
    if read is None:
        return "This upload predates the line count, so only the stored entries can be shown."
    missing = read - stored
    if missing == 0:
        return f"All {read:,} lines read from the {_source_word(facts)} are stored in the system."
    if facts.merge_stats is not None:
        made = int(facts.merge_stats.get("account_rows") or 0) + int(facts.merge_stats.get("pax_rows") or 0)
        if stored == made:
            return (f"All {made:,} entries the import made from the {read:,} lines read are "
                    "stored in the system. “Where the lines went” below accounts for the rest.")
        if stored < made:
            return (f"{made - stored:,} of the {made:,} entries the import made from the "
                    f"{_source_word(facts)} are not stored — the database rejected them.")
        return (f"{stored - made:,} more entries are stored than the import made — rows were "
                "added to this upload after it was imported.")
    if missing > 0:
        return (f"{missing:,} of the {read:,} lines read from the file are not stored. A line "
                "with no value in any mapped column (such as a totals line) is skipped, as is "
                "a line the database rejected.")
    return (f"{-missing:,} more entries are stored than lines were read — rows were added to "
            "this upload after it was imported.")


def _tax_amounts(row) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in row.taxes or []:
        code = t.get("code")
        if code and t.get("amount") is not None:
            out[code] = out.get(code, 0.0) + float(t["amount"])
    return out


def _legs(row) -> dict[int, dict]:
    return {int(s.get("leg") or i): s for i, s in enumerate(row.segments or [], start=1)}


def _leg_header(n: int, slot: str) -> str:
    return _LEG_HEADERS.get((n, slot)) or f"Leg {n}{_LEG_SLOT_LABEL[slot]}"


def _ssr_text(row) -> str | None:
    return " · ".join(
        f"{s.get('code')} {s.get('amount') or ''}".strip()
        for s in (row.ssr or []) if s.get("code")
    ) or None


def _layout(rows: Sequence) -> tuple[list[str], int]:
    """(tax codes in template order, legs to show) across every exported row."""
    codes = {t.get("code") for r in rows for t in (r.taxes or []) if t.get("code")}
    taxes = sorted(codes, key=lambda c: (_TAX_ORDER.get(c, len(_TAX_ORDER)), c))
    legs = max((n for r in rows for n in _legs(r)), default=0)
    return taxes, legs


def entry_columns(taxes: Sequence[str], legs: int) -> list[ColSpec]:
    # Template order — core, then taxes, then legs — so the sheet reads like the file
    # did; the system's own columns follow, never interleaved with the file's.
    cols = [ColSpec(c["header"], _KIND_BY_DTYPE[c["dtype"]], _WIDTH_BY_DTYPE[c["dtype"]]) for c in _CORE]
    cols += [ColSpec(code, "money", 10) for code in taxes]
    for n in range(1, legs + 1):
        cols += [ColSpec(_leg_header(n, "route"), "text", 11),
                 ColSpec(_leg_header(n, "flight_no"), "text", 11),
                 ColSpec(_leg_header(n, "dep_date"), "text", 14)]
    cols += [
        ColSpec("Airline", "text", 20),
        ColSpec("Departure Date", "date", 13),
        ColSpec("Row Type", "text", 10),
        ColSpec("Movement", "text", 14),
        ColSpec("SSR", "text", 16),
        ColSpec("Billing", "text", 26),
        ColSpec("System ID", "int", 11),
    ]
    return cols


def entry_values(row, taxes: Sequence[str], legs: int) -> list[Any]:
    out: list[Any] = [getattr(row, c["field"]) for c in _CORE]
    amounts = _tax_amounts(row)
    out += [amounts.get(code) for code in taxes]
    by_leg = _legs(row)
    for n in range(1, legs + 1):
        leg = by_leg.get(n) or {}
        out += [leg.get(slot) for slot in _LEG_SLOTS]
    out += [
        " ".join(x for x in (row.airline_code, row.airline_name) if x) or None,
        row.departure_date,
        row.row_kind,
        row.movement_kind,
        _ssr_text(row),
        billing_label(row),
        row.id,
    ]
    return out


def _totals(rows: Sequence) -> list[list[Any]]:
    def total(attr: str) -> Decimal:
        return sum((Decimal(str(v)) for r in rows if (v := getattr(r, attr)) is not None), Decimal("0"))
    out: list[list[Any]] = [[f["label"], total(f["field"])] for f in spec.SUMMARY_FIELDS]
    out.append(["Pax", sum(r.pax_count or 0 for r in rows)])
    return out


def summary_blocks(rows: Sequence, facts: UploadFacts) -> list[Block]:
    filtered = bool(facts.filters)
    upload: list[list[Any]] = [["File", facts.source_file or "—"]]
    if len(facts.files) > 1:
        for role, name, lines in facts.files:
            upload.append([f"{role.capitalize()} file",
                           f"{name or '—'}" + (f" ({lines:,} lines)" if lines is not None else "")])
    upload += [
        ["Airline", facts.airline or "Not set"],
        ["Uploaded by", facts.uploaded_by or "—"],
        ["Uploaded (UTC)", facts.uploaded_at],
        ["Import finished (UTC)", facts.completed_at],
        ["Exported (UTC)", facts.exported_at],
    ]

    check: list[list[Any]] = [
        ["Lines read from the " + _source_word(facts),
         facts.source_rows if facts.source_rows is not None else "—"],
        ["Entries stored in the system", facts.stored_rows],
    ]
    if facts.expected_rows is not None:
        check.append(["Expected records (entered at upload)", facts.expected_rows])
    check.append(["Entries in this export" + (" (filtered)" if filtered else ""), len(rows)])
    check.append(["Result", row_check(facts)])

    blocks = [
        Block("Upload", None, upload),
        Block("Row check", ["Check", "Count"], check, ["text", "int"]),
    ]
    breakdown = line_breakdown(facts.merge_stats) if facts.merge_stats else []
    if breakdown:
        blocks.append(Block("Where the lines went", ["", "Lines"], breakdown, ["text", "int"]))
    if filtered:
        blocks.append(Block("Filters applied to this export", ["Filter", "Value"],
                            [[label, value] for label, value in facts.filters]))
    blocks += [
        Block("Totals of the entries in this export", ["Field", "Amount"], _totals(rows),
              ["text", "money"]),
        Block("Billing — whole upload, as on the uploads screen", ["", "Lines"], [
            ["Billable lines (AG payment lines only)", facts.billable_rows],
            ["With a customer set", facts.resolved_rows],
            ["Sent to billing", facts.projected_rows],
        ], ["text", "int"]),
        Block("About this file", None, [
            ["Each row on the Entries sheet is one record stored in the system for this upload, "
             "in the order it was imported."],
            ["Columns use the upload template's own headers. Tax and leg columns appear only "
             "for the codes and legs this upload carries."],
            [f"{', '.join(SYSTEM_COLUMNS)} are added by the system — they are not read from "
             "the file."],
            ["Only AG payment lines are billed, so the billable count can be lower than the "
             "number of entries. The Billing column shows where each line stands."],
        ]),
    ]
    return blocks


def write_workbook(path: str, rows: Sequence, facts: UploadFacts) -> None:
    """Write the Entries + Summary workbook to `path`. Synchronous and CPU-bound — the
    endpoint runs it in a thread so a large upload doesn't stall the event loop."""
    taxes, legs = _layout(rows)
    wb = ReportWorkbook(path)
    try:
        wb.ensure_sheet("entries", ENTRIES_TITLE, entry_columns(taxes, legs), rank=1)
        for r in rows:
            wb.append("entries", entry_values(r, taxes, legs))
        wb.write_blocks("summary", SUMMARY_TITLE, rank=2, blocks=summary_blocks(rows, facts))
        wb.save()
    finally:
        wb.discard()
