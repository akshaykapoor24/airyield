"""Generic spec-driven vendor statements (TGQ HMPR, later NDC / LCC / GDS).

Upload an XLS/CSV export; the spec's fixed columns are stored verbatim in a JSONB
``data`` blob and the repeating ``Tax_TypeN`` / ``TaxN`` pairs are folded into a JSONB
``taxes`` array (so any number of taxes is supported — no fixed Tax1..Tax20 columns).
Each statement type has its OWN dedicated table, resolved by ``{slug}`` via
``STATEMENT_MODELS`` (e.g. ``tgq-hmpr`` → ``tgq_hmpr``). Same REST shape as the
airline-adjustments router, so the frontend batch view is reused unchanged. The
original spreadsheet is stored in GCS for preview/download. Scoped per user/tenant.
"""
from __future__ import annotations

import io
import math
import re
import uuid
from datetime import datetime

import pandas as pd
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import Numeric, case, cast, delete, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.statement_batch_airline_id import StatementBatchAirlineId
from app.models.statement_row import STATEMENT_MODELS
from app.models.tenant_airline import TenantAirline
from app.models.user import User
from app.services import sector_split, statement_spec as spec
from app.services.lcc_airline_selection import resolve_for_upload

router = APIRouter()

_MIN_MATCHED_COLUMNS = 3
_TAX_TYPE_RE = re.compile(r"^tax_type(\d+)$")
_TAX_AMT_RE = re.compile(r"^tax(\d+)$")
# Drill-in filters arrive as `f.<field>=value` so adding one is a spec edit, not a
# signature change. Unknown fields are ignored, never rejected (a stale bookmark should
# degrade, not 400).
_FILTER_PREFIX = "f."
# Facet dropdowns past this are unusable anyway; the client falls back to typing.
_MAX_FACET_VALUES = 200


def _bucket() -> str:
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _resolve(slug: str):
    """(normalized slug, dedicated model) or 404."""
    s = (slug or "").lower()
    model = STATEMENT_MODELS.get(s)
    if model is None or spec.spec_for(s) is None:
        raise HTTPException(status_code=404, detail=f"Unknown statement type '{slug}'.")
    return s, model


def _scope(model, user: User):
    return (model.tenant_id == user.tenant_id, model.created_by_id == user.id)


def _splits(model) -> bool:
    """Does this table carry the per-sector leg columns (models/statement_row._SplitMixin)?

    Only the ticket-shaped tables (tgq_hmpr, ndc) do; the ledger-shaped ones don't, so
    every leg/total reference below is gated on this.
    """
    return hasattr(model, "sector_count")


def _active_filters(slug: str, request: Request | None) -> dict[str, tuple[dict, str]]:
    """Declared `f.<field>` params present on the request → {field: (filter_spec, value)}."""
    if request is None:
        return {}
    declared = {f["field"]: f for f in spec.filter_specs(slug)}
    out: dict[str, tuple[dict, str]] = {}
    for key, raw in request.query_params.multi_items():
        if not key.startswith(_FILTER_PREFIX):
            continue
        f = declared.get(key[len(_FILTER_PREFIX):])
        value = (raw or "").strip()
        if f and value:
            out[f["field"]] = (f, value)
    return out


def _record_conds(model, slug: str, user: User, batch_id: str | None, request: Request | None) -> list:
    """Scope + batch + declared filters, with the export's own grand-total line excluded.

    The total line is a summary, not a ticket — it must never be a data row, get counted,
    or be swept into a SUM.
    """
    conds = [*_scope(model, user)]
    if batch_id:
        conds.append(model.batch_id == batch_id)
    if _splits(model):
        conds.append(model.is_total.is_(False))
    for field, (f, value) in _active_filters(slug, request).items():
        col = model.data[field].astext
        conds.append(col == value if f.get("type") == "select" else col.ilike(f"%{value}%"))
    return conds


def _num(model, field: str):
    """`data->>field` as NUMERIC, treating anything non-numeric as 0.

    Values are stored verbatim as strings (see `_clean`), so a stray "N/A" or a header
    fragment must not blow up the aggregate. The CASE guard is safe — Postgres won't
    constant-fold a cast of a column reference, so it only evaluates on matching rows.
    """
    txt = func.replace(func.coalesce(model.data[field].astext, ""), ",", "")
    return case(
        (txt.op("~")(literal(r"^-?\d+(\.\d+)?$")), cast(txt, Numeric(20, 4))),
        else_=literal(0, Numeric(20, 4)),
    )


