"""
evaluate_exclusion_for_payout — checks whether a ticket matches a deal's
"Exclusion For Payout" incl/excl rule using AND logic.

AND logic: ALL non-empty rule fields must match the ticket for exclusion to apply.
If any one non-empty field does not match, the ticket is NOT excluded.
All 18 rule fields are now evaluable, including soto, tourCode, fareTypeCategory, domesticCountry.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.airport import Airport
from app.models.uploaded_ticket import UploadedTicket
from app.services.deal_matching import _resolve_cabin_groups, _class_matches_groups


# All fields are now evaluable; this set is kept empty for backward compat
_UNMAPPABLE_FIELDS: set[str] = set()

# Flag fields that control date logic — pre-read before the loop, skip in loop
_FLAG_FIELDS = {"dateExclusionTicket", "dateExclusionTravel"}


def _val_to_list(v: Any) -> list[str]:
    """Normalize a rule field value (string or list) to a list of lowercase strings."""
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if x is not None and str(x).strip()]
    s = str(v).strip().lower()
    return [s] if s else []


def _match_any(rule_vals: list[str], ticket_val: str) -> bool:
    """True if ticket_val (lowercased) equals any value in rule_vals."""
    tv = ticket_val.strip().lower()
    return any(rv == tv for rv in rule_vals)


def _cat_match(rule_vals: list[str], apt_categorization: str) -> bool:
    """Match a rule's country-group values against an airport's categorization.

    Airport DB may store compound values like "MEAI/SAARC" meaning the airport
    belongs to BOTH MEAI and SAARC.  A rule value of "MEAI" should match.
    "GCC/MIDDLE EAST" is a single canonical name — it is matched as a whole.
    """
    if not apt_categorization:
        return False
    apt_lower = apt_categorization.strip().lower()
    # Split compound categorization into parts (e.g. "MEAI/SAARC" → {"meai","saarc"})
    apt_parts = {p.strip().lower() for p in apt_categorization.split("/")}
    return any(rv == apt_lower or rv in apt_parts for rv in rule_vals)


def _city_match(rule_vals: list[str], city_airport_name: str) -> bool:
    """True if any rule city value appears as a substring of the airport's city/name."""
    cn = city_airport_name.strip().lower()
    return any(rv in cn for rv in rule_vals)


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


