"""
evaluate_exclusion_for_payout — checks whether a ticket matches a deal's
"Exclusion For Payout" incl/excl rule using AND logic.

AND logic: ALL non-empty rule fields must match the ticket for exclusion to apply.
If any one non-empty field does not match, the ticket is NOT excluded.
Unmappable fields (soto, tourCode, etc.) are skipped (treated as matching).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.airport import Airport
from app.models.uploaded_ticket import UploadedTicket
from app.services.deal_matching import _resolve_cabin_groups, _class_matches_groups


# Fields we cannot map from a ticket — skip them rather than penalising
_UNMAPPABLE_FIELDS = {"soto", "tourCode", "fareTypeCategory", "domesticCountry"}

# Flag fields that control date logic — pre-read before the loop, skip in loop
_FLAG_FIELDS = {"dateExclusionTicket", "dateExclusionTravel"}


async def _get_airport(db: AsyncSession, iata: str) -> Airport | None:
    res = await db.execute(
        select(Airport).where(func.upper(Airport.iata_code) == iata.upper())
    )
    return res.scalar_one_or_none()


def _parse_rule_date(raw: Any) -> date | None:
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        from dateutil import parser as dp
        return dp.parse(str(raw), dayfirst=False).date()
    except Exception:
        return None


def _parse_ticket_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        from dateutil import parser as dp
        return dp.parse(raw, dayfirst=True).date()
    except Exception:
        return None


def _build_dates(
    ticket: UploadedTicket,
    use_ticket: bool,
    use_travel: bool,
) -> list[date]:
    """Build the list of dates that validFrom/validTo should be checked against."""
    out: list[date] = []
    if use_ticket:
        d = _parse_ticket_date(ticket.ticket_date)
        if d:
            out.append(d)
    if use_travel:
        d = (_parse_ticket_date(ticket.departure_datetime)
             or _parse_ticket_date(ticket.ticket_date))
        if d:
            out.append(d)
    return out


async def diagnose_exclusion_for_payout(
    excl_data: dict,
    db: AsyncSession,
    sector: str | None,
    booking_class: str | None,
    ticket_date_raw: str | None,
    departure_raw: str | None,
    airline_name: str | None,
):
    """
    Non-short-circuiting version of evaluate_exclusion_for_payout.
    Evaluates every non-empty field and returns an ExclusionRuleDiagnostic
    with a step-by-step breakdown of what matched and what did not.
    """
    from app.schemas.uploaded_ticket import ExclusionRuleStep, ExclusionRuleDiagnostic

    if not excl_data:
        return ExclusionRuleDiagnostic(rule_name="Exclusion For Payout", is_excluded=False, reason="", steps=[])

    use_ticket_date = excl_data.get("dateExclusionTicket") == "true"
    use_travel_date = excl_data.get("dateExclusionTravel") == "true"
    if not use_ticket_date and not use_travel_date:
        use_travel_date = True

    # Parse sector into IATA codes
    parts = [p.strip().upper() for p in (sector or "").split("/") if p.strip()]
    origin_iata = parts[0] if parts else None
    dest_iata   = parts[-1] if len(parts) > 1 else None

    _origin_apt: Airport | None | bool = False
    _dest_apt:   Airport | None | bool = False

    async def get_origin():
        nonlocal _origin_apt
        if _origin_apt is False:
            _origin_apt = await _get_airport(db, origin_iata) if origin_iata else None
        return _origin_apt

    async def get_dest():
        nonlocal _dest_apt
        if _dest_apt is False:
            _dest_apt = await _get_airport(db, dest_iata) if dest_iata else None
        return _dest_apt

    def _build_dates_raw() -> list[date]:
        out: list[date] = []
        if use_ticket_date:
            d = _parse_ticket_date(ticket_date_raw)
            if d:
                out.append(d)
        if use_travel_date:
            d = _parse_ticket_date(departure_raw) or _parse_ticket_date(ticket_date_raw)
            if d:
                out.append(d)
        return out

    steps: list[ExclusionRuleStep] = []
    all_matched = True  # AND logic over evaluated fields

    for field, rule_value in excl_data.items():
        if rule_value is None or rule_value == "" or rule_value == []:
            continue
        if field in _UNMAPPABLE_FIELDS or field in _FLAG_FIELDS:
            continue

        ticket_value_str = "—"
        field_matched: bool | None = None

        if field == "validFrom":
            rule_date = _parse_rule_date(rule_value)
            if rule_date is None:
                continue
            dates = _build_dates_raw()
            if not dates:
                continue
            field_matched = all(d >= rule_date for d in dates)
            ticket_value_str = ", ".join(str(d) for d in dates)

        elif field == "validTo":
            rule_date = _parse_rule_date(rule_value)
            if rule_date is None:
                continue
            dates = _build_dates_raw()
            if not dates:
                continue
            field_matched = all(d <= rule_date for d in dates)
            ticket_value_str = ", ".join(str(d) for d in dates)

        elif field == "originAirport":
            if not origin_iata:
                continue
            field_matched = origin_iata.upper() == str(rule_value).upper()
            ticket_value_str = origin_iata

        elif field == "destAirport":
            if not dest_iata:
                continue
            field_matched = dest_iata.upper() == str(rule_value).upper()
            ticket_value_str = dest_iata

        elif field == "originContinents":
            apt = await get_origin()
            if not apt or not apt.continent:
                continue
            field_matched = apt.continent.lower() == str(rule_value).lower()
            ticket_value_str = apt.continent

        elif field == "destContinents":
            apt = await get_dest()
            if not apt or not apt.continent:
                continue
            field_matched = apt.continent.lower() == str(rule_value).lower()
            ticket_value_str = apt.continent

        elif field == "continents":
            o_apt = await get_origin()
            d_apt = await get_dest()
            o_cont = (o_apt.continent or "").lower() if o_apt else ""
            d_cont = (d_apt.continent or "").lower() if d_apt else ""
            rv = str(rule_value).lower()
            if not o_cont and not d_cont:
                continue
            field_matched = (o_cont == rv) or (d_cont == rv)
            ticket_value_str = f"{o_cont or '—'} / {d_cont or '—'}"

        elif field == "originCountry":
            apt = await get_origin()
            if not apt or not apt.country:
                continue
            field_matched = apt.country.lower() == str(rule_value).lower()
            ticket_value_str = apt.country

        elif field == "destCountry":
            apt = await get_dest()
            if not apt or not apt.country:
                continue
            field_matched = apt.country.lower() == str(rule_value).lower()
            ticket_value_str = apt.country

        elif field == "originCountryGroup":
            apt = await get_origin()
            if not apt or not apt.categorization:
                continue
            field_matched = apt.categorization.lower() == str(rule_value).lower()
            ticket_value_str = apt.categorization

        elif field == "destCountryGroup":
            apt = await get_dest()
            if not apt or not apt.categorization:
                continue
            field_matched = apt.categorization.lower() == str(rule_value).lower()
            ticket_value_str = apt.categorization

        elif field == "countryGroup":
            o_apt = await get_origin()
            d_apt = await get_dest()
            o_cat = (o_apt.categorization or "").lower() if o_apt else ""
            d_cat = (d_apt.categorization or "").lower() if d_apt else ""
            rv = str(rule_value).lower()
            if not o_cat and not d_cat:
                continue
            field_matched = (o_cat == rv) or (d_cat == rv)
            ticket_value_str = f"{o_cat or '—'} / {d_cat or '—'}"

        elif field == "city":
            o_apt = await get_origin()
            d_apt = await get_dest()
            rv_lower = str(rule_value).lower()
            o_city = (o_apt.city_airport_name or "").lower() if o_apt else ""
            d_city = (d_apt.city_airport_name or "").lower() if d_apt else ""
            if not o_city and not d_city:
                continue
            field_matched = rv_lower in o_city or rv_lower in d_city
            ticket_value_str = f"{o_city or '—'} / {d_city or '—'}"

        elif field == "class":
            cabin_groups = await _resolve_cabin_groups(db, airline_name or "", booking_class)
            field_matched = _class_matches_groups(cabin_groups, str(rule_value))
            ticket_value_str = f"{booking_class or '—'} → {'/'.join(sorted(cabin_groups))}"

        else:
            continue

        if field_matched is None:
            continue

        steps.append(ExclusionRuleStep(
            field=field,
            rule_value=str(rule_value),
            ticket_value=ticket_value_str,
            matched=field_matched,
        ))
        if not field_matched:
            all_matched = False

    if not steps:
        return ExclusionRuleDiagnostic(rule_name="Exclusion For Payout", is_excluded=False, reason="No evaluable fields in rule", steps=[])

    is_excluded = all_matched  # AND: every evaluated field matched
    matched_fields = [s.field for s in steps if s.matched]
    reason = (
        f"Excluded: all {len(steps)} rule field(s) matched ({', '.join(matched_fields)})"
        if is_excluded
        else f"Not excluded: {sum(1 for s in steps if not s.matched)} field(s) did not match"
    )
    return ExclusionRuleDiagnostic(rule_name="Exclusion For Payout", is_excluded=is_excluded, reason=reason, steps=steps)


async def evaluate_exclusion_for_payout(
    ticket: UploadedTicket,
    excl_data: dict,
    db: AsyncSession,
) -> tuple[bool, str]:
    """
    Returns (is_excluded, reason_string).
    AND logic: all non-empty excl_data fields must match the ticket.
    """
    if not excl_data:
        return False, ""

    # Pre-read date exclusion flags to determine which date(s) validFrom/validTo check
    use_ticket_date = excl_data.get("dateExclusionTicket") == "true"
    use_travel_date = excl_data.get("dateExclusionTravel") == "true"
    if not use_ticket_date and not use_travel_date:
        use_travel_date = True  # backward-compat default

    # Parse sector into origin / dest IATA codes
    sector = (ticket.sector or "").strip()
    parts = [p.strip().upper() for p in sector.split("/") if p.strip()]
    origin_iata = parts[0] if parts else None
    dest_iata   = parts[-1] if len(parts) > 1 else None

    # Lazily fetched airport objects (avoid unnecessary DB hits)
    _origin_apt: Airport | None | bool = False  # False = not yet fetched
    _dest_apt:   Airport | None | bool = False

    async def get_origin():
        nonlocal _origin_apt
        if _origin_apt is False:
            _origin_apt = await _get_airport(db, origin_iata) if origin_iata else None
        return _origin_apt

    async def get_dest():
        nonlocal _dest_apt
        if _dest_apt is False:
            _dest_apt = await _get_airport(db, dest_iata) if dest_iata else None
        return _dest_apt

    matched_fields: list[str] = []

    for field, rule_value in excl_data.items():
        # Skip empty rule values
        if rule_value is None or rule_value == "" or rule_value == []:
            continue

        # Skip fields we can't evaluate from ticket data
        if field in _UNMAPPABLE_FIELDS or field in _FLAG_FIELDS:
            continue

        ticket_value: Any = None
        field_matched: bool | None = None  # None = couldn't evaluate → skip

        # ── Date range ────────────────────────────────────────────────────
        if field == "validFrom":
            rule_date = _parse_rule_date(rule_value)
            if rule_date is None:
                continue
            dates = _build_dates(ticket, use_ticket_date, use_travel_date)
            if not dates:
                continue
            field_matched = all(d >= rule_date for d in dates)

        elif field == "validTo":
            rule_date = _parse_rule_date(rule_value)
            if rule_date is None:
                continue
            dates = _build_dates(ticket, use_ticket_date, use_travel_date)
            if not dates:
                continue
            field_matched = all(d <= rule_date for d in dates)

        # ── Direct airport codes ─────────────────────────────────────────
        elif field == "originAirport":
            if not origin_iata:
                continue
            field_matched = origin_iata.upper() == str(rule_value).upper()

        elif field == "destAirport":
            if not dest_iata:
                continue
            field_matched = dest_iata.upper() == str(rule_value).upper()

        # ── Continent ────────────────────────────────────────────────────
        elif field == "originContinents":
            apt = await get_origin()
            if not apt or not apt.continent:
                continue
            field_matched = apt.continent.lower() == str(rule_value).lower()

        elif field == "destContinents":
            apt = await get_dest()
            if not apt or not apt.continent:
                continue
            field_matched = apt.continent.lower() == str(rule_value).lower()

        elif field == "continents":
            # Match if either origin OR dest continent equals rule value
            o_apt = await get_origin()
            d_apt = await get_dest()
            o_cont = (o_apt.continent or "").lower() if o_apt else ""
            d_cont = (d_apt.continent or "").lower() if d_apt else ""
            rv = str(rule_value).lower()
            if not o_cont and not d_cont:
                continue
            field_matched = (o_cont == rv) or (d_cont == rv)

        # ── Country ──────────────────────────────────────────────────────
        elif field == "originCountry":
            apt = await get_origin()
            if not apt or not apt.country:
                continue
            field_matched = apt.country.lower() == str(rule_value).lower()

        elif field == "destCountry":
            apt = await get_dest()
            if not apt or not apt.country:
                continue
            field_matched = apt.country.lower() == str(rule_value).lower()

        # ── Country group (categorization) ────────────────────────────────
        elif field == "originCountryGroup":
            apt = await get_origin()
            if not apt or not apt.categorization:
                continue
            field_matched = apt.categorization.lower() == str(rule_value).lower()

        elif field == "destCountryGroup":
            apt = await get_dest()
            if not apt or not apt.categorization:
                continue
            field_matched = apt.categorization.lower() == str(rule_value).lower()

        elif field == "countryGroup":
            # Match if either origin OR dest categorization equals rule value
            o_apt = await get_origin()
            d_apt = await get_dest()
            o_cat = (o_apt.categorization or "").lower() if o_apt else ""
            d_cat = (d_apt.categorization or "").lower() if d_apt else ""
            rv = str(rule_value).lower()
            if not o_cat and not d_cat:
                continue
            field_matched = (o_cat == rv) or (d_cat == rv)

        # ── City ─────────────────────────────────────────────────────────
        elif field == "city":
            o_apt = await get_origin()
            d_apt = await get_dest()
            rv_lower = str(rule_value).lower()
            o_city = (o_apt.city_airport_name or "").lower() if o_apt else ""
            d_city = (d_apt.city_airport_name or "").lower() if d_apt else ""
            if not o_city and not d_city:
                continue
            field_matched = rv_lower in o_city or rv_lower in d_city

        # ── Booking class (cabin group) ───────────────────────────────────
        elif field == "class":
            airline_name = ticket.airline_name or ""
            cabin_groups = await _resolve_cabin_groups(db, airline_name, ticket.booking_class)
            field_matched = _class_matches_groups(cabin_groups, str(rule_value))

        else:
            # Unknown field — skip
            continue

        if field_matched is False:
            # AND logic: one field doesn't match → ticket is NOT excluded
            return False, ""

        if field_matched is True:
            matched_fields.append(field)

    if not matched_fields:
        # No evaluable non-empty fields matched (all were skipped or empty)
        return False, ""

    reason = f"Excluded by Exclusion For Payout rule (matched: {', '.join(matched_fields)})"
    return True, reason
