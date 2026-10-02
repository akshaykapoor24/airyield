"""Accounting → Bank Statement.

Upload the tenant's own bank statement, sort its lines, link each deposit to the party
that paid it, and compare what every party was BILLED (Invoicing) with what they PAID
(these links). Parsing is services/bank_statement.py; the tables are
models/bank_statement.py, whose docstring explains the two rules that matter most here:
duplicates are skipped by `dedupe_key`, and an agency receipt lives in the agency ledger.

Scoped like Invoicing: tenant + the user who uploaded. Agencies are owned by `user_id`
(api/v1/agencies.py), corporates and employees by tenant + `created_by_id`.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.agency import CHANNELS, Agency, norm_channel
from app.models.agency_ledger import PAYMENT_MODES, AgencyLedger
from app.models.bank_statement import BankStatement, BankStatementRow
from app.models.billing import Billing
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.user import User
from app.schemas.bank_statement import (
    AcceptSuggestionsResult, BankRowUpdate, BankStatementDetail, BankStatementRead,
    BankStatementRowRead, BankStatementUploadResult, BilledReceivedRow,
    BilledReceivedSummary, PartyRef, RowSuggestion,
)
from app.services import agency_account as acct
from app.services import bank_statement as bs

router = APIRouter()

PARTY_TYPES = {"corporate", "customer", "agency"}
# Below this a name match is shown but never linked by "Accept suggestions".
_AUTO_ACCEPT = 0.85
# Agency ledger entries that are money IN from the agency.
_MONEY_IN = {"receipt", "topup"}


def _scope(current_user: User):
    return and_(
        BankStatement.tenant_id == current_user.tenant_id,
        BankStatement.created_by_id == current_user.id,
    )


def _row_scope(current_user: User):
    return and_(
        BankStatementRow.tenant_id == current_user.tenant_id,
        BankStatementRow.created_by_id == current_user.id,
    )


# ── Parties ──────────────────────────────────────────────────────────────────

class _Parties:
    """Every corporate, employee and agency the user can link a line to, loaded once."""

    def __init__(self):
        self.refs: dict[tuple[str, int], PartyRef] = {}
        self.candidates: list[bs.Candidate] = []
        self.agencies: dict[int, Agency] = {}

    @classmethod
    async def load(cls, db: AsyncSession, current_user: User) -> "_Parties":
        out = cls()
        corporates = (await db.execute(select(Corporate).where(
            Corporate.tenant_id == current_user.tenant_id,
            Corporate.created_by_id == current_user.id,
        ))).scalars().all()
        for c in corporates:
            name = (c.company or f"{c.first_name or ''} {c.last_name or ''}").strip() or f"Corporate #{c.id}"
            out._add("corporate", c.id, name, c.customer_code, None, None)

        customers = (await db.execute(select(Customer).where(
            Customer.tenant_id == current_user.tenant_id,
            Customer.created_by_id == current_user.id,
        ))).scalars().all()
        for c in customers:
            name = f"{c.first_name or ''} {c.last_name or ''}".strip() or f"Employee #{c.id}"
            out._add("customer", c.id, name, c.customer_code, c.company, None)

        agencies = (await db.execute(select(Agency).where(Agency.user_id == current_user.id))).scalars().all()
        for a in agencies:
            out.agencies[a.id] = a
            branch = a.branch_name or a.branch_code
            out._add("agency", a.id, a.name, a.customer_code, f"{branch} · {a.channels}", a.channels)
        return out

    def _add(self, ptype, pid, name, code, detail, channels):
        self.refs[(ptype, pid)] = PartyRef(
            party_type=ptype, party_id=pid, name=name, code=code, detail=detail, channels=channels,
        )
        self.candidates.append(bs.Candidate(ptype, pid, name))

    def of_row(self, row: BankStatementRow) -> Optional[PartyRef]:
        pid = {"corporate": row.corporate_id, "customer": row.customer_id, "agency": row.agency_id}.get(row.party_type or "")
        return self.refs.get((row.party_type, pid)) if pid else None


async def _history(db: AsyncSession, current_user: User) -> dict[str, tuple[str, int]]:
    """Counterparty name → the party it was last linked to. Next month's statement from
    the same payer then suggests the same party without needing a name match."""
    rows = (await db.execute(
        select(BankStatementRow.counterparty, BankStatementRow.party_type,
               BankStatementRow.corporate_id, BankStatementRow.customer_id, BankStatementRow.agency_id)
        .where(_row_scope(current_user), BankStatementRow.party_type.is_not(None),
               BankStatementRow.counterparty.is_not(None))
        .order_by(BankStatementRow.linked_at)
    )).all()
    out: dict[str, tuple[str, int]] = {}
    for name, ptype, corp, cust, ag in rows:
        pid = {"corporate": corp, "customer": cust, "agency": ag}.get(ptype)
        if pid:
            out[bs._norm(name)] = (ptype, pid)          # later links overwrite earlier ones
    return out


def _suggest(row: BankStatementRow, parties: _Parties, history: dict) -> Optional[RowSuggestion]:
    if row.direction != "in" or row.party_type or row.category != "receipt" or not row.counterparty:
        return None
    hit = history.get(bs._norm(row.counterparty))
    if hit and hit in parties.refs:
        return RowSuggestion(party=parties.refs[hit], score=1.0, source="history")
    found = bs.suggest(row.counterparty, parties.candidates)
    if not found:
        return None
    cand, score = found
    return RowSuggestion(party=parties.refs[(cand.party_type, cand.party_id)], score=score, source="name")


def _row_read(row: BankStatementRow, parties: _Parties, suggestion: Optional[RowSuggestion] = None) -> BankStatementRowRead:
    return BankStatementRowRead(
        id=row.id, statement_id=row.statement_id, line_no=row.line_no, tran_id=row.tran_id,
        value_date=row.value_date, txn_date=row.txn_date, posted_at=row.posted_at,
        cheque_ref=row.cheque_ref, remarks=row.remarks,
        withdrawal=float(row.withdrawal or 0), deposit=float(row.deposit or 0),
        balance=float(row.balance) if row.balance is not None else None,
        direction=row.direction, counterparty=row.counterparty, payment_mode=row.payment_mode,
        reference=row.reference, category=row.category, party=parties.of_row(row),
        agency_ledger_id=row.agency_ledger_id, note=row.note, suggestion=suggestion,
    )


# ── Linking ──────────────────────────────────────────────────────────────────

def _ledger_mode(mode: Optional[str]) -> str:
    return mode if mode in PAYMENT_MODES else "other"


async def _reverse_ledger_receipt(db: AsyncSession, row: BankStatementRow, current_user: User) -> None:
    """Cancel the receipt this row posted, the way the agency account screen would —
    by posting its opposite. Skipped if someone already reversed it by hand."""
    if not row.agency_ledger_id:
        return
    src = (await db.execute(select(AgencyLedger).where(AgencyLedger.id == row.agency_ledger_id))).scalar_one_or_none()
    row.agency_ledger_id = None
    if src is None:
        return
    already = (await db.execute(
        select(func.count()).select_from(AgencyLedger).where(AgencyLedger.reversal_of_id == src.id)
    )).scalar() or 0
    if already:
        return
    db.add(AgencyLedger(
        agency_id=src.agency_id, user_id=current_user.id, tenant_id=current_user.tenant_id,
        terms_id=src.terms_id, channel=src.channel, entry_date=date.today(),
        entry_type="reversal", amount=-Decimal(str(src.amount)),
        note=f"Reversal of #{src.id} (bank statement line unlinked)",
        reversal_of_id=src.id, created_by_id=current_user.id,
    ))


async def _unlink(db: AsyncSession, row: BankStatementRow, current_user: User) -> None:
    await _reverse_ledger_receipt(db, row, current_user)
    row.party_type = None
    row.corporate_id = row.customer_id = row.agency_id = None
    row.linked_at = None


async def _link(
    db: AsyncSession, row: BankStatementRow, ptype: str, pid: int,
    channel: Optional[str], parties: _Parties, current_user: User,
) -> None:
    if row.direction != "in":
        raise HTTPException(status_code=400, detail="Only deposits can be linked to a party.")
    if ptype not in PARTY_TYPES:
        raise HTTPException(status_code=400, detail=f"party_type must be one of {sorted(PARTY_TYPES)}.")
    if (ptype, pid) not in parties.refs:
        raise HTTPException(status_code=404, detail="That party was not found.")

    # Resolve the agency's account BEFORE touching the current link, so a refused
    # request leaves the row exactly as it was.
    ch = None
    if ptype == "agency":
        agency = parties.agencies[pid]
        ch = norm_channel(channel)
        if agency.channels in CHANNELS:
            ch = agency.channels
        elif ch not in CHANNELS:
            raise HTTPException(
                status_code=400,
                detail=f"{agency.name} trades on GDS and LCC — pick which account this receipt is for.",
            )

    if row.party_type:
        await _unlink(db, row, current_user)

    row.party_type = ptype
    row.corporate_id = pid if ptype == "corporate" else None
    row.customer_id = pid if ptype == "customer" else None
    row.agency_id = pid if ptype == "agency" else None
    row.category = "receipt"
    row.linked_at = datetime.utcnow()

    if ptype == "agency":
        terms = await acct.current_terms(db, pid, ch)
        entry = AgencyLedger(
            agency_id=pid, user_id=current_user.id, tenant_id=current_user.tenant_id,
            terms_id=terms.id if terms else None, channel=ch,
            entry_date=row.txn_date or row.value_date or date.today(),
            entry_type="receipt", amount=Decimal(str(row.deposit)),
            payment_mode=_ledger_mode(row.payment_mode),
            reference_no=(row.reference or row.tran_id or row.cheque_ref or None),
            note=f"Bank statement · {row.counterparty or row.remarks}"[:255],
            created_by_id=current_user.id,
        )
        db.add(entry)
        await db.flush()
        row.agency_ledger_id = entry.id


# ── Statements ───────────────────────────────────────────────────────────────

async def _link_stats(db: AsyncSession, current_user: User, statement_ids: list[int]) -> dict[int, dict]:
    if not statement_ids:
        return {}
    linked = BankStatementRow.party_type.is_not(None)
    open_receipt = and_(BankStatementRow.direction == "in", BankStatementRow.party_type.is_(None),
                        BankStatementRow.category == "receipt")
    rows = (await db.execute(
        select(
            BankStatementRow.statement_id,
            func.count().filter(linked),
            func.coalesce(func.sum(BankStatementRow.deposit).filter(linked), 0),
            func.count().filter(open_receipt),
            func.coalesce(func.sum(BankStatementRow.deposit).filter(open_receipt), 0),
        )
        .where(_row_scope(current_user), BankStatementRow.statement_id.in_(statement_ids))
        .group_by(BankStatementRow.statement_id)
    )).all()
    return {
        sid: dict(linked_count=lc, linked_amount=float(la), unlinked_receipt_count=uc,
                  unlinked_receipt_amount=float(ua))
        for sid, lc, la, uc, ua in rows
    }


def _statement_read(s: BankStatement, stats: Optional[dict] = None) -> BankStatementRead:
    return BankStatementRead(
        id=s.id, bank_name=s.bank_name, account_name=s.account_name, account_no=s.account_no,
        ifsc=s.ifsc, branch=s.branch, currency=s.currency, period_from=s.period_from,
        period_to=s.period_to, file_name=s.file_name, row_count=s.row_count,
        duplicate_count=s.duplicate_count, total_deposits=float(s.total_deposits or 0),
        total_withdrawals=float(s.total_withdrawals or 0), created_at=s.created_at,
        **(stats or {}),
    )


async def _owned(statement_id: int, db: AsyncSession, current_user: User) -> BankStatement:
    s = (await db.execute(
        select(BankStatement).where(BankStatement.id == statement_id, _scope(current_user))
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Bank statement not found")
    return s


@router.post("/upload", response_model=BankStatementUploadResult, status_code=status.HTTP_201_CREATED)
async def upload_statement(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        parsed = bs.parse_statement(content, file.filename or "")
    except bs.StatementError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    keyed = [(bs.dedupe_key(parsed.account_no, r), r) for r in parsed.rows]
    existing: set[str] = set()
    keys = [k for k, _ in keyed]
    for i in range(0, len(keys), 1000):
        existing |= set((await db.execute(
            select(BankStatementRow.dedupe_key).where(
                BankStatementRow.created_by_id == current_user.id,
                BankStatementRow.dedupe_key.in_(keys[i:i + 1000]),
            )
        )).scalars().all())

    fresh, seen = [], set()
    for k, r in keyed:
        if k in existing or k in seen:
            continue
        seen.add(k)
        fresh.append((k, r))
    skipped = len(keyed) - len(fresh)
    if not fresh:
        raise HTTPException(
            status_code=409,
            detail=f"Every one of the {len(keyed)} transactions in this file is already loaded. Nothing was added.",
        )

    statement = BankStatement(
        tenant_id=current_user.tenant_id, created_by_id=current_user.id,
        bank_name=parsed.bank_name, account_name=parsed.account_name, account_no=parsed.account_no,
        ifsc=parsed.ifsc, branch=parsed.branch, currency=parsed.currency,
        period_from=parsed.period_from, period_to=parsed.period_to,
        file_name=(file.filename or "statement")[:255],
        row_count=len(fresh), duplicate_count=skipped,
        total_deposits=sum((r.deposit for _, r in fresh), Decimal("0")),
        total_withdrawals=sum((r.withdrawal for _, r in fresh), Decimal("0")),
    )
    db.add(statement)
    await db.flush()
    for k, r in fresh:
        db.add(BankStatementRow(
            statement_id=statement.id, tenant_id=current_user.tenant_id, created_by_id=current_user.id,
            line_no=r.line_no, tran_id=(r.tran_id or None) and r.tran_id[:50],
            value_date=r.value_date, txn_date=r.txn_date, posted_at=r.posted_at,
            cheque_ref=(r.cheque_ref or None) and r.cheque_ref[:100], remarks=r.remarks,
            withdrawal=r.withdrawal, deposit=r.deposit, balance=r.balance,
            direction=r.direction, counterparty=(r.counterparty or None) and r.counterparty[:255],
            payment_mode=r.payment_mode, reference=(r.reference or None) and r.reference[:100],
            dedupe_key=k, category=r.category,
        ))
    await db.commit()
    await db.refresh(statement)
    stats = (await _link_stats(db, current_user, [statement.id])).get(statement.id)
    return BankStatementUploadResult(
        statement=_statement_read(statement, stats), inserted=len(fresh),
        skipped_duplicates=skipped, ignored_lines=parsed.ignored_lines,
    )


@router.get("/", response_model=list[BankStatementRead])
async def list_statements(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statements = (await db.execute(
        select(BankStatement).where(_scope(current_user)).order_by(BankStatement.created_at.desc())
    )).scalars().all()
    stats = await _link_stats(db, current_user, [s.id for s in statements])
    return [_statement_read(s, stats.get(s.id)) for s in statements]


@router.get("/parties", response_model=list[PartyRef])
async def list_parties(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Everyone a deposit can be linked to, for the picker — corporates, employees, agencies."""
    parties = await _Parties.load(db, current_user)
    return sorted(parties.refs.values(), key=lambda p: (p.party_type, p.name.lower()))


