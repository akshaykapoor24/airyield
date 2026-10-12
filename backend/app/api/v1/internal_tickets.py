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
