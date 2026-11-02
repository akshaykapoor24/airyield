"""Internal Statement's ticket API — `/internal-tickets`, over its own tables.

The same endpoints Customer data → Statement uses (`/tickets`, api/v1/tickets.py), pointed
at `internal_ticket_statements` + `internal_uploaded_tickets` (models/internal_ticket.py)
instead of the customer pair.

HOW. api/v1/tickets.py is loaded a SECOND time as its own module and, in that copy only,
the two model names are rebound to the internal classes. Its endpoint functions read those
names when they run, not when they are defined, so every query in the copy hits the
internal tables. The customer module is untouched — it is a separate module object.
One source of truth for the logic; a fix to tickets.py applies to both sections.

WHICH ENDPOINTS. Only the ones that read and write the two ticket tables and nothing
else: template, extract, confirm, add-to-statement, manual preview, statement list and
detail, ticket list / facets / detail, edit, delete, and the statement file. NOT the
commission calculation, income summary, billing-party, matched-deals or match-diagnosis
endpoints: those write or join `ticket_calculations`, `income_summaries`, `lcc_detailed`
and billing rows whose foreign keys point at the CUSTOMER tables, so on an internal ticket
they would fail or cross-link. What Internal Statement does with its data next is a
separate decision; until it is made, those features stay Customer-data only.

Series-contract re-matching after a save is switched off in the copy for the same reason:
it sweeps the customer tickets.
"""
import importlib.util
import sys

from fastapi import APIRouter

from app.api.v1 import tickets as _customer_tickets
from app.models.internal_ticket import InternalTicketStatement, InternalUploadedTicket

_NAME = "app.api.v1._internal_tickets_impl"
_spec = importlib.util.spec_from_file_location(_NAME, _customer_tickets.__file__)
_impl = importlib.util.module_from_spec(_spec)
sys.modules[_NAME] = _impl
_spec.loader.exec_module(_impl)

_impl.UploadedTicket = InternalUploadedTicket
_impl.TicketStatement = InternalTicketStatement


async def _no_series_rematch(*_args, **_kwargs) -> None:
    return None


_impl._rematch_series_contracts = _no_series_rematch

# A ticket is one row here, as it is one line on the statement and on the invoice —
# no per-leg split, no money divided. Upload and Create Ticket both read this flag.
_impl.SPLIT_MULTI_SECTOR = False

# An uploaded statement saves only the tickets not already loaded — of any period, at any
# time (services/ticket_duplicates.py). Customer data keeps saving every row.
_impl.DUPLICATE_CHECK = True

# An uploaded statement declares how its Ticket Date and Travel Date are written, and its
# dates are read that way — no day-first fallback (services/ticket_extraction.py
# DATE_FORMAT_FIELDS). Customer data keeps reading dates as it always has.
_impl.DATE_FORMATS_REQUIRED = True

# The Internal Statement standard format (see the flags in tickets.py): a ticket keeps its
# standard columns and not every source cell, Net Fare and Sales Channel follow the user's
# rules, and one file may hold every vendor's tickets ("All vendors").
_impl.KEEP_RAW_DATA = False
_impl.INTERNAL_STANDARD = True
_impl.MULTI_VENDOR = True

# A statement's column mapping is remembered when it is saved, and the next file with the same
# columns opens already mapped — as Third Party GDS does (services/saved_mapping.py).
MAPPING_SLUG = "internal-statement"
_impl.REMEMBER_MAPPING_SLUG = MAPPING_SLUG

# (method, path) of every endpoint Internal Statement gets — see the module docstring.
_ALLOWED = {
    ("GET", "/template/download"),
    ("POST", "/upload/extract"),
    ("POST", "/upload/confirm"),
    ("POST", "/statements/{batch_id}/tickets"),
    ("POST", "/manual/preview"),
    ("GET", "/statements"),
    ("GET", "/statements/{batch_id}"),
    ("GET", "/uploads"),
    ("GET", "/uploads/page"),
    ("GET", "/uploads/facets"),
    ("GET", "/uploads/{ticket_id}"),
    ("PATCH", "/uploads/{ticket_id}"),
    ("DELETE", "/uploads/{ticket_id}"),
    ("POST", "/statements/{batch_id}/file"),
    ("GET", "/statements/{batch_id}/file-url"),
}

router = APIRouter()
for _route in _impl.router.routes:
    _methods = getattr(_route, "methods", None) or set()
    if any((m, _route.path) in _ALLOWED for m in _methods):
        router.routes.append(_route)

# Every allowed endpoint must exist in tickets.py — a rename there must fail loudly here,
# not silently drop an Internal Statement feature.
_found = {(m, r.path) for r in router.routes for m in (getattr(r, "methods", None) or set())}
_missing = _ALLOWED - _found
if _missing:
    raise RuntimeError(f"internal_tickets: endpoints missing from tickets.py: {sorted(_missing)}")


