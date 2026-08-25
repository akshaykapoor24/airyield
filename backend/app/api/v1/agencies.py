from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import StreamingResponse

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.india_tax import (
    STATE_NAMES, canonical_state, normalise as norm_tax_id, tax_id_error,
)
from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import (
    AGENCY_CHANNELS, CHANNELS, DEFAULT_BRANCH_CODE, Agency, norm_channel, scope_covers,
)
from app.models.agency_entity import AgencyEntity
from app.models.agency_ledger import AgencyLedger
from app.models.agency_login_id import AgencyLoginId
from app.models.agency_terms import AgencyTerms
from app.models.deal import Deal
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.agency import (
    AGENCY_TYPES, BILLING_CYCLES,
    AgencyCreate, AgencyUpdate, AgencyRead, AgencyOverviewRow, AgencyTermsInput,
    AgencyTermsSummary, AgencyFromSuppliers, AgencyFromSuppliersResult, BulkUploadResult,
)

router = APIRouter()


def _cell(v) -> str:
    """Read a spreadsheet cell as a clean string. pandas reads empty cells as
    NaN (a truthy float), so guard against it instead of `str(v or "")`."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()


def _scope(current_user: User):
    """User scope — agencies are private to their owner."""
    return Agency.user_id == current_user.id


async def _get_scoped_agency(agency_id: int, db: AsyncSession, current_user: User) -> Agency:
    result = await db.execute(select(Agency).where(Agency.id == agency_id, _scope(current_user)))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Agency not found")
    return obj


async def _channel_taken(
    db: AsyncSession, current_user: User, name: str, branch_code: str, channel: str,
    exclude_id: int | None = None,
) -> str | None:
    """Is this vendor's branch already onboarded ON THIS CHANNEL? Returns why, or None.

    Neither name nor (name, branch) is enough on its own. Lords Delhi and Lords
    Mumbai are two agencies; so are Lords Delhi GDS and Lords Delhi LCC, which is
    the whole point of onboarding a two-channel agency twice. Mirrors
    `uq_agencies_user_name_branch_channel`.

    Checked in Python rather than as a fourth WHERE clause because a legacy BOTH
    row covers this channel without equalling it — `scope_covers` is the test, and
    a plain `channels == channel` comparison would let a GDS row be added under a
    BOTH row that already bills its GDS tickets.
    """
    q = select(Agency.id, Agency.channels).where(
        _scope(current_user),
        func.lower(Agency.name) == name.lower(),
        func.lower(Agency.branch_code) == branch_code.lower(),
    )
    if exclude_id is not None:
        q = q.where(Agency.id != exclude_id)

    for _id, existing in (await db.execute(q)).all():
        if not scope_covers(existing, channel):
            continue
        if existing == "BOTH":
            return (
                f"'{name}' branch '{branch_code}' is already onboarded as one agency covering "
                f"both channels, which includes {channel}."
            )
        return f"'{name}' branch '{branch_code}' is already onboarded on {channel}."
    return None


def _num(v) -> float | None:
    """Parse a money / percent value from JSON or a spreadsheet cell."""
    s = _cell(v)
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _validated_terms(values: dict) -> dict:
    """Validate ONE channel's commercial arrangement, or refuse it.

    The version this replaces silently coerced an unrecognised agency_type or
    billing_cycle to None and wiped the other four fields with it. That is exactly
    why "terms are mandatory" could not be enforced anywhere: a typo produced an
    agency with no arrangement rather than an error. Everything here 400s, and
    every message names the channel, because on a BOTH agency "pick cash or
    credit" does not say which half of the form is wrong.

      cash   -> deposit_amount is required and becomes the opening ledger topup;
                credit_limit is stored NULL, because a cash agency's limit IS the
                money on deposit and account_summary derives it from the ledger.
                (The old code stored limit = deposit here while switch_terms
                stored NULL for the same column — two writers, two answers.)
      credit -> credit_limit is required; deposit and usage are cleared.

    usage_percent is deliberately NOT capped at 100 — 110 means "warn once they
    are 10% past the deposit".
    """
    channel = norm_channel(values.get("channel"))
    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")

    atype = (_cell(values.get("agency_type")) or "").lower() or None
    if atype not in AGENCY_TYPES:
        raise HTTPException(status_code=400, detail=f"{channel} agency type must be 'cash' or 'credit'.")
    cycle = (_cell(values.get("billing_cycle")) or "").lower() or None
    if cycle not in BILLING_CYCLES:
        raise HTTPException(
            status_code=400,
            detail=f"{channel} billing cycle must be one of {sorted(BILLING_CYCLES)}.",
        )

    limit = _num(values.get("credit_limit"))
    deposit = _num(values.get("deposit_amount"))
    usage = _num(values.get("usage_percent"))

    for label, amount in (("Limit", limit), ("Deposit", deposit), ("Usage %", usage)):
        if amount is not None and amount < 0:
            raise HTTPException(status_code=400, detail=f"{channel} {label} cannot be negative.")

    if atype == "cash":
        if deposit is None:
            raise HTTPException(status_code=400, detail=f"{channel} is cash — enter the deposit amount.")
        limit = None
    else:
        if limit is None:
            raise HTTPException(status_code=400, detail=f"{channel} is credit — enter the credit limit.")
        deposit = None
        usage = None

    return {
        "channel": channel,
        "agency_type": atype,
        "credit_limit": limit,
        "deposit_amount": deposit,
        "usage_percent": usage,
        "billing_cycle": cycle,
    }


def _validated_channels(raw) -> tuple[str, list[str]]:
    """('GDS', ['GDS']) — the declared channel and the arrangement it needs.

    BOTH IS REFUSED HERE and the message says what to do instead, because an
    agency working both channels is now two rows rather than one row with two
    arrangements. Existing BOTH rows keep working; you just cannot make another.
    The tuple shape is kept so callers still read as "channel + the terms it
    needs" — the list is always one long now.
    """
    scope = norm_channel(raw)
    if scope == "BOTH":
        raise HTTPException(
            status_code=400,
            detail="An agency is onboarded per channel — add it once on GDS and again on LCC, "
                   "so each has its own terms, deposit and balance.",
        )
    if scope not in AGENCY_CHANNELS:
        raise HTTPException(status_code=400, detail=f"channels must be one of {sorted(AGENCY_CHANNELS)}.")
    return scope, [scope]


def _terms_for_scope(scope: str, required: list[str], rows: list[dict]) -> list[dict]:
    """Check the submitted arrangements cover the declared channel exactly."""
    seen = [r["channel"] for r in rows]
    if len(seen) != len(set(seen)):
        raise HTTPException(status_code=400, detail="Two arrangements were sent for the same channel.")
    missing = [c for c in required if c not in seen]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {scope} — {', '.join(missing)} terms are missing.",
        )
    extra = [c for c in seen if c not in required]
    if extra:
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {scope} — remove the {', '.join(extra)} terms.",
        )
    return rows


def _validated_state(raw) -> str:
    """The state, as one of the names a GSTIN can be checked against.

    MANDATORY, and mandatory because of the GSTIN rather than for its own sake: a
    GSTIN's first two characters ARE the state, so without knowing the state there
    is nothing to check them against and a Delhi GSTIN typed against a Maharashtra
    agency reads as valid. Accepted spellings are generous (case, punctuation,
    "Orissa" for Odisha) but the value must resolve to a real state — free text
    that resolves to nothing would defeat the check it exists for.
    """
    state = _cell(raw)
    if not state:
        raise HTTPException(
            status_code=400,
            detail="State is required — it is what a GSTIN's first two characters are checked against.",
        )
    resolved = canonical_state(state)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail=f"'{state}' is not an Indian state or union territory we can match a GST code to. "
                   f"Use one of: {', '.join(STATE_NAMES[:6])}…",
        )
    return resolved


def _validated_tax_ids(state: str, pan_raw, gst_raw, registered_raw) -> tuple[bool, str | None, str | None]:
    """(gst_registered, gst_number, pan_number), checked against each other.

    THE FOUR CHECKS, all in app.core.india_tax: PAN format and holder type; GSTIN
    format; GSTIN's state code against `state`; GSTIN's embedded PAN against the
    PAN field; and the mod-36 check digit. Nothing here calls out to a GST portal —
    every one of these is answerable from what is already on the form, which is why
    the form asks for state and PAN before it offers the GSTIN box.

    An UNREGISTERED agency stores no GSTIN. Clearing it rather than saving what was
    sent is deliberate: the two facts have to agree, and "not registered" is the
    one the user just asserted.
    """
    registered = bool(registered_raw) if registered_raw is not None else bool(_cell(gst_raw))
    pan = norm_tax_id(_cell(pan_raw))
    gst = norm_tax_id(_cell(gst_raw)) if registered else None

    if registered and not gst:
        raise HTTPException(
            status_code=400,
            detail="This agency is marked GST registered — enter its GSTIN, or mark it unregistered.",
        )

    problem = tax_id_error(gst, pan, state)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    return registered, gst, pan


async def _current_terms_map(db: AsyncSession, agency_ids: list[int]) -> dict[int, list[AgencyTermsSummary]]:
    """Every listed agency's open arrangements, in two queries rather than 2N.

    `deposit_paid` comes from the ledger because deposits are never stored on
    terms — under a ledger a cash agency's limit IS its money in.
    """
    if not agency_ids:
        return {}

    rows = (await db.execute(
        select(AgencyTerms)
        .where(AgencyTerms.agency_id.in_(agency_ids), AgencyTerms.effective_to.is_(None))
        .order_by(AgencyTerms.agency_id, AgencyTerms.channel)
    )).scalars().all()

    paid = {
        (r[0], r[1]): float(r[2] or 0)
        for r in (await db.execute(
            select(
                AgencyLedger.terms_id,
                AgencyLedger.channel,
                func.coalesce(func.sum(AgencyLedger.amount), 0),
            )
            .where(AgencyLedger.agency_id.in_(agency_ids), AgencyLedger.amount > 0)
            .group_by(AgencyLedger.terms_id, AgencyLedger.channel)
        )).all()
    }

    out: dict[int, list[AgencyTermsSummary]] = {}
    for t in rows:
        out.setdefault(t.agency_id, []).append(AgencyTermsSummary(
            channel=t.channel,
            agency_type=t.agency_type,
            billing_cycle=t.billing_cycle,
            credit_limit=float(t.credit_limit) if t.credit_limit is not None else None,
            usage_percent=float(t.usage_percent) if t.usage_percent is not None else None,
            terms_id=t.id,
            effective_from=t.effective_from,
            cycle_anchor_date=t.cycle_anchor_date,
            deposit_paid=paid.get((t.id, t.channel), 0.0),
        ))
    return out


async def _with_terms(db: AsyncSession, agencies: list[Agency]) -> list[AgencyRead]:
    terms = await _current_terms_map(db, [a.id for a in agencies])
    out = []
    for a in agencies:
        read = AgencyRead.model_validate(a)
        read.terms = terms.get(a.id, [])
        out.append(read)
    return out


def _open_terms_rows(
    agency: Agency, current_user: User, rows: list[dict], today: date
) -> list[AgencyTerms]:
    """One AgencyTerms per validated arrangement. Caller flushes and posts deposits."""
    return [
        AgencyTerms(
            agency_id=agency.id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            channel=t["channel"],
            effective_from=today,
            agency_type=t["agency_type"],
            credit_limit=Decimal(str(t["credit_limit"])) if t["credit_limit"] is not None else None,
            usage_percent=Decimal(str(t["usage_percent"])) if t["usage_percent"] is not None else None,
            billing_cycle=t["billing_cycle"],
            cycle_anchor_date=today,
            note="Opening terms",
            created_by_id=current_user.id,
        )
        for t in rows
    ]


def _opening_deposits(
    agency: Agency, current_user: User, rows: list[dict], terms: list[AgencyTerms], today: date
) -> list[AgencyLedger]:
    """The cash channels' first payments.

    A deposit entered on the add form is money that arrived, not a configuration
    value, so it goes on the ledger and the limit is read back from there.
    """
    by_channel = {t.channel: t for t in terms}
    out = []
    for t in rows:
        if t["agency_type"] != "cash" or not t["deposit_amount"]:
            continue
        row = by_channel.get(t["channel"])
        out.append(AgencyLedger(
            agency_id=agency.id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            terms_id=row.id if row else None,
            channel=t["channel"],
            entry_date=today,
            entry_type="topup",
            amount=Decimal(str(t["deposit_amount"])),
            note=f"Opening deposit ({t['channel']})",
            created_by_id=current_user.id,
        ))
    return out


def _valid_or_none(raw, *, is_gst: bool) -> str | None:
    """A tax id copied from the master, kept only if it stands up on its own.

    No state is available here, so this is format (and, for a GSTIN, check digit)
    only — the state and PAN cross-checks happen when someone edits the agency.
    A value that fails is dropped rather than raised on: bulk add would otherwise
    fail a whole batch over one bad cell in a master nobody here maintains.
    """
    value = norm_tax_id(raw)
    if not value:
        return None
    problem = tax_id_error(value, None) if is_gst else tax_id_error(None, value)
    return None if problem else value


def _from_supplier(supplier: Supplier, current_user: User, channels: str) -> Agency:
    """Build a new Agency by copying one supplier BRANCH (add-time snapshot).

    Phone and email fall back to the supplier DIRECTORY columns: across the whole
    master `contact_phone` / `contact_email` are empty and the real values live in
    `telephone_mobile` / `email_address`, so copying only the former filled nothing.

    STATE, GST AND PAN ARE LEFT BLANK. The master has no state at all (its nearest
    column, `region_chapter`, holds IATA chapters like "WESTERN REGION") and its
    gst/pan columns are empty across the file. Since a GSTIN can only be checked
    against a state, copying one without the other would store a number nothing
    has verified — so a bulk-added agency starts with all three empty and the Add
    Agency form's checks apply the moment someone edits it. Anything the master
    does happen to hold is copied only if it validates on its own.

    `branch_code` copies `suppliers.code`, which is unique across the master, and
    is part of what keeps two branches of one vendor apart. It is copied rather
    than joined for the same reason as every other field here: deleting a supplier
    must not be able to orphan or collide an agency.
    """
    return Agency(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=(supplier.name or "").strip(),
        supplier_id=supplier.id,
        branch_code=(supplier.code or "").strip() or DEFAULT_BRANCH_CODE,
        branch_name=(supplier.branch or supplier.city or None),
        # address_1..3 are one postal address split across three columns, not
        # alternatives. `state` has no source in the master — see the migration.
        address=", ".join(
            p.strip() for p in (supplier.address_1, supplier.address_2, supplier.address_3)
            if p and p.strip()
        ) or None,
        city=supplier.city,
        region_chapter=supplier.region_chapter,
        gst_registered=bool(_valid_or_none(supplier.gst_number, is_gst=True)),
        gst_number=_valid_or_none(supplier.gst_number, is_gst=True),
        pan_number=_valid_or_none(supplier.pan_number, is_gst=False),
        contact_phone=supplier.contact_phone or supplier.telephone_mobile,
        contact_email=supplier.contact_email or supplier.email_address or supplier.alternate_email_id,
        notes=supplier.notes,
        channels=channels,
        is_active=True,
    )


@router.get("/", response_model=list[AgencyRead])
async def list_agencies(
    skip: int = 0,
    limit: int = 500,
    search: Optional[str] = None,
    channel: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = select(Agency).where(_scope(current_user))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Agency.name.ilike(term),
            Agency.branch_name.ilike(term),
            Agency.branch_code.ilike(term),
            Agency.city.ilike(term),
            Agency.gst_number.ilike(term),
            Agency.pan_number.ilike(term),
        ))
    ch = norm_channel(channel)
    if ch is not None:
        if ch not in CHANNELS:
            raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
        q = q.where(or_(Agency.channels == ch, Agency.channels == "BOTH"))
    # Branch second, so a vendor's branches sit together under its name.
    q = q.order_by(Agency.name, Agency.branch_code).offset(skip).limit(limit)
    return await _with_terms(db, list((await db.execute(q)).scalars().all()))


@router.get("/overview", response_model=list[AgencyOverviewRow])
async def agencies_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One row per agency with its entity count and login-id count (drill-down source)."""
    ent_sub = (
        select(AgencyEntity.agency_id, func.count().label("c"))
        .where(AgencyEntity.user_id == current_user.id)
        .group_by(AgencyEntity.agency_id)
        .subquery()
    )
    lid_sub = (
        select(AgencyLoginId.agency_id, func.count().label("c"))
        .where(AgencyLoginId.user_id == current_user.id)
        .group_by(AgencyLoginId.agency_id)
        .subquery()
    )
    q = (
        select(
            Agency.id,
            Agency.name,
            Agency.branch_name,
            Agency.channels,
            func.coalesce(ent_sub.c.c, 0),
            func.coalesce(lid_sub.c.c, 0),
        )
        .outerjoin(ent_sub, ent_sub.c.agency_id == Agency.id)
        .outerjoin(lid_sub, lid_sub.c.agency_id == Agency.id)
        .where(_scope(current_user))
        .order_by(Agency.name, Agency.branch_code)
    )
    rows = (await db.execute(q)).all()
    return [
        AgencyOverviewRow(
            id=r[0], name=r[1], branch_name=r[2], channels=r[3],
            entity_count=r[4], login_id_count=r[5],
        )
        for r in rows
    ]


