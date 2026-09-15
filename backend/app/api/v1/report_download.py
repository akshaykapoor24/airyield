"""Workspace → Report download: pick uploads, generate one combined .xlsx in the background.

Mounted at /report-download with its own prefix — never under /statements, whose
``/{slug}/…`` catch-all would shadow these literal paths (see api/v1/__init__.py).

Scope is the caller's own uploads (tenant_id AND created_by_id), like every Vendors →
Statements screen. The platform admin has no workspace and gets 403, not an empty page.

The heavy modules (queries, selection, builder) are imported inside the handlers: they pull
in every statement model and mapper, and the API process should not pay for that at start.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status as http
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.report_download import (
    DownloadUrl, ExportCreate, ExportList, ExportRead, SourceCategorySummary, UploadsResponse,
    normalize_source_types, validate_period,
)
from app.services.report_download import jobs, storage

router = APIRouter()

# Finding uploads runs one aggregate per ticked type over the user's statement rows.
UPLOAD_SEARCH_LIMIT = 30
UPLOAD_SEARCH_WINDOW_S = 60


async def require_tenant_user(current_user: User = Depends(get_current_user)) -> User:
    """get_current_user, refused for a caller that belongs to no workspace."""
    if current_user.tenant_id is None:
        raise HTTPException(
            status_code=http.HTTP_403_FORBIDDEN,
            detail="Report download is only available inside a workspace.",
        )
    return current_user


@router.get("/sources", response_model=list[SourceCategorySummary])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """Upload and row counts per source type, grouped BSP / LCC / Third Party."""
    from app.services.report_download.queries import source_overview

    conn = await db.connection()
    return await source_overview(conn, current_user.tenant_id, current_user.id)


@router.get("/uploads", response_model=UploadsResponse)
async def find_uploads(
    date_from: date,
    date_to: date,
    types: str = Query(..., max_length=2000, description="Comma-separated source type keys"),
    basis: Literal["transaction", "upload"] = "transaction",
    bsp_scope: Literal["whole_statement", "issue_date"] = "whole_statement",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """The caller's uploads with rows in the period, for the picker."""
    from app.services.report_download.queries import list_matching_uploads

    try:
        validate_period(date_from, date_to)
        keys = normalize_source_types(types.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))

    allowed, retry_after = await rate_limit.hit(
        "report-uploads", str(current_user.id), UPLOAD_SEARCH_LIMIT, UPLOAD_SEARCH_WINDOW_S)
    if not allowed:
        raise HTTPException(
            status_code=http.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many searches. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )

    conn = await db.connection()
    return await list_matching_uploads(
        conn, current_user.tenant_id, current_user.id,
        types=keys, date_from=date_from, date_to=date_to, basis=basis, bsp_scope=bsp_scope,
    )


@router.post("/exports", response_model=ExportRead, status_code=http.HTTP_202_ACCEPTED)
async def create_export(
    payload: ExportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """Queue a report. 409 when the caller or workspace is at its active-report cap."""
    export = await jobs.create_export(db, current_user, payload)
    return await jobs.read_model(db, export)


@router.get("/exports", response_model=ExportList)
async def list_exports(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """The caller's report history, newest first. Polled while a report is active."""
    items, total = await jobs.list_exports(db, current_user, limit, offset)
    return ExportList(items=items, total=total)


@router.get("/exports/{export_id}", response_model=ExportRead)
async def get_export(
    export_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    export = await jobs.get_owned_export(db, current_user, export_id)
    return await jobs.read_model(db, export)


@router.post("/exports/{export_id}/retry", response_model=ExportRead, status_code=http.HTTP_202_ACCEPTED)
async def retry_export(
    export_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """Re-queue a failed or stalled report with the same period and uploads."""
    export = await jobs.get_owned_export(db, current_user, export_id)
    export = await jobs.retry_export(db, current_user, export)
    return await jobs.read_model(db, export)


@router.get("/exports/{export_id}/download-url", response_model=DownloadUrl)
async def get_download_url(
    export_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """A URL the browser can open directly: GCS signed, or a token link to /file."""
    export = await jobs.get_owned_export(db, current_user, export_id)
    stream_url = str(request.url_for("stream_report_export", export_id=export.id))
    url = await jobs.download_url(export, stream_url)
    return DownloadUrl(url=url, expires_in=jobs.DOWNLOAD_LINK_MINUTES * 60)


@router.get("/exports/{export_id}/file", name="stream_report_export")
async def stream_report_export(
    export_id: int,
    token: str = Query(..., max_length=2000, description="Short-lived link token from /download-url"),
    db: AsyncSession = Depends(get_db),
):
    """Stream a locally stored report.

    Deliberately not behind get_current_user: the link is opened by the browser without an
    Authorization header. The token — minted only for the report's owner, bound to the report
    id and that owner, valid for minutes — is the authorisation. Streamed from disk, never
    read into memory.
    """
    path, file_name = await jobs.open_local_file(db, export_id, token)
    return FileResponse(
        path,
        media_type=storage.XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": storage.content_disposition(file_name),
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/exports/{export_id}", status_code=http.HTTP_204_NO_CONTENT)
async def delete_export(
    export_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tenant_user),
):
    """Delete a report and its file. A report still generating stops within ~20 s."""
    export = await jobs.get_owned_export(db, current_user, export_id)
    await jobs.delete_export(db, current_user, export)
    return Response(status_code=http.HTTP_204_NO_CONTENT)
