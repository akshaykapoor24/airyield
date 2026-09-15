"""The Read Me sheet: what a report contains, how it was built and how to read it.

WHY IT MATTERS. A report is a file that outlives the screen that produced it: it is mailed
to an auditor or reopened months later, when nobody remembers which uploads were ticked,
which date basis was used or why a TGQ ticket shows "No – in another BSP upload". Read Me
carries all of that inside the workbook — the build parameters, every file that was and was
not included (with the reason), the column legend with sign rules, the Counts-In-Net rules
and the flag legend — so the numbers can be defended from the file alone.

Everything is rendered from the shared vocabularies in ``columns`` and ``registry``, so the
legend cannot drift from what the mappers write. Pure: no DB; values are plain strings, ints
and dates (the workbook converts them).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from app.services.report_download import columns as C
from app.services.report_download.registry import SOURCE_BY_KEY, SOURCES
from app.services.report_download.summary import fmt_datetime, period_text
from app.services.report_download.types import REPORT_ENGINE_VERSION, ReportMeta
from app.services.report_download.workbook import Block

IST_OFFSET = timedelta(hours=5, minutes=30)

T_REPORT = "Report"
T_FILES_INCLUDED = "Files included"
T_FILES_EXCLUDED = "Files not included"
T_SHEETS = "Sheets"
T_LEGEND = "Combined column legend"
T_TXN_TYPES = "Transaction types"
T_COUNTS_IN_NET = "Counts In Net"
T_FLAGS = "Data flags"
T_CAVEATS = "Caveats"
BLOCK_TITLES: tuple[str, ...] = (
    T_REPORT, T_FILES_INCLUDED, T_FILES_EXCLUDED, T_SHEETS, T_LEGEND, T_TXN_TYPES,
    T_COUNTS_IN_NET, T_FLAGS, T_CAVEATS,
)

FILES_INCLUDED_HEADERS = (
    "Category", "Source Type", "File", "Upload ID", "Uploaded At", "Reference", "Rows in file",
    "Rows included", "Rows w/o readable date", "Superseded rows", "Notes",
)
_FILES_INCLUDED_KINDS = ("text", "text", "text", "text", "datetime", "text", "int", "int", "int", "int", "text")

KIND_LABELS = {
    "text": "Text", "int": "Number", "date": "Date", "datetime": "Date & time",
    "money": "Money", "flag": "Flag",
}
SIGN_LABELS = {"S": "signed", "U": "unsigned", "": None}

BASIS_LABELS = {"transaction": "Issue / transaction date", "upload": "Upload date"}
BSP_SCOPE_LABELS = {
    "whole_statement": "Whole statements overlapping the period",
    "issue_date": "Rows issued in the period",
}
UNDATED_LABELS = {
    "include": "Included, flagged DATE_UNREADABLE",
    "exclude": "Left out of the report",
}
# Builders may pass a short code or the finished text; unknown values are shown as given.
EXCLUDED_REASONS = {
    "unticked": "Unticked by you",
    "not_completed": "Not completed at build time",
    "no_rows": "No rows in period",
    "no_rows_in_period": "No rows in period",
}

CAVEATS: tuple[str, ...] = (
    "BSP values are the printed statement values (signs as printed).",
    "NDC, TGQ HMPR, ADM/ACM/RA and Third Party amounts are signed from the transaction type.",
    "BSP and Third Party API amounts carry no currency; INR is assumed.",
    "LCC Flown Report, CTA/BTA and Third Party LCC layouts were built without real samples — check the mapping.",
    "Alphanumeric BSPlink memo numbers cannot be matched to BSP rows.",
    "Third party status reflects the booking's state when the file was uploaded.",
    "TGQ enrichment uses every TGQ HMPR upload except the ones you unticked.",
    "A BSP statement completed in the last 10 minutes may not yet have its SPDR cancellation charges distributed onto CANX rows.",
)

_NONE_ROW = "None"


def _get(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _yes_no(v: Any) -> str:
    return "Yes" if v else "No"


def _count(v: Any) -> str:
    try:
        return f"{int(v or 0):,}"
    except (TypeError, ValueError):
        return str(v)


def _source_label(v: Any) -> Optional[str]:
    if v is None:
        return None
    src = SOURCE_BY_KEY.get(str(v))
    return src.label if src is not None else str(v)


def _category(item: Mapping[str, Any]) -> Optional[str]:
    cat = item.get("category")
    if cat:
        return cat
    src = SOURCE_BY_KEY.get(str(item.get("source_type")))
    return src.category if src is not None else None


def _notes(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v or None
    text = "; ".join(str(n) for n in v if n)
    return text or None


def _generated_at(meta: ReportMeta) -> tuple[str, str]:
    utc = meta.generated_at
    if utc.tzinfo is not None:
        utc = utc.astimezone(timezone.utc).replace(tzinfo=None)
    return fmt_datetime(utc), fmt_datetime(utc + IST_OFFSET)


def _generated_by(meta: ReportMeta) -> Optional[str]:
    name, email = meta.generated_by_name, meta.generated_by_email
    if name and email:
        return f"{name} <{email}>"
    return name or email or None


def _report_block(meta: ReportMeta, tgq_stats: Any) -> Block:
    opts = meta.options
    utc_text, ist_text = _generated_at(meta)
    period = period_text(meta.period.date_from, meta.period.date_to) if meta.period else None
    source_keys = meta.source_types or ()
    ordered = [s.label for s in SOURCES if s.key in source_keys]
    ordered += [str(k) for k in source_keys if k not in SOURCE_BY_KEY]
    rows: list[list[Any]] = [
        ["Report name", meta.title or "Untitled report"],
        ["Report ID", str(meta.export_id) if meta.export_id is not None else None],
        ["Generated at (UTC)", utc_text],
        ["Generated at (IST, UTC+5:30)", ist_text],
        ["Generated by", _generated_by(meta)],
        ["Workspace", meta.tenant_name],
        ["Engine version", REPORT_ENGINE_VERSION],
        ["Period", period or "All dates"],
        ["Date basis", BASIS_LABELS.get(opts.basis, opts.basis)],
        ["BSP scope", BSP_SCOPE_LABELS.get(opts.bsp_scope, opts.bsp_scope)],
        ["Source types", ", ".join(ordered) or None],
        ["Detail sheets", _yes_no(opts.include_detail_sheets)],
        ["Passenger contact details", _yes_no(opts.include_pii)],
        ["Rows without a readable date", UNDATED_LABELS.get(opts.undated_rows, opts.undated_rows)],
    ]
    if tgq_stats is not None:
        rows.append([
            "TGQ enrichment index",
            f"Rows loaded: {_count(_get(tgq_stats, 'rows_loaded'))}; "
            f"batches used: {_count(_get(tgq_stats, 'batches_used'))}; "
            f"truncated: {_yes_no(_get(tgq_stats, 'truncated'))}",
        ])
    return Block(T_REPORT, ("Item", "Value"), rows, ("text", "text"))


def _files_included_block(files: Sequence[Mapping[str, Any]]) -> Block:
    rows = [
        [
            _category(f), _source_label(f.get("source_type")), f.get("file_name"), f.get("upload_id"),
            f.get("uploaded_at"), f.get("reference"), f.get("rows_in_file"), f.get("rows_included"),
            f.get("rows_undated"), f.get("rows_superseded"), _notes(f.get("notes")),
        ]
        for f in files
    ]
    if not rows:
        rows = [[_NONE_ROW] + [None] * (len(FILES_INCLUDED_HEADERS) - 1)]
    return Block(T_FILES_INCLUDED, FILES_INCLUDED_HEADERS, rows, _FILES_INCLUDED_KINDS)


def _files_excluded_block(files: Sequence[Mapping[str, Any]]) -> Block:
    rows = []
    for f in files:
        reason = f.get("reason")
        rows.append([
            f.get("file_name"), _source_label(f.get("source_type")), f.get("upload_id"),
            EXCLUDED_REASONS.get(reason, reason) if isinstance(reason, str) else reason,
        ])
    if not rows:
        rows = [[_NONE_ROW, None, None, None]]
    return Block(T_FILES_EXCLUDED, ("File", "Source Type", "Upload ID", "Reason"), rows, ("text",) * 4)


def readme_blocks(
    meta: ReportMeta,
    *,
    files_included: Sequence[Mapping[str, Any]],
    files_excluded: Sequence[Mapping[str, Any]],
    sheets: Sequence[tuple[str, int, str]],
    tgq_stats: Optional[Mapping[str, Any]] = None,
) -> list[Block]:
    """The Read Me sheet as nine blocks, always in ``BLOCK_TITLES`` order.

    ``files_included`` items: {category, source_type, file_name, upload_id, uploaded_at,
    reference, rows_in_file, rows_included, rows_undated, rows_superseded, notes};
    ``files_excluded`` items: {category, source_type, file_name, upload_id, reason};
    ``sheets``: (title, rows, description); ``tgq_stats``: {rows_loaded, batches_used,
    truncated} or None when no TGQ index was loaded.
    """
    txn_rows: list[list[Any]] = [[t, meaning] for t, meaning in C.TXN_TYPES.items()]
    txn_rows.append(["Sign rules", None])
    txn_rows += [[name, text] for name, text in C.SIGN_RULES_TEXT]

    sheet_rows = [[title, rows, description] for title, rows, description in sheets] or [[_NONE_ROW, None, None]]

    return [
        _report_block(meta, tgq_stats),
        _files_included_block(files_included),
        _files_excluded_block(files_excluded),
        Block(T_SHEETS, ("Sheet", "Rows", "Description"), sheet_rows, ("text", "int", "text")),
        Block(
            T_LEGEND, ("Column", "Type", "Sign", "Meaning"),
            [[c.header, KIND_LABELS.get(c.kind, c.kind), SIGN_LABELS.get(c.sign), c.meaning or None]
             for c in C.COMBINED_COLUMNS],
            ("text",) * 4,
        ),
        Block(T_TXN_TYPES, ("Type", "Meaning"), txn_rows, ("text", "text")),
        Block(T_COUNTS_IN_NET, ("Source", "Counts In Net"), [list(r) for r in C.COUNTS_IN_NET_RULES], ("text", "text")),
        Block(T_FLAGS, ("Flag", "Meaning"), [[k, v] for k, v in C.FLAG_LEGEND.items()], ("text", "text")),
        Block(T_CAVEATS, None, [[c] for c in CAVEATS], ("text",)),
    ]
