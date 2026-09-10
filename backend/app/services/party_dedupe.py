"""One party, one row — the duplicate rule behind Employee Master and Corporate Master.

WHY IT IS NOT "every column must differ". The two masters are LINKED
(models/customer.py): an employee belongs to a corporate, and services/party_inherit
copies that corporate's phone, email, GSTIN, PAN, markup and billing type onto every
employee under it. Fifty people at one company are therefore SUPPOSED to share those
eight values, so not one of them can identify a person. What identifies an employee is
their NAME under a given EMPLOYER, and that pair is what this refuses twice.

A CORPORATE is identified by either of two things, each enough on its own:

  * its NAME, because that is what the employee import matches on. Two corporates of one
    name make api/v1/customers.py::_corporate_name_map resolve to the lower id and file
    half a company's staff under the wrong one — silently, and on the link that decides
    whose invoice a ticket lands on.
  * its GSTIN, because a GST registration belongs to exactly one entity. Two corporates
    holding one are the same corporate entered twice, whatever they are called.

Scope is per workspace — tenant_id + created_by_id, the pair everything else in these
routers filters by. Another agency's "Acme Pvt Ltd" is not yours and never collides.

BOTH ENTRY POINTS COME THROUGH HERE. The Add/Edit form sends one row and gets a 409; the
Excel import sends many and each is reported against its own row number while the rest
still save. The import also has to catch a FILE THAT REPEATS ITSELF, which no query can
see — hence `claim`: an identity is taken by whichever row used it first, whether that
row is already in the database or three lines further up the sheet.

Nothing here deletes or merges anything. A duplicate is refused, never resolved.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate import Corporate
from app.models.customer import Customer
from app.models.user import User

__all__ = [
    "name_key", "code_key", "employer_key",
    "CustomerDuplicates", "CorporateDuplicates",
]


def name_key(value) -> str:
    """`"  Acme   Pvt Ltd "` → `"acme pvt ltd"`. The one spelling a name is compared under.

    LOWER + collapsed whitespace, matching the backfill in migration corp_link_01 and the
    employer matcher it became (api/v1/customers.py::_company_key, which now delegates
    here). The two must agree: a name the import treats as the same corporate has to be
    the name this treats as the same corporate.
    """
    return " ".join(str(value or "").split()).lower()


def code_key(value) -> str:
    """A GSTIN or PAN reduced to how it is stored — upper, unpadded. `""` when absent."""
    return str(value or "").strip().upper()


def employer_key(corporate_id: Optional[int], company) -> str:
    """WHO THEY WORK FOR, as one comparable string.

    A linked employee is keyed by the corporate's id; an unlinked one by the free text
    they named. `"name:"` — individual / direct — is a real employer value rather than a
    missing one, exactly as `corporate_id IS NULL` is on the column itself, so two
    unlinked people of the same name DO collide with each other.

    An id and a name never collide even when they are the same company: an unlinked row
    that happens to spell out a corporate's name is what the Re-link action exists to
    fix, and refusing to save it would leave the user with no way to get there.
    """
    if corporate_id is not None:
        return f"corp:{corporate_id}"
    return f"name:{name_key(company)}"


def _employer_phrase(company) -> str:
    """How a duplicate message names the employer. Blank is a state, so it is named too."""
    label = str(company or "").strip()
    return f"under {label}" if label else "as an individual / direct customer"


def _person_label(first_name, last_name) -> str:
    return " ".join(f"{first_name or ''} {last_name or ''}".split()) or "This employee"


class _Register:
    """Identities already taken, and the ones the current request takes as it runs.

    `_existing` is the workspace as it stands, loaded once — the import used to run a
    SELECT per row and a master is small enough to hold whole. `_claimed` is this
    request's own rows, which is the only way a file that lists the same party twice can
    be caught at all.
    """

    def __init__(self, existing: dict[tuple, str]):
        self._existing: dict[tuple, str] = existing
        self._claimed: dict[tuple, str] = {}

    def _holder(self, key: tuple, exclude: Optional[tuple]) -> Optional[tuple[str, str]]:
        """`(where, label)` for whoever holds `key` — 'master' or 'file' — else None."""
        if exclude is not None and key == exclude:
            return None                       # the row being edited is not its own duplicate
        if key in self._existing:
            return ("master", self._existing[key])
        if key in self._claimed:
            return ("file", self._claimed[key])
        return None

    def _claim(self, keys: list[tuple], label: str) -> None:
        for key in keys:
            self._claimed.setdefault(key, label)


class CustomerDuplicates(_Register):
    """The employee identity register: one NAME per EMPLOYER, per workspace.

    Deliberately NOT keyed on email, phone, GSTIN or PAN. All four are inherited from the
    corporate (services/party_inherit), so every employee of one company legitimately
    carries the same values — keying on any of them would reject the second colleague
    imported under a company that fills its staff's blanks, which is the normal case.
    """

    @classmethod
    async def load(cls, db: AsyncSession, current_user: User) -> "CustomerDuplicates":
        return cls.from_rows((await db.execute(
            select(Customer.first_name, Customer.last_name, Customer.corporate_id, Customer.company)
            .where(
                Customer.tenant_id == current_user.tenant_id,
                Customer.created_by_id == current_user.id,
            )
            # Ordered by id so a workspace that ALREADY holds duplicates — nothing
            # enforced this before — reports the first of them, not an arbitrary one.
            .order_by(Customer.id.asc())
        )).all())

    @classmethod
    def from_rows(cls, rows) -> "CustomerDuplicates":
        """`(first_name, last_name, corporate_id, company)` per employee, oldest first."""
        existing: dict[tuple, str] = {}
        for first_name, last_name, corporate_id, company in rows:
            key = cls.key(first_name, last_name, corporate_id, company)
            existing.setdefault(key, _person_label(first_name, last_name))
        return cls(existing)

    @staticmethod
    def key(first_name, last_name, corporate_id: Optional[int], company) -> tuple:
        return ("person", name_key(f"{first_name or ''} {last_name or ''}"),
                employer_key(corporate_id, company))

    def check(
        self,
        first_name, last_name,
        corporate_id: Optional[int],
        company,
        *,
        exclude: Optional[tuple] = None,
        claim: bool = True,
    ) -> Optional[str]:
        """Why this employee cannot be saved, or None — and on None, the identity is taken.

        `exclude` is the key the row being edited already holds, so an edit that does not
        move the person is not read as a clash with themselves. `claim=False` is for the
        checks that run before a row is known to be saveable for other reasons.
        """
        key = self.key(first_name, last_name, corporate_id, company)
        held = self._holder(key, exclude)
        if held is None:
            if claim:
                self._claim([key], _person_label(first_name, last_name))
            return None

        where, _ = held
        who = _person_label(first_name, last_name)
        where_phrase = _employer_phrase(company)
        if where == "file":
            return (
                f"{who} is listed more than once in this file {where_phrase}. "
                "Only the first one is saved."
            )
        return (
            f"{who} already exists in Employee Master {where_phrase}. "
            "Give them a last name, or a different employer, to tell the two apart."
        )


class CorporateDuplicates(_Register):
    """The corporate identity register: one NAME and one GSTIN per workspace.

    Two facets, each decisive on its own, so the message can say WHICH one clashed —
    "you already have this company" and "you already have this GST number under another
    name" are different mistakes with different fixes.
    """

    @classmethod
    async def load(cls, db: AsyncSession, current_user: User) -> "CorporateDuplicates":
        return cls.from_rows((await db.execute(
            select(Corporate.company, Corporate.gst_no)
            .where(
                Corporate.tenant_id == current_user.tenant_id,
                Corporate.created_by_id == current_user.id,
            )
            .order_by(Corporate.id.asc())
        )).all())

    @classmethod
    def from_rows(cls, rows) -> "CorporateDuplicates":
        """`(company, gst_no)` per corporate, oldest first."""
        existing: dict[tuple, str] = {}
        for company, gst_no in rows:
            label = (company or "").strip() or "an unnamed corporate"
            for key in cls.keys(company, gst_no):
                existing.setdefault(key, label)
        return cls(existing)

    @staticmethod
    def keys(company, gst_no) -> list[tuple]:
        """Every identity this corporate occupies. A blank GSTIN occupies none."""
        keys: list[tuple] = []
        company_key = name_key(company)
        if company_key:
            keys.append(("name", company_key))
        gst = code_key(gst_no)
        if gst:
            keys.append(("gstin", gst))
        return keys

    def check(
        self,
        company,
        gst_no,
        *,
        exclude: Optional[list[tuple]] = None,
        claim: bool = True,
    ) -> Optional[str]:
        """Why this corporate cannot be saved, or None — and on None, its identities are taken.

        `exclude` is the set of keys the row being edited already holds: an edit that
        keeps the same name or the same GSTIN is not a clash with itself, and each facet
        is excused independently so renaming one while keeping the other still works.
        """
        excluded = set(exclude or ())
        keys = self.keys(company, gst_no)
        for key in keys:
            held = self._holder(key, key if key in excluded else None)
            if held is None:
                continue
            where, label = held
            facet, value = key
            if facet == "name":
                subject = f"{(company or '').strip()}"
                return (
                    f"{subject} is listed more than once in this file. Only the first one is saved."
                    if where == "file" else
                    f"{subject} is already in Corporate Master. Corporate names must be unique — "
                    "the employee import links people to their employer by this name."
                )
            return (
                f"GST No {value} is used more than once in this file — on {label} as well. "
                "Only the first one is saved."
                if where == "file" else
                f"GST No {value} is already in Corporate Master, on {label}. "
                "A GST registration belongs to one entity, so this is that corporate again."
            )

        if claim:
            self._claim(keys, (company or "").strip() or "an unnamed corporate")
        return None
