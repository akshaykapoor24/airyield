"""The sender registry: which addresses' mail FareQube may read (architecture/04).

Built from the emails users typed while onboarding parties in User Master:

    Agency Master    (B2B)  agencies.contact_email   — scoped by agencies.user_id
    Corporate Master (B2E)  corporates.email         — scoped by tenant_id + created_by_id
    Employee Master  (B2C)  customers.email          — scoped by tenant_id + created_by_id

DERIVED FRESH ON EVERY SYNC, NOT STORED. A party onboarded a minute ago is a sender on the
next check, and a deactivated one stops being read, with no hooks to forget and no table to
drift. The masters are small enough that this is one cheap query each.

EXACT ADDRESSES ONLY. A domain rule ("anyone @consolidator.in") reads more than the user
typed, so it waits for the user's explicit choice (architecture/12 §12.8, question 2).

MESSY CELLS. `agencies.contact_email` is Text because the supplier directory packs several
addresses into one cell ("rahul@acme.in, accounts@acme.in / 98xxxxxxxx", "NA"), so addresses
are extracted, not assumed. An employee who inherited the corporate's email is not a sender
of their own: mail from that address is the corporate's.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agency import Agency
from app.models.corporate import Corporate
from app.models.customer import Customer

PARTY_LABEL = {"agency": "B2B", "corporate": "B2E", "customer": "B2C"}

_EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+")


def extract_addresses(cell: str | None) -> list[str]:
    """Every address in a free-text master cell, lowercased, de-duplicated, in order."""
    if not cell:
        return []
    seen: list[str] = []
    for m in _EMAIL_RE.findall(cell):
        addr = m.strip(".").lower()
        if addr not in seen:
            seen.append(addr)
    return seen


def base_address(addr: str) -> str:
    """'accounts+stmt@acme.in' → 'accounts@acme.in'. Plus-tags route mail, they do not change who sent it."""
    local, _, domain = addr.partition("@")
    return f"{local.split('+', 1)[0]}@{domain}"


@dataclass(frozen=True)
class Party:
    party_type: str        # agency | corporate | customer
    party_id: int
    label: str             # what the inbox shows
    owner_user_id: int     # whose master it is in

    def as_dict(self) -> dict:
        return {"party_type": self.party_type, "party_id": self.party_id, "label": self.label,
                "owner_user_id": self.owner_user_id, "segment": PARTY_LABEL[self.party_type]}


@dataclass
class Registry:
    by_address: dict[str, list[Party]] = field(default_factory=dict)

    def add(self, addr: str, party: Party) -> None:
        bucket = self.by_address.setdefault(addr, [])
        if party not in bucket:
            bucket.append(party)

    def lookup(self, addr: str | None) -> list[Party]:
        if not addr:
            return []
        addr = addr.lower()
        return self.by_address.get(addr) or self.by_address.get(base_address(addr)) or []

    @property
    def addresses(self) -> list[str]:
        return sorted(self.by_address)

    def __len__(self) -> int:
        return len(self.by_address)


def _agency_label(a: Agency) -> str:
    # The house label for agencies everywhere: name — branch · channel (see models/agency.py).
    branch = a.branch_name or a.branch_code
    return f"{a.name} — {branch} · {a.channels}" if branch else f"{a.name} · {a.channels}"


async def build(db: AsyncSession, tenant_id: int, owner_user_ids: list[int]) -> Registry:
    """The registry for these users' masters. A personal mailbox passes its owner; a shared
    workspace mailbox passes every user in the workspace."""
    reg = Registry()
    if not owner_user_ids:
        return reg

    agencies = (await db.execute(
        select(Agency).where(Agency.user_id.in_(owner_user_ids), Agency.is_active.is_(True))
    )).scalars().all()
    for a in agencies:
        for addr in extract_addresses(a.contact_email):
            reg.add(addr, Party("agency", a.id, _agency_label(a), a.user_id))

    corporates = (await db.execute(
        select(Corporate).where(Corporate.tenant_id == tenant_id,
                                Corporate.created_by_id.in_(owner_user_ids),
                                Corporate.is_active.is_(True))
    )).scalars().all()
    corporate_emails: dict[int, set[str]] = {}
    for c in corporates:
        addrs = extract_addresses(c.email)
        corporate_emails[c.id] = set(addrs)
        for addr in addrs:
            reg.add(addr, Party("corporate", c.id, c.company or "Corporate", c.created_by_id))

    customers = (await db.execute(
        select(Customer).where(Customer.tenant_id == tenant_id,
                               Customer.created_by_id.in_(owner_user_ids),
                               Customer.is_active.is_(True))
    )).scalars().all()
    for p in customers:
        inherited = corporate_emails.get(p.corporate_id or -1, set())
        name = " ".join(x for x in (p.first_name, p.last_name) if x) or "Customer"
        label = f"{name} ({p.company})" if p.company else name
        for addr in extract_addresses(p.email):
            if addr in inherited:
                continue      # the corporate's own address — its mail belongs to the corporate
            reg.add(addr, Party("customer", p.id, label, p.created_by_id))
    return reg
