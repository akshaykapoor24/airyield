"""Shared value types for the report pipeline. No DB, no openpyxl — import-safe everywhere."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

# Bumped when the same uploads would produce a differently-shaped or differently-valued
# workbook. Stored on report_exports.engine_version and printed on Read Me.
REPORT_ENGINE_VERSION = "1.1"

Basis = Literal["transaction", "upload"]
BspScope = Literal["whole_statement", "issue_date"]
UndatedRows = Literal["include", "exclude"]
SignMode = Literal["native", "type_signed"]


@dataclass(frozen=True, slots=True)
class DocKey:
    """A ticket/document identity: 3-digit IATA accounting code + serial.

    ``code`` is zero-padded to 3 digits, or None when the source carries no airline code.
    ``serial`` is the 10-digit document serial for numeric tickets, or the upper-cased
    alphanumeric form otherwise. Build with ``normalize.doc_key`` — never by hand.
    """
    code: Optional[str]
    serial: str


@dataclass(frozen=True, slots=True)
class Period:
    """Inclusive calendar-date range."""
    date_from: date
    date_to: date

    def contains(self, d: Optional[date]) -> bool:
        return d is not None and self.date_from <= d <= self.date_to


@dataclass(frozen=True)
class ReportOptions:
    basis: Basis = "transaction"
    bsp_scope: BspScope = "whole_statement"
    include_detail_sheets: bool = True
    include_pii: bool = False
    undated_rows: UndatedRows = "include"


@dataclass(frozen=True)
class SupplierSnap:
    """statement_batch_suppliers snapshot for a third-party upload."""
    supplier_id: Optional[int]
    name: Optional[str]
    code: Optional[str]
    branch: Optional[str]


@dataclass(frozen=True)
class AirlineSnap:
    """The airline an LCC upload was declared for (tenant_airlines via the batch link)."""
    tenant_airline_id: Optional[int]
    airline_id: Optional[int]
    name: Optional[str]
    code: Optional[str]              # 2-letter IATA designator
    iata_numeric_code: Optional[str] # 3-digit accounting code
    ref_id: Optional[str]


@dataclass(frozen=True)
class UploadMeta:
    """One included upload (a batch) as the mappers see it.

    ``header`` is the source's own header row where one exists (BspStatement for bsp,
    BspSummaryStatement for bsp-summary, LccDetailedBatch for lcc-detailed), else None.
    ``summary_header`` is the owner-scoped BspSummaryStatement paired to a BSP detailed
    statement through group_id (None when absent). ``upload_idx`` orders uploads of the
    SAME source newest-first (0 = newest); de-duplication keeps the lowest index.
    """
    source_key: str
    upload_id: str
    file_name: Optional[str]
    uploaded_at: Optional[datetime]
    upload_idx: int = 0
    status: Optional[str] = None
    reference: Optional[str] = None
    total_rows: Optional[int] = None
    header: Any = None
    summary_header: Any = None
    supplier: Optional[SupplierSnap] = None
    airline: Optional[AirlineSnap] = None
    source_format: Optional[str] = None


@dataclass(frozen=True)
class AirlineInfo:
    iata_code: Optional[str]
    numeric_code: Optional[str]
    name: Optional[str]


@dataclass
class AirlineMaster:
    """Global airlines master, loaded once per build. Lookups never raise."""
    by_numeric: dict[str, AirlineInfo] = field(default_factory=dict)   # "098" → info
    by_iata: dict[str, AirlineInfo] = field(default_factory=dict)      # "AI"  → info

    def numeric(self, code: Optional[str]) -> Optional[AirlineInfo]:
        c = (code or "").strip()
        if c.isdigit():
            c = c.zfill(3)
        return self.by_numeric.get(c) if c else None

    def iata(self, code: Optional[str]) -> Optional[AirlineInfo]:
        c = (code or "").strip().upper()
        return self.by_iata.get(c) if c else None


@dataclass
class LinkResult:
    """What linking decided for one Combined row. Every field is optional; the mapper
    copies non-None values onto the row (see columns.apply_link)."""
    linked_document: Optional[str] = None
    linked_via: Optional[str] = None
    also_in_bsp: Optional[str] = None        # "Yes – this report" | "Yes – other upload (<file>)" | "Yes – other period (<file>)" | "No"
    not_in_bsp: Optional[str] = None         # "Yes" | "In another BSP upload (<file>)" | "BSP row outside period (<file>)" | "Unknown – no ticket no."
    tgq_enriched: Optional[str] = None       # "Yes (<method>)" | "No"
    counts_in_net: Optional[str] = None      # overrides the mapper default when set
    flags: list[str] = field(default_factory=list)


@dataclass
class MapCtx:
    """Everything a mapper may read besides the row itself. Built by builder.py per upload."""
    upload: UploadMeta
    options: ReportOptions = field(default_factory=ReportOptions)
    period: Optional[Period] = None
    airlines: AirlineMaster = field(default_factory=AirlineMaster)
    tgq: Any = None                          # bsp_tgq_enrichment.TgqIndex (report mode) or None
    tgq_files: dict[str, str] = field(default_factory=dict)   # tgq batch_id → file name
    extra_keys: tuple[str, ...] = ()         # detail sheet: JSONB keys beyond the spec (already PII-filtered)
    tax_codes: tuple[str, ...] = ()          # detail sheet: BSP / LCC tax-code pivot columns, in order


@dataclass(frozen=True)
class ReportMeta:
    """Who / when / what for Read Me. ``generated_at`` is naive UTC."""
    export_id: Optional[int]
    title: Optional[str]
    generated_at: datetime
    generated_by_name: Optional[str]
    generated_by_email: Optional[str]
    tenant_name: Optional[str]
    period: Optional[Period]
    options: ReportOptions
    source_types: tuple[str, ...]


@dataclass(frozen=True)
class TaxComponent:
    """One bsp_tax_breakups row attached to a BSP row view by the builder."""
    component_type: Optional[str]   # TAX | FEE | PENALTY | …
    component_code: Optional[str]
    amount: Any                     # Decimal | float | None
