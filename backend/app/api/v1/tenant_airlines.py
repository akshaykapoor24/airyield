"""User Master → Airline Master.

The airlines a tenant works with, each carrying the tenant's OWN id(s) for it. Those
ids are what a user selects when uploading an LCC Detailed statement, which is the
only way the carrier can be known for LCC data — see models/tenant_airline.py for why.

Two things shape this module:

* The airline reference data (name / code / IATA numeric code / contract year) belongs
  to the platform admin's master. The tenant does not copy it; `GET /catalog` lists the
  master live and hangs the tenant's ids under each airline. So the screen arrives
  pre-filled and the only empty column is the one the user actually owns.
* A tenant normally holds SEVERAL ids per carrier. `tenant_airlines` already allowed
  that — only `(tenant_id, ref_id)` is unique — so ids are simply many rows sharing an
  `airline_id`, and no migration was needed.

The airline dropdown needs no endpoint here: GET /airlines/ already returns name,
iata_code, iata_numeric_code and contract_year (schemas/airline.py::AirlineRead).
"""
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.airline import Airline
from app.models.lcc_batch_airline_id import LccBatchAirlineId
from app.models.lcc_detailed import LccDetailedBatch
from app.models.statement_batch_airline_id import StatementBatchAirlineId
from app.models.tenant_airline import TenantAirline
from app.models.user import User
from app.schemas.tenant_airline import (
    TenantAirlineBulkCreate, TenantAirlineBulkResult, TenantAirlineBulkUploadResult,
    TenantAirlineCatalogPage, TenantAirlineCreate, TenantAirlineRead,
    TenantAirlineUpdate,
)
from app.services.tenant_airline_catalog import build_catalog

router = APIRouter()


def _scope(current_user: User):
    """Tenant scope — the airline master is shared across the tenant's users,
    matching login_ids.py rather than the per-user scoping the statements use."""
    return TenantAirline.tenant_id == current_user.tenant_id


