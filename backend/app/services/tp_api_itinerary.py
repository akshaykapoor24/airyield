"""What a Third Party API booking IS — a hotel stay, a train berth, a bus seat — for billing.

`uploaded_tickets` was built for airline tickets: a Ticket Number, an Airline, a Sector. A
hotel night has none of those, and printing "Sector: —" on its invoice line tells the
customer nothing. So every non-air line the projection writes carries `service_details`: a
small JSON description built HERE, which the billing pages and the invoice PDF read instead
of the airline columns. Display only — nothing is ever calculated from it.

DETERMINISTIC, NOT THE AI. TBO packs a train's or a bus's whole itinerary into one NARRATION
sentence, and the review step can already fill `train_name` / `origin` / … from it with the
AI pass (services/ai_statement_narration.py). That pass is optional and per-upload, though,
and TBO's sentences are machine-written with fixed labels — so the fields the AI pass (or a
mapped column) filled are PREFERRED, and a regex over the fixed labels is the fallback. A
bill must not depend on whether someone pressed a button on the review step.

The shape, for every category:

    {"category": "train", "label": "Train",
     "title":   "22221 NZM RAJDHANI",           # the column the Airline name sits in
     "route":   "CSMT → NZM",                   # the column the Sector sits in
     "summary": "22221 NZM RAJDHANI · CSMT → NZM · 3A · 02 Aug 2026",
     ...category fields (ISO dates, bare strings)...}

Keys whose value is unknown are OMITTED rather than stored as null, so the JSON says only
what the statement said.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime

from app.services import flat_statement as _flat
from app.services import markup_categories as mc

_MAX_TEXT = 200


def _clean(value) -> str | None:
    """Trimmed text with HTML entities decoded, or None.

    TBO's export double-escapes ampersands ("Hyatt Regency Pune &amp;amp; Residences"), so
    unescaping once would still print "&amp;" on an invoice. Unescape until it stops
    changing, bounded, because a property name can legitimately contain an "&".
    """
    s = _flat._clean(value)
    if not s:
        return None
    for _ in range(3):
        un = html.unescape(s)
        if un == s:
            break
        s = un
    s = " ".join(s.split())
    return s[:_MAX_TEXT] or None


def _first(data: dict, *fields: str) -> str | None:
    for f in fields:
        v = _clean(data.get(f))
        if v is not None:
            return v
    return None


# TBO writes "Aug  2 2026" — a padded day, so the whitespace is collapsed before parsing.
_NARR_DATE = r"[A-Za-z]{3}\s+\d{1,2}\s+\d{4}"


def _narr_date(raw: str | None) -> str | None:
    """"Aug  2 2026" → "2026-08-02". None when it does not read as that exact shape."""
    if not raw:
        return None
    try:
        return datetime.strptime(" ".join(raw.split()), "%b %d %Y").date().isoformat()
    except ValueError:
        return None


def _display_date(iso: str | None) -> str | None:
    """"2026-08-02" → "02 Aug 2026". Anything that is not ISO is shown as it came."""
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10]).strftime("%d %b %Y")
    except ValueError:
        return iso


def _int_text(value) -> str | None:
    """"4" / "4.0" → "4". Counts are stored as text in `data`."""
    s = _clean(value)
    if s is None:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    return str(int(n)) if n == int(n) and n >= 0 else None


def _search(pattern: str, text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(pattern, text, re.I)
    return _clean(m.group(1)) if m else None


# ── stations: "C SHIVAJI MAH T (CSMT)" → ("C SHIVAJI MAH T", "CSMT") ─────────
_STATION_WITH_CODE = re.compile(r"^(?P<name>.*?)\s*\((?P<code>[A-Z0-9]{2,6})\)\s*$")
_BARE_CODE = re.compile(r"^[A-Z]{2,5}$")


def _station(raw: str | None) -> tuple[str | None, str | None]:
    s = _clean(raw)
    if not s:
        return None, None
    m = _STATION_WITH_CODE.match(s)
    if m:
        return (_clean(m.group("name")), m.group("code"))
    if _BARE_CODE.match(s):
        return None, s          # "CNB" is a code with no name beside it
    return s, None


# ── narration patterns (TBO) ─────────────────────────────────────────────────
_TRAIN = re.compile(
    r"Train\s*Name-\s*(?P<name>.+?)\s+Train\s*number-\s*(?P<number>\S+)"
    r"(?:\s+TravelDate-\s*(?P<date>" + _NARR_DATE + r"))?"
    r"(?:\s+From-\s*(?P<from>.+?))?"
    r"(?:\s+To-\s*(?P<to>.+?))?\s*$",
    re.I,
)
_BUS = {
    "ticket_no": r"TicketNo-\s*(\S+)",
    "seat": r"SeatName-\s*(.+?)\s+(?:Source-|Destination-|DateOfJourney-|$)",
    "from": r"Source-\s*(.+?)\s+(?:Destination-|DateOfJourney-|$)",
    "to": r"Destination-\s*(.+?)(?:\s+DateOfJourney-|\s*$)",
    "date": r"DateOfJourney-\s*(" + _NARR_DATE + r")",
}
_HOTEL = {
    "address": r"Address-\s*(.+?)\s+RoomName-",
    "room_name": r"RoomName-\s*(.+?)\s+Checkin\s*Date-",
    "check_in": r"Checkin\s*Date-\s*(" + _NARR_DATE + r")",
    "check_out": r"CheckOut\s*Date-\s*(" + _NARR_DATE + r")",
    "city": r"City\s*Reference-\s*(.+?)\s*$",
}


def _arrow(a: str | None, b: str | None) -> str | None:
    if a and b:
        return f"{a} → {b}"
    return a or b


def _date_range(start: str | None, end: str | None) -> str | None:
    """"30 Aug → 31 Aug 2026" — the year once when both ends share it."""
    a, b = _display_date(start), _display_date(end)
    if a and b and a[-4:] == b[-4:] and a[-4:].isdigit():
        a = a[:-5]
    return _arrow(a, b)


def _nights(check_in: str | None, check_out: str | None) -> str | None:
    try:
        n = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
    except (TypeError, ValueError):
        return None
    return str(n) if n > 0 else None


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "")}


def _join(*parts) -> str | None:
    s = " · ".join(p for p in parts if p)
    return s or None


# ── per category ─────────────────────────────────────────────────────────────

def _hotel(data: dict, narration: str | None) -> dict:
    check_in = _first(data, "start_date", "travel_date") or _narr_date(_search(_HOTEL["check_in"], narration))
    check_out = _first(data, "end_date") or _narr_date(_search(_HOTEL["check_out"], narration))
    nights = _int_text(data.get("no_of_nights")) or _nights(check_in, check_out)
    property_name = _first(data, "airline_property_name")
    # MMT names the city in `origin` ("Departure/Hotel City"); TBO in `destination`.
    city = _first(data, "destination", "origin") or _search(_HOTEL["city"], narration)
    stay = _date_range(check_in, check_out)
    return _compact({
        "title": property_name or "Hotel",
        "route": city,
        "summary": _join(property_name, city, stay,
                         f"{nights} night{'' if nights == '1' else 's'}" if nights else None),
        "property": property_name,
        "address": _search(_HOTEL["address"], narration),
        "city": city,
        "country": _first(data, "origin_country"),
        "room_name": _search(_HOTEL["room_name"], narration),
        "check_in": check_in,
        "check_out": check_out,
        "nights": nights,
        "rooms": _int_text(data.get("no_of_rooms")),
        "star_rating": _int_text(data.get("hotel_star_rating")),
        "guests": _int_text(data.get("pax_count")),
    })


def _train(data: dict, narration: str | None) -> dict:
    m = _TRAIN.search(narration or "")
    name = _first(data, "train_name") or (_clean(m.group("name")) if m else None)
    number = _first(data, "train_number") or (_clean(m.group("number")) if m else None)
    from_name, from_code = _station(m.group("from") if m else None)
    to_name, to_code = _station(m.group("to") if m else None)
    from_name = _first(data, "origin") or from_name
    from_code = _first(data, "origin_code") or from_code
    to_name = _first(data, "destination") or to_name
    to_code = _first(data, "destination_code") or to_code
    journey = (_first(data, "travel_date", "start_date")
               or _narr_date(m.group("date") if m else None))
    klass = _first(data, "booking_class")
    # A 10-digit reference is the IRCTC PNR. TBO's "TBOB…" reference is its own booking id
    # for a berth IRCTC never confirmed, and must not be printed as a PNR.
    ref = _first(data, "pnr", "reference_no")
    pnr = ref if ref and re.fullmatch(r"\d{10}", ref) else None
    title = " ".join(p for p in (number, name) if p) or "Train"
    route = _arrow(from_code or from_name, to_code or to_name)
    return _compact({
        "title": title,
        "route": route,
        "summary": _join(title if title != "Train" else None, route, klass, _display_date(journey)),
        "train_name": name,
        "train_number": number,
        "from_station": from_name,
        "from_code": from_code,
        "to_station": to_name,
        "to_code": to_code,
        "journey_date": journey,
        "class": klass,
        "quota": _first(data, "quota"),
        "pnr": pnr,
        "passengers": _int_text(data.get("pax_count")),
    })


def _bus(data: dict, narration: str | None) -> dict:
    operator = _first(data, "airline_property_name")
    origin = _first(data, "origin") or _search(_BUS["from"], narration)
    destination = _first(data, "destination") or _search(_BUS["to"], narration)
    journey = _first(data, "travel_date", "start_date") or _narr_date(_search(_BUS["date"], narration))
    seat = _search(_BUS["seat"], narration)
    route = _arrow(origin, destination)
    return _compact({
        "title": operator or "Bus",
        "route": route,
        "summary": _join(operator, route, f"Seat {seat}" if seat else None, _display_date(journey)),
        "operator": operator,
        "ticket_no": _search(_BUS["ticket_no"], narration),
        "seat": seat,
        "from": origin,
        "to": destination,
        "journey_date": journey,
        "passengers": _int_text(data.get("pax_count")),
    })


def _car(data: dict, narration: str | None) -> dict:
    vehicle = _first(data, "vehicle_type", "airline_property_name")
    pickup = _first(data, "origin")
    drop = _first(data, "destination")
    start = _first(data, "start_date", "travel_date")
    end = _first(data, "end_date")
    route = _arrow(pickup, drop)
    when = _date_range(start, end)
    return _compact({
        "title": vehicle or "Car",
        "route": route,
        "summary": _join(vehicle, route, when),
        "vehicle_type": vehicle,
        "vehicles": _int_text(data.get("no_of_vehicle")),
        "pickup": pickup,
        "drop": drop,
        "start_date": start,
        "end_date": end,
    })


def _air(data: dict, narration: str | None) -> dict:
    """For the worklist's summary cell only — an air ticket's details live in its own columns."""
    airline = _first(data, "airline_property_name")
    route = _arrow(_first(data, "origin_code", "origin"), _first(data, "destination_code", "destination"))
    flight = _first(data, "flight_number")
    return _compact({
        "title": airline or "Flight",
        "route": route,
        "summary": _join(airline, route, flight,
                         _display_date(_first(data, "start_date", "travel_date"))),
    })


def _generic(data: dict, narration: str | None) -> dict:
    title = _first(data, "airline_property_name")
    return _compact({"title": title, "summary": _join(title, narration)})


_BUILDERS = {
    mc.CATEGORY_AIR: _air,
    mc.CATEGORY_HOTEL: _hotel,
    mc.CATEGORY_TRAIN: _train,
    mc.CATEGORY_BUS: _bus,
    mc.CATEGORY_CAR: _car,
}


def describe(data: dict, category: str | None) -> dict | None:
    """The `service_details` for one row of a given category, or None with no category."""
    if not category:
        return None
    narration = _clean((data or {}).get("narration"))
    body = _BUILDERS.get(category, _generic)(data or {}, narration)
    return {"category": category,
            "label": mc.CATEGORY_LABELS.get(category, category.title()),
            **body}


def summary(data: dict, category: str | None) -> str | None:
    """Just the one-line description — what the worklist's row shows."""
    d = describe(data, category)
    return d.get("summary") if d else None


def travel_date(details: dict | None) -> str | None:
    """The ISO date this service starts on, for `uploaded_tickets.travel_dt`."""
    if not details:
        return None
    for key in ("check_in", "journey_date", "start_date"):
        if details.get(key):
            return details[key]
    return None
