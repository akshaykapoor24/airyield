"""Spec-driven statements (NDC, Third Party API …) → "entries in system" workbook for one upload.

The uploads list already serves the ORIGINAL file back. This is the other half of the
check a user runs after an import — did every line land, and was it read right — built
from the stored rows, never from the stored file:

  * Entries — one row per stored entry, in file order, with exactly the columns the Open
    screen shows (services/statement_display.py is the one definition both read). Values
    are as stored — the file's own text — except amounts, which are written as numbers so
    the sheet can be added up. A type with a billing flow, once billing is set up, also gets
    its worklist's own per-row columns: Billing, plus NDC's Line or Third Party API's
    Category and Kind.
  * Summary — entries stored, what the type skips by design, the totals, and the billing
    counts exactly as the uploads screen shows them.

The LCC Detailed type has its own schema and its own export (services/lcc_export.py).

Pure: the endpoint (api/v1/statements.py) queries, computes each row's billing facts with
the type's own functions, and hands everything over — so this is unit-testable without a
database. Cell safety (formula injection from uploaded text, XML-illegal characters, 15-digit
ids) is ReportWorkbook's, not re-done here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from app.services.report_download.workbook import Block, ColSpec, ReportWorkbook
from app.services.statement_balance import to_decimal

ENTRIES_TITLE = "Entries"
SUMMARY_TITLE = "Summary"

# The billing worklists' own words (NdcBillingWorklist / TpApiBillingWorklist), so the
# sheet and the screen never describe one row two ways.
BILLING_LABEL = {
    "invoiced": "On an invoice", "sent": "In billing", "stale": "Re-send",
    "withdrawn": "Party removed", "ready": "Ready to send", "no_party": "Needs a party",
    "latched": "On its ticket", "unlatched": "Needs a ticket", "not_billable": "Not billable",
}
# NDC's Line column: which ticket an ancillary line's money is billed on.
LINE_LABEL = {
    "anchor": "Ticket", "latched": "Rolled up", "orphan": "No ticket",
    "ambiguous": "Several tickets", "unidentified": "Unidentified",
}
# Third Party API's Kind column: what the row is, or why it does not bill.
KIND_LABEL = {
    "sale": "Charge", "refund": "Credit",
    "no_category": "No billing category", "pending": "Payment pending",
    "cancelled": "Cancelled — nothing to bill", "needs_review": "Refund to review",
    "no_amount": "No amount", "not_flight": "Needs Re-match",
}


def file_name(source_file: str | None) -> str:
    """`<upload name> - entries in system.xlsx`, safe on every OS."""
    stem = re.sub(r"\.(xlsx|xls|csv|tsv|txt)$", "", (source_file or "").strip(), flags=re.I)
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", stem).strip(" .") or "upload"
    return f"{stem} - entries in system.xlsx"


@dataclass
class Entry:
    """One stored row, as the endpoint hands it over."""
    record: dict                  # statement_display.flatten_record(slug, row) — carries "id"
    billing: str | None = None    # billing_state(row, ticket), once billing is set up
    extras: dict[str, Any] = field(default_factory=dict)   # {header: label} beside Billing


@dataclass
class UploadFacts:
    """The upload-level facts the Summary reports. `stored_rows` is a live COUNT of the
    upload's entries, counted exactly as the uploads list counts them."""
    type_label: str
    source_file: str | None
    stored_rows: int
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    # Lines read from the file — only the types that capture control figures record it
    # (statement_spec `captures_controls`). None for NDC and API, which the Summary says
    # plainly rather than guessing.
    file_rows: int | None = None
    # What the type skips on content by design (statement_spec `row_filter`) — NDC's
    # unpaid holds and free seats — so a file with more lines than entries is explained.
    row_filter: dict | None = None
    # The uploads list's billing counters. None for a type with no billing flow; {} (or
    # resolution_status "none") for one whose billing has not been set up yet.
    billing: dict | None = None
    filters: list[tuple[str, str]] = field(default_factory=list)   # (label, value)
    exported_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    @property
    def billing_set_up(self) -> bool:
        return bool(self.billing) and self.billing.get("resolution_status") != "none"


def entry_columns(columns: Sequence[dict], *, extra_headers: Sequence[str] = (),
                  with_billing: bool = False) -> list[ColSpec]:
    cols = [ColSpec(c["header"], "money" if c.get("kind") == "money" else "text",
                    12 if c.get("kind") == "money" else 16) for c in columns]
    if with_billing:
        cols += [ColSpec(h, "text", 16) for h in extra_headers]
        cols.append(ColSpec("Billing", "text", 16))
    cols.append(ColSpec("System ID", "int", 11))
    return cols


def _cell(value: Any, money: bool) -> Any:
    # An amount that won't parse ("N/A", a header fragment) stays as the file's text rather
    # than becoming a silent 0 — the same reason the Open screen leaves it visible.
    if money and value not in (None, ""):
        d = to_decimal(value)
        return d if d is not None else value
    return value


def entry_values(entry: Entry, columns: Sequence[dict], *, extra_headers: Sequence[str] = (),
                 with_billing: bool = False) -> list[Any]:
    out = [_cell(entry.record.get(c["field"]), c.get("kind") == "money") for c in columns]
    if with_billing:
        out += [entry.extras.get(h) for h in extra_headers]
        out.append(BILLING_LABEL.get(entry.billing or "", entry.billing))
    out.append(entry.record.get("id"))
    return out