async def _load(pk: int, db: AsyncSession, current_user: User) -> TenantAirline:
    obj = (await db.execute(
        select(TenantAirline)
        .options(selectinload(TenantAirline.airline))
        .where(TenantAirline.id == pk, _scope(current_user))
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Airline not found in your Airline Master.")
    return obj


async def _airline_or_400(db: AsyncSession, airline_id: int) -> Airline:
    airline = (await db.execute(select(Airline).where(Airline.id == airline_id))).scalar_one_or_none()
    if not airline:
        raise HTTPException(status_code=400, detail=f"Airline id {airline_id} not found in the airline master.")
    return airline


async def _ref_owner(
    db: AsyncSession, current_user: User, ref_id: str, exclude_pk: int | None = None
) -> str | None:
    """The airline already holding `ref_id`, or None when the id is free.

    Returns the name rather than a bool because once a tenant has hundreds of ids,
    "already used" on its own tells the user nothing they can act on.
    """
    q = select(TenantAirline.airline_name).where(
        _scope(current_user), func.lower(TenantAirline.ref_id) == ref_id.lower()
    )
    if exclude_pk is not None:
        q = q.where(TenantAirline.id != exclude_pk)
    # .first(), not .scalar_one_or_none(): airline_name is nullable, and a NULL
    # snapshot would otherwise be indistinguishable from "no such row".
    row = (await db.execute(q)).first()
    return (row[0] or "another airline") if row is not None else None


async def _usage_counts(db: AsyncSession, ta_ids: list[int]) -> dict[int, int]:
    """`{tenant_airline_id: uploaded statements using it}`.

    Three sources, because an id can be declared on an upload in three ways:
      * `lcc_batch_airline_ids` — the SET on an LCC Detailed batch;
      * `lcc_detailed_batch.tenant_airline_id` — that batch's primary column;
      * `statement_batch_airline_ids` — the set on a DI / Divided PNR / Flown Report /
        CTA-BTA upload, which keeps no batch header of its own.

    Counting fewer would report an id that is merely a secondary selection, or one used
    only by the spec-driven types, as unused — and the delete guard below would then let
    the user remove it, silently unlinking it from statements that name it. UNION
    de-duplicates, so an id recorded in two places is still one statement.
    """
    if not ta_ids:
        return {}
    linked = select(
        LccBatchAirlineId.batch_id.label("batch_id"),
        LccBatchAirlineId.tenant_airline_id.label("ta_id"),
    ).where(LccBatchAirlineId.tenant_airline_id.in_(ta_ids))
    primary = select(
        LccDetailedBatch.batch_id.label("batch_id"),
        LccDetailedBatch.tenant_airline_id.label("ta_id"),
    ).where(LccDetailedBatch.tenant_airline_id.in_(ta_ids))
    # batch_id is only unique per slug here, so prefix it — otherwise the impossible
    # collision of a uuid across two types would silently merge two statements into one.
    spec_driven = select(
        (StatementBatchAirlineId.slug + ":" + StatementBatchAirlineId.batch_id).label("batch_id"),
        StatementBatchAirlineId.tenant_airline_id.label("ta_id"),
    ).where(StatementBatchAirlineId.tenant_airline_id.in_(ta_ids))
    everywhere = linked.union(primary, spec_driven).subquery()
    return dict((await db.execute(
        select(everywhere.c.ta_id, func.count()).group_by(everywhere.c.ta_id)
    )).all())


async def _guard_duplicate_ref(
    db: AsyncSession, current_user: User, ref_id: str, exclude_pk: int | None = None
) -> None:
    """The ref id is the selection key at LCC upload, so it must be unique per tenant
    — across airlines, not just within one. Two carriers sharing the id `KT471` would
    render two indistinguishable options in the upload picker. Checked here so the
    user gets a readable 409 instead of a unique-violation 500."""
    owner = await _ref_owner(db, current_user, ref_id, exclude_pk)
    if owner:
        raise HTTPException(status_code=409, detail=f"The id '{ref_id}' is already used by {owner}.")


@router.get("/", response_model=list[TenantAirlineRead])
async def list_tenant_airlines(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The flat list of ids. This is the LCC upload picker's source
    (components/statements/lcc/LccUploadWizard.tsx and LccDetailedView.tsx) — the
    Airline Master screen itself uses /catalog."""
    q = select(TenantAirline).options(selectinload(TenantAirline.airline)).where(_scope(current_user))
    if active is not None:
        q = q.where(TenantAirline.is_active.is_(active))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            TenantAirline.ref_id.ilike(term),
            TenantAirline.airline_name.ilike(term),
            TenantAirline.airline_code.ilike(term),
            TenantAirline.iata_numeric_code.ilike(term),
        ))
    q = q.order_by(TenantAirline.airline_name, TenantAirline.ref_id).offset(skip).limit(limit)
    return (await db.execute(q)).scalars().all()


# ── The Airline Master screen ────────────────────────────────────────────────
# Declared before "/{pk}": FastAPI matches in declaration order, so below it these
# literal paths would bind there and 422. Same trap airlines.py documents.

@router.get("/catalog", response_model=TenantAirlineCatalogPage)
async def list_catalog(
    scope: str = "mine",
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The platform airline master with this tenant's ids on it.

    `scope=mine` (default) lists only airlines the tenant has at least one id for —
    the everyday screen. `scope=all` lists the whole master so the user can find any
    airline and give it an id; those come back with an empty `ids`, which is the
    blank-ID row on screen.
    """
    mine_subq = select(TenantAirline.airline_id).where(_scope(current_user))

    conds = []
    if search and search.strip():
        term = f"%{search.strip()}%"
        conds.append(or_(
            Airline.name.ilike(term),
            Airline.iata_code.ilike(term),
            Airline.iata_numeric_code.ilike(term),
            Airline.icao_code.ilike(term),
            # Searching by one's own id has to find the airline it belongs to —
            # that id is the handle the user actually remembers.
            Airline.id.in_(
                select(TenantAirline.airline_id)
                .where(_scope(current_user), TenantAirline.ref_id.ilike(term))
            ),
        ))

    # `is_active` has a Python-side default but NO server default, so a row written
    # outside the ORM can be NULL. isnot(False) keeps those visible — NULL is not
    # "inactive". An airline the tenant already uses is always listed, active or not.
    all_cond = or_(Airline.is_active.isnot(False), Airline.id.in_(mine_subq))
    mine_cond = Airline.id.in_(mine_subq)

    mine_count = (await db.execute(
        select(func.count()).select_from(Airline).where(*conds, mine_cond)
    )).scalar_one()
    all_count = (await db.execute(
        select(func.count()).select_from(Airline).where(*conds, all_cond)
    )).scalar_one()

    scope_cond = mine_cond if scope == "mine" else all_cond
    total = mine_count if scope == "mine" else all_count

    airlines = (await db.execute(
        select(Airline)
        .where(*conds, scope_cond)
        .order_by(Airline.name)
        .offset(skip).limit(limit)
    )).scalars().all()

    page_ids = [a.id for a in airlines]
    rows: list[TenantAirline] = []
    usage: dict[int, int] = {}
    if page_ids:
        rows = list((await db.execute(
            select(TenantAirline)
            .where(_scope(current_user), TenantAirline.airline_id.in_(page_ids))
        )).scalars().all())
        if rows:
            # One grouped query for the whole page rather than a count per id.
            usage = await _usage_counts(db, [r.id for r in rows])

    return TenantAirlineCatalogPage(
        items=build_catalog(airlines, rows, usage),
        total=total,
        mine_count=mine_count,
        all_count=all_count,
    )


# 200, not 201: partial success is the normal outcome here, and "201 Created" on a
# call where every id was rejected would be a lie. The body says what landed.
@router.post("/bulk", response_model=TenantAirlineBulkResult)
async def create_tenant_airline_ids(
    payload: TenantAirlineBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add several ids for ONE airline in a single save — the normal case, since a
    tenant holds a handful of agent logins per carrier.

    Partial success is deliberate: one duplicate should not discard the other four
    ids the user typed, so failures come back per id for correction.
    """
    airline = await _airline_or_400(db, payload.airline_id)

    # Every id the tenant already holds, fetched once instead of a query per id.
    taken = {
        (ref or "").lower(): (name or "another airline")
        for ref, name in (await db.execute(
            select(TenantAirline.ref_id, TenantAirline.airline_name).where(_scope(current_user))
        )).all()
    }

    created: list[TenantAirline] = []
    errors: list[dict] = []
    seen: set[str] = set()

    for item in payload.ids:
        ref_id = (item.ref_id or "").strip()
        if not ref_id:
            continue
        key = ref_id.lower()
        if key in seen:
            errors.append({"ref_id": ref_id, "error": "Repeated twice in this form."})
            continue
        if key in taken:
            errors.append({"ref_id": ref_id, "error": f"Already used by {taken[key]}."})
            continue
        seen.add(key)

        obj = TenantAirline(
            tenant_id=current_user.tenant_id,
            created_by_id=current_user.id,
            ref_id=ref_id,
            is_active=item.is_active if item.is_active is not None else True,
        )
        obj.apply_master(airline)
        db.add(obj)
        created.append(obj)

    if not created:
        if errors:
            return TenantAirlineBulkResult(created=[], errors=errors)
        raise HTTPException(status_code=400, detail="Enter at least one id for this airline.")

    await db.commit()

    fresh = (await db.execute(
        select(TenantAirline)
        .options(selectinload(TenantAirline.airline))
        .where(TenantAirline.id.in_([o.id for o in created]))
        .order_by(TenantAirline.ref_id)
    )).scalars().all()
    return TenantAirlineBulkResult(created=list(fresh), errors=errors)


def _cell(v) -> str:
    """Read a spreadsheet cell as a clean string. pandas reads empty cells as NaN
    (a truthy float), so guard against it instead of `str(v or "")`."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


# The id column, and the airline column. Aliases matter: the obvious workflow is to
# export the platform master (/airlines/export writes "Code"), add an ID column and
# upload that sheet back.
_ID_COLS = ("ID", "REF_ID", "AIRLINE_REF_ID", "LOGIN_ID")
_CODE_COLS = ("AIRLINE_CODE", "CODE", "IATA_CODE")


def _first(row, names: tuple[str, ...]) -> str:
    for n in names:
        v = _cell(row.get(n))
        if v:
            return v
    return ""


@router.post("/bulk-upload", response_model=TenantAirlineBulkUploadResult)
async def bulk_upload_tenant_airline_ids(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import ids from a spreadsheet — AIRLINE_CODE, ID, ACTIVE.

    Repeat the airline code to give one carrier several ids; that is the point of the
    file. Rows are reported individually rather than aborting the sheet, so a typo in
    one row does not cost the user the other three hundred.
    """
    content = await file.read()
    filename = (file.filename or "").lower()

    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        df.columns = [
            str(c).strip().upper().replace(" ", "_").replace("/", "_").replace("-", "_")
            for c in df.columns
        ]
        df.dropna(how="all", inplace=True)
        return df

    try:
        df = None
        used_header_row = 0
        for header_row in (0, 1, 2):
            try:
                if filename.endswith(".xls"):
                    df_try = pd.read_excel(BytesIO(content), dtype=str, header=header_row)
                else:
                    df_try = pd.read_excel(BytesIO(content), dtype=str, engine="openpyxl", header=header_row)
                df_try = _normalize_columns(df_try)
                cols = set(df_try.columns)
                if cols & set(_ID_COLS) and cols & set(_CODE_COLS):
                    df = df_try
                    used_header_row = header_row
                    break
            except Exception:
                continue

        if df is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing required columns: AIRLINE_CODE and ID. Your header may be on "
                    "a different row (a title row above it, say). "
                    "Required: AIRLINE_CODE, ID  |  Optional: ACTIVE"
                ),
            )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=400,
            detail=f"Cannot parse file: {e}. Make sure it is a valid .xlsx or .xls file.",
        )

    # The platform master, keyed by code — one query, then an in-memory lookup.
    airlines = (await db.execute(select(Airline))).scalars().all()
    by_code: dict[str, Airline] = {}
    for a in airlines:
        if a.iata_code:
            by_code.setdefault(a.iata_code.strip().upper(), a)

    taken = {
        (ref or "").lower(): (name or "another airline")
        for ref, name in (await db.execute(
            select(TenantAirline.ref_id, TenantAirline.airline_name).where(_scope(current_user))
        )).all()
    }

    total = len(df)
    success = 0
    errors: list[str] = []

    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        ref_id = _first(row, _ID_COLS)
        code = _first(row, _CODE_COLS).upper()

        if not ref_id or not code:
            errors.append(f"Row {row_num}: AIRLINE_CODE and ID are both required.")
            continue

        airline = by_code.get(code)
        if not airline:
            errors.append(
                f"Row {row_num}: airline code '{code}' is not in the airline master — skipped."
            )
            continue

        key = ref_id.lower()
        if key in taken:
            errors.append(f"Row {row_num}: the id '{ref_id}' is already used by {taken[key]} — skipped.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            obj = TenantAirline(
                tenant_id=current_user.tenant_id,
                created_by_id=current_user.id,
                ref_id=ref_id,
                is_active=is_active,
            )
            obj.apply_master(airline)
            db.add(obj)
            await db.commit()
            # Claim it immediately so a duplicate later in the same file is caught.
            taken[key] = airline.name
            success += 1
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return TenantAirlineBulkUploadResult(
        total=total, success=success, failed=total - success, errors=errors,
    )


@router.get("/template")
async def download_tenant_airline_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Airline IDs"
    ws.append(["AIRLINE_CODE", "ID", "ACTIVE"])
    # Indigo three times on purpose: the sample has to show that repeating the code
    # is how you give one airline several ids.
    ws.append(["6E", "6E-DEL-88213", "yes"])
    ws.append(["6E", "6E-BOM-11902", "yes"])
    ws.append(["6E", "6E-MAA-44510", "yes"])
    ws.append(["AI", "KTDEL471", "yes"])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="airline_id_template.xlsx"'},
    )


@router.post("/", response_model=TenantAirlineRead, status_code=status.HTTP_201_CREATED)
async def create_tenant_airline(
    payload: TenantAirlineCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ref_id = (payload.ref_id or "").strip()
    if not ref_id:
        raise HTTPException(status_code=400, detail="An id for this airline is required.")
    airline = await _airline_or_400(db, payload.airline_id)
    await _guard_duplicate_ref(db, current_user, ref_id)

    obj = TenantAirline(
        tenant_id=current_user.tenant_id,
        created_by_id=current_user.id,
        ref_id=ref_id,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    obj.apply_master(airline)
    db.add(obj)
    await db.commit()
    return await _load(obj.id, db, current_user)


@router.get("/{pk}", response_model=TenantAirlineRead)
async def get_tenant_airline(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await _load(pk, db, current_user)


@router.patch("/{pk}", response_model=TenantAirlineRead)
async def update_tenant_airline(
    pk: int,
    payload: TenantAirlineUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(pk, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "ref_id" in data:
        ref_id = (data["ref_id"] or "").strip()
        if not ref_id:
            raise HTTPException(status_code=400, detail="An id for this airline is required.")
        await _guard_duplicate_ref(db, current_user, ref_id, exclude_pk=pk)
        obj.ref_id = ref_id

    if "airline_id" in data and data["airline_id"] is not None:
        # Re-point at a different master row: re-snapshot everything with it.
        obj.apply_master(await _airline_or_400(db, data["airline_id"]))

    if "is_active" in data and data["is_active"] is not None:
        obj.is_active = data["is_active"]

    await db.commit()
    return await _load(obj.id, db, current_user)


@router.delete("/{pk}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_airline(
    pk: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _load(pk, db, current_user)

    # Deleting would silently strip this id from statements already uploaded against
    # it — the batch FK is ON DELETE SET NULL and the link FK is CASCADE, so neither
    # stops it at the database. Refuse here instead and say how many.
    in_use = (await _usage_counts(db, [pk])).get(pk, 0)
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{obj.ref_id}' is used by {in_use} uploaded statement(s). "
                "Mark it inactive instead — that hides it from new uploads and keeps "
                "the airline on the statements already imported."
            ),
        )

    await db.delete(obj)
    await db.commit()
