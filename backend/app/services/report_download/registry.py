"""One ``ReportSource`` per Vendors → Statements type the report can export (15 of them).

WHY A REGISTRY. The fifteen statement types live in four storage shapes — BSP's own
statement/row pair, the BSP summary pair, the three BSPlink adjustment tables and the
spec-driven JSONB tables (plus LCC Detailed's dedicated batch/row schema). The upload
listing, the selection check, the builder and Read Me all need the same facts about each
type: which model holds its rows, which attribute carries the upload id, whether a
half-parsed upload must be skipped, which sheet it lands on and in what order, how its money
is signed. Keeping those facts in one table means a new statement type is one entry here
(plus a mapper) instead of a hunt through five modules, and the registry test pins every
model in ``STATEMENT_MODELS`` / ``ADJUSTMENT_MODELS`` to exactly one entry so a type can
never silently fall out of the report.

Order matters: ``SOURCES`` is in sheet (rank) order, which is also the order the category →
type tree is shown in and the order the builder writes detail sheets. Ranks 1-3 are the
fixed Read Me / Summary / Combined sheets (``README_SHEET`` …); sources take 4-18.

Pure data plus model imports — no DB access, safe to import anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from app.models.airline_adjustment import AirlineACM, AirlineADM, AirlineRA
from app.models.bsp_statement import BspStatement, BspStatementRow
from app.models.bsp_summary import BspSummaryRow, BspSummaryStatement
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.statement_row import STATEMENT_MODELS
from app.services.report_download.columns import CAT_BSP, CAT_LCC, CAT_TP
from app.services.report_download.types import SignMode

Storage = Literal["bsp", "bsp_summary", "adjustment", "spec", "lcc_detailed"]


@dataclass(frozen=True)
class ReportSource:
    """Everything the pipeline needs to know about one statement type.

    ``storage`` picks the query shape: ``bsp`` / ``bsp_summary`` / ``lcc_detailed`` have a
    header table (``header_model``) whose ``batch_id`` the rows reference through
    ``batch_attr``; ``adjustment`` and ``spec`` tables carry ``batch_id``, ``source_file`` and
    ``uploaded_at`` on every row and have no header. ``completed_only`` marks the types
    parsed asynchronously in chunks, where rows of a pending/failed upload are partial.
    ``exclude_totals`` marks the sector-split tables whose declared grand-total line is
    stored as a row (``is_total``). ``period_fields`` is Read Me text for the
    transaction-date basis (the upload basis always uses the upload time).
    """
    key: str
    category: str
    label: str
    sheet_title: str
    rank: int
    storage: Storage
    model: type
    header_model: Optional[type]
    batch_attr: str
    feeds_combined: bool
    completed_only: bool
    exclude_totals: bool
    schema_unverified: bool
    sign_mode: SignMode
    nav: tuple[str, str]
    period_fields: str


@dataclass(frozen=True)
class FixedSheet:
    """A workbook sheet that is not a source's detail sheet."""
    key: str
    title: str
    rank: int


README_SHEET = FixedSheet("readme", "Read Me", 1)
SUMMARY_SHEET = FixedSheet("summary", "Summary", 2)
COMBINED_SHEET = FixedSheet("combined", "Combined", 3)
FIXED_SHEETS: tuple[FixedSheet, ...] = (README_SHEET, SUMMARY_SHEET, COMBINED_SHEET)

CATEGORY_ORDER: tuple[str, ...] = (CAT_BSP, CAT_LCC, CAT_TP)


def _adjustment(key: str, label: str, model: type, rank: int, period_fields: str) -> ReportSource:
    return ReportSource(
        key=key, category=CAT_BSP, label=label, sheet_title=label, rank=rank,
        storage="adjustment", model=model, header_model=None, batch_attr="batch_id",
        feeds_combined=True, completed_only=False, exclude_totals=False,
        schema_unverified=False, sign_mode="type_signed", nav=("bsp", "adm-acm-ra"),
        period_fields=period_fields,
    )


def _spec(
    key: str, category: str, label: str, sheet_title: str, rank: int, nav: tuple[str, str],
    period_fields: str, *, sign_mode: SignMode, exclude_totals: bool = False,
    schema_unverified: bool = False,
) -> ReportSource:
    return ReportSource(
        key=key, category=category, label=label, sheet_title=sheet_title, rank=rank,
        storage="spec", model=STATEMENT_MODELS[key], header_model=None, batch_attr="batch_id",
        feeds_combined=True, completed_only=False, exclude_totals=exclude_totals,
        schema_unverified=schema_unverified, sign_mode=sign_mode, nav=nav,
        period_fields=period_fields,
    )


