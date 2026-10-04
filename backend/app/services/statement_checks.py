"""Payment Module steps 2, 3 and 5: is a loaded statement complete, and is it the vendor's?

Run per upload of a statement type that captures controls (tp-gds, mo-gds). Five checks,
each with its own status and a sentence a person can act on:

  rows        lines read from the file = rows saved = rows still present
  amount      opening + Σ ticket net = closing — the statement's own arithmetic (±₹1)
  continuity  this statement's opening = the previous statement's closing, same vendor —
              a gap means a statement in between was never loaded
  controls    the expected record count / net amount the uploader declared, if any
  vendor      (vendor statements) the file's Customer ID — your account at the vendor — is
              the one confirmed for the vendor chosen at upload, not another vendor's

Status per check: pass | fail | warn | na. Verdict per upload: `incomplete` if any check
fails, `attention` if any warns, `complete` if something passed, otherwise `unverified`.

The figures come from SQL aggregates over the statement rows plus the upload's control row
(models/statement_batch_control.py); the judgement is pure functions below, testable
without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, case, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_ledger import VendorAccount
from app.models.statement_batch_control import StatementBatchControl
from app.models.statement_batch_supplier import StatementBatchSupplier
from app.models.statement_row import STATEMENT_MODELS
from app.services import statement_balance

TOLERANCE = Decimal("1.00")
VENDOR_SLUG = "tp-gds"

PASS, FAIL, WARN, NA = "pass", "fail", "warn", "na"


def normalize_account(value) -> str | None:
    """'2102611', ' 2102611.0 ' → '2102611'. A spreadsheet's float cast is not an account."""
    if value is None:
        return None
    s = str(value).strip().upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s or None


def _money(v: Decimal | None) -> str:
    return "—" if v is None else f"₹{v.quantize(Decimal('0.01')):,}"


@dataclass
class BatchFacts:
    slug: str
    batch_id: str
    source_file: str | None = None
    uploaded_at: datetime | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None
    rows_now: int = 0
    ticket_rows: int = 0
    ticket_net: Decimal = Decimal("0")
    period_from: str | None = None
    period_to: str | None = None
    opening: Decimal | None = None
    opening_source: str | None = None       # file | user
    closing: Decimal | None = None
    # What the agency paid against the account in the period ("LESS PAYMENT" lines).
    payments: Decimal | None = None
    file_rows: int | None = None
    loaded_rows: int | None = None
    expected_count: int | None = None
    expected_amount: Decimal | None = None
    # normalised Customer ID → (name, ticket rows carrying it)
    accounts: dict[str, tuple[str | None, int]] = field(default_factory=dict)


def _check(key: str, label: str, status: str, detail: str, **extra) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, **extra}


def check_rows(f: BatchFacts) -> dict:
    present = f.rows_now
    if f.loaded_rows is None:
        return _check("rows", "Records", NA,
                      f"{f.ticket_rows} tickets loaded. This upload predates control figures, "
                      f"so the file's own line count was not recorded.")
    if present != f.loaded_rows:
        return _check("rows", "Records", FAIL,
                      f"{f.loaded_rows} rows were saved at upload but {present} are present now "
                      f"— rows were deleted or re-processed since.")
    if f.file_rows is not None and f.file_rows != f.loaded_rows:
        gap = f.file_rows - f.loaded_rows
        return _check("rows", "Records", WARN,
                      f"The file had {f.file_rows} lines; {f.loaded_rows} were saved. "
                      f"{gap} line{'s' if gap != 1 else ''} had no mapped values.")
    balance = f.rows_now - f.ticket_rows
    extra = ""
    if balance:
        extra = f" + {balance} balance line{'s' if balance != 1 else ''}"
    return _check("rows", "Records", PASS,
                  f"All {f.loaded_rows} lines saved — {f.ticket_rows} tickets{extra}.")


def check_amount(f: BatchFacts) -> dict:
    if f.closing is None:
        return _check("amount", "Amount", NA,
                      f"Σ ticket net {_money(f.ticket_net)}. The file prints no BALANCE line to "
                      f"check it against.")
    if f.opening is None:
        why = ("this upload predates opening-balance capture" if f.loaded_rows is None
               else "the file prints no opening (OLD) line")
        return _check("amount", "Amount", NA,
                      f"Closing balance {_money(f.closing)}, but {why} — enter the opening "
                      f"balance to verify the statement's arithmetic.", needs_opening=True)
    paid = f.payments or Decimal("0")
    expected = f.opening + f.ticket_net - paid
    diff = f.closing - expected
    sum_text = (f"Opening {_money(f.opening)} + tickets {_money(f.ticket_net)}"
                f"{f' − payments {_money(paid)}' if f.payments else ''}")
    if abs(diff) <= TOLERANCE:
        return _check("amount", "Amount", PASS, f"{sum_text} = closing {_money(f.closing)}.")
    return _check("amount", "Amount", FAIL,
                  f"{sum_text} = {_money(expected)}, but the statement closes at "
                  f"{_money(f.closing)} (difference {_money(diff)}) — lines are missing or "
                  f"extra.")