def row_check(facts: UploadFacts) -> str:
    """One sentence: are the file's lines in the system?"""
    stored, read = facts.stored_rows, facts.file_rows
    if read is not None:
        if read == stored:
            return f"All {read:,} lines read from the file are stored in the system."
        if read > stored:
            return (f"{read - stored:,} of the {read:,} lines read from the file are not entries: "
                    "the statement's own opening, balance and total lines, and lines with nothing "
                    "in a mapped column, are kept out.")
    msg = (f"{stored:,} entries are stored in the system for this upload — the same count the "
           "uploads list shows.")
    rf = facts.row_filter
    if rf:
        msg += (f" {rf.get('note', '').strip()} Skipped {rf.get('header', 'type')} values: "
                f"{', '.join(rf.get('exclude') or [])}.")
    return msg


def _totals(entries: Sequence[Entry], summary_fields: Sequence[dict]) -> list[list[Any]]:
    out = []
    for f in summary_fields:
        total = sum((d for e in entries if (d := to_decimal(e.record.get(f["field"]))) is not None),
                    Decimal("0"))
        out.append([f["label"], total])
    return out


def _count_block(title: str, header: str, values: Sequence[Any], order: Sequence[str] = ()) -> Block:
    """How many exported entries carry each value of one column — first-seen order, except
    that a declared vocabulary (the billing states) sorts in its own order."""
    counts: dict[str, int] = {}
    for v in values:
        key = str(v) if v not in (None, "") else "—"
        counts[key] = counts.get(key, 0) + 1
    rows = [[k, n] for k, n in counts.items()]
    if order:
        rank = {label: i for i, label in enumerate(order)}
        rows.sort(key=lambda kv: rank.get(kv[0], len(rank)))
    return Block(title, [header, "Lines"], rows, ["text", "int"])


def summary_blocks(entries: Sequence[Entry], facts: UploadFacts, summary_fields: Sequence[dict],
                   *, extra_headers: Sequence[str] = (), with_billing: bool = False) -> list[Block]:
    filtered = bool(facts.filters)
    check: list[list[Any]] = []
    if facts.file_rows is not None:
        check.append(["Lines read from the file", facts.file_rows])
    check += [
        ["Entries stored in the system", facts.stored_rows],
        ["Entries in this export" + (" (filtered)" if filtered else ""), len(entries)],
        ["Result", row_check(facts)],
    ]
    blocks = [
        Block("Upload", None, [
            ["Statement", facts.type_label],
            ["File", facts.source_file or "—"],
            ["Uploaded by", facts.uploaded_by or "—"],
            ["Uploaded (UTC)", facts.uploaded_at],
            ["Exported (UTC)", facts.exported_at],
        ]),
        Block("Row check", ["Check", "Count"], check, ["text", "int"]),
    ]
    if filtered:
        blocks.append(Block("Filters applied to this export", ["Filter", "Value"],
                            [[label, value] for label, value in facts.filters]))
    if summary_fields:
        blocks.append(Block("Totals of the entries in this export", ["Field", "Amount"],
                            _totals(entries, summary_fields), ["text", "money"]))

    if facts.billing is not None:
        title = "Billing — whole upload, as on the uploads screen"
        if not facts.billing_set_up:
            # Every row would otherwise read "Needs a party": billing_state falls back to it
            # for a row nobody has matched, which here only means nobody has looked yet.
            blocks.append(Block(title, None, [[
                "Billing has not been set up for this upload yet — use Set up billing on the "
                "uploads list. The Billing columns appear in this download once it is."]]))
        else:
            b = facts.billing
            rows: list[list[Any]] = [
                ["Billable lines", b.get("billable_rows", 0)],
                ["With a customer set", b.get("resolved_rows", 0)],
                ["Tickets sent to billing", b.get("projected_tickets", 0)],
            ]
            if b.get("unlatched_rows"):
                rows.append(["Ancillary lines with no ticket to attach to", b["unlatched_rows"]])
            blocks.append(Block(title, ["", "Lines"], rows, ["text", "int"]))
    if with_billing:
        blocks.append(_count_block("Entries in this export by billing state", "Billing",
                                   [BILLING_LABEL.get(e.billing or "", e.billing) for e in entries],
                                   order=list(BILLING_LABEL.values())))
        for h in extra_headers:
            blocks.append(_count_block(f"Entries in this export by {h.lower()}", h,
                                       [e.extras.get(h) for e in entries]))

    about = [
        ["Each row on the Entries sheet is one entry stored in the system for this upload, in "
         "file order, with the same columns as the Open screen."],
        ["Values are as stored — the file's own text — except amounts, which are written as "
         "numbers so they can be added up."],
    ]
    if with_billing:
        names = " and ".join([", ".join(extra_headers), "Billing"]) if extra_headers else "Billing"
        about.append([f"{names} {'show' if extra_headers else 'shows'} where each line stands on its way into billing, in the "
                      "Billing screen's own words."])
    about.append(["System ID is the entry's id in the system — it is not read from the file."])
    blocks.append(Block("About this file", None, about))
    return blocks


def write_workbook(path: str, columns: Sequence[dict], entries: Sequence[Entry], facts: UploadFacts,
                   summary_fields: Sequence[dict] = (), *, extra_headers: Sequence[str] = (),
                   with_billing: bool = False) -> None:
    """Write the Entries + Summary workbook to `path`. Synchronous and CPU-bound — the
    endpoint runs it in a thread so a large upload doesn't stall the event loop."""
    flags = {"extra_headers": tuple(extra_headers), "with_billing": with_billing}
    wb = ReportWorkbook(path)
    try:
        wb.ensure_sheet("entries", ENTRIES_TITLE, entry_columns(columns, **flags), rank=1)
        for e in entries:
            wb.append("entries", entry_values(e, columns, **flags))
        wb.write_blocks("summary", SUMMARY_TITLE, rank=2,
                        blocks=summary_blocks(entries, facts, summary_fields, **flags))
        wb.save()
    finally:
        wb.discard()