SOURCES: tuple[ReportSource, ...] = (
    # ── BSP ────────────────────────────────────────────────────────────────────
    ReportSource(
        key="bsp", category=CAT_BSP, label="BSP", sheet_title="BSP Detailed", rank=4,
        storage="bsp", model=BspStatementRow, header_model=BspStatement,
        batch_attr="statement_id", feeds_combined=True, completed_only=True,
        exclude_totals=False, schema_unverified=False, sign_mode="native", nav=("bsp", "bsp"),
        period_fields=(
            "statement period (period_from – period_to) overlapping the range; with "
            "'Only rows issued in the period': issue_date, else statement period start"
        ),
    ),
    # The uploaded Summary PDF restates the detailed statement's totals per airline/FOP, so
    # it gets its own sheet and the tie-out but never Combined rows (that would double count).
    ReportSource(
        key="bsp-summary", category=CAT_BSP, label="BSP Summary", sheet_title="BSP Summary",
        rank=5, storage="bsp_summary", model=BspSummaryRow, header_model=BspSummaryStatement,
        batch_attr="summary_id", feeds_combined=False, completed_only=True,
        exclude_totals=False, schema_unverified=False, sign_mode="native", nav=("bsp", "bsp"),
        period_fields="statement period (period_from – period_to) overlapping the range",
    ),
    _adjustment("adm", "ADM", AirlineADM, 6, "issue_date, else reporting_date"),
    _adjustment("acm", "ACM", AirlineACM, 7, "issue_date, else reporting_date"),
    _adjustment("ra", "RA", AirlineRA, 8, "application_date, else reporting_date"),
    _spec(
        "tgq-hmpr", CAT_BSP, "TGQ HMPR", "TGQ HMPR", 9, ("bsp", "tgq-hmpr"),
        "ticket_date (refunds: void/exchange/refund date, else ticket_date)",
        sign_mode="type_signed", exclude_totals=True,
    ),
    _spec(
        "ndc", CAT_BSP, "NDC", "NDC", 10, ("bsp", "ndc"),
        "date_of_issue, else date_of_booking",
        sign_mode="type_signed", exclude_totals=True,
    ),
    # ── LCC ────────────────────────────────────────────────────────────────────
    ReportSource(
        key="lcc-detailed", category=CAT_LCC, label="LCC Detailed Statement",
        sheet_title="LCC Detailed", rank=11, storage="lcc_detailed", model=LccDetailed,
        header_model=LccDetailedBatch, batch_attr="batch_id", feeds_combined=True,
        completed_only=True, exclude_totals=False, schema_unverified=False,
        sign_mode="native", nav=("lcc", "statement-detailed"),
        period_fields="transaction_date",
    ),
    _spec(
        "lcc-di", CAT_LCC, "LCC DI Statement", "LCC DI", 12, ("lcc", "di"),
        "deposit_date", sign_mode="native",
    ),
    _spec(
        "lcc-divided-pnr", CAT_LCC, "LCC Divided PNR", "LCC Divided PNR", 13,
        ("lcc", "divided-pnr"), "divided_date, else booking_date", sign_mode="native",
    ),
    _spec(
        "lcc-flown-report", CAT_LCC, "LCC Flown Report", "LCC Flown Report", 14,
        ("lcc", "flown-report"), "flown_date, else travel_date, else booking_date",
        sign_mode="native", schema_unverified=True,
    ),
    _spec(
        "lcc-cta-bta", CAT_LCC, "LCC CTA/BTA Report", "LCC CTA-BTA", 15, ("lcc", "cta-bta"),
        "transaction_date, else booking_date", sign_mode="native", schema_unverified=True,
    ),
    # ── Third Party ────────────────────────────────────────────────────────────
    _spec(
        "tp-gds", CAT_TP, "Third Party GDS", "TP GDS", 16, ("third-party", "gds"),
        "issue_date", sign_mode="type_signed",
    ),
    _spec(
        "tp-lcc", CAT_TP, "Third Party LCC", "TP LCC", 17, ("third-party", "lcc"),
        "issue_date", sign_mode="type_signed", schema_unverified=True,
    ),
    _spec(
        "tp-api", CAT_TP, "Third Party API", "TP API", 18, ("third-party", "api"),
        "transaction_date, else booking_date", sign_mode="type_signed",
    ),
)

SOURCE_BY_KEY: dict[str, ReportSource] = {s.key: s for s in SOURCES}


def get_source(key: str) -> ReportSource:
    """The source for ``key``; raises KeyError for an unknown type (callers validate input)."""
    try:
        return SOURCE_BY_KEY[key]
    except KeyError:
        raise KeyError(f"Unknown report source type {key!r}") from None


def source_keys() -> tuple[str, ...]:
    """Every source key, in sheet order."""
    return tuple(s.key for s in SOURCES)