@router.get("/summary", response_model=BilledReceivedSummary)
async def billed_vs_received(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What each party was billed, what they paid, and the difference.

    Billed is `billings.grand_total` — every saved invoice, filtered on its period end.
    Received is the deposits linked to a corporate or employee, and for an agency the
    money-in side of its ledger (bank-linked AND hand-entered receipts, net of reversals),
    filtered on the transaction date.
    """
    parties = await _Parties.load(db, current_user)

    bq = select(Billing.corporate_id, Billing.customer_id, Billing.agency_id,
                func.sum(Billing.grand_total), func.count()).where(
        Billing.tenant_id == current_user.tenant_id, Billing.created_by_id == current_user.id,
    )
    if date_from:
        bq = bq.where(Billing.period_to >= date_from)
    if date_to:
        bq = bq.where(Billing.period_to <= date_to)
    billed: dict[tuple[str, int], list] = {}
    for corp, cust, ag, total, n in (await db.execute(bq.group_by(Billing.corporate_id, Billing.customer_id, Billing.agency_id))).all():
        key = ("corporate", corp) if corp else ("customer", cust) if cust else ("agency", ag) if ag else None
        if key:
            billed[key] = [float(total or 0), n]

    received: dict[tuple[str, int], list] = {}
    rq = select(BankStatementRow.party_type, BankStatementRow.corporate_id, BankStatementRow.customer_id,
                func.sum(BankStatementRow.deposit), func.count()).where(
        _row_scope(current_user), BankStatementRow.party_type.in_(["corporate", "customer"]),
    )
    if date_from:
        rq = rq.where(BankStatementRow.txn_date >= date_from)
    if date_to:
        rq = rq.where(BankStatementRow.txn_date <= date_to)
    for ptype, corp, cust, total, n in (await db.execute(
        rq.group_by(BankStatementRow.party_type, BankStatementRow.corporate_id, BankStatementRow.customer_id)
    )).all():
        pid = corp if ptype == "corporate" else cust
        if pid:
            received[(ptype, pid)] = [float(total or 0), n]

    if parties.agencies:
        lq = select(AgencyLedger).where(AgencyLedger.agency_id.in_(list(parties.agencies)))
        entries = (await db.execute(lq)).scalars().all()
        by_id = {e.id: e for e in entries}
        for e in entries:
            if date_from and e.entry_date < date_from or date_to and e.entry_date > date_to:
                continue
            if e.entry_type in _MONEY_IN:
                amt, n = float(e.amount), 1
            elif e.entry_type == "reversal" and e.reversal_of_id in by_id \
                    and by_id[e.reversal_of_id].entry_type in _MONEY_IN:
                amt, n = float(e.amount), -1
            else:
                continue
            cur = received.setdefault(("agency", e.agency_id), [0.0, 0])
            cur[0] += amt
            cur[1] += n

    out = []
    for key in set(billed) | set(received):
        ref = parties.refs.get(key)
        if not ref:
            continue
        b, bn = billed.get(key, [0.0, 0])
        r, rn = received.get(key, [0.0, 0])
        if not b and not r:
            continue
        out.append(BilledReceivedRow(
            party=ref, billed=round(b, 2), invoices=bn, received=round(r, 2), receipts=max(rn, 0),
            outstanding=round(b - r, 2),
        ))
    out.sort(key=lambda x: (-x.outstanding, x.party.name.lower()))

    uq = select(func.count(), func.coalesce(func.sum(BankStatementRow.deposit), 0)).where(
        _row_scope(current_user), BankStatementRow.direction == "in",
        BankStatementRow.party_type.is_(None), BankStatementRow.category == "receipt",
    )
    if date_from:
        uq = uq.where(BankStatementRow.txn_date >= date_from)
    if date_to:
        uq = uq.where(BankStatementRow.txn_date <= date_to)
    ucount, uamount = (await db.execute(uq)).one()

    tb = round(sum(x.billed for x in out), 2)
    tr = round(sum(x.received for x in out), 2)
    return BilledReceivedSummary(
        rows=out, total_billed=tb, total_received=tr, total_outstanding=round(tb - tr, 2),
        unlinked_receipt_count=ucount, unlinked_receipt_amount=float(uamount),
    )


@router.patch("/rows/{row_id}", response_model=BankStatementRowRead)
async def update_row(
    row_id: int,
    payload: BankRowUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (await db.execute(
        select(BankStatementRow).where(BankStatementRow.id == row_id, _row_scope(current_user))
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Statement line not found")
    data = payload.model_dump(exclude_unset=True)
    parties = await _Parties.load(db, current_user)

    if "party_type" in data:
        if data["party_type"] is None:
            await _unlink(db, row, current_user)
        else:
            if data.get("party_id") is None:
                raise HTTPException(status_code=400, detail="party_id is required to link a line.")
            await _link(db, row, data["party_type"], data["party_id"], data.get("agency_channel"), parties, current_user)

    if "category" in data and data["category"] is not None:
        cat = data["category"]
        allowed = bs.IN_CATEGORIES if row.direction == "in" else bs.OUT_CATEGORIES
        if cat not in allowed:
            raise HTTPException(status_code=400, detail=f"A {'deposit' if row.direction == 'in' else 'withdrawal'} can be: {', '.join(sorted(allowed))}.")
        # A linked line IS a receipt; calling it anything else means it is no longer
        # money from that party.
        if cat != "receipt" and row.party_type:
            await _unlink(db, row, current_user)
        row.category = cat

    if "note" in data:
        row.note = (data["note"] or "").strip()[:255] or None

    await db.commit()
    await db.refresh(row)
    return _row_read(row, parties)


@router.get("/{statement_id}", response_model=BankStatementDetail)
async def get_statement(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    statement = await _owned(statement_id, db, current_user)
    rows = (await db.execute(
        select(BankStatementRow).where(BankStatementRow.statement_id == statement.id)
        .order_by(BankStatementRow.txn_date, BankStatementRow.posted_at, BankStatementRow.line_no, BankStatementRow.id)
    )).scalars().all()
    parties = await _Parties.load(db, current_user)
    history = await _history(db, current_user)
    stats = (await _link_stats(db, current_user, [statement.id])).get(statement.id)
    return BankStatementDetail(
        statement=_statement_read(statement, stats),
        rows=[_row_read(r, parties, _suggest(r, parties, history)) for r in rows],
        categories=bs.CATEGORIES,
    )


@router.post("/{statement_id}/accept-suggestions", response_model=AcceptSuggestionsResult)
async def accept_suggestions(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link every open deposit whose suggestion is strong: one learnt from an earlier
    link, or a name match of at least _AUTO_ACCEPT. Agencies are left for a click — a
    link there posts a receipt into their ledger, and may need a channel picked."""
    statement = await _owned(statement_id, db, current_user)
    rows = (await db.execute(
        select(BankStatementRow).where(
            BankStatementRow.statement_id == statement.id, BankStatementRow.direction == "in",
            BankStatementRow.party_type.is_(None), BankStatementRow.category == "receipt",
        )
    )).scalars().all()
    parties = await _Parties.load(db, current_user)
    history = await _history(db, current_user)
    linked = skipped = 0
    for row in rows:
        s = _suggest(row, parties, history)
        if not s or (s.source != "history" and s.score < _AUTO_ACCEPT):
            continue
        if s.party.party_type == "agency":
            skipped += 1
            continue
        await _link(db, row, s.party.party_type, s.party.party_id, None, parties, current_user)
        linked += 1
    await db.commit()
    return AcceptSuggestionsResult(linked=linked, skipped_agencies=skipped)


@router.delete("/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_statement(
    statement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Removes the statement and its lines. Receipts its lines posted to agency ledgers
    are REVERSED, not deleted — the ledger never loses an entry."""
    statement = await _owned(statement_id, db, current_user)
    posted = (await db.execute(
        select(BankStatementRow).where(
            BankStatementRow.statement_id == statement.id, BankStatementRow.agency_ledger_id.is_not(None),
        )
    )).scalars().all()
    for row in posted:
        await _reverse_ledger_receipt(db, row, current_user)
    await db.flush()
    await db.execute(delete(BankStatementRow).where(BankStatementRow.statement_id == statement.id))
    await db.delete(statement)
    await db.commit()