# ── Internal Statement's own endpoints ───────────────────────────────────────
# Not borrowed from tickets.py. Deleting a statement there would have to reckon with
# everything that hangs off a CUSTOMER ticket — calculations, income summaries,
# billing, reconciliation links. Nothing references the internal tables (their only
# foreign keys point OUT, to agencies, users and the like), so here a statement and
# its tickets can simply go.

from fastapi import Depends, HTTPException  # noqa: E402
from sqlalchemy import and_, delete, func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import get_db  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.models.user import User  # noqa: E402


@router.delete("/statements/{batch_id}")
async def delete_internal_statement(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete one statement and every ticket filed under it, permanently.

    Scoped the way every read here is — tenant and creator — so a batch id from
    someone else's list is a 404, not a delete. The stored source file, if any, is
    left where it is.
    """
    owned = and_(
        InternalTicketStatement.batch_id == batch_id,
        InternalTicketStatement.tenant_id == current_user.tenant_id,
        InternalTicketStatement.created_by_id == current_user.id,
    )
    if (await db.execute(select(InternalTicketStatement.batch_id).where(owned))).first() is None:
        raise HTTPException(status_code=404, detail="Statement not found")

    ticket_scope = and_(
        InternalUploadedTicket.batch_id == batch_id,
        InternalUploadedTicket.tenant_id == current_user.tenant_id,
        InternalUploadedTicket.created_by_id == current_user.id,
    )
    tickets = (await db.execute(
        select(func.count()).select_from(InternalUploadedTicket).where(ticket_scope)
    )).scalar_one()
    await db.execute(delete(InternalUploadedTicket).where(ticket_scope))
    await db.execute(delete(InternalTicketStatement).where(owned))
    await db.commit()
    return {"batch_id": batch_id, "deleted_tickets": tickets}


# ── Upload: tickets already loaded ───────────────────────────────────────────
# Under /upload/… on purpose: the borrowed GET /statements/{batch_id} is registered first
# and would take any /statements/<word> path for a batch id.

from pydantic import BaseModel  # noqa: E402

from app.schemas.uploaded_ticket import TicketRow  # noqa: E402
from app.services import ticket_duplicates  # noqa: E402


class _DuplicatesPayload(BaseModel):
    rows: list[TicketRow]


@router.post("/upload/duplicates")
async def check_duplicates(
    payload: _DuplicatesPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Which of these rows are duplicates of a ticket already loaded — from any uploaded
    statement or Create Ticket entry — nothing is written. The review step shows it before
    Save is pressed: each duplicate and where its ticket is already loaded, how many rows are
    new, and — when none are — why nothing will be saved. Through the same code
    /upload/confirm uses, which decides again."""
    found = await ticket_duplicates.find(
        db, current_user, [r.model_dump() for r in payload.rows],
        statements=InternalTicketStatement, tickets=InternalUploadedTicket)
    return found.preview()


# ── Upload: what the attached file says about itself ─────────────────────────
# The upload step fills the statement details in from these and waits for Next, so the
# user checks the customer, the period, the name and the date format before mapping.

from datetime import date  # noqa: E402

from fastapi import File, Form, UploadFile  # noqa: E402
from pydantic import Field  # noqa: E402

from app.services import statement_party, statement_period, ticket_extraction  # noqa: E402


class _GuessPayload(BaseModel):
    file_name: str = Field(..., max_length=500)
    # The lines above the header, as /upload/extract returned them (`preamble`).
    preamble: list[str] = Field(default_factory=list)


def _period_dict(period, source: str | None) -> dict | None:
    if not period:
        return None
    return {"from": period[0].isoformat(), "to": period[1].isoformat(),
            "label": statement_period.label(*period), "source": source}


@router.post("/upload/guess")
async def guess_statement(
    payload: _GuessPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What an attached file says about itself — who it is for and the days it covers — to
    pre-fill the statement details. Writes nothing; every answer is a suggestion the page
    shows and the user can change.

    `period` is the file name's (services/statement_period.py), else the header line's
    ("For The Period 8 August 2026 To 15 August 2026"); `header_period` is the header's
    only when it says something else. `party` is services/statement_party.py's reading of
    the file name and header lines against the user's agencies and corporates.
    """
    today = date.today()
    preamble = [str(p) for p in payload.preamble if p][:40]
    named = statement_period.from_file_name(payload.file_name, today)
    header = statement_period.find_period(" \n ".join(preamble), today)
    party = await statement_party.guess(db, current_user, payload.file_name, preamble,
                                        statements=InternalTicketStatement)
    return {
        "period": _period_dict(named, "file name") or _period_dict(header, "statement header"),
        "header_period": _period_dict(header, "statement header") if named and header and header != named else None,
        "party": party.as_dict(),
    }


# ── The declared date format ─────────────────────────────────────────────────
# How the file writes its Ticket Date and Travel Date (services/ticket_extraction.py
# DATE_FORMAT_FIELDS): read off the file where it shows it, else this customer's last
# statement — the upload step fills it in from these, and the user checks it.

_MAX_DETECT_MB = 50


@router.post("/upload/detect-date-formats")
async def detect_date_formats(
    file: UploadFile = File(...),
    # As /upload/extract detected them, so the columns read are the ones it found.
    sheet_name: str | None = Form(None),
    header_row: int | None = Form(None),
    # The statement period, when the page has one: it is what settles a date that reads both
    # ways round ("05/08/2026"). Without it only one-way dates ("13/08/2026") count.
    valid_from: str | None = Form(None),
    valid_to: str | None = Form(None),
    current_user: User = Depends(get_current_user),
):
    """The order each of the file's date columns is written in, as far as the file shows it
    (services/date_format_detect.py). Writes nothing."""
    content = await file.read(_MAX_DETECT_MB * 1024 * 1024 + 1)
    if len(content) > _MAX_DETECT_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {_MAX_DETECT_MB} MB limit.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    period = _impl._period_or_none(valid_from, valid_to)
    try:
        fields = ticket_extraction.detect_date_formats(
            content, file.filename or "", sheet_name=sheet_name, header_row=header_row, valid_period=period)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"period_label": statement_period.label(*period) if period else None, "fields": fields}


def _party_conditions(party) -> list | None:
    """This customer's statements, or None when there is no one to look up (an untyped
    statement, or a walk-in Direct customer with no record)."""
    S, ct = InternalTicketStatement, getattr(party, "customer_type", None)
    if ct == "agency" and party.agency_id is not None:
        return [S.customer_type == "agency", S.customer_agency_id == party.agency_id]
    if ct == "corporate" and party.corporate_id is not None:
        return [S.customer_type == "corporate", S.corporate_id == party.corporate_id]
    if ct == "direct" and party.customer_id is not None:
        return [S.customer_type == "direct", S.customer_id == party.customer_id]
    return None


@router.get("/upload/last-date-formats")
async def last_date_formats(
    customer_type: str | None = None,
    customer_agency_id: int | None = None,
    corporate_id: int | None = None,
    customer_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The date formats this customer's latest statement declared — a customer system writes
    its dates the same way each time. Nulls when it has none. Writes nothing."""
    none = {"date_formats": None, "statement_name": None, "created_at": None}
    party = await _impl._resolve_customer_party(db, current_user, customer_type, customer_agency_id,
                                                corporate_id, customer_id)
    conds = _party_conditions(party)
    if conds is None:
        return none
    S = InternalTicketStatement
    row = (await db.execute(
        select(S.date_formats, S.statement_name, S.created_at)
        .where(S.tenant_id == current_user.tenant_id, S.created_by_id == current_user.id,
               S.date_formats.isnot(None), *conds)
        .order_by(S.created_at.desc(), S.batch_id.desc())
        .limit(1)
    )).first()
    if row is None:
        return none
    return {"date_formats": row.date_formats, "statement_name": row.statement_name,
            "created_at": row.created_at.isoformat() if row.created_at else None}


# ── Upload: "All vendors" — which vendor each Supplier Name is ───────────────
# A multi-vendor sales report names the supplier every ticket was bought from (Yatra's
# tkt_supplier_name: "JETHI TRAVELS - 6E", "TSC Travel Services Pvt Ltd", "IATA BSP" …).
# The preview asks once per name — and channel, since a vendor is onboarded once per channel
# — which Agency Master row it is, the way Upload Deal's "All suppliers" asks per Source
# (services/deal_vendor_resolver.py). A choice saved once is offered again next time.

from collections import Counter  # noqa: E402

from app.models.agency import Agency  # noqa: E402
from app.services import deal_vendor_resolver as dvr  # noqa: E402

# Names that say the ticket was bought from the airline itself — its BSP stock, or its
# own portal — rather than from a consolidator.
_AIRLINE_DIRECT_WORDS = ("BSP", "PORTAL")


class _SupplierName(BaseModel):
    name: str = Field(..., max_length=300)
    channel: str | None = Field(None, max_length=10)     # GDS | LCC, from the rows' tickets


class _SuppliersPayload(BaseModel):
    suppliers: list[_SupplierName] = Field(default_factory=list, max_length=2000)


async def _remembered_suppliers(db: AsyncSession, current_user: User) -> dict[str, str]:
    """source_key → "agency:<id>" | "airline": what this user's saved tickets with that
    Supplier Name were filed under, by majority (a tie decides nothing). Read off the
    tickets themselves — they are the record of every earlier choice."""
    T = InternalUploadedTicket
    found = (await db.execute(
        select(T.supplier_name, T.payable_type, T.payable_agency_id, func.count())
        .where(T.tenant_id == current_user.tenant_id, T.created_by_id == current_user.id,
               T.supplier_name.isnot(None), T.payable_type.isnot(None))
        .group_by(T.supplier_name, T.payable_type, T.payable_agency_id)
    )).all()
    votes: dict[str, Counter] = {}
    for name, kind, agency_id, n in found:
        choice = "airline" if kind == "airline" else f"agency:{agency_id}" if agency_id else None
        key = dvr.source_key(name)
        if choice and key:
            votes.setdefault(key, Counter())[choice] += n
    out: dict[str, str] = {}
    for key, counts in votes.items():
        ranked = counts.most_common(2)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            out[key] = ranked[0][0]
    return out


@router.post("/upload/suppliers")
async def resolve_suppliers(
    payload: _SuppliersPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Which vendor each Supplier Name of an "All vendors" upload is. Writes nothing.

    One line per name and channel: `status` as deal_vendor_resolver says it (remembered,
    matched, suggested, ambiguous, not_onboarded, blank), `agency_id` only when it is
    certain, `candidates` to offer otherwise. `airline_direct` when this name was saved as
    bought from the airline before; `airline_hint` when the name looks like it (BSP, a
    portal) and no agency fits. The rows carry whatever the reviewer leaves; confirm checks
    each agency is theirs."""
    agencies = [
        dvr.AgencyRef(id=a.id, name=a.name, channels=a.channels, branch_code=a.branch_code,
                      branch_name=a.branch_name, agency_code=a.agency_code)
        for a in (await db.execute(
            select(Agency).where(Agency.user_id == current_user.id, Agency.is_active.is_(True))
        )).scalars()
    ]
    remembered = await _remembered_suppliers(db, current_user)
    by_agency = {k: int(v.split(":", 1)[1]) for k, v in remembered.items() if v.startswith("agency:")}

    out = []
    for s in payload.suppliers:
        channel = (s.channel or "").strip().upper() or None
        key = dvr.source_key(s.name)
        line = {"group": f"{key}|{channel or ''}", "source": s.name.strip(), "channel": channel,
                "status": None, "agency_id": None, "candidates": [], "note": None,
                "airline_direct": False, "airline_hint": False}
        if key and remembered.get(key) == "airline":
            line.update(status=dvr.REMEMBERED, airline_direct=True,
                        note="Saved as bought from the airline on an earlier upload.")
        else:
            m = dvr.resolve_source(s.name, channel, agencies, by_agency)
            line.update(status=m.status, agency_id=m.agency_id, candidates=m.candidates, note=m.note)
            if m.status == dvr.NOT_ONBOARDED and any(w in s.name.upper() for w in _AIRLINE_DIRECT_WORDS):
                line["airline_hint"] = True
        out.append(line)
    return {"suppliers": out}


# ── Upload: the column mapping remembered from an earlier statement ──────────
# Asked when the upload step's Next is pressed — by then the customer is settled (it is read
# off the file after the file is read) — and again when the sheet or header row changes.

from app.services import saved_mapping  # noqa: E402


class _SavedMappingPayload(BaseModel):
    columns: list[str] = Field(default_factory=list, max_length=500)
    # The alias map's answer for these columns — what the first read suggested.
    by_name: dict[str, str] = Field(default_factory=dict)
    customer_type: str | None = None
    customer_agency_id: int | None = None
    corporate_id: int | None = None
    customer_id: int | None = None
    multi_vendor: bool = False


@router.post("/upload/saved-mapping")
async def saved_column_mapping(
    payload: _SavedMappingPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The mapping the column step opens with. Writes nothing.

    Best first (services/saved_mapping.propose): this customer's mapping for exactly these
    columns; this customer's mapping for columns that have since changed — kept for the columns
    still there, new ones matched by name; another customer's mapping for exactly these
    columns; else the name match (`by_name`). A column left unmapped when it was saved stays
    unmapped. Only this user's own mappings are read, so the ids are not authorised here —
    they are only compared with what the user saved before."""
    party = None if payload.multi_vendor else _impl.CustomerParty(
        (payload.customer_type or "").strip().lower() or None,
        agency_id=payload.customer_agency_id, corporate_id=payload.corporate_id,
        customer_id=payload.customer_id)
    proposal = await saved_mapping.propose_for(
        db, current_user, MAPPING_SLUG, _impl.mapping_party(party, payload.multi_vendor),
        payload.columns, _impl.mapping_fields(), payload.by_name)
    return {"mapping": proposal.mapping, "remembered": proposal.info()}
