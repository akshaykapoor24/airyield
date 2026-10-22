"""Who a statement file is for — read off its file name and the lines above its header.

Internal Statement → Upload Statement asks who the tickets were sold to. The file usually
says: "GLOBE 01 AUG TO 31 AUG.xls" is Globe Air Travels' statement, and its own title lines
("GLOBE ALL INDIA SERVICES LIMITED - (WEST BENGAL)") say it again. This reads that and
proposes the customer — a SUGGESTION the upload page pre-selects, which the user sees and
can change; the save still authorises whatever is picked
(api/v1/tickets.py::_resolve_customer_party).

WHO CAN BE PROPOSED: the user's own active agencies (B2B — Agency Master) and corporates
(B2E — Corporate Master). Never a Direct customer: a person's name in a file name is
exactly where a guess goes wrong (services/customer_resolver.py says why it never guesses).

HOW A NAME IS FOUND: services/deal_supplier_check.py's rule, which already reads deal sheets
for their supplier — a company is named when ALL of its distinctive words appear as whole
words ("Globe Air Travels" → "globe", "Akbar Travels of India" → "akbar"), or its whole
name is written without spaces. No similarity scores: a near miss is not proposed.

DECIDING, strongest evidence first:
  1. the file name — exactly one company (all its branches and channels together) named
     there is the answer;
  2. else the lines above the header, under the same rule;
  3. two or more companies named at the same level is AMBIGUOUS, and the page asks.
The workspace's own name, and the words every statement's name is made of ("STATEMENT",
"BSP", month names), are taken out of the text first: "TRIUMPHH BSP STATEMENT 08-15TH AUG"
names the tenant and the paperwork, not a customer.

WHICH ROW OF THE COMPANY: one agency is onboarded once per branch and per channel, so
"Globe Air Travels" can be several Agency Master rows. One is picked only when exactly one
fits, by, in order: the row this user filed the company's statements under last time; a
branch, city or state named in the text ("(WEST BENGAL)"); there being only one row. Else
the rows go back as candidates for the user to choose from.

Pure core (`identify`) over plain rows, so it is tested without a database; `load` and
`guess` read the rows.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import deal_supplier_check as dsc
from app.services import statement_period
from app.services.party_dedupe import name_key

RESOLVED, AMBIGUOUS, UNRESOLVED = "resolved", "ambiguous", "unresolved"

# The vocabulary of a statement's own name and title — never a customer's distinctive word.
_PAPERWORK = {
    "statement", "statements", "stmt", "stmnt", "statment", "account", "accounts", "ledger",
    "report", "summary", "invoice", "invoices", "bill", "bills", "billing", "sale", "sales",
    "ticket", "tickets", "bsp", "gds", "lcc", "ndc", "our", "copy", "final", "revised",
    "updated", "week", "weekly", "month", "monthly", "period", "from", "to", "till", "upto",
    "inr", "total",
}


@dataclass(frozen=True)
class PartyRow:
    """A master row that could be the customer."""
    customer_type: str                 # agency | corporate
    id: int
    name: str
    places: tuple[str, ...] = ()       # branch name, city, state — what tells branches apart


@dataclass(frozen=True)
class PastUpload:
    """An earlier statement of this user's, newest first: who it was filed under."""
    customer_type: str
    party_id: int


@dataclass
class PartyGuess:
    status: str = UNRESOLVED
    customer_type: str | None = None
    party_id: int | None = None
    name: str | None = None
    candidates: list[dict] = field(default_factory=list)   # [{customer_type, id, name}]
    source: str | None = None          # "file name" | "statement header"
    narrowed_by: str | None = None     # "previous upload" | "branch" | None
    matched: str | None = None         # the words found, as written in the file

    def as_dict(self) -> dict:
        return {
            "status": self.status, "customer_type": self.customer_type, "id": self.party_id,
            "name": self.name, "candidates": self.candidates, "source": self.source,
            "narrowed_by": self.narrowed_by, "matched": self.matched,
        }


def _clean(text: str, own_names: list[str]) -> str:
    """Lower-cased, with the workspace's own name — whole, and each of its distinctive words,
    since a file name carries "TRIUMPHH" rather than "Triumphh Travel N More Pvt Ltd" — the
    month names and the paperwork vocabulary blanked out."""
    own = [n for n in own_names if n]
    out = dsc.strip_airlines(text or "", own)
    out = re.sub(rf"(?<![a-z]){statement_period.MON}", " ", out, flags=re.I)
    drop = _PAPERWORK | {w for n in own for w in dsc.distinctive(n)}
    return " ".join(w for w in re.findall(r"[a-z0-9]+", out) if w not in drop)


def _named_words(name: str, text: str) -> str | None:
    """The candidate's words as they appear in `text` — for the note the page shows."""
    toks = dsc.distinctive(name)
    found = [w for w in toks if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text)]
    return " ".join(found).upper() if found else None


