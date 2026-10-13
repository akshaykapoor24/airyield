"""The sender registry: whose mail FareQube may read (architecture/04).

Built from the emails users typed while onboarding parties in User Master:

    Agency Master    (B2B)  agencies.contact_email   — scoped by agencies.user_id
    Corporate Master (B2E)  corporates.email         — scoped by tenant_id + created_by_id
    Employee Master  (B2C)  customers.email          — scoped by tenant_id + created_by_id

DERIVED FRESH ON EVERY SYNC, NOT STORED. A party onboarded a minute ago is a sender on the
next check, and a deactivated one stops being read, with no hooks to forget and no table to
drift. The masters are small enough that this is one cheap query each.

ADDRESSES AND THEIR DOMAINS (architecture/12 §12.8, question 2 — decided: domains). A large
agency mails from many people: the address typed in the master is one of them, while the
statement comes from accounts@ and the deal from a sales manager. So an onboarded address
also makes its domain a sender — onboarding rahul@acme.in reads mail from anyone@acme.in.
Three limits keep that to what the user meant:
  - a free-mail or ISP domain (gmail.com, rediffmail.com …) is never a domain sender, or one
    agency on Gmail would read everyone's Gmail. Those parties stay exact-address only;
  - nor is the workspace's own domain (its users' and the mailbox's), or every internal mail
    would arrive as if from that party;
  - an exact address beats a domain, and an agency or corporate owns its domain before a
    customer does. An employee's work domain is their corporate's (architecture/04 §4.6).
Subdomains are not covered: acme.in does not read mail.acme.in.

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

from app.core.email_domains import PUBLIC_EMAIL_DOMAINS
from app.models.agency import Agency
from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.user import User

PARTY_LABEL = {"agency": "B2B", "corporate": "B2E", "customer": "B2C"}

# Domains shared by unrelated people: one address there says nothing about anyone else on it.
# The signup list plus the Indian ISP and regional free-mail domains suppliers really use.
SHARED_DOMAINS: frozenset[str] = PUBLIC_EMAIL_DOMAINS | {
    "outlook.in", "live.in", "hotmail.in", "live.co.uk", "yahoo.co.uk", "zohomail.in",
    "sify.com", "vsnl.net", "vsnl.com", "bsnl.in", "indiatimes.com", "in.com",
    "googlegroups.com", "mail.ru", "yandex.ru", "qq.com", "163.com",
}

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


def domain_of(addr: str | None) -> str:
    """'Rahul@ACME.in' → 'acme.in'; '' when there is no '@'."""
    _, at, domain = (addr or "").rpartition("@")
    return domain.strip().lower() if at else ""


@dataclass(frozen=True)
class Party:
    party_type: str        # agency | corporate | customer
    party_id: int
    label: str             # what the inbox shows
    owner_user_id: int     # whose master it is in

    def as_dict(self, via: str | None = None) -> dict:
        return {"party_type": self.party_type, "party_id": self.party_id, "label": self.label,
                "owner_user_id": self.owner_user_id, "segment": PARTY_LABEL[self.party_type], "via": via}


def _add(bucket: dict[str, list[Party]], key: str, party: Party) -> None:
    parties = bucket.setdefault(key, [])
    if party not in parties:
        parties.append(party)


@dataclass
class Registry:
    by_address: dict[str, list[Party]] = field(default_factory=dict)
    by_domain: dict[str, list[Party]] = field(default_factory=dict)

    def add(self, addr: str, party: Party) -> None:
        _add(self.by_address, addr, party)

    def add_domain(self, domain: str, party: Party) -> None:
        _add(self.by_domain, domain, party)

    def match(self, addr: str | None) -> tuple[str | None, list[Party]]:
        """How `addr` is a sender — "address" or "domain" — and whose; (None, []) when it is not.
        The exact (or plus-tag base) address first: it names the party the user typed it on."""
        if not addr:
            return None, []
        addr = addr.lower()
        parties = self.by_address.get(addr) or self.by_address.get(base_address(addr))
        if parties:
            return "address", parties
        parties = self.by_domain.get(domain_of(addr))
        if parties:
            return "domain", parties
        return None, []

    def lookup(self, addr: str | None) -> list[Party]:
        return self.match(addr)[1]

    @property
    def search_terms(self) -> list[str]:
        """What to ask the mail server for: "@acme.in" per domain, plus every address no domain
        covers. IMAP's FROM is a substring match and Gmail's from: takes "@domain", so one term
        finds the whole company; the exact sender is re-checked after download either way."""
        terms = [f"@{d}" for d in self.by_domain]
        terms += [a for a in self.by_address if domain_of(a) not in self.by_domain]
        return sorted(terms)

    def __len__(self) -> int:
        return len(self.by_address) + len(self.by_domain)


def _agency_label(a: Agency) -> str:
    # The house label for agencies everywhere: name — branch · channel (see models/agency.py).
    branch = a.branch_name or a.branch_code
    return f"{a.name} — {branch} · {a.channels}" if branch else f"{a.name} · {a.channels}"


async def _own_domains(db: AsyncSession, tenant_id: int, mailbox_address: str | None) -> set[str]:
    """The workspace's own domains: its users' and the mailbox's. Never a domain sender."""
    emails = (await db.execute(select(User.email).where(User.tenant_id == tenant_id))).scalars().all()
    return {d for d in (domain_of(e) for e in [*emails, mailbox_address]) if d}