@router.post("/", response_model=AgencyRead, status_code=status.HTTP_201_CREATED)
async def create_agency(
    payload: AgencyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Onboard one branch of a vendor on one channel, with a complete arrangement.

    ONE CHANNEL PER CALL. A vendor that works both is posted twice and becomes two
    rows, so each channel carries its own terms, deposit, ledger and invoices — see
    _validated_channels, which refuses BOTH and says so.

    Everything lands in ONE transaction — agency, its terms row, and the opening
    deposit. The version this replaces committed twice, so a failure between them
    left an agency with terms and no money in.
    """
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required.")

    scope, required = _validated_channels(payload.channels)

    branch_code = (payload.branch_code or "").strip() or DEFAULT_BRANCH_CODE
    clash = await _channel_taken(db, current_user, name, branch_code, scope)
    if clash:
        raise HTTPException(status_code=400, detail=clash)

    # State first: the GSTIN check needs it, and refusing the whole create over a
    # missing state before touching money is cheaper than unwinding one.
    state = _validated_state(payload.state)
    gst_registered, gst_number, pan_number = _validated_tax_ids(
        state, payload.pan_number, payload.gst_number, payload.gst_registered,
    )

    rows = _terms_for_scope(
        scope, required,
        [_validated_terms(t.model_dump()) for t in (payload.terms or [])],
    )

    today = date.today()
    agency = Agency(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        name=name,
        supplier_id=payload.supplier_id,
        branch_code=branch_code,
        branch_name=(payload.branch_name or "").strip() or None,
        address=(payload.address or "").strip() or None,
        state=state,
        city=(payload.city or "").strip() or None,
        region_chapter=(payload.region_chapter or "").strip() or None,
        gst_registered=gst_registered,
        gst_number=gst_number,
        pan_number=pan_number,
        contact_phone=(payload.contact_phone or "").strip() or None,
        contact_email=(payload.contact_email or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        channels=scope,
        is_active=payload.is_active if payload.is_active is not None else True,
    )
    db.add(agency)
    await db.flush()   # need agency.id before the opening terms rows

    # Opening every arrangement here (rather than lazily) means the switch guard
    # always has a period to close, and the ledger always has a terms_id to file
    # entries under.
    terms = _open_terms_rows(agency, current_user, rows, today)
    db.add_all(terms)
    await db.flush()   # need terms ids for the deposit entries

    db.add_all(_opening_deposits(agency, current_user, rows, terms, today))
    await db.commit()
    await db.refresh(agency)
    return (await _with_terms(db, [agency]))[0]


@router.post("/from-suppliers", response_model=AgencyFromSuppliersResult)
async def create_agencies_from_suppliers(
    payload: AgencyFromSuppliers,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Copy several supplier BRANCHES into new agencies, on identical terms.

    The same arrangement is applied to every one of them, which is the honest
    shape: you cannot bulk-onboard forty agencies without saying how they pay, and
    creating them termless is precisely the state that let the list screen show
    "Cash" while the account page reported no terms at all.

    Idempotent — a supplier branch already onboarded ON THIS CHANNEL is skipped
    rather than erroring, so re-running a partial batch is safe. Running the batch
    again on the OTHER channel is not a re-run: it onboards the same branches a
    second time, which is how a set of agencies comes to work both.

    State, GST and PAN land empty here — see _from_supplier for why the master
    cannot supply them.
    """
    ids = list(dict.fromkeys(payload.supplier_ids or []))  # de-dup, keep order
    if not ids:
        raise HTTPException(status_code=400, detail="supplier_ids is required.")

    scope, required = _validated_channels(payload.channels)
    rows = _terms_for_scope(
        scope, required,
        [_validated_terms(t.model_dump()) for t in (payload.terms or [])],
    )

    suppliers = (await db.execute(select(Supplier).where(Supplier.id.in_(ids)))).scalars().all()
    by_id = {s.id: s for s in suppliers}

    # (name, branch_code) -> the channels already onboarded for it, lower-cased.
    # Keyed on the pair rather than the name alone — a second BRANCH of an already
    # onboarded vendor is a new agency, not a duplicate — and holding the channels
    # rather than a bare presence flag, because the same branch on the OTHER
    # channel is also a new agency. A legacy BOTH row covers whatever is asked for,
    # which is why the membership test goes through `scope_covers`.
    existing: dict[tuple[str, str], set[str]] = {}
    for n, b, ch in (await db.execute(
        select(Agency.name, Agency.branch_code, Agency.channels).where(_scope(current_user))
    )).all():
        existing.setdefault((n.lower(), (b or "").lower()), set()).add(ch)

    today = date.today()
    created: list[Agency] = []
    skipped = 0
    for sid in ids:
        s = by_id.get(sid)
        if s is None:
            skipped += 1
            continue
        name = (s.name or "").strip()
        branch = (s.code or "").strip() or DEFAULT_BRANCH_CODE
        key = (name.lower(), branch.lower())
        if not name or any(scope_covers(ch, scope) for ch in existing.get(key, ())):
            skipped += 1
            continue
        agency = _from_supplier(s, current_user, scope)
        db.add(agency)
        created.append(agency)
        existing.setdefault(key, set()).add(scope)

    if created:
        await db.flush()   # ids for the terms rows
        for a in created:
            terms = _open_terms_rows(a, current_user, rows, today)
            db.add_all(terms)
            await db.flush()   # terms ids for the deposits
            db.add_all(_opening_deposits(a, current_user, rows, terms, today))
        await db.commit()
        for a in created:
            await db.refresh(a)

    return AgencyFromSuppliersResult(
        created=len(created),
        skipped=skipped,
        agencies=await _with_terms(db, created),
    )


@router.post("/bulk-upload", response_model=BulkUploadResult)
async def bulk_upload_agencies(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    filename = (file.filename or "").lower()
    required = {"NAME", "CHANNELS"}

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
        last_missing = None
        for header_row in (0, 1, 2):
            try:
                if filename.endswith(".xls"):
                    df_try = pd.read_excel(BytesIO(content), dtype=str, header=header_row)
                else:
                    df_try = pd.read_excel(BytesIO(content), dtype=str, engine="openpyxl", header=header_row)
                df_try = _normalize_columns(df_try)
                missing = required - set(df_try.columns)
                last_missing = missing
                if not missing:
                    df = df_try
                    used_header_row = header_row
                    break
            except Exception:
                continue

        if df is None:
            detail = (
                "Missing required columns: NAME, CHANNELS. Check that the header is in the first few rows."
                if last_missing is None else
                f"Missing required columns: {sorted(last_missing)}. Required: NAME, CHANNELS"
            )
            # A sheet from the old template has AGENCY_TYPE and no CHANNELS. Say so
            # rather than letting the user guess which column changed.
            if last_missing and "CHANNELS" in last_missing:
                detail += (
                    " — terms are now per channel. Download the new template: CHANNELS plus"
                    " GDS_TYPE / GDS_LIMIT / GDS_DEPOSIT / GDS_USAGE_PCT / GDS_BILLING_CYCLE"
                    " and the LCC_ equivalents, instead of the single AGENCY_TYPE / LIMIT /"
                    " DEPOSIT / USAGE_PCT / BILLING_CYCLE."
                )
            raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=f"Cannot parse file: {e}. Ensure it is a valid .xlsx or .xls file.")

    total = len(df)
    success = 0
    errors: list[str] = []

    today = date.today()
    for i, row in df.iterrows():
        row_num = i + used_header_row + 2
        name = _cell(row.get("NAME"))
        if not name:
            errors.append(f"Row {row_num}: NAME is required.")
            continue

        active_raw = _cell(row.get("ACTIVE")).lower()
        is_active = active_raw not in ("0", "no", "false", "inactive", "n")

        try:
            scope, required_channels = _validated_channels(row.get("CHANNELS"))
            branch_code = _cell(row.get("BRANCH_CODE")) or DEFAULT_BRANCH_CODE
            clash = await _channel_taken(db, current_user, name, branch_code, scope)
            if clash:
                errors.append(f"Row {row_num}: {clash} Skipped.")
                continue

            # Same rules as the Add Agency form — a sheet is not a way around them.
            # GST_REGISTERED is optional: a row that leaves it blank but fills GST
            # is registered, which is what the old template's rows meant.
            state = _validated_state(row.get("STATE"))
            registered_raw = _cell(row.get("GST_REGISTERED")).lower()
            gst_registered, gst_number, pan_number = _validated_tax_ids(
                state,
                row.get("PAN"),
                row.get("GST"),
                (registered_raw in ("1", "yes", "true", "y", "registered")) if registered_raw else None,
            )

            # One block of columns per channel, read only for the channel the row
            # declares — an LCC row leaves the GDS_ columns blank.
            rows_terms = _terms_for_scope(scope, required_channels, [
                _validated_terms({
                    "channel": ch,
                    "agency_type": row.get(f"{ch}_TYPE"),
                    "credit_limit": row.get(f"{ch}_LIMIT"),
                    "deposit_amount": row.get(f"{ch}_DEPOSIT"),
                    "usage_percent": row.get(f"{ch}_USAGE_PCT"),
                    "billing_cycle": row.get(f"{ch}_BILLING_CYCLE"),
                })
                for ch in required_channels
            ])

            agency = Agency(
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                name=name,
                branch_code=branch_code,
                branch_name=_cell(row.get("BRANCH_NAME")) or None,
                address=_cell(row.get("ADDRESS")) or None,
                state=state,
                city=_cell(row.get("CITY")) or None,
                region_chapter=_cell(row.get("REGION")) or None,
                gst_registered=gst_registered,
                gst_number=gst_number,
                pan_number=pan_number,
                contact_phone=_cell(row.get("PHONE")) or None,
                contact_email=_cell(row.get("EMAIL")) or None,
                notes=_cell(row.get("NOTES")) or None,
                channels=scope,
                is_active=is_active,
            )
            db.add(agency)
            await db.flush()
            terms = _open_terms_rows(agency, current_user, rows_terms, today)
            db.add_all(terms)
            await db.flush()
            db.add_all(_opening_deposits(agency, current_user, rows_terms, terms, today))
            await db.commit()
            success += 1
        except HTTPException as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e.detail}")
        except Exception as e:
            await db.rollback()
            errors.append(f"Row {row_num}: {e}")

    return BulkUploadResult(total=total, success=success, failed=total - success, errors=errors)