def check_continuity(f: BatchFacts, prev: BatchFacts | None,
                     copy: BatchFacts | None = None) -> dict:
    if copy is not None:
        # Comparing a second copy's opening with the first copy's closing would report a
        # missing statement that is not missing — say what it actually is.
        when = copy.uploaded_at.strftime("%d %b %Y") if copy.uploaded_at else "earlier"
        same_close = f.closing is not None and copy.closing is not None
        dup = (" Reconciliation flags this copy's tickets as duplicates."
               if f.slug == VENDOR_SLUG else "")
        return _check("continuity", "Continuity", WARN,
                      f"The same statement as {copy.source_file or copy.batch_id}, uploaded "
                      f"{when} — the same {f.ticket_rows} tickets and net"
                      f"{', closing at the same balance' if same_close else ''}. If it was "
                      f"loaded twice by mistake, delete one.{dup}")
    if prev is None:
        return _check("continuity", "Continuity", NA,
                      "No earlier statement from this vendor to chain to.")
    if prev.closing is None or f.opening is None:
        return _check("continuity", "Continuity", NA,
                      f"Previous statement: {prev.source_file or prev.batch_id}. "
                      f"{'It prints no closing balance.' if prev.closing is None else 'This one has no opening balance.'}")
    diff = f.opening - prev.closing
    prev_name = prev.source_file or "the previous statement"
    if abs(diff) <= TOLERANCE:
        return _check("continuity", "Continuity", PASS,
                      f"Opens at {_money(f.opening)}, where {prev_name} closed.")
    return _check("continuity", "Continuity", FAIL,
                  f"{prev.source_file or 'The previous statement'} closed at "
                  f"{_money(prev.closing)} but this one opens at {_money(f.opening)} "
                  f"(difference {_money(diff)}) — a statement in between may not be loaded.")


def check_controls(f: BatchFacts) -> dict:
    if f.expected_count is None and f.expected_amount is None:
        return _check("controls", "Control totals", NA,
                      "No expected record count or amount was entered for this upload.")
    problems, fine = [], []
    if f.expected_count is not None:
        (fine if f.expected_count == f.ticket_rows else problems).append(
            f"expected {f.expected_count} records, loaded {f.ticket_rows}")
    if f.expected_amount is not None:
        diff = f.ticket_net - f.expected_amount
        (fine if abs(diff) <= TOLERANCE else problems).append(
            f"expected {_money(f.expected_amount)}, loaded {_money(f.ticket_net)}")
    if problems:
        return _check("controls", "Control totals", FAIL, "; ".join(problems).capitalize() + ".")
    return _check("controls", "Control totals", PASS, "; ".join(fine).capitalize() + ".")


def check_vendor(f: BatchFacts, confirmed: dict[int, set[str]],
                 seen_elsewhere: dict[str, set[str]]) -> dict:
    """`confirmed`: supplier id → confirmed account ids. `seen_elsewhere`: account id →
    names of OTHER vendors whose statements carry it."""
    accounts = {a: v for a, v in f.accounts.items() if a}
    if not accounts:
        return _check("vendor", "Vendor", NA,
                      "This file prints no Customer ID, so the vendor cannot be verified "
                      "from its contents.")
    if len(accounts) > 1:
        listed = ", ".join(sorted(accounts))
        return _check("vendor", "Vendor", FAIL,
                      f"The file mixes several customer accounts ({listed}) — it may be more "
                      f"than one vendor's statement.")
    account, (name, _n) = next(iter(accounts.items()))
    shown = f"{account}{f' ({name})' if name else ''}"
    own = confirmed.get(f.supplier_id or -1, set())
    if account in own:
        return _check("vendor", "Vendor", PASS,
                      f"Customer ID {shown} is your confirmed account with "
                      f"{f.supplier_name or 'this vendor'}.", account=account)
    other_owner = [sid for sid, accs in confirmed.items() if account in accs and sid != f.supplier_id]
    if other_owner:
        return _check("vendor", "Vendor", FAIL,
                      f"Customer ID {shown} is confirmed for a different vendor — this file "
                      f"was probably uploaded under the wrong vendor.", account=account)
    if seen_elsewhere.get(account):
        names = ", ".join(sorted(seen_elsewhere[account]))
        return _check("vendor", "Vendor", FAIL,
                      f"Customer ID {shown} also appears on statements from {names} — check "
                      f"this was uploaded under the right vendor.", account=account)
    if own:
        return _check("vendor", "Vendor", FAIL,
                      f"{f.supplier_name or 'This vendor'}'s confirmed account is "
                      f"{', '.join(sorted(own))}, but this file is for {shown}.", account=account)
    return _check("vendor", "Vendor", WARN,
                  f"Customer ID {shown} has not been confirmed for "
                  f"{f.supplier_name or 'this vendor'} yet. Confirm it once and later "
                  f"statements are checked automatically.", account=account, confirmable=True)