def _money_str(value) -> str | None:
    """Serialize a Decimal as a string — a float round-trip would lose paise."""
    return None if value is None else format(value.normalize(), "f")


def _clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    return s


def _read_df(content: bytes, filename: str, header_row: int) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), dtype=str, sep=None, engine="python", header=header_row)
    if name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str, header=header_row)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl", header=header_row)


def _parse(content: bytes, filename: str, slug: str):
    """(df, {col->field}, {col->normalized}) for the header row that recognises the most columns."""
    field_set = set(spec.fields(slug))
    best = None
    last_err: Exception | None = None
    for header_row in (0, 1, 2):
        try:
            df = _read_df(content, filename, header_row)
        except Exception as e:  # noqa: BLE001 — unreadable at this offset, try the next
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        colmap: dict = {}
        normmap: dict = {}
        for col in df.columns:
            key = spec.norm(col)
            normmap[col] = key
            if key in field_set and key not in colmap.values():
                colmap[col] = key
        if best is None or len(colmap) > best[0]:
            best = (len(colmap), df, colmap, normmap)
    if best is None:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv.")
    matched, df, colmap, normmap = best
    if matched < _MIN_MATCHED_COLUMNS:
        sample = ", ".join(spec.headers(slug)[:5])
        raise HTTPException(
            status_code=400,
            detail=f"This doesn't look like a {spec.spec_for(slug)['label']} file — only {matched} known "
                   f"column(s) were recognised. Expected headers such as: {sample}…",
        )
    return df, colmap, normmap


def _fold_taxes(row, normmap: dict) -> list[dict]:
    """Fold every Tax_TypeN / TaxN pair (any N) into [{type, amount}, ...]; drop empty types."""
    types: dict[int, str | None] = {}
    amounts: dict[int, str | None] = {}
    for col, nz in normmap.items():
        m = _TAX_TYPE_RE.match(nz)
        if m:
            types[int(m.group(1))] = _clean(row[col])
            continue
        m = _TAX_AMT_RE.match(nz)
        if m:
            amounts[int(m.group(1))] = _clean(row[col])
    out: list[dict] = []
    for n in sorted(types):
        t = types[n]
        if t:
            out.append({"type": t, "amount": amounts.get(n)})
    return out


def _detect_df(content: bytes, filename: str, score_fn):
    """Pick the header row (0/1/2) whose columns score highest via `score_fn(cols)`."""
    best = None
    last_err: Exception | None = None
    for hr in (0, 1, 2):
        try:
            df = _read_df(content, filename, hr)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        df.dropna(how="all", inplace=True)
        score = score_fn([str(c) for c in df.columns])
        if best is None or score > best[0]:
            best = (score, df)
    if best is None:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {last_err}. Upload a valid .xlsx, .xls or .csv.")
    if best[0] < _MIN_MATCHED_COLUMNS:
        raise HTTPException(status_code=400, detail="This doesn't look like a valid statement — too few recognised columns.")
    return best[1]


def _seg_str(s: dict) -> str:
    return f"{s.get('route') or ''} {s.get('flight_no') or ''}".strip()


def _display_columns(slug: str) -> list[dict]:
    """Ordered display columns: the spec's own, plus folded/derived/leg extras.

    Single source of truth so `/records` and `/columns` can never drift apart.
    """
    parser_name = spec.parser(slug)
    cols = spec.columns(slug)
    if parser_name == "lcc":
        cols = cols + [
            {"header": "Taxes", "field": "__taxes__"},
            {"header": "Segments", "field": "__segments__"},
            {"header": "SSR", "field": "__ssr__"},
            {"header": "Format", "field": "__format__"},
        ]
    elif parser_name:  # any other custom parser (DI / Divided PNR / Flown / Third Party …) is a flat ledger
        cols = cols + [{"header": "Format", "field": "__format__"}]
    elif spec.fold_taxes(slug):
        cols = cols + [{"header": "Taxes", "field": "__taxes__"}]

    # Airline accounting code, lifted out of the ticket-number cell at ingest.
    tn = spec.ticket_no_config(slug)
    if tn:
        col = {"header": tn.get("header", "Airline_Code"), "field": tn.get("code_field", "airline_code")}
        i = next((k for k, c in enumerate(cols) if c["header"] == tn.get("before")), len(cols))
        cols = cols[:i] + [col] + cols[i:]

    if spec.split_config(slug):
        # First, not next to `Sectors`: that sits at column ~48 of 66, where a Leg column
        # would be invisible without scrolling — and which leg a row is is row identity.
        cols = [{"header": "Leg", "field": "__leg__"}] + cols

    money = spec.money_fields(slug)
    if money:
        cols = [{**c, "kind": "money"} if c["field"] in money else c for c in cols]
    return cols