async def build(db: AsyncSession, tenant_id: int, owner_user_ids: list[int], *,
                mailbox_address: str | None = None) -> Registry:
    """The registry for these users' masters. A personal mailbox passes its owner; a shared
    workspace mailbox passes every user in the workspace."""
    reg = Registry()
    if not owner_user_ids:
        return reg

    blocked = SHARED_DOMAINS | await _own_domains(db, tenant_id, mailbox_address)

    def company_domain(addr: str) -> str | None:
        d = domain_of(addr)
        return d if d and d not in blocked else None

    # Who owns a domain: agencies and corporates first; a customer only where none of them does.
    org_domains: dict[str, list[Party]] = {}
    person_domains: dict[str, list[Party]] = {}

    agencies = (await db.execute(
        select(Agency).where(Agency.user_id.in_(owner_user_ids), Agency.is_active.is_(True))
    )).scalars().all()
    for a in agencies:
        party = Party("agency", a.id, _agency_label(a), a.user_id)
        for addr in extract_addresses(a.contact_email):
            reg.add(addr, party)
            if d := company_domain(addr):
                _add(org_domains, d, party)

    corporates = (await db.execute(
        select(Corporate).where(Corporate.tenant_id == tenant_id,
                                Corporate.created_by_id.in_(owner_user_ids),
                                Corporate.is_active.is_(True))
    )).scalars().all()
    corporate_emails: dict[int, set[str]] = {}
    corporate_party: dict[int, Party] = {}
    for c in corporates:
        party = corporate_party[c.id] = Party("corporate", c.id, c.company or "Corporate", c.created_by_id)
        addrs = extract_addresses(c.email)
        corporate_emails[c.id] = set(addrs)
        for addr in addrs:
            reg.add(addr, party)
            if d := company_domain(addr):
                _add(org_domains, d, party)

    customers = (await db.execute(
        select(Customer).where(Customer.tenant_id == tenant_id,
                               Customer.created_by_id.in_(owner_user_ids),
                               Customer.is_active.is_(True))
    )).scalars().all()
    for p in customers:
        inherited = corporate_emails.get(p.corporate_id or -1, set())
        employer = corporate_party.get(p.corporate_id or -1)
        name = " ".join(x for x in (p.first_name, p.last_name) if x) or "Customer"
        label = f"{name} ({p.company})" if p.company else name
        party = Party("customer", p.id, label, p.created_by_id)
        for addr in extract_addresses(p.email):
            if addr in inherited:
                continue      # the corporate's own address — its mail belongs to the corporate
            reg.add(addr, party)
            if d := company_domain(addr):
                # A colleague of an employee writes for the corporate, not for that employee.
                _add(org_domains if employer else person_domains, d, employer or party)

    for d, parties in org_domains.items():
        reg.by_domain[d] = parties
    for d, parties in person_domains.items():
        reg.by_domain.setdefault(d, parties)
    return reg