async def diagnose_inclusion_for_payout(
    incl_data: dict,
    db: AsyncSession,
    sector: str | None,
    booking_class: str | None,
    ticket_date_raw: str | None,
    departure_raw: str | None,
    airline_name: str | None,
    tour_code: str | None = None,
):
    """
    Non-short-circuiting version of evaluate_inclusion_for_payout.
    Returns ExclusionRuleDiagnostic where:
      is_excluded=False  → ticket IS in the inclusion set (good)
      is_excluded=True   → ticket is NOT in the inclusion set (will be excluded from payout)
    """
    from app.schemas.uploaded_ticket import ExclusionRuleStep, ExclusionRuleDiagnostic

    if not incl_data:
        return ExclusionRuleDiagnostic(rule_name="Inclusion For Payout", is_excluded=False, reason="No inclusion rule configured — all tickets included by default", steps=[])

    use_ticket_date = incl_data.get("dateExclusionTicket") == "true"
    use_travel_date = incl_data.get("dateExclusionTravel") == "true"
    if not use_ticket_date and not use_travel_date:
        use_travel_date = True

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
    all_matched = True  # AND logic — all filled fields must match

    for field, rule_value in incl_data.items():
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

        else:
            rv_list = _val_to_list(rule_value)
            if not rv_list:
                continue

            if field == "originAirport":
                if not origin_iata:
                    continue
                field_matched = _match_any(rv_list, origin_iata)
                ticket_value_str = origin_iata

            elif field == "destAirport":
                if not dest_iata:
                    continue
                field_matched = _match_any(rv_list, dest_iata)
                ticket_value_str = dest_iata

            elif field == "originContinents":
                apt = await get_origin()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)
                ticket_value_str = apt.continent

            elif field == "destContinents":
                apt = await get_dest()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)
                ticket_value_str = apt.continent

            elif field == "continents":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cont = (o_apt.continent or "") if o_apt else ""
                d_cont = (d_apt.continent or "") if d_apt else ""
                if not o_cont and not d_cont:
                    continue
                field_matched = (o_cont and _match_any(rv_list, o_cont)) or (d_cont and _match_any(rv_list, d_cont))
                ticket_value_str = f"{o_cont or '—'} / {d_cont or '—'}"

            elif field == "originCountry":
                apt = await get_origin()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)
                ticket_value_str = apt.country

            elif field == "destCountry":
                apt = await get_dest()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)
                ticket_value_str = apt.country

            elif field == "originCountryGroup":
                apt = await get_origin()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)
                ticket_value_str = apt.categorization

            elif field == "destCountryGroup":
                apt = await get_dest()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)
                ticket_value_str = apt.categorization

            elif field == "countryGroup":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cat = (o_apt.categorization or "") if o_apt else ""
                d_cat = (d_apt.categorization or "") if d_apt else ""
                if not o_cat and not d_cat:
                    continue
                field_matched = (o_cat and _cat_match(rv_list, o_cat)) or (d_cat and _cat_match(rv_list, d_cat))
                ticket_value_str = f"{o_cat or '—'} / {d_cat or '—'}"

            elif field == "city":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_city = (o_apt.city_airport_name or "") if o_apt else ""
                d_city = (d_apt.city_airport_name or "") if d_apt else ""
                if not o_city and not d_city:
                    continue
                field_matched = (o_city and _city_match(rv_list, o_city)) or (d_city and _city_match(rv_list, d_city))
                ticket_value_str = f"{o_city or '—'} / {d_city or '—'}"

            elif field == "class":
                cabin_groups = await _resolve_cabin_groups(db, airline_name or "", booking_class)
                field_matched = any(_class_matches_groups(cabin_groups, rv) for rv in rv_list)
                ticket_value_str = f"{booking_class or '—'} → {'/'.join(sorted(cabin_groups))}"

            elif field == "soto":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country and not d_country:
                    continue
                field_matched = False
                for sv in rv_list:
                    if sv == "soto all" and o_country == "india":
                        field_matched = True; break
                    elif sv == "soto within india" and d_country == "india" and o_country != "india":
                        field_matched = True; break
                    elif sv == "soto outside india" and d_country and d_country != "india":
                        field_matched = True; break
                ticket_value_str = f"origin={o_country or '—'} / dest={d_country or '—'}"

            elif field == "tourCode":
                tc = (tour_code or "").strip().lower()
                field_matched = bool(tc) and tc in rv_list
                ticket_value_str = tour_code or "—"

            elif field == "fareTypeCategory":
                bclass_parts = {p.strip().upper() for p in (booking_class or "").split("/") if p.strip()}
                has_tour_code = bool((tour_code or "").strip())
                field_matched = False
                for fc in rv_list:
                    if fc == "normal":
                        field_matched = True; break
                    elif fc == "group" and "G" in bclass_parts:
                        field_matched = True; break
                    elif fc in {"corporate", "tour", "excursion"} and has_tour_code:
                        field_matched = True; break
                ticket_value_str = f"class={booking_class or '—'}"

            elif field == "domesticCountry":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country or not d_country:
                    continue
                field_matched = any(o_country == rv and d_country == rv for rv in rv_list)
                ticket_value_str = f"origin={o_country or '—'} / dest={d_country or '—'}"

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
        return ExclusionRuleDiagnostic(rule_name="Inclusion For Payout", is_excluded=False, reason="No evaluable fields in inclusion rule — all tickets included by default", steps=[])

    is_included = all_matched
    matched_fields = [s.field for s in steps if s.matched]
    not_matched_fields = [s.field for s in steps if not s.matched]
    if is_included:
        reason = f"Included: all {len(steps)} rule field(s) matched ({', '.join(matched_fields)})"
    else:
        reason = f"Not included: {len(not_matched_fields)} field(s) did not match ({', '.join(not_matched_fields)})"

    # is_excluded=True means ticket is NOT in inclusion set (excluded from payout)
    return ExclusionRuleDiagnostic(rule_name="Inclusion For Payout", is_excluded=not is_included, reason=reason, steps=steps)