def _build_rows(model, slug: str, prov: dict, data: dict, taxes: list[dict], seq: int) -> list:
    """One parsed source line → the model row(s) it becomes.

    Shared by upload and re-process so both always produce identical output. For a type
    that declares no `split_sectors` this is a single unchanged row, i.e. exactly the old
    behaviour.
    """
    if not _splits(model):
        return [model(**prov, data=data, taxes=taxes)]

    # The export's own grand-total line: kept (it's the vendor's declared figure, shown in
    # the summary slab) but flagged, so it never behaves like a ticket. Checked before any
    # derivation — it carries no ticket number to split.
    if sector_split.is_total_row(data, spec.total_row_config(slug)):
        return [model(**prov, data=data, taxes=taxes, row_seq=seq,
                      sector_index=1, sector_count=1,
                      split_status=sector_split.TOTAL, is_total=True)]

    source_data = data   # verbatim, before anything is derived from it
    data, derived = sector_split.apply_ticket_no(data, spec.ticket_no_config(slug))

    cfg = spec.split_config(slug)
    if not cfg:
        return [model(**prov, data=data, taxes=taxes, row_seq=seq,
                      sector_index=1, sector_count=1, split_status=sector_split.SINGLE,
                      orig_data=source_data if derived else None)]

    out = []
    for leg_data, leg_taxes, idx, count, status in sector_split.split_row(data, taxes, cfg):
        # Stored whenever the row was actually altered — it's the audit trail and the
        # source for re-deriving legs under a different allocation rule.
        changed = count > 1 or derived
        out.append(model(
            **prov, data=leg_data, taxes=leg_taxes, row_seq=seq,
            sector_index=idx, sector_count=count, split_status=status,
            orig_data=source_data if changed else None,
            orig_taxes=taxes if count > 1 else None,
        ))
    return out


def _get_builder(parser_name: str):
    """Resolve a custom-parser module exposing build_col_map(cols) + build_row(row, cols)."""
    if parser_name == "lcc":
        from app.services import lcc_statement as m
        return m
    if parser_name == "di":
        from app.services import di_statement as m
        return m
    if parser_name == "divided-pnr":
        from app.services import divided_pnr as m
        return m
    if parser_name == "flown-report":
        from app.services import flown_report as m
        return m
    if parser_name == "cta-bta":
        from app.services import cta_bta_report as m
        return m
    # Generic flat parsers (Third Party GDS/LCC, …) registered in flat_statement.
    from app.services import flat_statement
    b = flat_statement.get(parser_name)
    if b is not None:
        return b
    raise HTTPException(status_code=500, detail=f"No parser registered for '{parser_name}'.")


# ── routes ───────────────────────────────────────────────────────────────────
@router.get("/{slug}/columns")
async def get_columns(slug: str, current_user: User = Depends(get_current_user)):
    slug, _ = _resolve(slug)
    return _display_columns(slug)


