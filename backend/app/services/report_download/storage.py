"""Where a generated report workbook is stored, and how it is named on the way out.

GCS first (``reports_bucket``), local disk as the fallback — the same contract as every other
stored file (services/file_store.py), with two differences that matter for a report:

  * THE LOCAL ROOT IS NOT UPLOAD_DIR. main.py mounts UPLOAD_DIR as public static files, and a
    report holds every PNR and passenger name the user uploaded. ``local_root`` refuses to
    resolve anywhere under it, so a misconfigured REPORTS_LOCAL_DIR fails loudly instead of
    publishing reports. Local files are only ever served by the token-checked stream endpoint.
  * THE PATH IS NOT GUESSABLE. ``blob_name`` embeds the row's random ``storage_key``, so a
    report id alone does not locate its file in a bucket listing or on disk.

The download file name is ASCII and built from the period and report id only — the user's
free-text title never reaches a header or a path.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from app.config import settings
from app.services import file_store
from app.services.bsp_export import xlsx_filename
from app.services.master_export import XLSX_MEDIA_TYPE

__all__ = [
    "XLSX_MEDIA_TYPE", "StoredExportRef", "reports_bucket", "local_root",
    "export_file_name", "blob_name", "content_disposition",
]


class StoredExportRef(Protocol):
    """The report_exports fields that decide where its file lives."""
    id: int
    tenant_id: int
    created_by_id: int
    storage_key: str
    file_name: str | None


def reports_bucket() -> str:
    """The bucket new reports go to; '' means local disk only."""
    return (
        settings.GCS_REPORTS_BUCKET_NAME
        or settings.GCS_BSP_BUCKET_NAME
        or settings.GCS_TICKETS_BUCKET_NAME
    )


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def local_root() -> Path:
    """Absolute local directory for reports that could not (or need not) go to GCS.

    Resolved against the backend package like file_store's own root, so the API and the
    worker agree regardless of their working directories. Raises RuntimeError — not an
    assert, which ``python -O`` would strip — when it would sit under the public uploads
    mount, checked against both the package-resolved UPLOAD_DIR and the CWD-resolved one
    StaticFiles actually serves.
    """
    root = Path(settings.REPORTS_LOCAL_DIR)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root   # …/backend/<REPORTS_LOCAL_DIR>
    root = root.resolve()
    for public in {file_store._root().resolve(), Path(settings.UPLOAD_DIR).resolve()}:
        if _is_within(root, public):
            raise RuntimeError(
                f"REPORTS_LOCAL_DIR ({root}) overlaps the public uploads directory ({public}). "
                "Generated reports must never be served as static files; point it elsewhere."
            )
    return root


def export_file_name(export_id: int, date_from: date, date_to: date) -> str:
    """``airyield-report-20260701-20260731-r42.xlsx`` — ASCII only, no user text."""
    return xlsx_filename("airyield-report", f"{date_from:%Y%m%d}-{date_to:%Y%m%d}", f"r{export_id}")


def blob_name(export: StoredExportRef) -> str:
    """``reports/{tenant}/{user}/{id}-{storage_key}/{file_name}`` for one report row.

    Deterministic for the row, so a finalize that loses its fence can delete exactly the
    object it just wrote. The ``reports/`` prefix is what the GCS lifecycle rule matches.
    """
    if not export.file_name:
        raise ValueError("A report's file name must be set before its blob name is built.")
    return (
        f"reports/{export.tenant_id}/{export.created_by_id}/"
        f"{export.id}-{export.storage_key}/{export.file_name}"
    )


def content_disposition(file_name: str) -> str:
    """``attachment`` header with an ASCII ``filename`` and an RFC 5987 ``filename*``.

    Our own names are already ASCII, but the header must stay valid for any name: a
    non-ASCII character in ``filename=""`` breaks some clients, and a quote or backslash
    would end the quoted-string early. Modern browsers take ``filename*``; the ASCII
    fallback is for everything else.
    """
    fallback = "".join(
        c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in file_name
    ) or "report.xlsx"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(file_name, safe='')}"
