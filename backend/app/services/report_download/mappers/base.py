"""Detail-sheet column contract shared by every mapper module.

A mapper module describes its detail sheet as a list of ``DetailCol``; each column knows how
to read its value from a row view. The builder turns them into workbook column specs and
calls ``detail_values`` per row. Values are raw Python (str / Decimal / float / int / date /
datetime / None); the workbook's ``excel_value`` makes them Excel-safe.

Row views are any objects with attribute access for the source model's columns plus the
documented extras (see the report contract) — SQLAlchemy ``Row`` wrappers in production,
``types.SimpleNamespace`` in tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from app.services.report_download.types import MapCtx

Getter = Callable[[Any, MapCtx], Any]


@dataclass(frozen=True)
class DetailCol:
    header: str
    getter: Getter
    kind: str = "text"      # text | money | date | datetime | int
    width: int = 14


def attr(name: str) -> Getter:
    """Getter for a plain attribute of the row view."""
    return lambda row, ctx: getattr(row, name, None)


def data_key(name: str) -> Getter:
    """Getter for ``row.data[name]`` (JSONB-backed statement tables)."""
    def _get(row: Any, ctx: MapCtx) -> Any:
        data = getattr(row, "data", None) or {}
        return data.get(name) if isinstance(data, dict) else None
    return _get


def provenance_cols(row_ref: Callable[[Any], str]) -> list[DetailCol]:
    """The four columns every detail sheet starts with, in this exact order."""
    return [
        DetailCol("Row Ref", lambda row, ctx: row_ref(row), "text", 22),
        DetailCol("Source File", lambda row, ctx: ctx.upload.file_name, "text", 28),
        DetailCol("Upload ID", lambda row, ctx: ctx.upload.upload_id, "text", 20),
        DetailCol("Uploaded At (UTC)", lambda row, ctx: ctx.upload.uploaded_at, "datetime", 18),
    ]


def detail_values(cols: Sequence[DetailCol], row: Any, ctx: MapCtx) -> list[Any]:
    return [c.getter(row, ctx) for c in cols]


def column_specs(cols: Iterable[DetailCol]):
    """DetailCol → workbook.ColSpec (imported lazily so this module stays openpyxl-free)."""
    from app.services.report_download.workbook import ColSpec
    return [ColSpec(c.header, c.kind, c.width) for c in cols]


def row_ref(table: str, ident: Any) -> str:
    return f"{table}:{ident}"
