"""Request / response shapes for Workspace → Report download (api/v1/report_download.py).

The response models mirror frontend/src/lib/reportDownload.ts field for field; renaming one
here breaks the page silently, so treat them as a published contract.

Validation that protects the worker lives on the request model rather than in the handler:
period span, known source types, and hard caps on how many upload ids one request may carry
(a request is re-verified id by id against the database, so an unbounded list is a cheap way
to make the API do unbounded work).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import settings
from app.services.report_download.types import Basis, BspScope, UndatedRows

MAX_INCLUDED_UPLOADS = 500
MAX_UNTICKED_UPLOADS = 2000
MAX_TITLE_LENGTH = 200

DisplayStatus = Literal["waiting", "generating", "stalled", "ready", "failed", "expired"]


# ── shared validation (also used for the GET /uploads query string) ───────────

def normalize_source_types(values: list[str]) -> list[str]:
    """Trimmed, de-duplicated (first occurrence wins) and checked against the registry.

    Raises ValueError naming the unknown keys. The registry is imported here, not at module
    load, so importing the schemas never drags in every statement model.
    """
    from app.services.report_download.registry import source_keys

    known = set(source_keys())
    out: list[str] = []
    for raw in values:
        key = (raw or "").strip()
        if key and key not in out:
            out.append(key)
    unknown = [k for k in out if k not in known]
    if unknown:
        raise ValueError(f"Unknown source type(s): {', '.join(unknown)}.")
    if not out:
        raise ValueError("Pick at least one source type.")
    return out


def validate_period(date_from: date, date_to: date) -> None:
    """Raises ValueError for a reversed range or one longer than the configured maximum."""
    if date_from > date_to:
        raise ValueError("The From date must be on or before the To date.")
    span = (date_to - date_from).days + 1
    if span > settings.REPORT_EXPORT_MAX_PERIOD_DAYS:
        raise ValueError(
            f"The period is {span} days; a report can cover at most "
            f"{settings.REPORT_EXPORT_MAX_PERIOD_DAYS} days. Narrow the period."
        )


# ── requests ─────────────────────────────────────────────────────────────────

class UploadRef(BaseModel):
    source_type: str = Field(min_length=1, max_length=40)
    upload_id: str = Field(min_length=1, max_length=100)


class ExportOptionsIn(BaseModel):
    include_detail_sheets: bool = True
    include_pii: bool = False
    undated_rows: UndatedRows = "include"


class ExportCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    date_from: date
    date_to: date
    basis: Basis = "transaction"
    bsp_scope: BspScope = "whole_statement"
    source_types: list[str] = Field(min_length=1, max_length=50)
    included_uploads: list[UploadRef] = Field(min_length=1, max_length=MAX_INCLUDED_UPLOADS)
    unticked_uploads: list[UploadRef] = Field(default_factory=list, max_length=MAX_UNTICKED_UPLOADS)
    options: ExportOptionsIn = Field(default_factory=ExportOptionsIn)

    @field_validator("title")
    @classmethod
    def _blank_title_is_none(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        return v or None

    @field_validator("source_types")
    @classmethod
    def _known_source_types(cls, v: list[str]) -> list[str]:
        return normalize_source_types(v)

    @model_validator(mode="after")
    def _consistent(self) -> "ExportCreate":
        validate_period(self.date_from, self.date_to)
        wanted = set(self.source_types)

        def dedupe(refs: list[UploadRef], what: str) -> list[UploadRef]:
            seen: set[tuple[str, str]] = set()
            out: list[UploadRef] = []
            for ref in refs:
                if ref.source_type not in wanted:
                    raise ValueError(
                        f"{what} upload {ref.upload_id} is a '{ref.source_type}' file, "
                        "which is not one of the selected source types."
                    )
                pair = (ref.source_type, ref.upload_id)
                if pair not in seen:
                    seen.add(pair)
                    out.append(ref)
            return out

        self.included_uploads = dedupe(self.included_uploads, "Included")
        self.unticked_uploads = dedupe(self.unticked_uploads, "Unticked")
        both = ({(r.source_type, r.upload_id) for r in self.included_uploads}
                & {(r.source_type, r.upload_id) for r in self.unticked_uploads})
        if both:
            raise ValueError("An upload cannot be both included and unticked.")
        return self


# ── responses ────────────────────────────────────────────────────────────────

class SourceTypeSummary(BaseModel):
    key: str
    label: str
    uploads: int
    rows: int


class SourceCategorySummary(BaseModel):
    category: str
    types: list[SourceTypeSummary]


class DuplicateRef(BaseModel):
    upload_id: str
    file_name: Optional[str] = None


class UploadItem(BaseModel):
    source_type: str
    category: str
    label: str
    upload_id: str
    file_name: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    status: Optional[str] = None
    reference: Optional[str] = None
    total_rows: int
    rows_in_period: Optional[int] = None
    rows_undated: Optional[int] = None
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    selectable: bool
    default_selected: bool
    possible_duplicate_of: Optional[DuplicateRef] = None
    notes: list[str] = Field(default_factory=list)


class UploadsResponse(BaseModel):
    uploads: list[UploadItem]
    estimated_rows: int


class ExportListItem(BaseModel):
    id: int
    title: Optional[str] = None
    status: str
    display_status: DisplayStatus
    stage: Optional[str] = None
    processed_rows: int
    estimated_rows: int
    queue_position: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    basis: Optional[str] = None
    source_types: list[str] = Field(default_factory=list)
    combined_rows: Optional[int] = None
    file_size: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    error_code: Optional[str] = None
    error: Optional[str] = None


class ExportRead(ExportListItem):
    params: dict
    selection: dict
    sheet_row_counts: Optional[dict] = None
    summary: Optional[dict] = None
    file_name: Optional[str] = None


class ExportList(BaseModel):
    items: list[ExportListItem]
    total: int


class DownloadUrl(BaseModel):
    url: str
    expires_in: int