async def diagnose_exclusion_for_payout(
    excl_data: dict,
    db: AsyncSession,
    sector: str | None,
    booking_class: str | None,
    ticket_date_raw: str | None,
    departure_raw: str | None,
    airline_name: str | None,
    tour_code: str | None = None,
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

        else:
            rv_list = _val_to_list(rule_value)
            if not rv_list:
                continue

            if field == "originAirport":
                if not origin_iata:
                    continue
                field_matched = _match_any(rv_list, origin_iata)
                ticket_value_str = origin_iata

            elif field == "destAirport":
                if not dest_iata:
                    continue
                field_matched = _match_any(rv_list, dest_iata)
                ticket_value_str = dest_iata

            elif field == "originContinents":
                apt = await get_origin()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)
                ticket_value_str = apt.continent

            elif field == "destContinents":
                apt = await get_dest()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)
                ticket_value_str = apt.continent

            elif field == "continents":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cont = (o_apt.continent or "") if o_apt else ""
                d_cont = (d_apt.continent or "") if d_apt else ""
                if not o_cont and not d_cont:
                    continue
                field_matched = (o_cont and _match_any(rv_list, o_cont)) or (d_cont and _match_any(rv_list, d_cont))
                ticket_value_str = f"{o_cont or '—'} / {d_cont or '—'}"

            elif field == "originCountry":
                apt = await get_origin()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)
                ticket_value_str = apt.country

            elif field == "destCountry":
                apt = await get_dest()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)
                ticket_value_str = apt.country

            elif field == "originCountryGroup":
                apt = await get_origin()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)
                ticket_value_str = apt.categorization

            elif field == "destCountryGroup":
                apt = await get_dest()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)
                ticket_value_str = apt.categorization

            elif field == "countryGroup":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cat = (o_apt.categorization or "") if o_apt else ""
                d_cat = (d_apt.categorization or "") if d_apt else ""
                if not o_cat and not d_cat:
                    continue
                field_matched = (o_cat and _cat_match(rv_list, o_cat)) or (d_cat and _cat_match(rv_list, d_cat))
                ticket_value_str = f"{o_cat or '—'} / {d_cat or '—'}"

            elif field == "city":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_city = (o_apt.city_airport_name or "") if o_apt else ""
                d_city = (d_apt.city_airport_name or "") if d_apt else ""
                if not o_city and not d_city:
                    continue
                field_matched = (o_city and _city_match(rv_list, o_city)) or (d_city and _city_match(rv_list, d_city))
                ticket_value_str = f"{o_city or '—'} / {d_city or '—'}"

            elif field == "class":
                cabin_groups = await _resolve_cabin_groups(db, airline_name or "", booking_class)
                field_matched = any(_class_matches_groups(cabin_groups, rv) for rv in rv_list)
                ticket_value_str = f"{booking_class or '—'} → {'/'.join(sorted(cabin_groups))}"

            elif field == "soto":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country and not d_country:
                    continue
                field_matched = False
                for sv in rv_list:
                    if sv == "soto all" and o_country == "india":
                        field_matched = True; break
                    elif sv == "soto within india" and d_country == "india" and o_country != "india":
                        field_matched = True; break
                    elif sv == "soto outside india" and d_country and d_country != "india":
                        field_matched = True; break
                ticket_value_str = f"origin={o_country or '—'} / dest={d_country or '—'}"

            elif field == "tourCode":
                tc = (tour_code or "").strip().lower()
                field_matched = bool(tc) and tc in rv_list
                ticket_value_str = tour_code or "—"

            elif field == "fareTypeCategory":
                bclass_parts = {p.strip().upper() for p in (booking_class or "").split("/") if p.strip()}
                has_tour_code = bool((tour_code or "").strip())
                field_matched = False
                for fc in rv_list:
                    if fc == "normal":
                        field_matched = True; break
                    elif fc == "group" and "G" in bclass_parts:
                        field_matched = True; break
                    elif fc in {"corporate", "tour", "excursion"} and has_tour_code:
                        field_matched = True; break
                ticket_value_str = f"class={booking_class or '—'}"

            elif field == "domesticCountry":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country or not d_country:
                    continue
                field_matched = any(o_country == rv and d_country == rv for rv in rv_list)
                ticket_value_str = f"origin={o_country or '—'} / dest={d_country or '—'}"

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


