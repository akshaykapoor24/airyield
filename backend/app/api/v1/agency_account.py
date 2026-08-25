"""Agency account — commercial terms history and the payment ledger, per channel.

Mounted under /agencies/{agency_id}/… but kept in its own module: Agency Master
is identity, this is money, and they have different rules and different readers.

EVERY ENDPOINT HERE IS ABOUT ONE CHANNEL. An agency is routinely cash on GDS and
credit on LCC, which means two limits, two cycles and two balances under one row.
`_resolve_channel` fills the blank for an agency that trades on only one, and
refuses to guess for one that trades on both — picking wrong would show someone
the other arrangement's money.

The type switch lives here rather than on `PATCH /agencies/{id}` on purpose.
Flipping agency_type is not a field edit — it is a guarded state transition that
has to close one arrangement and open another, and only at a cycle boundary with
a settled balance. Opening and closing a whole channel is the same kind of
transition, which is why /channels/open and /channels/close are here too and not
a PATCH field either. PATCH refuses all of it outright (see agencies.py).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import CHANNELS, Agency, norm_channel, scope_covers
from app.models.agency_ledger import MANUAL_ENTRY_TYPES, PAYMENT_MODES, AgencyLedger
from app.models.agency_terms import AgencyTerms
from app.models.user import User
from app.schemas.agency import AGENCY_TYPES, BILLING_CYCLES
from app.schemas.agency_account import (
    AccountSummary, ChannelCloseRequest, ChannelOpenRequest, CycleRead,
    LedgerEntryCreate, LedgerEntryRead, SwitchPreview, SwitchRequest, TermsRead,
)
from app.services import agency_account as acct

router = APIRouter()

# Entry types whose stored amount is negative (value leaving the agency's balance).
_NEGATIVE_TYPES = {"refund", "invoice"}


async def _owned(agency_id: int, db: AsyncSession, current_user: User) -> Agency:
    res = await db.execute(select(Agency).where(Agency.id == agency_id, Agency.user_id == current_user.id))
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Agency not found")
    return obj


def _resolve_channel(agency: Agency, channel: Optional[str]) -> str:
    """Which channel this request is about.

    Omitting it is only legal for a single-channel agency. With two arrangements
    open, guessing which account was meant is guessing whose money it is, so the
    request is rejected rather than answered with a plausible wrong number.
    """
    ch = norm_channel(channel)
    if ch is None:
        if agency.channels in CHANNELS:
            return agency.channels
        raise HTTPException(
            status_code=400,
            detail="This agency trades on GDS and LCC — specify ?channel=GDS or ?channel=LCC.",
        )
    if ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
    if agency.channels != "BOTH" and agency.channels != ch:
        raise HTTPException(
            status_code=400,
            detail=f"This agency trades on {agency.channels} only — it has no {ch} account.",
        )
    return ch


def _signed(entry_type: str, amount: float) -> Decimal:
    """Apply the ledger's sign convention so callers never pass a negative."""
    amt = Decimal(str(abs(amount)))
    return -amt if entry_type in _NEGATIVE_TYPES else amt


def _widen(channels: str, opening: str) -> str:
    return "BOTH" if channels != opening else channels


def _narrow(channels: str, closing: str) -> str:
    """What is left after closing one channel. 'BOTH' minus one is the other."""
    if channels != "BOTH":
        return channels
    return "LCC" if closing == "GDS" else "GDS"


def _read_entry(entry: AgencyLedger, running: Decimal, is_reversed: bool = False) -> LedgerEntryRead:
    return LedgerEntryRead(
        id=entry.id, channel=entry.channel, entry_date=entry.entry_date,
        entry_type=entry.entry_type, amount=float(entry.amount),
        balance_after=float(running), billing_id=entry.billing_id,
        payment_mode=entry.payment_mode, reference_no=entry.reference_no,
        note=entry.note, reversal_of_id=entry.reversal_of_id, is_reversed=is_reversed,
    )