def _place_named(place: str, words: set[str]) -> bool:
    toks = [w for w in re.findall(r"[a-z0-9]+", (place or "").lower()) if len(w) >= 3]
    return bool(toks) and all(t in words for t in toks)


def _narrow(members: list[PartyRow], past: list[PastUpload], text: str) -> tuple[PartyRow | None, str | None]:
    if len(members) == 1:
        return members[0], None
    ids = {m.id for m in members}
    ct = members[0].customer_type
    for p in past:                                   # newest first
        if p.customer_type == ct and p.party_id in ids:
            return next(m for m in members if m.id == p.party_id), "previous upload"
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    placed = [m for m in members if any(_place_named(pl, words) for pl in m.places)]
    if len(placed) == 1:
        return placed[0], "branch"
    return None, None


def _candidates(members: list[PartyRow]) -> list[dict]:
    return [{"customer_type": m.customer_type, "id": m.id, "name": m.name} for m in members]


def identify(file_name: str | None, preamble: list[str] | None, rows: list[PartyRow],
             past: list[PastUpload] = (), own_names: list[str] = ()) -> PartyGuess:
    """The customer a statement file names — see the module docstring."""
    stem = statement_period.file_stem(file_name)
    raw_body = " \n ".join(str(p) for p in (preamble or []) if p)
    head_text, body_text = _clean(stem, list(own_names)), _clean(raw_body, list(own_names))
    head, body = dsc.Indexed(head_text), dsc.Indexed(body_text)

    groups: dict[tuple[str, str], list[PartyRow]] = defaultdict(list)
    for r in rows:
        if r.name and r.name.strip():
            groups[(r.customer_type, name_key(r.name))].append(r)

    in_head, in_body = [], []
    for key, members in groups.items():
        ev = dsc.find(dsc.Candidate(label=members[0].name, name=members[0].name), head, body)
        if ev.strong:
            in_head.append(key)
        elif ev.hits:
            in_body.append(key)

    keys, source = (in_head, "file name") if in_head else (in_body, "statement header")
    if not keys:
        return PartyGuess(UNRESOLVED)
    if len(keys) > 1:
        members = [m for k in keys for m in groups[k]]
        types = {m.customer_type for m in members}
        return PartyGuess(AMBIGUOUS, customer_type=types.pop() if len(types) == 1 else None,
                          candidates=_candidates(members), source=source)

    members = groups[keys[0]]
    pick, how = _narrow(members, list(past), f"{head_text} {body_text}")
    matched = _named_words(members[0].name, head_text if source == "file name" else body_text)
    if pick is None:
        return PartyGuess(AMBIGUOUS, customer_type=members[0].customer_type, name=members[0].name,
                          candidates=_candidates(members), source=source, matched=matched)
    return PartyGuess(RESOLVED, customer_type=pick.customer_type, party_id=pick.id, name=pick.name,
                      candidates=_candidates(members) if len(members) > 1 else [],
                      source=source, narrowed_by=how, matched=matched)


# ── reading the rows ─────────────────────────────────────────────────────────
async def load(db: AsyncSession, user, statements) -> tuple[list[PartyRow], list[PastUpload], list[str]]:
    """The user's active agencies and corporates, their latest statements (newest first,
    from `statements` — the section's model) and the workspace's own name."""
    from app.models.agency import Agency
    from app.models.corporate import Corporate
    from app.models.tenant import Tenant

    rows: list[PartyRow] = []
    for id_, name, branch, city, state in (await db.execute(
        select(Agency.id, Agency.name, Agency.branch_name, Agency.city, Agency.state)
        .where(Agency.user_id == user.id, Agency.is_active.isnot(False))
    )).all():
        rows.append(PartyRow("agency", id_, name, tuple(p for p in (branch, city, state) if p)))
    for id_, company, city, state in (await db.execute(
        select(Corporate.id, Corporate.company, Corporate.city, Corporate.state)
        .where(Corporate.tenant_id == user.tenant_id, Corporate.created_by_id == user.id,
               Corporate.is_active.isnot(False), Corporate.company.isnot(None))
    )).all():
        rows.append(PartyRow("corporate", id_, company, tuple(p for p in (city, state) if p)))

    S = statements
    past: list[PastUpload] = []
    for ct, agency_id, corporate_id in (await db.execute(
        select(S.customer_type, S.customer_agency_id, S.corporate_id)
        .where(S.tenant_id == user.tenant_id, S.created_by_id == user.id,
               S.customer_type.in_(("agency", "corporate")), S.file_name != "Manual Entry")
        .order_by(S.created_at.desc()).limit(200)
    )).all():
        pid = agency_id if ct == "agency" else corporate_id
        if pid is not None:
            past.append(PastUpload(ct, pid))

    tenant_name = (await db.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))).scalar_one_or_none()
    return rows, past, [tenant_name] if tenant_name else []


async def guess(db: AsyncSession, user, file_name: str | None, preamble: list[str] | None, *,
                statements) -> PartyGuess:
    rows, past, own = await load(db, user, statements)
    return identify(file_name, preamble, rows, past, own)