def verdict(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    if FAIL in statuses:
        return "incomplete"
    if WARN in statuses:
        return "attention"
    if PASS in statuses:
        return "complete"
    return "unverified"


def evaluate(f: BatchFacts, prev: BatchFacts | None, confirmed: dict[int, set[str]],
             seen_elsewhere: dict[str, set[str]], copy: BatchFacts | None = None) -> dict:
    checks = [check_rows(f), check_amount(f), check_continuity(f, prev, copy), check_controls(f)]
    if f.slug == VENDOR_SLUG:
        checks.append(check_vendor(f, confirmed, seen_elsewhere))
    return {
        "batch_id": f.batch_id,
        "slug": f.slug,
        "verdict": verdict(checks),
        "checks": checks,
        "figures": {
            "file_rows": f.file_rows, "loaded_rows": f.loaded_rows, "rows_now": f.rows_now,
            "ticket_rows": f.ticket_rows, "ticket_net": str(f.ticket_net),
            "opening": str(f.opening) if f.opening is not None else None,
            "opening_source": f.opening_source,
            "closing": str(f.closing) if f.closing is not None else None,
            "payments": str(f.payments) if f.payments is not None else None,
            "expected_count": f.expected_count,
            "expected_amount": str(f.expected_amount) if f.expected_amount is not None else None,
            "period_from": f.period_from, "period_to": f.period_to,
            "accounts": [{"account": a, "name": n, "rows": c} for a, (n, c) in f.accounts.items()],
        },
    }


def same_statement(a: BatchFacts, b: BatchFacts) -> bool:
    """Two uploads of ONE statement: the same tickets adding to the same net, closing at the
    same balance when both print one (else covering the same days).

    Content, not dates: a refund carries its original issue date, so consecutive statements'
    periods overlap routinely and an overlap proves nothing.
    """
    if not a.ticket_rows or a.ticket_rows != b.ticket_rows \
            or abs(a.ticket_net - b.ticket_net) > TOLERANCE:
        return False
    if a.closing is not None and b.closing is not None:
        return abs(a.closing - b.closing) <= TOLERANCE
    return (a.period_from, a.period_to) == (b.period_from, b.period_to)


def _same_vendor(f: BatchFacts, o: BatchFacts) -> bool:
    return o.batch_id != f.batch_id and f.supplier_id is not None and o.supplier_id == f.supplier_id


def copy_of(f: BatchFacts, others: list[BatchFacts]) -> BatchFacts | None:
    """The earlier upload this one repeats — the same vendor's same statement — if any."""
    def uploaded(x: BatchFacts):
        return x.uploaded_at or datetime.min

    earlier = [o for o in others
               if _same_vendor(f, o) and uploaded(o) < uploaded(f) and same_statement(o, f)]
    return min(earlier, key=uploaded) if earlier else None


def previous_of(f: BatchFacts, others: list[BatchFacts]) -> BatchFacts | None:
    """The same vendor's statement immediately before this one: by period, then upload.
    Another copy of this very statement is not its predecessor (`copy_of`)."""
    def when(x: BatchFacts):
        return (x.period_to or "", x.uploaded_at or datetime.min)

    earlier = [o for o in others
               if _same_vendor(f, o) and when(o) < when(f) and not same_statement(o, f)]
    return max(earlier, key=when) if earlier else None


# ── loading ──────────────────────────────────────────────────────────────────
def _num(model, key: str):
    col = model.data[key].astext
    return case((col.op("~")(r"^-?\d+(\.\d+)?$"), cast(col, Numeric)), else_=0)


async def load_facts(db: AsyncSession, slug: str, tenant_id: int, user_id: int,
                     batch_ids: list[str] | None = None) -> dict[str, BatchFacts]:
    """Facts for the given uploads of one type (all of the user's uploads when None)."""
    m = STATEMENT_MODELS[slug]
    scope = [m.tenant_id == tenant_id, m.created_by_id == user_id]
    if batch_ids:
        scope.append(m.batch_id.in_(batch_ids))
    is_ticket = m.data[statement_balance.ROW_KIND_KEY].astext.is_(None)

    facts: dict[str, BatchFacts] = {}
    for r in (await db.execute(
        select(m.batch_id, func.max(m.source_file), func.max(m.uploaded_at), func.count(),
               func.count().filter(is_ticket), func.sum(_num(m, "net_amount")).filter(is_ticket),
               func.min(m.data["issue_date"].astext).filter(is_ticket),
               func.max(m.data["issue_date"].astext).filter(is_ticket))
        .where(*scope).group_by(m.batch_id)
    )).all():
        facts[r[0]] = BatchFacts(
            slug=slug, batch_id=r[0], source_file=r[1], uploaded_at=r[2], rows_now=r[3] or 0,
            ticket_rows=r[4] or 0, ticket_net=Decimal(r[5] or 0),
            period_from=r[6], period_to=r[7])
    if not facts:
        return facts
    ids = list(facts)

    lines: dict[str, list] = {}
    for batch_id, data in (await db.execute(
        select(m.batch_id, m.data).where(*scope, m.batch_id.in_(ids), ~is_ticket)
        .order_by(m.id.asc())
    )).all():
        lines.setdefault(batch_id, []).append(
            ((data or {}).get(statement_balance.ROW_KIND_KEY), (data or {}).get("net_amount")))
    for batch_id, kinds in lines.items():
        fig = statement_balance.account_figures(kinds)
        f = facts[batch_id]
        f.closing, f.payments = fig["closing"], fig["payments"]
        if fig["opening"] is not None:
            f.opening, f.opening_source = fig["opening"], "file"

    for ctl in (await db.execute(
        select(StatementBatchControl).where(
            StatementBatchControl.slug == slug, StatementBatchControl.batch_id.in_(ids),
            StatementBatchControl.tenant_id == tenant_id)
    )).scalars().all():
        f = facts[ctl.batch_id]
        f.file_rows, f.loaded_rows = ctl.file_rows, ctl.loaded_rows
        f.expected_count = ctl.expected_count
        f.expected_amount = Decimal(ctl.expected_amount) if ctl.expected_amount is not None else None
        if f.opening is None and ctl.opening_balance is not None:
            f.opening, f.opening_source = Decimal(ctl.opening_balance), ctl.opening_source
        if f.closing is None and ctl.closing_balance is not None:
            f.closing = Decimal(ctl.closing_balance)

    for link in (await db.execute(
        select(StatementBatchSupplier).where(
            StatementBatchSupplier.slug == slug, StatementBatchSupplier.batch_id.in_(ids),
            StatementBatchSupplier.tenant_id == tenant_id)
    )).scalars().all():
        facts[link.batch_id].supplier_id = link.supplier_id
        facts[link.batch_id].supplier_name = link.supplier_name

    # Inlined, not bound: a bound key renders as two different parameters in SELECT and
    # GROUP BY, which Postgres then refuses to treat as the same expression.
    acct_col = literal_column(f"{m.__tablename__}.data ->> 'customer_id'")
    for batch_id, acct, name, n in (await db.execute(
        select(m.batch_id, acct_col, func.max(m.data["customer_name"].astext), func.count())
        .where(*scope, m.batch_id.in_(ids), is_ticket)
        .group_by(m.batch_id, acct_col)
    )).all():
        a = normalize_account(acct)
        if a:
            prev_name, prev_n = facts[batch_id].accounts.get(a, (None, 0))
            facts[batch_id].accounts[a] = (prev_name or name, prev_n + (n or 0))
    return facts


async def check_uploads(db: AsyncSession, slug: str, tenant_id: int, user_id: int,
                        batch_ids: list[str] | None = None) -> dict[str, dict]:
    """The checks for the given uploads, keyed by batch id."""
    everything = await load_facts(db, slug, tenant_id, user_id, None)
    wanted = [b for b in (batch_ids or list(everything)) if b in everything]

    confirmed: dict[int, set[str]] = {}
    for sid, acct in (await db.execute(
        select(VendorAccount.supplier_id, VendorAccount.account_id).where(
            VendorAccount.tenant_id == tenant_id, VendorAccount.created_by_id == user_id)
    )).all():
        confirmed.setdefault(sid, set()).add(acct)

    vendor_facts = everything if slug == VENDOR_SLUG else {}
    out: dict[str, dict] = {}
    others = list(everything.values())
    for b in wanted:
        f = everything[b]
        seen: dict[str, set[str]] = {}
        for o in vendor_facts.values():
            if o.supplier_id is None or o.supplier_id == f.supplier_id:
                continue
            for a in o.accounts:
                seen.setdefault(a, set()).add(o.supplier_name or f"vendor #{o.supplier_id}")
        out[b] = evaluate(f, previous_of(f, others), confirmed, seen, copy=copy_of(f, others))
        out[b]["supplier_id"] = f.supplier_id
        out[b]["supplier_name"] = f.supplier_name
        out[b]["source_file"] = f.source_file
    return out
