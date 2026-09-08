"""Validating the Agency Master row a third-party statement upload is attributed to.

A consolidator statement never names its sender — the sample GDS export's "Customer Name"
is the tenant's own name, as the consolidator's customer — so the uploader declares it,
exactly as they declare the carrier on an LCC export. Without it the B2B supplier guard in
`services/deal_matching.py` has nothing to compare against and every row comes back
unmatched.

**The chosen agency must trade on this statement's channel.** That is not a tidiness rule.
`models/agency.py` explains the trap it closes: a vendor working both channels is onboarded
TWICE, one row per channel, with the SAME name — so "Lords Delhi" is two different
commercial relationships with two different sets of terms and, after Stage 2, two different
B2B deals. Picking the LCC row for a GDS statement would price it against the wrong deal
and produce a plausible, wrong number rather than an error. The channel check is what makes
the pick unambiguous.

**Scoped by `user_id`, not `tenant_id`.** Agencies are user-scoped (models/agency.py:
"every user maintains their OWN set of agencies, visible only to them"). A tenant-wide
filter would let one user attribute their statement to a colleague's agency — which would
then match that colleague's deals.

`resolve_agency_choice` is the rule itself — pure and session-free, so it is unit-tested
without a database, like `services/lcc_airline_selection.py`. `resolve_for_upload` adds the
lookup. Neither raises HTTPException: the router maps these errors to 400.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agency import Agency, scope_covers


class UnknownAgency(ValueError):
    """No agency was chosen, or the id is not one of this user's. User-facing message."""


class InactiveAgency(ValueError):
    """The chosen agency has been deactivated."""


class AgencyChannelMismatch(ValueError):
    """The chosen agency does not trade on this statement's channel."""


def agency_label(agency) -> str:
    """'Lords Travels — DEL · GDS'. The branch and channel are NOT decoration.

    Two rows of one vendor share a name exactly, so a label that stops at the name shows
    two identical options; models/agency.py requires every agency dropdown to carry both.
    """
    branch = getattr(agency, "branch_name", None) or getattr(agency, "branch_code", None)
    parts = [agency.name]
    if branch:
        parts.append(f"— {branch}")
    if getattr(agency, "channels", None):
        parts.append(f"· {agency.channels}")
    return " ".join(parts)


def resolve_agency_choice(agency, channel: str):
    """The agency to attribute this upload to, or a ValueError carrying what to tell the user.

    `agency` is None when nothing was picked OR when the id belonged to someone else —
    deliberately the same answer, so a guessed id cannot be distinguished from a blank one.
    """
    if agency is None:
        raise UnknownAgency(
            "Select the agency this statement came from — the file itself doesn't name your "
            "consolidator, and the commission run needs it to find the right B2B deal. "
            "Add them under User master → Agency Master first if they aren't listed."
        )
    if not agency.is_active:
        raise InactiveAgency(
            f"'{agency_label(agency)}' is inactive. Re-activate it under User master → "
            f"Agency Master, or pick another agency."
        )
    if not scope_covers(agency.channels, channel):
        raise AgencyChannelMismatch(
            f"'{agency_label(agency)}' trades on {agency.channels}, not {channel}. A vendor "
            f"working both channels is onboarded twice, once per channel — pick their "
            f"{channel} row, or open the {channel} channel on this one."
        )
    return agency


async def resolve_for_upload(db: AsyncSession, user, agency_id: int | None):
    """This user's Agency Master row for an upload, or a ValueError. Channel is checked by
    the caller passing it through `resolve_agency_choice`."""
    if agency_id is None:
        return None
    return (await db.execute(
        select(Agency).where(Agency.id == agency_id, Agency.user_id == user.id)
    )).scalar_one_or_none()


async def resolve_for_channel(db: AsyncSession, user, agency_id: int | None, channel: str):
    """The whole check in one call: look the agency up under this user, then apply the rule."""
    return resolve_agency_choice(await resolve_for_upload(db, user, agency_id), channel)