async def evaluate_inclusion_for_payout(
    ticket: UploadedTicket,
    incl_data: dict,
    db: AsyncSession,
) -> tuple[bool, str]:
    """
    Returns (is_included, reason_string).
    AND logic: all non-empty incl_data fields must match the ticket.
    If all match → ticket IS in the inclusion set → is_included=True.
    If any field does not match → ticket is NOT included → is_included=False.
    Empty / no evaluable fields → is_included=True (include all by default).
    """
    if not incl_data:
        return True, ""

    use_ticket_date = incl_data.get("dateExclusionTicket") == "true"
    use_travel_date = incl_data.get("dateExclusionTravel") == "true"
    if not use_ticket_date and not use_travel_date:
        use_travel_date = True

    sector = (ticket.sector or "").strip()
    parts = [p.strip().upper() for p in sector.split("/") if p.strip()]
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

    matched_fields: list[str] = []

    for field, rule_value in incl_data.items():
        if rule_value is None or rule_value == "" or rule_value == []:
            continue
        if field in _UNMAPPABLE_FIELDS or field in _FLAG_FIELDS:
            continue

        field_matched: bool | None = None

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

        else:
            rv_list = _val_to_list(rule_value)
            if not rv_list:
                continue

            if field == "originAirport":
                if not origin_iata:
                    continue
                field_matched = _match_any(rv_list, origin_iata)

            elif field == "destAirport":
                if not dest_iata:
                    continue
                field_matched = _match_any(rv_list, dest_iata)

            elif field == "originContinents":
                apt = await get_origin()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)

            elif field == "destContinents":
                apt = await get_dest()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)

            elif field == "continents":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cont = (o_apt.continent or "") if o_apt else ""
                d_cont = (d_apt.continent or "") if d_apt else ""
                if not o_cont and not d_cont:
                    continue
                field_matched = (o_cont and _match_any(rv_list, o_cont)) or (d_cont and _match_any(rv_list, d_cont))

            elif field == "originCountry":
                apt = await get_origin()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)

            elif field == "destCountry":
                apt = await get_dest()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)

            elif field == "originCountryGroup":
                apt = await get_origin()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)

            elif field == "destCountryGroup":
                apt = await get_dest()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)

            elif field == "countryGroup":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cat = (o_apt.categorization or "") if o_apt else ""
                d_cat = (d_apt.categorization or "") if d_apt else ""
                if not o_cat and not d_cat:
                    continue
                field_matched = (o_cat and _cat_match(rv_list, o_cat)) or (d_cat and _cat_match(rv_list, d_cat))

            elif field == "city":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_city = (o_apt.city_airport_name or "") if o_apt else ""
                d_city = (d_apt.city_airport_name or "") if d_apt else ""
                if not o_city and not d_city:
                    continue
                field_matched = (o_city and _city_match(rv_list, o_city)) or (d_city and _city_match(rv_list, d_city))

            elif field == "class":
                airline_name = ticket.airline_name or ""
                cabin_groups = await _resolve_cabin_groups(db, airline_name, ticket.booking_class)
                field_matched = any(_class_matches_groups(cabin_groups, rv) for rv in rv_list)

            elif field == "soto":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country and not d_country:
                    continue
                field_matched = False
                for sv in rv_list:
                    if sv == "soto all" and o_country == "india":
                        field_matched = True; break
                    elif sv == "soto within india" and d_country == "india" and o_country != "india":
                        field_matched = True; break
                    elif sv == "soto outside india" and d_country and d_country != "india":
                        field_matched = True; break

            elif field == "tourCode":
                tc = (ticket.tour_code or "").strip().lower()
                field_matched = bool(tc) and tc in rv_list

            elif field == "fareTypeCategory":
                bclass_parts = {p.strip().upper() for p in (ticket.booking_class or "").split("/") if p.strip()}
                has_tour_code = bool((ticket.tour_code or "").strip())
                field_matched = False
                for fc in rv_list:
                    if fc == "normal":
                        field_matched = True; break
                    elif fc == "group" and "G" in bclass_parts:
                        field_matched = True; break
                    elif fc in {"corporate", "tour", "excursion"} and has_tour_code:
                        field_matched = True; break

            elif field == "domesticCountry":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country or not d_country:
                    continue
                field_matched = any(o_country == rv and d_country == rv for rv in rv_list)

            else:
                continue

        if field_matched is False:
            # AND logic: one field doesn't match → ticket is NOT in inclusion set
            return False, f"Not included: '{field}' did not match inclusion rule"

        if field_matched is True:
            matched_fields.append(field)

    if not matched_fields:
        # No evaluable non-empty fields → include all by default
        return True, ""

    reason = f"Included by Inclusion For Payout rule (matched: {', '.join(matched_fields)})"
    return True, reason


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

        else:
            rv_list = _val_to_list(rule_value)
            if not rv_list:
                continue

            # ── Direct airport codes ──────────────────────────────────────
            if field == "originAirport":
                if not origin_iata:
                    continue
                field_matched = _match_any(rv_list, origin_iata)

            elif field == "destAirport":
                if not dest_iata:
                    continue
                field_matched = _match_any(rv_list, dest_iata)

            # ── Continent ──────────────────────────────────────────────────
            elif field == "originContinents":
                apt = await get_origin()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)

            elif field == "destContinents":
                apt = await get_dest()
                if not apt or not apt.continent:
                    continue
                field_matched = _match_any(rv_list, apt.continent)

            elif field == "continents":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cont = (o_apt.continent or "") if o_apt else ""
                d_cont = (d_apt.continent or "") if d_apt else ""
                if not o_cont and not d_cont:
                    continue
                field_matched = (o_cont and _match_any(rv_list, o_cont)) or (d_cont and _match_any(rv_list, d_cont))

            # ── Country ────────────────────────────────────────────────────
            elif field == "originCountry":
                apt = await get_origin()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)

            elif field == "destCountry":
                apt = await get_dest()
                if not apt or not apt.country:
                    continue
                field_matched = _match_any(rv_list, apt.country)

            # ── Country group (categorization) ─────────────────────────────
            elif field == "originCountryGroup":
                apt = await get_origin()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)

            elif field == "destCountryGroup":
                apt = await get_dest()
                if not apt or not apt.categorization:
                    continue
                field_matched = _cat_match(rv_list, apt.categorization)

            elif field == "countryGroup":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_cat = (o_apt.categorization or "") if o_apt else ""
                d_cat = (d_apt.categorization or "") if d_apt else ""
                if not o_cat and not d_cat:
                    continue
                field_matched = (o_cat and _cat_match(rv_list, o_cat)) or (d_cat and _cat_match(rv_list, d_cat))

            # ── City ───────────────────────────────────────────────────────
            elif field == "city":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_city = (o_apt.city_airport_name or "") if o_apt else ""
                d_city = (d_apt.city_airport_name or "") if d_apt else ""
                if not o_city and not d_city:
                    continue
                field_matched = (o_city and _city_match(rv_list, o_city)) or (d_city and _city_match(rv_list, d_city))

            # ── Booking class (cabin group) ─────────────────────────────────
            elif field == "class":
                airline_name = ticket.airline_name or ""
                cabin_groups = await _resolve_cabin_groups(db, airline_name, ticket.booking_class)
                field_matched = any(_class_matches_groups(cabin_groups, rv) for rv in rv_list)

            # ── SOTO (India origin/destination rule) ──────────────────────────
            elif field == "soto":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country and not d_country:
                    continue
                field_matched = False
                for sv in rv_list:
                    if sv == "soto all" and o_country == "india":
                        field_matched = True; break
                    elif sv == "soto within india" and d_country == "india" and o_country != "india":
                        field_matched = True; break
                    elif sv == "soto outside india" and d_country and d_country != "india":
                        field_matched = True; break

            # ── Tour code match ────────────────────────────────────────────────
            elif field == "tourCode":
                tc = (ticket.tour_code or "").strip().lower()
                field_matched = bool(tc) and tc in rv_list

            # ── Fare type category ─────────────────────────────────────────────
            elif field == "fareTypeCategory":
                bclass_parts = {p.strip().upper() for p in (ticket.booking_class or "").split("/") if p.strip()}
                has_tour_code = bool((ticket.tour_code or "").strip())
                field_matched = False
                for fc in rv_list:
                    if fc == "normal":
                        field_matched = True; break
                    elif fc == "group" and "G" in bclass_parts:
                        field_matched = True; break
                    elif fc in {"corporate", "tour", "excursion"} and has_tour_code:
                        field_matched = True; break

            # ── Domestic country (both endpoints same country) ─────────────────
            elif field == "domesticCountry":
                o_apt = await get_origin()
                d_apt = await get_dest()
                o_country = (o_apt.country or "").strip().lower() if o_apt else ""
                d_country = (d_apt.country or "").strip().lower() if d_apt else ""
                if not o_country or not d_country:
                    continue
                field_matched = any(o_country == rv and d_country == rv for rv in rv_list)

            else:
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