@router.get("/{agency_id}/account", response_model=AccountSummary)
async def get_account(
    agency_id: int,
    channel: Optional[str] = Query(None, description="GDS | LCC — required when the agency trades on both"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _owned(agency_id, db, current_user)
    ch = _resolve_channel(agency, channel)
    return await acct.account_summary(db, agency, current_user, date.today(), ch)


@router.get("/{agency_id}/ledger", response_model=list[LedgerEntryRead])
async def list_ledger(
    agency_id: int,
    channel: Optional[str] = Query(None, description="GDS | LCC — omit for a combined statement"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Oldest first, with a running balance — this is a statement, not a log.

    Omitting `channel` here returns BOTH channels, unlike the other endpoints: a
    combined statement is a meaningful thing to look at. But the running balance
    is then accumulated PER CHANNEL, because one running total across two separate
    accounts is not a number that means anything. Rows come back in date order
    regardless, each carrying its own channel.
    """
    agency = await _owned(agency_id, db, current_user)
    ch = norm_channel(channel)
    if ch is not None and ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")

    q = select(AgencyLedger).where(AgencyLedger.agency_id == agency_id)
    if ch is not None:
        q = q.where(AgencyLedger.channel == ch)
    rows = (await db.execute(
        q.order_by(AgencyLedger.entry_date, AgencyLedger.id)
    )).scalars().all()

    reversed_ids = {r.reversal_of_id for r in rows if r.reversal_of_id}
    running: dict[str, Decimal] = {}
    out = []
    for r in rows:
        running[r.channel] = running.get(r.channel, Decimal("0.00")) + Decimal(str(r.amount))
        out.append(_read_entry(r, running[r.channel], r.id in reversed_ids))
    return out


@router.post("/{agency_id}/ledger", response_model=LedgerEntryRead, status_code=status.HTTP_201_CREATED)
async def post_ledger_entry(
    agency_id: int,
    payload: LedgerEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _owned(agency_id, db, current_user)
    ch = _resolve_channel(agency, payload.channel)
    etype = (payload.entry_type or "").strip().lower()
    if etype not in MANUAL_ENTRY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"entry_type must be one of {sorted(MANUAL_ENTRY_TYPES)}.",
        )
    if payload.amount is None or float(payload.amount) <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    mode = (payload.payment_mode or "").strip().lower() or None
    if mode and mode not in PAYMENT_MODES:
        raise HTTPException(status_code=400, detail=f"payment_mode must be one of {sorted(PAYMENT_MODES)}.")

    terms = await acct.current_terms(db, agency_id, ch)
    # An adjustment may go either way; everything else has a fixed direction.
    amount = Decimal(str(payload.amount)) if etype == "adjustment" and payload.amount > 0 else _signed(etype, payload.amount)
    if etype == "adjustment" and (payload.note or "").lower().startswith("-"):
        amount = -abs(amount)

    entry = AgencyLedger(
        agency_id=agency.id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        terms_id=terms.id if terms else None,
        channel=ch,
        entry_date=payload.entry_date or date.today(),
        entry_type=etype,
        amount=amount,
        payment_mode=mode,
        reference_no=(payload.reference_no or "").strip() or None,
        note=(payload.note or "").strip() or None,
        created_by_id=current_user.id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return _read_entry(entry, await acct.balance(db, agency_id, ch))


@router.post("/{agency_id}/ledger/{entry_id}/reverse", response_model=LedgerEntryRead, status_code=status.HTTP_201_CREATED)
async def reverse_ledger_entry(
    agency_id: int,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel an entry by posting its opposite. Nothing is ever deleted."""
    await _owned(agency_id, db, current_user)
    src = (await db.execute(
        select(AgencyLedger).where(AgencyLedger.id == entry_id, AgencyLedger.agency_id == agency_id)
    )).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=404, detail="Ledger entry not found")

    already = (await db.execute(
        select(func.count()).select_from(AgencyLedger).where(AgencyLedger.reversal_of_id == entry_id)
    )).scalar() or 0
    if already:
        raise HTTPException(status_code=400, detail="This entry has already been reversed.")

    entry = AgencyLedger(
        agency_id=agency_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        terms_id=src.terms_id,
        # Inherited, never re-resolved: a reversal must land in the same account
        # as the entry it cancels or it moves money between channels.
        channel=src.channel,
        entry_date=date.today(),
        entry_type="reversal",
        amount=-Decimal(str(src.amount)),
        billing_id=src.billing_id,
        note=f"Reversal of #{src.id} ({src.entry_type})",
        reversal_of_id=src.id,
        created_by_id=current_user.id,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return _read_entry(entry, await acct.balance(db, agency_id, src.channel))


@router.get("/{agency_id}/terms", response_model=list[TermsRead])
async def list_terms(
    agency_id: int,
    channel: Optional[str] = Query(None, description="GDS | LCC — omit for every channel's history"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Newest first — the arrangement history behind the current one."""
    await _owned(agency_id, db, current_user)
    ch = norm_channel(channel)
    if ch is not None and ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")

    q = select(AgencyTerms).where(AgencyTerms.agency_id == agency_id)
    if ch is not None:
        q = q.where(AgencyTerms.channel == ch)
    rows = (await db.execute(
        q.order_by(AgencyTerms.channel, AgencyTerms.effective_from.desc(), AgencyTerms.id.desc())
    )).scalars().all()
    return rows


@router.get("/{agency_id}/cycles", response_model=list[CycleRead])
async def list_cycles(
    agency_id: int,
    channel: Optional[str] = Query(None, description="GDS | LCC — required when the agency trades on both"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agency = await _owned(agency_id, db, current_user)
    ch = _resolve_channel(agency, channel)
    terms = await acct.current_terms(db, agency_id, ch)
    if not terms:
        return []
    return await acct.cycles_with_status(db, agency_id, terms, date.today())


@router.get("/{agency_id}/switch-preview", response_model=SwitchPreview)
async def switch_preview(
    agency_id: int,
    channel: Optional[str] = Query(None, description="GDS | LCC — required when the agency trades on both"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What is standing in the way of a type switch, and what to do about it."""
    agency = await _owned(agency_id, db, current_user)
    ch = _resolve_channel(agency, channel)
    terms = await acct.current_terms(db, agency_id, ch)
    blockers = await acct.switch_blockers(db, agency, terms, current_user, date.today(), ch)
    return SwitchPreview(
        can_switch=not blockers,
        channel=ch,
        current_type=terms.agency_type if terms else None,
        blockers=blockers,
    )


@router.post("/{agency_id}/switch", response_model=TermsRead)
async def switch_terms(
    agency_id: int,
    payload: SwitchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Close this channel's arrangement and open a new one, at a cycle boundary.

    Re-checks the blockers server-side: the screen disables the button, but the
    endpoint is what actually holds the rule. Only the named channel moves — the
    other one's terms, balance and cycle are untouched.
    """
    agency = await _owned(agency_id, db, current_user)
    ch = _resolve_channel(agency, payload.channel)
    new_type = (payload.agency_type or "").strip().lower()
    cycle = (payload.billing_cycle or "").strip().lower()
    if new_type not in AGENCY_TYPES:
        raise HTTPException(status_code=400, detail="agency_type must be 'cash' or 'credit'.")
    if cycle not in BILLING_CYCLES:
        raise HTTPException(status_code=400, detail=f"billing_cycle must be one of {sorted(BILLING_CYCLES)}.")

    today = date.today()
    effective = payload.effective_from or today
    terms = await acct.current_terms(db, agency_id, ch)

    if terms is not None:
        blockers = await acct.switch_blockers(db, agency, terms, current_user, today, ch)
        if blockers:
            raise HTTPException(status_code=409, detail={"message": f"Cannot switch {ch} yet.", "blockers": blockers})
        if effective < terms.effective_from:
            raise HTTPException(status_code=400, detail="effective_from cannot precede the current terms.")

        # Settled within tolerance but not exactly zero — write off the few paise
        # rather than leaving a period that never closes cleanly.
        bal = await acct.balance(db, agency_id, ch, terms.id)
        if bal != acct.ZERO:
            db.add(AgencyLedger(
                agency_id=agency.id, user_id=current_user.id, tenant_id=current_user.tenant_id,
                terms_id=terms.id, channel=ch, entry_date=effective, entry_type="adjustment",
                amount=-bal, note="Rounding write-off on terms change",
                created_by_id=current_user.id,
            ))
        terms.effective_to = effective

    limit = Decimal(str(payload.credit_limit)) if payload.credit_limit is not None else None
    usage = Decimal(str(payload.usage_percent)) if payload.usage_percent is not None else None
    if limit is not None and limit < 0:
        raise HTTPException(status_code=400, detail="Limit cannot be negative.")
    if usage is not None and usage < 0:
        raise HTTPException(status_code=400, detail="Usage % cannot be negative.")
    if new_type == "credit":
        usage = None                       # credit has no deposit to threshold
    else:
        limit = None                       # on cash the limit IS the deposit

    fresh = AgencyTerms(
        agency_id=agency.id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        channel=ch,
        effective_from=effective,
        effective_to=None,
        agency_type=new_type,
        credit_limit=limit,
        usage_percent=usage,
        billing_cycle=cycle,
        cycle_anchor_date=effective,       # the new arrangement restarts the clock
        note=(payload.note or "").strip() or None,
        created_by_id=current_user.id,
    )
    db.add(fresh)
    await db.commit()
    await db.refresh(fresh)
    return fresh


@router.post("/{agency_id}/channels/open", response_model=TermsRead, status_code=status.HTTP_201_CREATED)
async def open_channel(
    agency_id: int,
    payload: ChannelOpenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start trading with this agency on a channel it did not trade on before.

    A guarded transition, not a PATCH: it opens a commercial arrangement, and for
    cash it takes the first deposit. Also the repair path for an agency onboarded
    on one channel that later needs the other.

    THE ORDINARY WAY TO ADD A CHANNEL IS NOW A SECOND AGENCY — Agency Master
    onboards one row per channel, so each has its own terms, deposit and balance.
    This endpoint still widens a row to BOTH, but it refuses to do so when a
    sibling row already covers that channel: the two would then match the same
    vendor name on the same tickets, and both could bill them.
    """
    agency = await _owned(agency_id, db, current_user)
    ch = norm_channel(payload.channel)
    if ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
    if await acct.current_terms(db, agency_id, ch) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"This agency already has an open {ch} arrangement — use /switch to change its type.",
        )

    sibling = (await db.execute(
        select(Agency.id, Agency.channels).where(
            Agency.user_id == current_user.id,
            Agency.id != agency.id,
            func.lower(Agency.name) == (agency.name or "").lower(),
            func.lower(Agency.branch_code) == (agency.branch_code or "").lower(),
        )
    )).all()
    if any(scope_covers(existing, ch) for _id, existing in sibling):
        raise HTTPException(
            status_code=409,
            detail=f"'{agency.name}' branch '{agency.branch_code}' is already onboarded separately on "
                   f"{ch} — open that agency instead. Widening this one would leave two accounts "
                   "claiming the same tickets.",
        )

    new_type = (payload.agency_type or "").strip().lower()
    cycle = (payload.billing_cycle or "").strip().lower()
    if new_type not in AGENCY_TYPES:
        raise HTTPException(status_code=400, detail="agency_type must be 'cash' or 'credit'.")
    if cycle not in BILLING_CYCLES:
        raise HTTPException(status_code=400, detail=f"billing_cycle must be one of {sorted(BILLING_CYCLES)}.")

    limit = Decimal(str(payload.credit_limit)) if payload.credit_limit is not None else None
    usage = Decimal(str(payload.usage_percent)) if payload.usage_percent is not None else None
    deposit = Decimal(str(payload.deposit_amount)) if payload.deposit_amount is not None else None
    for label, amount in (("Limit", limit), ("Usage %", usage), ("Deposit", deposit)):
        if amount is not None and amount < 0:
            raise HTTPException(status_code=400, detail=f"{label} cannot be negative.")
    if new_type == "cash":
        limit = None                       # on cash the limit IS the deposit
        if deposit is None:
            raise HTTPException(status_code=400, detail=f"{ch} is cash — enter the deposit amount.")
    else:
        usage, deposit = None, None
        if limit is None:
            raise HTTPException(status_code=400, detail=f"{ch} is credit — enter the credit limit.")

    effective = payload.effective_from or date.today()
    fresh = AgencyTerms(
        agency_id=agency.id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        channel=ch,
        effective_from=effective,
        effective_to=None,
        agency_type=new_type,
        credit_limit=limit,
        usage_percent=usage,
        billing_cycle=cycle,
        cycle_anchor_date=effective,
        note=(payload.note or "").strip() or f"{ch} channel opened",
        created_by_id=current_user.id,
    )
    db.add(fresh)
    await db.flush()

    if deposit and deposit > 0:
        db.add(AgencyLedger(
            agency_id=agency.id, user_id=current_user.id, tenant_id=current_user.tenant_id,
            terms_id=fresh.id, channel=ch, entry_date=effective, entry_type="topup",
            amount=deposit, note=f"Opening deposit ({ch})", created_by_id=current_user.id,
        ))

    agency.channels = _widen(agency.channels, ch)
    await db.commit()
    await db.refresh(fresh)
    return fresh


@router.post("/{agency_id}/channels/close", status_code=status.HTTP_200_OK)
async def close_channel(
    agency_id: int,
    payload: ChannelCloseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop trading with this agency on one channel.

    Same guard as a type switch, for the same reason — the arrangement has to end
    at a cycle boundary with everything billed and the balance settled, or the
    money left behind belongs to nothing.
    """
    agency = await _owned(agency_id, db, current_user)
    ch = norm_channel(payload.channel)
    if ch not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"channel must be one of {sorted(CHANNELS)}.")
    if agency.channels != "BOTH":
        raise HTTPException(
            status_code=409,
            detail="An agency must trade on at least one channel — mark it inactive instead.",
        )

    terms = await acct.current_terms(db, agency_id, ch)
    if terms is None:
        raise HTTPException(status_code=404, detail=f"This agency has no open {ch} arrangement.")

    blockers = await acct.switch_blockers(db, agency, terms, current_user, date.today(), ch)
    if blockers:
        raise HTTPException(
            status_code=409,
            detail={"message": f"Cannot close {ch} yet.", "blockers": blockers},
        )

    terms.effective_to = payload.effective_from or date.today()
    terms.note = (payload.note or "").strip() or f"{ch} channel closed"
    agency.channels = _narrow(agency.channels, ch)
    await db.commit()
    return {"agency_id": agency.id, "channels": agency.channels, "closed": ch}
