"""Inclusion / exclusion rules for payout — does this ticket fall inside what a rule describes?

A rule is a description of a kind of ticket, filled in on the deal's Inclusion For Payout /
Exclusion For Payout tabs:

    INCLUSION  only tickets the rule describes are paid; every other ticket is left out.
    EXCLUSION  tickets the rule describes are not paid; every other ticket is.

ALL filled fields must hold for a ticket to fit the description (AND); several values in
one field are alternatives (OR). Both were confirmed by the user on 2026-10-27.

THREE ANSWERS, NOT TWO. Each field is True (matches), False (does not) or None — could not
be judged, because the ticket does not carry what the field needs: no sector, a sector that
is not a route, an airport the Airport Master does not hold, no travel date. "Could not be
judged" used to be silently skipped, which passed an inclusion rule and dodged an exclusion
rule on terms nobody checked. Now:

    any field False          → the ticket does not fit the rule
    else any field None      → undecided — the caller withholds (needs_data) and says why
    else                     → the ticket fits the rule

WHERE THE TICKET GOES comes from its Sector, through services/route_resolution.py: origin is
the first airport, destination is the last — or the turnaround of a round trip (DEL/ALA/DEL
→ ALA). Every place field reads that origin / destination off the Airport Master:

    originAirport / destAirport                  the IATA code itself
    originContinents / destContinents            CONTINENT
    originCountry / destCountry                  COUNTRY
    originCountryGroup / destCountryGroup        CATEGORIZATION ("MEAI/SAARC" is in both)
    continents / countryGroup / city             the WHOLE ROUTE must lie inside — origin
                                                 AND destination (user's rule, 2026-10-27)

"Select this option if the route is vice versa" makes the origin / destination fields match
in either direction: a DEL → Europe rule also covers Europe → DEL.

DATES. Date Exclusion picks what Valid From / To test: Ticket Date (the issue date), Travel
Date, or both. With neither picked the travel date is tested, as the form's hint says.

CLASS is the ticket's booking-class codes against the rule's ("S", "E" — the airline's own
codes from the Airline Class Master; a cabin name such as "Economy" still works through the
master). STRICT on a ticket printed per segment ("H/ H/ E/ N", user's rule 2026-10-27):

    inclusion  EVERY segment's class must be listed — never pay on a class the deal left out
    exclusion  ANY segment in a listed class excludes the ticket

FARE TYPE CATEGORY (user's rules, 2026-10-27), any picked value may match:

    Normal                      every ticket, whatever its class
    Group                       G class — every segment G for inclusion, any for exclusion
    Corporate / Excursion / Tour the ticket's tour code is one the rule's Tour Code lists
                                (Tour Code is that fare type's parameter, not a second
                                condition, while one of these is picked)

TOUR CODE alone matches a ticket carrying one of the listed codes. A statement that does not
print tour codes at all leaves both undecided (RuleFacts.tour_code_known).

Domestic Country was taken off the rule form (2026-10-27) and is no longer judged: a stored
value nobody can see or edit must not decide a payout.

SOTO (Sold Outside, Ticketed Outside) is a journey that starts outside India — All, or split
by where it ends: within India (ALA/DEL) or outside it (KUL/DAC). See `_soto`.

PAYOUT vs TRIGGER. The same engine judges both kinds of rule. Payout rules decide whether a
ticket is PAID (commission_core.judge_payout_rules); trigger rules decide whether it COUNTS
TOWARD A SLAB TARGET (deal_matching._period_cumulative) — a SOTO ticket excluded for trigger
can still be paid, it just adds nothing to the achieved amount.

ONE ENGINE. `evaluate_rule` is pure and is the only place a field is judged. The commission
run, the legacy boolean wrappers (BSP, uploaded tickets) and both diagnosis popups all go
through it, so a popup can never explain a verdict the run did not reach. It used to be
three near-identical copies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.airport import split_categorization
from app.models.uploaded_ticket import UploadedTicket
from app.services.deal_matching import (
    SKIP_CLASS, SKIP_TRAVEL_DATE, _class_master_map, _class_matches_groups, _fallback_cabin,
    _resolve_cabin_groups, _split_class_codes, describe_cabin,
)
from app.services.route_resolution import Route, resolve_route

# Keys that steer evaluation rather than describe a ticket.
_FLAG_FIELDS = {"dateExclusionTicket", "dateExclusionTravel", "viceVersa"}

# Criterion labels a None field reports, for the caller's needs_data reason.
MISSING_SECTOR = "sector"
MISSING_AIRPORT = "airport"
MISSING_ISSUE_DATE = "issue_date"
MISSING_TOUR_CODE = "tour_code"

FIELD_LABELS = {
    "validFrom": "Valid from", "validTo": "Valid to",
    "continents": "Continents", "countryGroup": "Country group", "city": "City",
    "originContinents": "Origin continent", "destContinents": "Destination continent",
    "originCountryGroup": "Origin country group", "destCountryGroup": "Destination country group",
    "originCountry": "Origin country", "destCountry": "Destination country",
    "originAirport": "Origin airport", "destAirport": "Destination airport",
    "class": "Class", "soto": "SOTO", "tourCode": "Tour code",
    "fareTypeCategory": "Fare type",
}

# Fare types identified by the ticket's tour code — the rule's Tour Code is their parameter.
_TOUR_FARE_TYPES = {"corporate", "excursion", "tour"}

# field → (end of the route, what is read off that airport). See the module note.
_DIRECTIONAL = {
    "originAirport":      ("origin", "code"),
    "destAirport":        ("dest", "code"),
    "originContinents":   ("origin", "continent"),
    "destContinents":     ("dest", "continent"),
    "originCountry":      ("origin", "country"),
    "destCountry":        ("dest", "country"),
    "originCountryGroup": ("origin", "group"),
    "destCountryGroup":   ("dest", "group"),
}
# Whole route inside: origin AND destination.
_WHOLE_ROUTE = {"continents": "continent", "countryGroup": "group", "city": "city"}
_ATTR_NOUN = {"continent": "continent", "country": "country", "group": "country group",
              "city": "city"}


# ── small helpers ────────────────────────────────────────────────────────────

def _val_to_list(v: Any) -> list[str]:
    """Normalize a rule field value (string or list) to a list of lowercase strings."""
    if isinstance(v, list):
        return [str(x).strip().lower() for x in v if x is not None and str(x).strip()]
    s = str(v).strip().lower()
    return [s] if s else []


def _show(v: Any) -> str:
    """A rule value as a person reads it — 'Asia, Europe', not "['Asia', 'Europe']"."""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if x is not None and str(x).strip())
    return str(v)


def _match_any(rule_vals: list[str], ticket_val: str) -> bool:
    """True if ticket_val (lowercased) equals any value in rule_vals."""
    tv = ticket_val.strip().lower()
    return any(rv == tv for rv in rule_vals)


def _segment_listed(code: str, cabin: str, rule_vals: list[str]) -> bool:
    """Is one segment's class among the rule's values? A value is the airline's own class
    code ("e" — B2B Standard rules store those) or a cabin ("economy", "all") resolved
    through the Airline Class Master. `rule_vals` are lowercased by `_val_to_list`."""
    return any(rv == code.lower() or _class_matches_groups({cabin}, rv) for rv in rule_vals)


def _classes_listed(class_cabins: dict[str, str], rule_vals: list[str],
                    inclusion: bool) -> bool:
    """STRICT, per segment (user's rule, 2026-10-27): an inclusion needs EVERY segment's
    class listed, an exclusion bites on ANY. "H/ H/ E/ N" with E is outside an E-only
    inclusion and inside an E exclusion."""
    hits = [_segment_listed(code, cabin, rule_vals) for code, cabin in class_cabins.items()]
    return all(hits) if inclusion else any(hits)


def _or3(values) -> bool | None:
    values = list(values)
    if any(v is True for v in values):
        return True
    if any(v is None for v in values):
        return None
    return False


def _tour_code_in(facts: "RuleFacts", rule_codes: list[str]) -> bool | None:
    """Does the ticket carry one of `rule_codes`? With no codes listed, any tour code at all
    (rules saved before Tour Code was required for Corporate / Excursion / Tour). None when
    the source prints no tour code to look at."""
    tc = (facts.tour_code or "").strip().lower()
    if not tc:
        return False if facts.tour_code_known else None
    return tc in rule_codes if rule_codes else True


def _cat_match(rule_vals: list[str], apt_categorization: str) -> bool:
    """Match a rule's country-group values against an airport's categorization.

    Airport DB may store compound values like "MEAI/SAARC" meaning the airport
    belongs to BOTH MEAI and SAARC.  A rule value of "MEAI" should match.
    "GCC/MIDDLE EAST" is a single canonical name — it is matched as a whole.
    """
    if not apt_categorization:
        return False
    apt_lower = apt_categorization.strip().lower()
    # split_categorization knows the canonical group names, so a combination such
    # as "GCC/MIDDLE EAST/APAC" yields {"gcc/middle east", "apac"} rather than
    # shredding the one canonical name that legitimately contains a slash.
    apt_parts = {p.strip().lower() for p in split_categorization(apt_categorization)}
    # Keep the naive split too: pre-existing data may hold values that predate
    # the canonical list, and dropping them here would silently relax a rule.
    apt_parts |= {p.strip().lower() for p in apt_categorization.split("/")}
    return any(rv == apt_lower or rv in apt_parts for rv in rule_vals)


def _city_match(rule_vals: list[str], city: str) -> bool:
    """The airport's city IS the rule's city, or starts with it as a whole word: "London"
    covers "London Heathrow" and "London" but not "East London" (South Africa), which the
    old substring test matched."""
    cn = city.strip().lower()
    for rv in rule_vals:
        if cn == rv or (cn.startswith(rv) and not cn[len(rv)].isalnum()):
            return True
    return False


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _to_date(raw: Any, dayfirst: bool = True) -> date | None:
    """A date from a date, a datetime, or text.

    ISO FIRST. The commission run passes ISO dates, and dateutil with dayfirst=True reads
    "2026-10-05" as 10 MAY — every Valid From / To test on a day ≤ 12 compared the wrong
    date. Other text (an uploaded ticket's "05/10/2026", "14MAY26") still parses day-first.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    if _ISO.match(s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    try:
        from dateutil import parser as dp
        return dp.parse(s, dayfirst=dayfirst).date()
    except Exception:
        return None


def _and3(values) -> bool | None:
    values = list(values)
    if any(v is False for v in values):
        return False
    if any(v is None for v in values):
        return None
    return True


# ── what a rule is judged against ────────────────────────────────────────────

@dataclass
class RuleFacts:
    """One ticket, reduced to what rule fields read. Built once per ticket (`load_facts`)
    and shared by every rule of every deal considered for it."""
    sector: str | None = None
    route: Route | None = None
    issue_date: date | None = None
    travel_date: date | None = None
    booking_class: str | None = None
    cabin_groups: set[str] | None = None     # None: no class to read
    cabin_label: str | None = None
    # Each distinct class code on the ticket → its cabin, in segment order ({"H": "Economy",
    # "E": "Premium Economy"}) — what a strict Class rule reads segment by segment.
    class_cabins: dict[str, str] = field(default_factory=dict)
    tour_code: str | None = None
    # False: the source prints no tour code at all, so a blank one is unknown, not "none".
    tour_code_known: bool = True
    skip_fields: frozenset[str] = frozenset()


async def load_facts(
    db: AsyncSession, *,
    sector: str | None,
    booking_class: str | None,
    issue_date: Any,
    travel_date: Any,
    airline_name: str | None,
    tour_code: str | None = None,
    skip_fields: set[str] | None = None,
    tour_code_known: bool = True,
) -> RuleFacts:
    """Everything `evaluate_rule` needs that lives in a master table — the route's airports
    and the class codes' cabins — fetched once (both lookups are memoised per session)."""
    has_class = bool((booking_class or "").strip())
    master = await _class_master_map(db, airline_name or "") if has_class else {}
    return RuleFacts(
        sector=sector,
        route=await resolve_route(db, sector),
        issue_date=_to_date(issue_date),
        travel_date=_to_date(travel_date),
        booking_class=booking_class,
        cabin_groups=await _resolve_cabin_groups(db, airline_name or "", booking_class) if has_class else None,
        cabin_label=await describe_cabin(db, airline_name, booking_class) if has_class else None,
        class_cabins={c: master.get(c) or _fallback_cabin(c)
                      for c in dict.fromkeys(_split_class_codes(booking_class))},
        tour_code=(tour_code or "").strip() or None,
        tour_code_known=tour_code_known,
        skip_fields=frozenset(skip_fields or ()),
    )


# ── the verdict ──────────────────────────────────────────────────────────────

@dataclass
class FieldResult:
    field: str
    rule_value: str
    ticket_value: str
    matched: bool | None             # None = could not be judged
    missing: str | None = None       # what it needed and the ticket could not give

    @property
    def label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field)


@dataclass
class RuleVerdict:
    inclusion: bool
    applies: bool | None             # does the ticket fit what the rule describes
    steps: list[FieldResult] = field(default_factory=list)
    reversed_route: bool = False     # matched only with origin and destination swapped

    @property
    def empty(self) -> bool:
        """No condition the engine knows — the rule constrains nothing."""
        return not self.steps

    @property
    def blocks(self) -> bool:
        """This rule stops the payout: outside an inclusion, or inside an exclusion."""
        if self.empty:
            return False
        return self.applies is False if self.inclusion else self.applies is True

    @property
    def undecided(self) -> bool:
        return not self.empty and self.applies is None

    @property
    def missing(self) -> set[str]:
        return {s.missing for s in self.steps if s.matched is None and s.missing}

    def _labels(self, matched) -> str:
        return ", ".join(s.label for s in self.steps if s.matched is matched)

    def reason(self) -> str:
        """Value-free on purpose: the gaps tab groups rows by reason, and a ticket's own
        values (its country, its dates) would split one actionable bucket into hundreds.
        The popup carries the values."""
        if self.empty:
            return ""
        kind = "inclusion" if self.inclusion else "exclusion"
        vv = " (route matched vice versa)" if self.reversed_route else ""
        if self.applies is False:
            return (f"Outside the inclusion rule — {self._labels(False)} did not match"
                    if self.inclusion else
                    f"Not covered by the exclusion rule — {self._labels(False)} did not match")
        if self.applies is None:
            return f"The {kind} rule could not be checked — {self._labels(None)} not known"
        return (f"Inside the inclusion rule — {self._labels(True)} matched{vv}"
                if self.inclusion else
                f"Excluded by the exclusion rule — {self._labels(True)} matched{vv}")


# ── judging one field ────────────────────────────────────────────────────────

def _no_route(fld: str, raw: Any, facts: RuleFacts) -> FieldResult:
    shown = ("not printed" if not (facts.sector or "").strip()
             else f"'{facts.sector}' is not a route")
    return FieldResult(fld, _show(raw), shown, None, MISSING_SECTOR)


def _at(route: Route, code: str, attr: str, values: list[str]) -> tuple[bool | None, str]:
    """One end of the route against one rule field: (matched, what the ticket showed)."""
    if attr == "code":
        return _match_any(values, code), code
    apt = route.airport(code)
    if apt is None:
        return None, f"{code} (not in Airport Master)"
    raw = {"continent": apt.continent, "country": apt.country,
           "group": apt.categorization, "city": apt.city}[attr]
    if not raw:
        return None, f"{code} (no {_ATTR_NOUN[attr]} in Airport Master)"
    if attr == "group":
        ok = _cat_match(values, raw)
    elif attr == "city":
        # The full master name too: rules saved from the batch page hold
        # "Delhi - Indira Gandhi International Airport", the newer forms "Delhi".
        ok = _city_match(values, raw) or _city_match(values, apt.city_airport_name or "")
    else:
        ok = _match_any(values, raw)
    return ok, f"{raw} ({code})"


def _directional(fld: str, raw: Any, values: list[str], route: Route,
                 origin: str, dest: str) -> FieldResult:
    end, attr = _DIRECTIONAL[fld]
    ok, shown = _at(route, origin if end == "origin" else dest, attr, values)
    return FieldResult(fld, _show(raw), shown, ok, MISSING_AIRPORT if ok is None else None)


def _whole_route(fld: str, raw: Any, values: list[str], route: Route) -> FieldResult:
    attr = _WHOLE_ROUTE[fld]
    o_ok, o_shown = _at(route, route.origin, attr, values)
    d_ok, d_shown = _at(route, route.destination, attr, values)
    ok = _and3((o_ok, d_ok))
    return FieldResult(fld, _show(raw), f"{o_shown} → {d_shown}", ok,
                       MISSING_AIRPORT if ok is None else None)


def _countries(route: Route) -> tuple[str | None, str | None]:
    def c(code):
        apt = route.airport(code)
        return (apt.country or "").strip().lower() or None if apt else None
    return c(route.origin), c(route.destination)


def _date_field(fld: str, raw: Any, rule_data: dict, facts: RuleFacts) -> FieldResult | None:
    rule_date = _to_date(raw, dayfirst=False)
    if rule_date is None:
        return None                   # an unreadable rule date constrains nothing
    use_ticket = str(rule_data.get("dateExclusionTicket") or "").lower() == "true"
    use_travel = str(rule_data.get("dateExclusionTravel") or "").lower() == "true"
    if not use_ticket and not use_travel:
        use_travel = True
    tested = ([("ticket date", facts.issue_date)] if use_ticket else []) + \
             ([("travel date", facts.travel_date)] if use_travel else [])
    shown_rule = f"{rule_date:%d %b %Y}"
    unknown = [name for name, d in tested if d is None]
    if unknown:
        return FieldResult(fld, shown_rule, f"{unknown[0]} not known", None,
                           SKIP_TRAVEL_DATE if unknown[0] == "travel date" else MISSING_ISSUE_DATE)
    if fld == "validFrom":
        ok = all(d >= rule_date for _n, d in tested)
    else:
        ok = all(d <= rule_date for _n, d in tested)
    return FieldResult(fld, shown_rule, ", ".join(f"{n} {d:%d %b %Y}" for n, d in tested), ok)


def _soto(value: str, origin: str | None, dest: str | None) -> bool | None:
    """One SOTO option against a route's two ends (lowercased countries, None = not known).

    SOTO — Sold Outside, Ticketed Outside — is a journey that STARTS outside India (user's
    rules, 2026-10-27); connections never count, only the two ends:

        SOTO All            starts outside India
        SOTO within India   starts outside India, ends in India     (ALA/DEL)
        SOTO outside India  starts outside India, ends outside it   (KUL/DAC, ATQ/DEL/LHR/YYZ)

    so All = within + outside. A journey starting in India is never SOTO, whatever its end.
    """
    if origin is None:
        return None
    if origin == "india":
        return False
    if value == "soto all":
        return True
    if dest is None:
        return None
    if value == "soto within india":
        return dest == "india"
    if value == "soto outside india":
        return dest != "india"
    return False


def _class_shown(facts: RuleFacts) -> str:
    codes = "/".join(facts.class_cabins) or "—"
    return f"{codes} → {facts.cabin_label or '—'}"


def _tour_shown(facts: RuleFacts) -> str:
    if facts.tour_code:
        return facts.tour_code
    return "none" if facts.tour_code_known else "not printed"


def _fare_type(raw: Any, values: list[str], rule_data: dict, facts: RuleFacts,
               inclusion: bool) -> FieldResult:
    """Fare Type Category — see the module note. Any picked value may match (OR)."""
    has_class = bool(facts.class_cabins) and "class" not in facts.skip_fields
    tour_codes = _val_to_list(rule_data.get("tourCode") or [])
    results: list[bool | None] = []
    missing: str | None = None
    for fc in values:
        if fc == "normal":
            results.append(True)
        elif fc == "group":
            if not has_class:
                results.append(None)
                missing = missing or SKIP_CLASS
            else:
                g = [code == "G" for code in facts.class_cabins]
                results.append(all(g) if inclusion else any(g))
        elif fc in _TOUR_FARE_TYPES:
            hit = _tour_code_in(facts, tour_codes)
            results.append(hit)
            if hit is None:
                missing = missing or MISSING_TOUR_CODE
        else:
            results.append(False)
    ok = _or3(results)
    shown = f"class {'/'.join(facts.class_cabins) or 'not printed'} · tour code {_tour_shown(facts)}"
    rule_shown = _show(raw) + (f" (tour code {_show(rule_data.get('tourCode'))})"
                               if tour_codes and _TOUR_FARE_TYPES & set(values) else "")
    return FieldResult("fareTypeCategory", rule_shown, shown, ok, missing if ok is None else None)


def _other_field(fld: str, raw: Any, values: list[str], facts: RuleFacts,
                 rule_data: dict, inclusion: bool) -> FieldResult | None:
    route = facts.route

    if fld in _WHOLE_ROUTE:
        return _whole_route(fld, raw, values, route) if route else _no_route(fld, raw, facts)

    if fld == "class":
        if not facts.class_cabins:
            return FieldResult(fld, _show(raw), "not printed", None, SKIP_CLASS)
        return FieldResult(fld, _show(raw), _class_shown(facts),
                           _classes_listed(facts.class_cabins, values, inclusion))

    if fld == "soto":
        if route is None:
            return _no_route(fld, raw, facts)
        o, d = _countries(route)
        ok = _or3(_soto(sv, o, d) for sv in values)
        shown = f"{(o or '?').title()} → {(d or '?').title()}"
        return FieldResult(fld, _show(raw), shown, ok, MISSING_AIRPORT if ok is None else None)

    if fld == "tourCode":
        if _TOUR_FARE_TYPES & set(_val_to_list(rule_data.get("fareTypeCategory") or [])):
            return None               # Corporate / Excursion / Tour's parameter — judged there
        hit = _tour_code_in(facts, values)
        return FieldResult(fld, _show(raw), _tour_shown(facts), hit,
                           MISSING_TOUR_CODE if hit is None else None)

    if fld == "fareTypeCategory":
        return _fare_type(raw, values, rule_data, facts, inclusion)

    # Anything else — Domestic Country, taken off the form on 2026-10-27, or a key the
    # engine does not know — constrains nothing.
    return None


def evaluate_rule(rule_data: dict, facts: RuleFacts, *, inclusion: bool,
                  vice_versa: bool = False) -> RuleVerdict:
    """Judge one rule against one ticket. Pure — see the module note for the semantics."""
    vv = vice_versa or str(rule_data.get("viceVersa") or "").lower() == "true"
    route = facts.route
    steps: list[FieldResult] = []
    reverse: dict[int, FieldResult] = {}      # step index → the same field, route swapped

    for fld, raw in (rule_data or {}).items():
        if raw is None or raw == "" or raw == [] or fld in _FLAG_FIELDS:
            continue
        if fld in facts.skip_fields:
            # The caller knows this ticket cannot supply it. Skipping is not passing.
            steps.append(FieldResult(fld, _show(raw), "not printed", None,
                                     SKIP_CLASS if fld == "class" else fld))
            continue
        if fld in ("validFrom", "validTo"):
            r = _date_field(fld, raw, rule_data, facts)
            if r is not None:
                steps.append(r)
            continue
        values = _val_to_list(raw)
        if not values:
            continue
        if fld in _DIRECTIONAL:
            if route is None:
                steps.append(_no_route(fld, raw, facts))
                continue
            steps.append(_directional(fld, raw, values, route, route.origin, route.destination))
            if vv:
                reverse[len(steps) - 1] = _directional(
                    fld, raw, values, route, route.destination, route.origin)
            continue
        r = _other_field(fld, raw, values, facts, rule_data, inclusion)
        if r is not None:
            steps.append(r)

    # Vice versa: the origin / destination fields hold in either direction. Show — and judge
    # by — whichever direction fits better; the AND below then equals AND(other fields,
    # OR(forward, reverse)).
    reversed_route = False
    if reverse:
        fwd = _and3(steps[i].matched for i in reverse)
        rev = _and3(r.matched for r in reverse.values())
        if (rev is True and fwd is not True) or (rev is None and fwd is False):
            for i, r in reverse.items():
                steps[i] = FieldResult(r.field, r.rule_value, f"{r.ticket_value} (vice versa)",
                                       r.matched, r.missing)
            reversed_route = True

    applies = _and3(s.matched for s in steps) if steps else None
    return RuleVerdict(inclusion=inclusion, applies=applies, steps=steps,
                       reversed_route=reversed_route)


async def judge_rule(
    db: AsyncSession, rule_data: dict, *, inclusion: bool,
    sector: str | None, booking_class: str | None,
    ticket_date_raw: Any, departure_raw: Any, airline_name: str | None,
    tour_code: str | None = None, skip_fields: set[str] | None = None,
    vice_versa: bool = False, tour_code_known: bool = True,
) -> RuleVerdict:
    facts = await load_facts(
        db, sector=sector, booking_class=booking_class, issue_date=ticket_date_raw,
        travel_date=departure_raw, airline_name=airline_name, tour_code=tour_code,
        skip_fields=skip_fields, tour_code_known=tour_code_known)
    return evaluate_rule(rule_data, facts, inclusion=inclusion, vice_versa=vice_versa)


# ── boolean wrappers (BSP commission, uploaded-ticket calculation) ───────────
# These answer yes / no, so "could not be judged" has to collapse to one side. It collapses
# the way it always did — a field that could not be judged is left out — so these callers
# keep their behaviour apart from the corrected route, dates and class. The commission
# runner reads the three-way verdict instead (commission_core.judge_payout_rules).

async def evaluate_inclusion_for_payout_values(
    db: AsyncSession,
    incl_data: dict,
    *,
    sector:          str | None,
    booking_class:   str | None,
    ticket_date_raw: str | None,
    departure_raw:   str | None,
    airline_name:    str | None,
    tour_code:       str | None = None,
    skip_fields:     set[str] | None = None,
    vice_versa:      bool = False,
) -> tuple[bool, str]:
    """(is_included, reason). Not included only when a field definitely did not match."""
    if not incl_data:
        return True, ""
    v = await judge_rule(
        db, incl_data, inclusion=True, sector=sector, booking_class=booking_class,
        ticket_date_raw=ticket_date_raw, departure_raw=departure_raw,
        airline_name=airline_name, tour_code=tour_code, skip_fields=skip_fields,
        vice_versa=vice_versa)
    if v.applies is False:
        return False, v.reason()
    if not any(s.matched is True for s in v.steps):
        return True, ""
    return True, f"Inside the inclusion rule — {v._labels(True)} matched"


async def evaluate_exclusion_for_payout_values(
    db: AsyncSession,
    excl_data: dict,
    *,
    sector:          str | None,
    booking_class:   str | None,
    ticket_date_raw: str | None,
    departure_raw:   str | None,
    airline_name:    str | None,
    tour_code:       str | None = None,
    skip_fields:     set[str] | None = None,
    vice_versa:      bool = False,
) -> tuple[bool, str]:
    """(is_excluded, reason). Excluded when no field failed and at least one matched."""
    if not excl_data:
        return False, ""
    v = await judge_rule(
        db, excl_data, inclusion=False, sector=sector, booking_class=booking_class,
        ticket_date_raw=ticket_date_raw, departure_raw=departure_raw,
        airline_name=airline_name, tour_code=tour_code, skip_fields=skip_fields,
        vice_versa=vice_versa)
    if v.applies is False or not any(s.matched is True for s in v.steps):
        return False, ""
    return True, f"Excluded by the exclusion rule — {v._labels(True)} matched"


async def evaluate_inclusion_for_payout(
    ticket: UploadedTicket,
    incl_data: dict,
    db: AsyncSession,
) -> tuple[bool, str]:
    return await evaluate_inclusion_for_payout_values(
        db, incl_data,
        sector=ticket.sector,
        booking_class=ticket.booking_class,
        ticket_date_raw=ticket.ticket_date,
        departure_raw=ticket.departure_datetime,
        airline_name=ticket.airline_name,
        tour_code=ticket.tour_code,
    )


async def evaluate_exclusion_for_payout(
    ticket: UploadedTicket,
    excl_data: dict,
    db: AsyncSession,
) -> tuple[bool, str]:
    return await evaluate_exclusion_for_payout_values(
        db, excl_data,
        sector=ticket.sector,
        booking_class=ticket.booking_class,
        ticket_date_raw=ticket.ticket_date,
        departure_raw=ticket.departure_datetime,
        airline_name=ticket.airline_name,
        tour_code=ticket.tour_code,
    )


# ── diagnosis popups ─────────────────────────────────────────────────────────

def diagnostic_from(v: RuleVerdict, rule_name: str):
    """A RuleVerdict in the popup's shape. `is_excluded` True means the rule blocks the
    payout, for both kinds — unchanged, so every existing reader keeps working."""
    from app.schemas.uploaded_ticket import ExclusionRuleDiagnostic, ExclusionRuleStep

    if v.empty:
        return ExclusionRuleDiagnostic(
            rule_name=rule_name, is_excluded=False, steps=[],
            reason=("No condition set — every ticket is included" if v.inclusion
                    else "No condition set — nothing is excluded"))
    return ExclusionRuleDiagnostic(
        rule_name=rule_name, is_excluded=v.blocks, undecided=v.undecided, reason=v.reason(),
        steps=[ExclusionRuleStep(field=s.field, label=s.label, rule_value=s.rule_value,
                                 ticket_value=s.ticket_value, matched=s.matched)
               for s in v.steps],
    )


async def diagnose_inclusion_for_payout(
    incl_data: dict,
    db: AsyncSession,
    sector: str | None,
    booking_class: str | None,
    ticket_date_raw: str | None,
    departure_raw: str | None,
    airline_name: str | None,
    tour_code: str | None = None,
    skip_fields: set[str] | None = None,
    vice_versa: bool = False,
    incentive_type: str | None = None,
    tour_code_known: bool = True,
):
    """is_excluded=True → the ticket is NOT in the inclusion set (left out of the payout)."""
    v = await judge_rule(
        db, incl_data or {}, inclusion=True, sector=sector, booking_class=booking_class,
        ticket_date_raw=ticket_date_raw, departure_raw=departure_raw,
        airline_name=airline_name, tour_code=tour_code, skip_fields=skip_fields,
        vice_versa=vice_versa, tour_code_known=tour_code_known)
    name = "Inclusion For Payout" + (f" · {incentive_type}" if incentive_type else "")
    return diagnostic_from(v, name)


async def diagnose_exclusion_for_payout(
    excl_data: dict,
    db: AsyncSession,
    sector: str | None,
    booking_class: str | None,
    ticket_date_raw: str | None,
    departure_raw: str | None,
    airline_name: str | None,
    tour_code: str | None = None,
    skip_fields: set[str] | None = None,
    vice_versa: bool = False,
    incentive_type: str | None = None,
    tour_code_known: bool = True,
):
    """is_excluded=True → the exclusion rule takes this ticket out of the payout."""
    v = await judge_rule(
        db, excl_data or {}, inclusion=False, sector=sector, booking_class=booking_class,
        ticket_date_raw=ticket_date_raw, departure_raw=departure_raw,
        airline_name=airline_name, tour_code=tour_code, skip_fields=skip_fields,
        vice_versa=vice_versa, tour_code_known=tour_code_known)
    name = "Exclusion For Payout" + (f" · {incentive_type}" if incentive_type else "")
    return diagnostic_from(v, name)