@router.get("/template")
async def download_agency_template():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Agency Template"
    # ONE ROW IS ONE AGENCY ON ONE CHANNEL. CHANNELS is GDS or LCC — never BOTH.
    # A vendor branch that works both gets TWO rows, as the first two below show,
    # so each channel keeps its own terms, deposit and balance.
    #
    # One block of terms columns per channel; a row fills only the block its
    # CHANNELS value declares and leaves the other blank.
    #   cash   -> DEPOSIT and USAGE_PCT; LIMIT is left blank (a cash limit IS the
    #             deposit, read back from the ledger)
    #   credit -> LIMIT only
    #
    # STATE IS REQUIRED on every row — the GSTIN's first two characters are checked
    # against it (07 is Delhi, 27 is Maharashtra), and characters 3-12 against PAN.
    # GST_REGISTERED may be left blank: a row with a GST is taken as registered.
    ws.append([
        "NAME", "BRANCH_CODE", "BRANCH_NAME", "ADDRESS", "STATE", "CITY", "REGION",
        "PAN", "GST_REGISTERED", "GST",
        "PHONE", "EMAIL", "NOTES", "CHANNELS",
        "GDS_TYPE", "GDS_LIMIT", "GDS_DEPOSIT", "GDS_USAGE_PCT", "GDS_BILLING_CYCLE",
        "LCC_TYPE", "LCC_LIMIT", "LCC_DEPOSIT", "LCC_USAGE_PCT", "LCC_BILLING_CYCLE",
        "ACTIVE",
    ])
    # The same branch twice — cash on GDS (it books on our IATA stock, so it pays
    # first) and credit on LCC. Identical identity, two agencies, two balances.
    ws.append([
        "Lords Travels", "DEL", "Delhi", "12 Connaught Place", "Delhi", "NEW DELHI", "NORTHERN REGION",
        "AAPFU0939F", "yes", "07AAPFU0939F1ZX", "9876543210", "ops@lords.com", "", "GDS",
        "cash", "", "10000000", "90", "monthly",
        "", "", "", "", "",
        "yes",
    ])
    ws.append([
        "Lords Travels", "DEL", "Delhi", "12 Connaught Place", "Delhi", "NEW DELHI", "NORTHERN REGION",
        "AAPFU0939F", "yes", "07AAPFU0939F1ZX", "9876543210", "ops@lords.com", "", "LCC",
        "", "", "", "", "",
        "credit", "5000000", "", "", "fortnightly",
        "yes",
    ])
    # The same vendor's other branch — a different state, so a different GSTIN
    # against the same PAN. One legal entity, one GSTIN per state it registers in.
    ws.append([
        "Lords Travels", "BOM", "Mumbai", "4 Nariman Point", "Maharashtra", "MUMBAI", "WESTERN REGION",
        "AAPFU0939F", "yes", "27AAPFU0939F1ZV", "9876500001", "bom@lords.com", "", "GDS",
        "credit", "3000000", "", "", "monthly",
        "", "", "", "", "",
        "yes",
    ])
    # Not GST registered — GST_REGISTERED is "no" and the GST column stays empty.
    ws.append([
        "Aadesh Travels", "MAIN", "", "", "Delhi", "NEW DELHI", "NORTHERN REGION",
        "AACCA1234K", "no", "", "9876500000", "ops@aadesh.com", "", "LCC",
        "", "", "", "", "",
        "credit", "5000000", "", "", "weekly",
        "yes",
    ])

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="agency_template.xlsx"'},
    )