async def _airline_selection(
    db: AsyncSession, slug: str, user: User, tenant_airline_ids: list[int]
) -> list[TenantAirline]:
    """The Airline Master ids declared for this upload.

    Required only for the types whose spec says so — the LCC ones, whose exports name
    no carrier. TGQ HMPR, NDC and the third-party types share this endpoint and carry
    their own airline, so a selection sent for them is ignored rather than stored.
    """
    if not spec.requires_airline_id(slug):
        return []
    try:
        return await resolve_for_upload(db, user.tenant_id, tenant_airline_ids)
    except ValueError as exc:
        # MixedAirlineSelection and UnknownAirlineId are both ValueErrors and both
        # carry a message written for the user.
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{slug}/upload")
async def upload_statement(
    slug: str,
    file: UploadFile = File(...),
    tenant_airline_ids: list[int] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse a statement export → verbatim fixed columns + folded taxes, under one batch.

    For the LCC types the uploader must also declare which of their Airline Master ids
    the file covers — the export names no carrier, so nothing else identifies it. That
    is resolved BEFORE the file is parsed or stored, so a rejected selection cannot
    leave a half-imported batch behind.
    """
    slug, model = _resolve(slug)
    airlines = await _airline_selection(db, slug, current_user, tenant_airline_ids)

    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    parser_name = spec.parser(slug)
    batch_id = str(uuid.uuid4())
    uploaded_at = datetime.utcnow()

    # Store the original file in GCS (best-effort — never lose a successful import).
    file_url = None
    try:
        from app.services import gcs
        blob_name = f"statements/{current_user.tenant_id}/{slug}/{batch_id}/{file.filename}"
        await gcs.upload_bytes(content, blob_name, file.content_type or "application/octet-stream", _bucket())
        file_url = blob_name
    except Exception:  # noqa: BLE001
        file_url = None

    objs = []
    source_rows = 0
    if parser_name:
        # Multi-format normalizer (LCC / DI): alias-map → canonical fields (+ fold taxes/segments/ssr for LCC).
        builder = _get_builder(parser_name)
        df = _detect_df(content, file.filename or "", lambda cols: len(builder.build_col_map(cols)))
        cols = [str(c) for c in df.columns]
        matched = len(builder.build_col_map(cols))
        for _, row in df.iterrows():
            b = builder.build_row(row, cols)
            if not (b["data"] or b["taxes"] or b["segments"] or b["ssr"]):
                continue  # blank row
            source_rows += 1
            objs.append(model(
                tenant_id=current_user.tenant_id, created_by_id=current_user.id,
                batch_id=batch_id, source_file=file.filename, file_url=file_url, uploaded_at=uploaded_at,
                data=b["data"], taxes=b["taxes"], segments=b["segments"],
                ssr=b["ssr"], raw_data=b["raw_data"], source_format=b["source_format"],
            ))
    else:
        # Verbatim spec-driven path (TGQ HMPR / NDC): fixed columns + Tax_TypeN/TaxN folding.
        df, colmap, normmap = _parse(content, file.filename or "", slug)
        matched = len(colmap)
        fold = spec.fold_taxes(slug)
        prov = dict(
            tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            batch_id=batch_id, source_file=file.filename, file_url=file_url,
            uploaded_at=uploaded_at,
        )
        for seq, (_, row) in enumerate(df.iterrows(), start=1):
            data = {field: _clean(row[col]) for col, field in colmap.items()}
            taxes = _fold_taxes(row, normmap) if fold else []
            if not any(v is not None for v in data.values()) and not taxes:
                continue  # blank row
            source_rows += 1
            objs.extend(_build_rows(model, slug, prov, data, taxes, seq))

    if not objs:
        raise HTTPException(status_code=400, detail="No data rows were found in the file.")

    db.add_all(objs)
    for ta in airlines:
        db.add(StatementBatchAirlineId(
            tenant_id=current_user.tenant_id, slug=slug,
            batch_id=batch_id, tenant_airline_id=ta.id,
        ))
    await db.commit()
    return {
        "batch_id": batch_id,
        "type": slug,
        "file_name": file.filename,
        "inserted": len(objs),
        "matched_columns": matched,
        "source_rows": source_rows,
        "leg_rows": sum(1 for o in objs if not getattr(o, "is_total", False)),
        "airline_name": airlines[0].airline_name if airlines else None,
        "airline_code": airlines[0].airline_code if airlines else None,
        "airline_ref_ids": [ta.ref_id for ta in airlines],
    }


@router.get("/{slug}/records")
async def list_records(
    slug: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    batch_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated rows — fixed columns flattened from `data`, plus a folded `Taxes` column.

    Types that declare them additionally get `f.<field>` filters, a `summary` block totalled
    over the whole filtered set, and a `Leg` column. Every one of those keys is absent for a
    type that declares none, so the shared frontend view is unchanged for it.
    """
    slug, model = _resolve(slug)
    conds = _record_conds(model, slug, current_user, batch_id, request)
    active = _active_filters(slug, request)

    total = await db.scalar(select(func.count()).select_from(select(model).where(*conds).subquery()))

    # File order, not insertion order reversed: `id DESC` used to surface the export's last
    # line (its grand total) first. Sort on row_seq so re-processed legs stay under their
    # parent rather than landing at the end of the batch.
    order = [model.uploaded_at.desc()]
    if _splits(model):
        order += [func.coalesce(model.row_seq, model.id).asc(),
                  func.coalesce(model.sector_index, 1).asc()]
    order.append(model.id.asc())
    q = select(model).where(*conds).order_by(*order).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    parser_name = spec.parser(slug)
    fold = spec.fold_taxes(slug)
    split_cfg = spec.split_config(slug)
    cols = _display_columns(slug)

    out_rows = []
    for r in rows:
        d = dict(r.data or {})
        d["id"] = r.id
        if split_cfg:
            count = getattr(r, "sector_count", None)
            d["__leg__"] = f"{r.sector_index}/{count}" if count else ""
            d["__split__"] = getattr(r, "split_status", None)
            d["__legs__"] = count
        if parser_name == "lcc":
            d["__taxes__"] = " · ".join(
                f"{t.get('code')} {t.get('amount') or ''}".strip()
                for t in (r.taxes or []) if t.get("code")
            )
            d["__segments__"] = " · ".join(_seg_str(s) for s in (r.segments or []))
            d["__ssr__"] = " · ".join(
                f"{s.get('code')} {s.get('amount') or ''}".strip()
                for s in (r.ssr or []) if s.get("code")
            )
            d["__format__"] = r.source_format or ""
        elif parser_name:
            d["__format__"] = r.source_format or ""
        elif fold:
            d["__taxes__"] = " · ".join(
                f"{t.get('type')} {t.get('amount') or ''}".strip()
                for t in (r.taxes or []) if t.get("type")
            )
        out_rows.append(d)

    payload = {"total": total or 0, "limit": limit, "offset": offset, "columns": cols, "rows": out_rows}

    filters = spec.filter_specs(slug)
    if filters:
        payload["filters"] = filters

    sum_specs = spec.summary_fields(slug)
    if sum_specs:
        payload["summary"] = await _summary(
            db, model, slug, current_user, batch_id, conds, sum_specs, bool(active)
        )

    # Gated on the spec, not just the table: `ndc` carries the leg columns but has
    # splitting switched off, and offering to re-process it would be a prompt to nowhere.
    if _splits(model) and split_cfg and batch_id:
        # Batch-scoped on purpose: whether this upload predates splitting is a property of
        # the upload, not of whatever filter happens to be applied.
        payload["needs_reprocess"] = bool(await db.scalar(
            select(func.count()).select_from(model).where(
                model.batch_id == batch_id, *_scope(model, current_user),
                model.sector_count.is_(None),
            )
        ))
    return payload


async def _summary(db, model, slug, user, batch_id, conds, sum_specs, has_filters) -> dict:
    """Column totals over the ENTIRE filtered set, plus the file's own declared total.

    Both are shown side by side rather than picking one: real exports are not always
    internally consistent, and quietly presenting a single number would hide that.
    """
    fields = [f["field"] for f in sum_specs]
    agg = (await db.execute(
        select(func.count().label("n"), *[func.sum(_num(model, f)).label(f"s_{f}") for f in fields])
        .where(*conds)
    )).one()

    computed = {f: _money_str(getattr(agg, f"s_{f}")) or "0" for f in fields}

    declared: dict | None = None
    note: str | None = None
    if _splits(model) and batch_id:
        totals = (await db.execute(
            select(model).where(model.is_total.is_(True), model.batch_id == batch_id, *_scope(model, user))
            .limit(2)
        )).scalars().all()
        if len(totals) == 1:
            declared = {f: (totals[0].data or {}).get(f) for f in fields}
        elif len(totals) > 1:
            note = "This upload has more than one Total line — showing computed figures only."

    leg_count = agg.n or 0
    source_rows = leg_count
    if _splits(model):
        source_rows = await db.scalar(
            select(func.count(func.distinct(func.coalesce(model.row_seq, model.id)))).where(*conds)
        ) or 0

    return {
        "fields": sum_specs,
        "computed": computed,
        "declared": declared,
        # A filtered subset is not comparable to a whole-file total; saying so beats
        # flashing a delta that only means "you filtered something out".
        "declared_comparable": bool(declared) and not has_filters,
        "declared_note": note,
        "row_count": source_rows,
        "leg_count": leg_count,
    }


@router.get("/{slug}/records/facets")
async def record_facets(
    slug: str,
    batch_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Distinct values for every `select` filter this type declares — `{}` when it has none.

    Post-split these are genuinely useful: `traveldt` holds one date per row instead of
    "28APR 28APR 14MAY 15MAY", so it collapses to a short, pickable list.
    """
    slug, model = _resolve(slug)
    selects = [f for f in spec.filter_specs(slug) if f.get("type") == "select"]
    if not selects:
        return {}

    conds = [*_scope(model, current_user)]
    if batch_id:
        conds.append(model.batch_id == batch_id)
    if _splits(model):
        conds.append(model.is_total.is_(False))

    out: dict[str, list[str]] = {}
    for f in selects:
        col = model.data[f["field"]].astext
        values = (await db.execute(
            select(func.distinct(col)).where(*conds, col.isnot(None), col != "")
            .order_by(col).limit(_MAX_FACET_VALUES)
        )).scalars().all()
        out[f["field"]] = [v for v in values if v]
    return out


@router.post("/{slug}/batches/{batch_id}/resplit")
async def resplit_batch(
    slug: str,
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-derive this upload's per-sector rows in place — no re-upload needed.

    Covers batches imported before splitting existed, and re-deriving legs if the
    allocation rule changes. Idempotent: `orig_data` holds the pre-split row, so running
    it on already-split rows reproduces exactly the same set. All-or-nothing — the delete
    and the re-insert share one transaction, so a failure can't leave a half-split batch.
    """
    slug, model = _resolve(slug)
    if not _splits(model):
        raise HTTPException(status_code=400, detail=f"{spec.spec_for(slug)['label']} rows are not split by sector.")

    rows = (await db.execute(
        select(model).where(model.batch_id == batch_id, *_scope(model, current_user))
        .order_by(func.coalesce(model.row_seq, model.id).asc(),
                  func.coalesce(model.sector_index, 1).asc(), model.id.asc())
    )).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="Upload not found.")

    # Collapse back to source lines first: sibling legs share a row_seq and carry the same
    # orig_data, so only the first of each group is a distinct source row.
    sources: list[tuple[dict, list, dict]] = []
    seen: set = set()
    for i, r in enumerate(rows, start=1):
        key = r.row_seq if r.row_seq is not None else f"id:{r.id}"
        if key in seen:
            continue
        seen.add(key)
        prov = dict(
            tenant_id=r.tenant_id, created_by_id=r.created_by_id, batch_id=r.batch_id,
            source_file=r.source_file, file_url=r.file_url, uploaded_at=r.uploaded_at,
        )
        sources.append((dict(r.orig_data or r.data or {}), list(r.orig_taxes or r.taxes or []), prov))

    objs = []
    for seq, (data, taxes, prov) in enumerate(sources, start=1):
        objs.extend(_build_rows(model, slug, prov, data, taxes, seq))

    await db.execute(delete(model).where(model.batch_id == batch_id, *_scope(model, current_user)))
    db.add_all(objs)
    await db.commit()
    return {
        "source_rows": len(sources),
        "leg_rows": sum(1 for o in objs if not o.is_total),
        "total_rows": len(objs),
    }


@router.get("/{slug}/batches")
async def list_batches(slug: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """One row per upload — file name, when, how many rows, whether the file is stored."""
    slug, model = _resolve(slug)
    # Match what the drill-in actually shows: the declared grand-total line is a summary,
    # not an entry.
    row_count = (func.count().filter(model.is_total.is_(False)) if _splits(model) else func.count())
    q = (
        select(
            model.batch_id,
            model.source_file,
            func.max(model.file_url).label("file_url"),
            func.max(model.uploaded_at).label("uploaded_at"),
            row_count.label("row_count"),
        )
        .where(*_scope(model, current_user))
        .group_by(model.batch_id, model.source_file)
        .order_by(func.max(model.uploaded_at).desc())
    )
    rows = (await db.execute(q)).all()

    # The declared airline ids, for the types that have them. ONE query for the whole
    # list rather than a lookup per batch. Empty for every other type, and for uploads
    # made before the airline was captured — those show "—" rather than a guess.
    links: dict[str, list[TenantAirline]] = {}
    if spec.requires_airline_id(slug) and rows:
        for batch_id, ta in (await db.execute(
            select(StatementBatchAirlineId.batch_id, TenantAirline)
            .join(TenantAirline, TenantAirline.id == StatementBatchAirlineId.tenant_airline_id)
            .where(
                StatementBatchAirlineId.slug == slug,
                StatementBatchAirlineId.tenant_id == current_user.tenant_id,
                StatementBatchAirlineId.batch_id.in_([r.batch_id for r in rows]),
            )
            .order_by(TenantAirline.ref_id)
        )).all():
            links.setdefault(batch_id, []).append(ta)

    return [
        {
            "batch_id": r.batch_id,
            "source_file": r.source_file,
            "uploaded_at": r.uploaded_at,
            "row_count": r.row_count,
            "has_file": bool(r.file_url),
            "created_by_name": current_user.full_name,
            # Every id in a batch shares one carrier, so the first row's airline is
            # the batch's airline — see services/lcc_airline_selection.py.
            "airline_name": links[r.batch_id][0].airline_name if links.get(r.batch_id) else None,
            "airline_code": links[r.batch_id][0].airline_code if links.get(r.batch_id) else None,
            "airline_ref_ids": [ta.ref_id for ta in links.get(r.batch_id, [])],
            "tenant_airline_ids": [ta.id for ta in links.get(r.batch_id, [])],
        }
        for r in rows
    ]


@router.get("/{slug}/batches/{batch_id}/file-url")
async def get_batch_file_url(
    slug: str,
    batch_id: str,
    inline: bool = Query(True, description="inline (preview) vs attachment (download)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Signed GCS URL for the original uploaded file — inline for preview, attachment for download."""
    slug, model = _resolve(slug)
    row = (await db.execute(
        select(model.file_url, model.source_file)
        .where(model.batch_id == batch_id, *_scope(model, current_user)).limit(1)
    )).first()
    if not row or not row.file_url:
        raise HTTPException(status_code=404, detail="No file stored for this upload.")
    from app.services import gcs
    url = await gcs.generate_signed_url(row.file_url, _bucket(), expiry_minutes=60, inline=inline)
    return {"url": url, "file_name": row.source_file}


@router.delete("/{slug}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_record(slug: str, record_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a record — and, for a split ticket, all of its sibling legs.

    A leg is a slice of one ticket, not a standalone entry: dropping one would leave a
    part-ticket behind and silently skew every column total.
    """
    slug, model = _resolve(slug)
    obj = (await db.execute(
        select(model).where(model.id == record_id, *_scope(model, current_user))
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Record not found.")

    if _splits(model) and (obj.sector_count or 1) > 1 and obj.row_seq is not None:
        await db.execute(delete(model).where(
            model.batch_id == obj.batch_id, model.row_seq == obj.row_seq, *_scope(model, current_user)
        ))
    else:
        await db.delete(obj)
    await db.commit()


@router.delete("/{slug}/batches/{batch_id}")
async def delete_batch(slug: str, batch_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete an entire upload (all rows sharing the batch_id)."""
    slug, model = _resolve(slug)
    res = await db.execute(delete(model).where(model.batch_id == batch_id, *_scope(model, current_user)))
    # Explicitly: batch_id carries no FK, because these types keep no batch header row
    # for one to point at. Left behind, these links would keep an airline id looking
    # in-use forever and block its deletion from the Airline Master.
    await db.execute(
        delete(StatementBatchAirlineId).where(
            StatementBatchAirlineId.slug == slug,
            StatementBatchAirlineId.batch_id == batch_id,
            StatementBatchAirlineId.tenant_id == current_user.tenant_id,
        )
    )
    await db.commit()
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Upload not found.")
    return {"deleted": res.rowcount}


@router.get("/{slug}/template")
async def download_template(slug: str, current_user: User = Depends(get_current_user)):
    """Blank .xlsx with the exact headers (fixed columns + Tax_Type1/Tax1 … pairs)."""
    slug, _ = _resolve(slug)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = f"{spec.spec_for(slug)['label']} Template"[:31]
    ws.append(spec.template_headers(slug))

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{slug}_template.xlsx"'},
    )