@router.get("/{agency_id}", response_model=AgencyRead)
async def get_agency(
    agency_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _get_scoped_agency(agency_id, db, current_user)
    return (await _with_terms(db, [agency]))[0]


@router.patch("/{agency_id}", response_model=AgencyRead)
async def update_agency(
    agency_id: int,
    payload: AgencyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Identity only. Money and branch move through their own guarded endpoints.

    Terms used to be patchable here, and that produced two bugs worth naming so
    nobody puts them back: this handler could open a terms period without posting
    the deposit that came with it (so the balance read zero), and it wrote
    `credit_limit = deposit_amount` for cash while /switch wrote NULL for the same
    column. Both are gone because the field is gone.

    STATE AND THE TAX IDS ARE RE-CHECKED HERE, as a set. They cannot be validated
    one at a time — a GSTIN is only right relative to a state and a PAN — so a
    PATCH touching any of the three is checked against the stored values of the
    other two. That does mean editing a row saved before these checks existed
    forces its state and GSTIN to be made consistent, which is the point.
    """
    obj = await _get_scoped_agency(agency_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)

    for field, endpoint in (
        ("channels", "POST /agencies/{id}/channels/open or /channels/close"),
        ("branch_code", "a new agency — a branch is a separate account"),
        ("agency_type", "POST /agencies/{id}/switch"),
    ):
        if field in data:
            raise HTTPException(
                status_code=409,
                detail=f"'{field}' cannot be changed here — use {endpoint}.",
            )

    if "name" in data:
        new_name = (data["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="name cannot be empty.")
        clash = await _channel_taken(
            db, current_user, new_name, obj.branch_code, obj.channels, exclude_id=obj.id,
        )
        if clash:
            raise HTTPException(status_code=400, detail=clash)
        data["name"] = new_name

    if {"state", "gst_number", "pan_number", "gst_registered"} & data.keys():
        sent = lambda field, stored: data[field] if field in data else stored  # noqa: E731
        # `gst_registered` falls back to None — not to the stored flag — when a
        # GSTIN is being set without one, so _validated_tax_ids infers it from the
        # value rather than dropping the number because the row was last saved
        # unregistered.
        registered = (
            data["gst_registered"] if "gst_registered" in data
            else None if "gst_number" in data
            else obj.gst_registered
        )
        data["state"] = _validated_state(sent("state", obj.state))
        data["gst_registered"], data["gst_number"], data["pan_number"] = _validated_tax_ids(
            data["state"],
            sent("pan_number", obj.pan_number),
            sent("gst_number", obj.gst_number),
            registered,
        )

    for field, value in data.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return (await _with_terms(db, [obj]))[0]


@router.delete("/{agency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agency(
    agency_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    obj = await _get_scoped_agency(agency_id, db, current_user)

    # The FK cascade would take the ledger with it. Deposits, receipts and
    # invoices are financial history — deactivate the agency instead.
    entries = (await db.execute(
        select(func.count()).select_from(AgencyLedger).where(AgencyLedger.agency_id == agency_id)
    )).scalar() or 0
    if entries:
        raise HTTPException(
            status_code=409,
            detail=f"This agency has {entries} payment entries and cannot be deleted. "
                   "Mark it inactive instead — deleting it would destroy its account history.",
        )

    # deals.agency_id is ON DELETE RESTRICT, so without this the delete would fail
    # deep in the driver with an unreadable FK error. It is RESTRICT rather than
    # SET NULL because nulling the id would break the deal's own scope CHECK.
    deals_named = (await db.execute(
        select(func.count()).select_from(Deal).where(Deal.agency_id == agency_id)
    )).scalar() or 0
    if deals_named:
        raise HTTPException(
            status_code=409,
            detail=f"This agency is named on {deals_named} outgoing deal(s) and cannot be deleted. "
                   "Close or re-scope those deals first, or mark the agency inactive.",
        )

    await db.delete(obj)
    await db.commit()
