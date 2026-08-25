"""
DealMatchingService — finds the best approved deal for a given ticket.

Reads exclusively from the unified `deals` table (new schema).

Match criteria (in order):
  1. Airline name (case-insensitive)
  2. Deal validity: valid_from <= travel_date <= valid_to
  3. Per-incentive: flight_type (Domestic/International/Both)
  4. Per-incentive: booking class (Economy/Business/Premium/All)
  5. Trigger type (airline deals): Sales/Flown vs ticket invoice_type
  6. Per-incentive sub-validity: contract_valid_from / contract_valid_to

`direction` picks which side of the book is searched, and it changes rules 7-8:

  INBOUND  (default) — deals you RECEIVE, the income side. BSP settlement runs
                       and anything else asking "what did we earn". `deal_type`
                       is restricted by statement_type and a B2B deal must name
                       the statement's own supplier.

  OUTBOUND           — deals you FLOAT to a customer, the commission you PAY.
                       What the customer-side ticket run uses. Every outgoing
                       deal is b2b by construction, so statement_type does NOT
                       restrict deal_type here — an AIRLINE-format statement
                       sold to a sub-agency would otherwise match nothing. The
                       supplier-name guard is replaced by `customer_scope`:

                         7. Scope guard — a deal naming a DIFFERENT party is not
                            a candidate at all. Common ('all') deals always are.
                         8. Scope ladder — a deal naming this exact customer
                            beats the common one outright. The common deal is
                            reached only when no customer-specific deal matched.

statement_type restricts which deal_type is searched (INBOUND only):
  "B2B"     → only deals with deal_type="b2b"; supplier enforced
  "AIRLINE" → only deals with deal_type="airline"
  None      → both

Incentive is computed from DealIncentiveConfig:
  Fixed/Percentage → base × incentive_amt_pct / 100
  Fixed/Number     → flat incentive_amt_pct amount
  Slab             → find right band in DealIncentiveSlab, read from DealIncentiveSlabValue
"""
from __future__ import annotations

import calendar
from datetime import date
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from dateutil import parser as _du
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from app.models.airline_class_master import AirlineClassMaster
from app.models.airline import Airline
from app.models.uploaded_ticket import UploadedTicket
from app.models.deal import (
    Deal as UnifiedDeal,
    DealIncentiveConfig,
    DealIncentiveSlab,
    DealRule,
    DealStatusType,
    DealLifecycleType,
    DealDirection,
    DealScopeType,
    build_rule_dict,
)

# ── Cabin class groupings ──────────────────────────────────────────────────
_BUSINESS_CLASSES = {"C", "J", "D", "I"}
_FIRST_CLASSES    = {"F", "A", "P"}
# Everything else → Economy


# ── "criterion not printed by the source document" ─────────────────────────
# A BSP settlement PDF prints no cabin class and no travel date. Passing None
# for those is NOT the same as skipping them: _resolve_cabin_groups turns an
# empty booking class into {"Economy"}, so an Economy-only deal would match by
# accident and a Business deal could never match. Callers name the criteria
# their source cannot supply and the dependent filters are bypassed instead.
SKIP_CLASS       = "class"
SKIP_TRAVEL_DATE = "travel_date"

# Sums the achieved base for an airline over a period, for slab band selection.
# Defaults to the uploaded-ticket scan (_period_cumulative_base); BSP runs pass
# their own provider so the band reflects the airline's own settlement.
CumulativeProvider = Callable[[str, date, date, "str | None", "str | None"], Awaitable[float]]


def _normalize_class_type(raw: str) -> str:
    """'ECONOMY CLASS' → 'Economy', 'BUSINESS CLASS' → 'Business', 'FIRST CLASS' → 'First'."""
    r = raw.upper()
    if "BUSINESS" in r:
        return "Business"
    if "FIRST" in r:
        return "First"
    return "Economy"


async def _resolve_cabin_groups(
    db: AsyncSession,
    airline_name: str,
    booking_class: str | None,
) -> set[str]:
    """Query AirlineClassMaster for per-airline class mapping; fall back to hardcoded sets.

    The master lookup is memoised per session (`db.info`), which matters once BSP rows carry
    a real booking class: this then fires once per row in the matcher AND once per `class`
    rule field in the exclusion evaluator, over tens of thousands of rows. Only the resolved
    {code: group} strings are cached — never ORM rows, which the run's periodic commits
    would expire.
    """
    if not booking_class:
        return {"Economy"}
    codes = [p.strip().upper() for p in booking_class.replace(" ", "").split("/") if p.strip()]
    if not codes:
        return {"Economy"}

    airline_key = (airline_name or "").lower()
    cache: dict[str, dict[str, str]] = db.info.setdefault("_class_master_cache", {})
    master_map = cache.get(airline_key)
    if master_map is None:
        res = await db.execute(
            select(AirlineClassMaster).where(
                func.lower(AirlineClassMaster.airline_name) == airline_key,
                AirlineClassMaster.is_active == True,
            )
        )
        master_map = {row.class_code: _normalize_class_type(row.class_type) for row in res.scalars()}
        cache[airline_key] = master_map

    groups: set[str] = set()
    for code in codes:
        if code in master_map:
            groups.add(master_map[code])
        else:
            if code in _BUSINESS_CLASSES:
                groups.add("Business")
            elif code in _FIRST_CLASSES:
                groups.add("First")
            else:
                groups.add("Economy")
    return groups or {"Economy"}


def _class_matches_groups(cabin_groups: set[str], plb_class: str | None) -> bool:
    if not plb_class or plb_class.lower() in ("all", "both", ""):
        return True
    return plb_class.strip().title() in cabin_groups



# ── Filter helpers ─────────────────────────────────────────────────────────

def _flight_type_matches(segment_type: str | None, plb_flight_type: str | None) -> bool:
    """DOM/INT segment vs PLB flightType (Domestic / International / Both / null).

    Accepts any common variant from the ticket XLS:
      International, INTERNATIONAL, INTL, INTER, Int, INT  → treated as INT
      Domestic, DOMESTIC, Dom, DOM                          → treated as DOM
    """
    if not plb_flight_type or plb_flight_type.lower() in ("both", "all", ""):
        return True
    if not segment_type:
        return True  # can't determine, allow
    seg = segment_type.strip().upper()
    # Normalise full names / aliases → standard abbreviations
    if seg in ("INTERNATIONAL", "INTL", "INTER"):
        seg = "INT"
    elif seg in ("DOMESTIC",):
        seg = "DOM"
    ft = plb_flight_type.strip().lower()
    if seg == "DOM" and ft in ("domestic", "dom"):
        return True
    if seg == "INT" and ft in ("international", "int"):
        return True
    return False



_NORMAL_SALE_TYPES = {"sales", "sale", "invoice"}


def _trigger_matches(invoice_type: str | None, trigger_type: str | None) -> bool:
    """Ticket invoice_type (Sales/Flown) vs deal trigger_type."""
    if not trigger_type:
        return True
    if not invoice_type:
        return True
    iv = invoice_type.strip().lower()
    tt = trigger_type.strip().lower()
    if iv in _NORMAL_SALE_TYPES and tt in _NORMAL_SALE_TYPES:
        return True
    return iv == tt



# ── Incentive calculation ──────────────────────────────────────────────────

def _calc_base(
    sell_fare: float | None,
    sell_tax_yq: float | None,
    sale_yr: float | None,
    target_calc_cols: str | None,
) -> float:
    """Compute the ticket base amount from target_calc_cols (Basic / Basic+YQ / Basic+YQ+YR)."""
    target = (target_calc_cols or "Basic").upper().replace(" ", "")
    base = float(sell_fare or 0)
    if "YQ" in target:
        base += float(sell_tax_yq or 0)
    if "YR" in target:
        base += float(sale_yr or 0)
    return base


def _pick_slab_value(slab: DealIncentiveSlab, seg_key: str, class_key: str):
    """Return (value, value_type) from a slab's values collection, or None."""
    if not slab.values:
        return None
    val_map = {sv.value_key: sv for sv in slab.values if sv.value is not None and sv.value_key != "capped"}
    # Priority: exact segment+class → all+class → segment+all → generic
    for key in (
        f"{seg_key}_{class_key}",
        f"all_{class_key}",
        f"{seg_key}_all",
        class_key,
        "value",
        "amount",
    ):
        if key in val_map:
            sv = val_map[key]
            return float(sv.value), (sv.value_type or "number")
    # Last resort: first available non-capped value
    for sv in slab.values:
        if sv.value_key != "capped" and sv.value is not None:
            return float(sv.value), (sv.value_type or "number")
    return None


def _compute_slab_incentive(
    config: DealIncentiveConfig,
    base: float,
    segment_type: str | None,
    cabin_groups: set[str],
) -> float | None:
    """Find the right slab band and return the computed incentive, or None."""
    if not config.slabs:
        return None

    seg = (segment_type or "").strip().upper()
    if seg in ("DOMESTIC", "DOM"):
        ticket_segment = "Domestic"
        seg_key = "domestic"
    elif seg in ("INTERNATIONAL", "INTL", "INT", "INTER"):
        ticket_segment = "International"
        seg_key = "international"
    else:
        ticket_segment = None
        seg_key = "all"

    # Pick highest-priority cabin class
    class_key = "economy"
    for g in ("Business", "First"):
        if g in cabin_groups:
            class_key = g.lower()
            break

    # Sort by threshold DESC; first slab where base >= threshold wins
    sorted_slabs = sorted(config.slabs, key=lambda s: float(s.base_target_amount or 0), reverse=True)
    for slab in sorted_slabs:
        if base < float(slab.base_target_amount or 0):
            continue
        # Slab-level segment filter
        slab_seg = (slab.segment or "").strip()
        if slab_seg and slab_seg.lower() not in ("both", "all", ""):
            if ticket_segment and slab_seg != ticket_segment:
                continue
        # Slab-level class filter
        slab_cls = (slab.class_ or "").strip()
        if slab_cls and slab_cls.lower() not in ("all", ""):
            if slab_cls.lower() != class_key:
                continue
        picked = _pick_slab_value(slab, seg_key, class_key)
        if picked is None:
            continue
        v, v_type = picked
        if "percent" in v_type.lower():
            result = round(base * v / 100, 2)
        else:
            result = round(v, 2)
        cap = config.capped_incentive_amount
        if cap is not None:
            result = min(result, float(cap))
        return result
    return None


def _compute_incentive_from_config(
    config: DealIncentiveConfig,
    sell_fare:    float | None,
    sell_tax_yq:  float | None,
    sale_yr:      float | None,
    segment_type: str | None = None,
    cabin_groups: set[str] | None = None,
) -> float | None:
    """Compute incentive for one DealIncentiveConfig row — handles Fixed and Slab targets."""
    base = _calc_base(sell_fare, sell_tax_yq, sale_yr, config.target_calc_cols)
    target_based = (config.target_based or "Fixed").strip().lower()

    if target_based == "slab":
        return _compute_slab_incentive(config, base, segment_type, cabin_groups or set())

    # Fixed path
    if config.incentive_amt_pct is None:
        return None
    try:
        amt = float(config.incentive_amt_pct)
    except (TypeError, ValueError):
        return None

    num_pct = (config.incentive_num_pct or "Percentage").strip().lower()
    if "percent" in num_pct:
        result = round(base * amt / 100, 2)
    else:
        result = round(amt, 2)

    cap = config.capped_incentive_amount
    if cap is not None:
        result = min(result, float(cap))
    return result


# ── Ancillary calculation ───────────────────────────────────────────────────
# Ancillary incentive is unique: it is NOT computed from the base fare but from
# the ticket's own ancillary fee columns (Exc. Bag. / Meals / Seat Sel.), each
# scaled by the deal's per-sub-type Percentage or added as a flat Number.

# Deal ancillary sub-type label → ticket fee field. Only these three have a
# corresponding ticket column; the rest (Transport, Group, Lounge, Cab) are skipped.
_ANCILLARY_FEE_LABELS = ("Baggage Type", "Meals", "Seat Fees")


def _compute_ancillary_from_items(
    items: dict | None,
    seat_selection: float | None,
    excess_baggage: float | None,
    meals: float | None,
) -> float | None:
    """Ancillary incentive = sum over Baggage/Meals/Seat of (fee × pct) or flat number.
    Returns None when no sub-type applies (so the column stays empty)."""
    if not items:
        return None
    fee_by_label = {
        "Baggage Type": excess_baggage,
        "Meals":        meals,
        "Seat Fees":    seat_selection,
    }
    total = 0.0
    matched = False
    for label in _ANCILLARY_FEE_LABELS:
        sub = items.get(label)
        if not isinstance(sub, dict):
            continue
        amount = sub.get("amount")
        if amount in (None, ""):
            continue
        with_type = (sub.get("withType") or "").strip().lower()
        if with_type.startswith("without"):      # "Without Baggage/Meal/Seat Fees" → excluded
            continue
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            continue
        num_pct = (sub.get("numPct") or "Percentage").strip().lower()
        if "percent" in num_pct:
            total += float(fee_by_label[label] or 0) * amt / 100.0
        else:                                     # "Number" → flat amount per ticket
            total += amt
        matched = True
    return round(total, 2) if matched else None


# ── Slab (cumulative) calculation ───────────────────────────────────────────
# Slab incentives depend on the TOTAL achieved sales for the airline in the
# period (quarter / half / year), not a single ticket. The period is derived
# from the ticket's departure date + the deal's Contract Year + the incentive's
# Frequency. The cumulative total selects the slab band; the % is then read by
# the ticket's own segment × class. (Fixed deals are untouched by all of this.)

def _is_slab(config: DealIncentiveConfig) -> bool:
    return (config.amount_based_type or "").strip().lower() == "slab based" or bool(getattr(config, "slabs", None))


def _safe_date(*raws: str | None) -> date | None:
    for raw in raws:
        if not raw:
            continue
        try:
            s = str(raw).strip()
            # ISO YYYY-MM-DD — parse directly to avoid dayfirst misreading 06 as day
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s[:10])
            return _du.parse(s, dayfirst=True).date()
        except Exception:
            continue
    return None


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _period_range(d: date, contract_year: str | None, frequency: str | None):
    """Return (period_label, start_date, end_date) for the bucket the date falls in,
    honouring Calendar vs Financial year. None if frequency isn't slab-relevant."""
    cy = (contract_year or "").strip().lower()
    financial = "financial" in cy or cy == "fy"
    freq = (frequency or "").strip().lower()
    y, m = d.year, d.month

    if "quarter" in freq:
        if not financial:                                  # Calendar quarters
            q = (m - 1) // 3 + 1
            sm = (q - 1) * 3 + 1
            return (f"Q{q}", date(y, sm, 1), _month_end(y, sm + 2))
        fy_q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3, 1: 4, 2: 4, 3: 4}[m]
        sy = y if m >= 4 else y - 1                         # financial-year start year
        qy, qm = {1: (sy, 4), 2: (sy, 7), 3: (sy, 10), 4: (sy + 1, 1)}[fy_q]
        return (f"Q{fy_q}", date(qy, qm, 1), _month_end(qy, qm + 2))

    if "half" in freq:
        if not financial:
            if m <= 6:
                return ("H1", date(y, 1, 1), date(y, 6, 30))
            return ("H2", date(y, 7, 1), date(y, 12, 31))
        if 4 <= m <= 9:
            return ("H1", date(y, 4, 1), _month_end(y, 9))
        sy = y if m >= 10 else y - 1
        return ("H2", date(sy, 10, 1), _month_end(sy + 1, 3))

    if "year" in freq:
        if not financial:
            return ("Y1", date(y, 1, 1), date(y, 12, 31))
        sy = y if m >= 4 else y - 1
        return ("Y1", date(sy, 4, 1), _month_end(sy + 1, 3))

    return None


def _slab_seg_key(segment_type: str | None) -> str:
    s = (segment_type or "").strip().upper()
    if s in ("INTERNATIONAL", "INTL", "INTER", "INT"):
        return "intl"
    return "dom"   # default / domestic


def _slab_class_key(cabin_groups: set[str] | None, config_class: str | None = None) -> str:
    """Slab rate cell class. When the source has no cabin class (cabin_groups is
    None), fall back to the class the incentive itself is written for, so a
    Business-only deal reads its Business rate instead of an Economy one."""
    if cabin_groups is None:
        c = (config_class or "").strip().lower()
        if c in ("business", "first"):
            return "Business"
        if "premium" in c:
            return "Premium"
        return "Economy"
    g = {x.lower() for x in cabin_groups}
    if "business" in g or "first" in g:
        return "Business"
    if any("premium" in x for x in g):
        return "Premium"
    return "Economy"


def _pick_amount_slab_cell(slab: DealIncentiveSlab, seg_key: str, class_key: str) -> float | None:
    """Read the band's % for this segment × class — keys are 'domEconomy', 'intlBusiness', …"""
    if not slab.values:
        return None
    want = f"{seg_key}{class_key}"
    for sv in slab.values:
        if sv.value_key == want and sv.value is not None:
            return float(sv.value)
    return None


async def _period_cumulative_base(
    db: AsyncSession,
    airline_name: str,
    start: date,
    end: date,
    flight_type: str | None,
    target_calc_cols: str | None,
    tenant_id: int,
    created_by_id: int,
) -> float:
    """Sum the base of every ticket for this airline whose departure date is in
    [start, end] and whose segment matches the incentive's flight type."""
    ares = await db.execute(select(Airline).where(func.lower(Airline.name) == airline_name.lower()))
    airline = ares.scalar_one_or_none()
    variants: set[str] = set()
    if airline:
        for c in (airline.iata_code, airline.icao_code):
            if not c:
                continue
            c = c.strip()
            variants.add(c.upper())
            if c.isdigit():
                variants.add(c.zfill(3))
                variants.add(c.lstrip("0") or c)
    if not variants:
        return 0.0

    tres = await db.execute(
        select(
            UploadedTicket.sell_fare, UploadedTicket.sell_tax_yq, UploadedTicket.sale_yr,
            UploadedTicket.departure_datetime, UploadedTicket.ticket_date, UploadedTicket.segment_type,
        ).where(
            UploadedTicket.tenant_id == tenant_id,
            UploadedTicket.created_by_id == created_by_id,
            func.upper(UploadedTicket.airlines_code).in_({v.upper() for v in variants}),
        )
    )
    total = 0.0
    for sf, yq, yr, dep, tdate, seg in tres.all():
        if sf is None:
            continue
        if not _flight_type_matches(seg, flight_type):
            continue
        d = _safe_date(dep, tdate)
        if d is None or not (start <= d <= end):
            continue
        total += _calc_base(
            float(sf),
            float(yq) if yq is not None else None,
            float(yr) if yr is not None else None,
            target_calc_cols,
        )
    return round(total, 2)


_SEG_LABEL = {"dom": "Domestic", "intl": "International"}


async def _compute_slab_cumulative_detailed(
    db: AsyncSession,
    config: DealIncentiveConfig,
    deal: UnifiedDeal,
    travel_date: date,
    segment_type: str | None,
    cabin_groups: set[str] | None,
    sell_fare: float | None,
    sell_tax_yq: float | None,
    sale_yr: float | None,
    tenant_id: int,
    created_by_id: int,
    airline_name: str,
    cumulative_provider: CumulativeProvider | None = None,
) -> tuple[float | None, dict]:
    """Slab incentive for one ticket + a human-readable breakdown for the diagnosis
    popup. Find the period band from the cumulative achieved sales, then apply the
    band's segment×class %. No cap (out of scope)."""
    base = _calc_base(sell_fare, sell_tax_yq, sale_yr, config.target_calc_cols)
    seg_key, class_key = _slab_seg_key(segment_type), _slab_class_key(cabin_groups, config.class_)
    cell_label = f"{_SEG_LABEL.get(seg_key, 'Domestic')} {class_key}"
    num_pct = (config.incentive_num_pct or "Percentage").strip().lower()
    det: dict = {"cell_label": cell_label, "base": round(base, 2), "num_pct": "Percentage" if "percent" in num_pct else "Number"}

    if not config.slabs:
        det["formula"] = "slab — no slab rows configured"
        return None, det
    # Date-wise slabs (B2B Standard) carry an explicit [valid_from, valid_to] per
    # row that replaces the Quarterly/Half-Yearly frequency period. Otherwise fall
    # back to deriving the period from Contract Year + Frequency.
    date_wise = any(s.valid_from and s.valid_to for s in config.slabs)
    if date_wise:
        candidates = [
            s for s in config.slabs
            if s.valid_from and s.valid_to and s.valid_from <= travel_date <= s.valid_to
        ]
        if not candidates:
            det["formula"] = f"slab — travel date {travel_date} outside every slab date window"
            return None, det
        start = min(s.valid_from for s in candidates)
        end   = max(s.valid_to   for s in candidates)
        label = f"{start:%d %b %Y}–{end:%d %b %Y}"
    else:
        pr = _period_range(travel_date, deal.contract_year, config.frequency)
        if pr is None:
            det["formula"] = f"slab — could not resolve period (Contract Year / Frequency missing)"
            return None, det
        label, start, end = pr
        candidates = None   # resolved after cumulative via the frequency-label filter

    det.update({
        "period_label": label,
        "period_range": f"{start:%d %b %Y} → {end:%d %b %Y}",
    })

    if cumulative_provider is not None:
        cumulative = await cumulative_provider(
            airline_name, start, end, config.flight_type, config.target_calc_cols,
        )
    else:
        cumulative = await _period_cumulative_base(
            db, airline_name, start, end, config.flight_type, config.target_calc_cols, tenant_id, created_by_id,
        )
    det["achieved"] = round(cumulative, 2)

    if candidates is None:
        def _slab_in_period(s: DealIncentiveSlab) -> bool:
            if label.startswith("Q"):
                return (s.quarterly_freq or "").strip().upper() == label
            if label.startswith("H"):
                return (s.half_yearly_freq or "").strip().upper() == label
            return True   # Yearly → all slab rows
        candidates = [s for s in config.slabs if _slab_in_period(s)] or list(config.slabs)

    # Highest band whose minimum (base_target_amount = Target From) ≤ cumulative.
    # Above the top band → top band (highest threshold wins). Below the first → 0.
    candidates.sort(key=lambda s: float(s.base_target_amount or 0), reverse=True)
    chosen = next((s for s in candidates if cumulative >= float(s.base_target_amount or 0)), None)
    if chosen is None:
        min_target = min((float(s.base_target_amount or 0) for s in candidates), default=0)
        det["target"] = round(min_target, 2)
        det["formula"] = (
            f"{label}: achieved ₹{cumulative:,.0f} < min target ₹{min_target:,.0f} → target not met (₹0)"
        )
        return 0.0, det   # target not met

    target = float(chosen.base_target_amount or 0)
    det["target"] = round(target, 2)
    cell = _pick_amount_slab_cell(chosen, seg_key, class_key)
    if cell is None:
        det["formula"] = f"{label}: band ≥₹{target:,.0f} reached, but no rate set for {cell_label}"
        return None, det

    det["cell_pct"] = cell
    if "percent" in num_pct:
        inc = round(base * cell / 100, 2)
        det["formula"] = (
            f"{label} achieved ₹{cumulative:,.0f} → band ≥₹{target:,.0f} → {cell_label} {cell}% · "
            f"₹{round(base,2):,.0f} × {cell}% = ₹{inc:,.2f}"
        )
    else:
        inc = round(cell, 2)
        det["formula"] = (
            f"{label} achieved ₹{cumulative:,.0f} → band ≥₹{target:,.0f} → {cell_label} flat ₹{inc:,.2f}"
        )
    det["incentive"] = inc
    return inc, det


async def _compute_slab_cumulative(
    db: AsyncSession,
    config: DealIncentiveConfig,
    deal: UnifiedDeal,
    travel_date: date,
    segment_type: str | None,
    cabin_groups: set[str] | None,
    sell_fare: float | None,
    sell_tax_yq: float | None,
    sale_yr: float | None,
    tenant_id: int,
    created_by_id: int,
    airline_name: str,
    cumulative_provider: CumulativeProvider | None = None,
) -> float | None:
    inc, _ = await _compute_slab_cumulative_detailed(
        db, config, deal, travel_date, segment_type, cabin_groups,
        sell_fare, sell_tax_yq, sale_yr, tenant_id, created_by_id, airline_name,
        cumulative_provider=cumulative_provider,
    )
    return inc


# ── Outgoing-deal customer scope ───────────────────────────────────────────
# The mirror image of Deal.scope_type, read off the TICKET. An outgoing deal is
# floated either to one named party or to everybody; this says which party the
# ticket in hand was sold to, so the two can be compared.

@dataclass(frozen=True)
class CustomerScope:
    """WHO a ticket was sold to, as the outgoing matcher needs it.

    `kind` is 'agency' | 'corporate' | 'direct' | None. None is NOT the same as
    'direct': direct means the sale is known to be to a walk-in, None means the
    ticket carries no customer tag at all. Both reach common deals only, but the
    second is a data gap worth reporting rather than a business fact.
    """
    kind:         str | None = None
    agency_id:    int | None = None
    corporate_id: int | None = None
    name:         str | None = None      # display only, for diagnosis text


# Ladder rungs. Higher wins outright — a deal naming this exact customer is used
# even when a common deal would have paid more, because the specific arrangement
# IS the agreement with that customer.
SCOPE_SPECIFIC = 2
SCOPE_COMMON   = 1

_SCOPE_LABEL = {SCOPE_SPECIFIC: "customer-specific", SCOPE_COMMON: "common"}


def _deal_scope_type(deal: UnifiedDeal) -> str:
    st = deal.scope_type
    return st.value if hasattr(st, "value") else str(st or DealScopeType.ALL.value)


def _scope_tier(deal: UnifiedDeal, party: CustomerScope | None) -> int | None:
    """Which rung of the ladder this outgoing deal sits on for this ticket.

    None means the deal is not a candidate at all — it names a different party.
    A party-less ticket (direct, or untagged) can only ever reach common deals;
    it must never fall through to some other agency's rate.
    """
    st = _deal_scope_type(deal)
    if st == DealScopeType.ALL.value:
        return SCOPE_COMMON
    if party is None:
        return None
    if st == DealScopeType.AGENCY.value:
        if party.kind == "agency" and party.agency_id is not None and deal.agency_id == party.agency_id:
            return SCOPE_SPECIFIC
        return None
    if st == DealScopeType.CORPORATE.value:
        if party.kind == "corporate" and party.corporate_id is not None and deal.corporate_id == party.corporate_id:
            return SCOPE_SPECIFIC
        return None
    return None


def _party_label(party: CustomerScope | None) -> str:
    if party is None or party.kind is None:
        return "untagged"
    if party.name:
        return f"{party.kind}: {party.name}"
    ident = party.agency_id if party.kind == "agency" else party.corporate_id
    return f"{party.kind} #{ident}" if ident else party.kind


def _deal_scope_label(deal: UnifiedDeal) -> str:
    st = _deal_scope_type(deal)
    if st == DealScopeType.ALL.value:
        return "All Customers"
    return f"{st}: {deal.scope_party_name or deal.supplier_name or '—'}"


# ── Result type ────────────────────────────────────────────────────────────

@dataclass
class DealMatchResult:
    deal_id:              int
    deal_type:            str           # 'airline' | 'b2b'
    deal_name:            str
    deal_no:              str           # e.g. "AIR-0014", "B2B-0001"
    calculated_incentive: float | None  # PLB value (backward compat)
    incentive_breakdown:  dict[str, float] = field(default_factory=dict)
    is_unified:           bool = False  # True = came from unified deals table
    valid_from:           date | None = None
    valid_to:             date | None = None
    deal_maker_name:      str | None  = None
    iata_commission:      str | None  = None  # deal's IATA commission %, applied to ticket sell fare
    # Outgoing runs only: which rung of the scope ladder this deal was reached on.
    # None on inbound matches, which have no scope.
    scope_tier:           int | None  = None
    scope_label:          str | None  = None


# ── Main service ───────────────────────────────────────────────────────────

class DealMatchingService:

    @staticmethod
    async def find_all_deals(
        db:              AsyncSession,
        airline_name:    str,
        travel_date:     date,
        tenant_id:       int,
        created_by_id:   int,
        issue_date:      date | None = None,
        segment_type:    str | None = None,
        booking_class:   str | None = None,
        invoice_type:    str | None = None,
        sell_fare:       float | None = None,
        sell_tax_yq:     float | None = None,
        sale_yr:         float | None = None,
        seat_selection:  float | None = None,
        excess_baggage:  float | None = None,
        meals:           float | None = None,
        supplier_agency: str | None = None,
        statement_type:  str | None = None,
        skip_criteria:   set[str] | None = None,
        cumulative_provider: CumulativeProvider | None = None,
        direction:       DealDirection = DealDirection.INBOUND,
        customer_scope:  CustomerScope | None = None,
    ) -> list[DealMatchResult]:
        """
        Search the unified deals table, return ALL matching deals sorted by
        calculated_incentive descending (highest first).

        statement_type restricts which deal_type is searched (INBOUND only):
          "B2B"     → only deals with deal_type="b2b"; supplier match enforced.
          "AIRLINE" → only deals with deal_type="airline".
          None/other → both deal types.

        direction picks the side of the book. OUTBOUND searches the deals you
        floated to your customers instead of the ones you receive, drops the
        statement_type→deal_type restriction (every outgoing deal is b2b), and
        swaps the supplier-name guard for customer_scope: deals naming another
        party are dropped, and a deal naming THIS customer beats the common one
        outright — the common deal is returned only when no specific one matched.

        skip_criteria names the filters the caller's source cannot evaluate
        (SKIP_CLASS / SKIP_TRAVEL_DATE) — used by BSP settlement rows, which
        print no cabin class and no travel date. cumulative_provider overrides
        where slab achievement is summed from.
        """
        airline_lower = airline_name.lower()
        is_outbound = direction == DealDirection.OUTBOUND
        # Outgoing deals are always b2b, so an AIRLINE-format statement sold to a
        # sub-agency must NOT be narrowed to deal_type='airline' — that pool is
        # empty by construction and every such ticket would come back unmatched.
        is_b2b     = not is_outbound and (statement_type or "").upper() == "B2B"
        is_airline = not is_outbound and (statement_type or "").upper() == "AIRLINE"
        skips = skip_criteria or set()
        # None = "unknown", which the slab cell picker reads differently from an
        # empty set; never fabricate {"Economy"} for a source without a class.
        cabin_groups = (
            None if SKIP_CLASS in skips
            else await _resolve_cabin_groups(db, airline_name, booking_class)
        )
        matches: list[DealMatchResult] = []

        # Contract validity keys off the ticket ISSUE date; travel/slab checks keep
        # the departure date. Fall back to travel_date when no issue date is given.
        contract_date = issue_date or travel_date

        # ── Unified deals table (single source of truth) ───────────────────
        where_clauses = [
            UnifiedDeal.tenant_id             == tenant_id,
            UnifiedDeal.created_by_id         == created_by_id,
            # One side of the book only, and never a mix. INBOUND deals are the
            # income you earn; OUTBOUND deals are the commission you pay a customer.
            # A run asking for one must never be handed the other.
            UnifiedDeal.direction             == direction,
            UnifiedDeal.status                == DealStatusType.APPROVED,
            UnifiedDeal.deal_lifecycle_status == DealLifecycleType.ACTIVE,
            func.lower(UnifiedDeal.airline_name) == airline_lower,
            UnifiedDeal.valid_from.is_not(None),
            UnifiedDeal.valid_to.is_not(None),
            UnifiedDeal.valid_from <= contract_date,
            UnifiedDeal.valid_to   >= contract_date,
        ]
        # Push deal_type filter into the query to reduce rows fetched
        if is_b2b:
            where_clauses.append(UnifiedDeal.deal_type == "b2b")
        elif is_airline:
            where_clauses.append(UnifiedDeal.deal_type == "airline")

        u_result = await db.execute(
            select(UnifiedDeal)
            .options(
                selectinload(UnifiedDeal.incentives)
                .selectinload(DealIncentiveConfig.slabs)
                .selectinload(DealIncentiveSlab.values)
            )
            .where(and_(*where_clauses))
            .order_by(UnifiedDeal.created_at.desc())
        )
        for deal in u_result.scalars().all():
            deal_type_str = deal.deal_type.value  # "airline" | "b2b"

            if is_outbound:
                # Scope guard. Replaces the supplier-name guard entirely: an
                # outgoing deal's supplier_name is a snapshot of the scope label
                # ("All Customers" on a common deal), so comparing it to the
                # statement's agency name would reject every common deal.
                scope_tier = _scope_tier(deal, customer_scope)
                if scope_tier is None:
                    continue
            else:
                scope_tier = None
                # Supplier guard (B2B)
                if deal_type_str == "b2b" and supplier_agency:
                    if deal.supplier_name and deal.supplier_name.lower() != supplier_agency.lower():
                        continue

            # Trigger guard (airline deals only)
            if deal_type_str == "airline" and not _trigger_matches(invoice_type, deal.trigger_type):
                continue

            # Per-incentive matching: flight type, class, sub-validity, compute
            breakdown: dict[str, float] = {}
            for config in deal.incentives:
                if not _flight_type_matches(segment_type, config.flight_type):
                    continue
                if SKIP_CLASS not in skips and not _class_matches_groups(cabin_groups or set(), config.class_):
                    continue
                vf = config.contract_valid_from
                vt = config.contract_valid_to
                if vf and vt and not (vf <= contract_date <= vt):
                    continue
                # Travel-date window (B2B Standard, date-wise). Only enforced when both
                # bounds are set; NULL on legacy/airline deals ⇒ no travel filter.
                tvf = config.travel_valid_from
                tvt = config.travel_valid_to
                if SKIP_TRAVEL_DATE not in skips and tvf and tvt and not (tvf <= travel_date <= tvt):
                    continue
                if config.ancillary_items:
                    # Ancillary → from the ticket's own fee columns, not the base fare.
                    inc = _compute_ancillary_from_items(
                        config.ancillary_items, seat_selection, excess_baggage, meals,
                    )
                elif _is_slab(config):
                    # Slab → cumulative period band (Fixed path is left untouched).
                    inc = await _compute_slab_cumulative(
                        db, config, deal, travel_date, segment_type, cabin_groups,
                        sell_fare, sell_tax_yq, sale_yr, tenant_id, created_by_id, airline_name,
                        cumulative_provider=cumulative_provider,
                    )
                else:
                    inc = _compute_incentive_from_config(
                        config, sell_fare, sell_tax_yq, sale_yr, segment_type, cabin_groups,
                    )
                if inc is not None:
                    breakdown[config.incentive_type] = inc

            if breakdown:
                # Total incentive = sum of all computed types; used for ranking + Delta Comm
                total_inc = round(sum(breakdown.values()), 2)
                matches.append(DealMatchResult(
                    deal_id=deal.id,
                    deal_type=deal_type_str,
                    deal_name=deal.airline_name or airline_name,
                    # 6 digits, matching deals.py:_unified_deal_to_repo_item — the two
                    # used to disagree, so one deal showed a different number in the
                    # repository than in a commission row.
                    deal_no=f"{'B2B' if deal_type_str == 'b2b' else 'AIR'}-{deal.id:06d}",
                    calculated_incentive=total_inc,
                    incentive_breakdown=breakdown,
                    is_unified=True,
                    valid_from=deal.valid_from,
                    valid_to=deal.valid_to,
                    deal_maker_name=deal.deal_maker_name,
                    iata_commission=deal.iata_commission,
                    scope_tier=scope_tier,
                    scope_label=_deal_scope_label(deal) if is_outbound else None,
                ))

        # ── Scope ladder (outgoing only) ───────────────────────────────────
        # A deal written for THIS customer wins outright, even when a common deal
        # would have paid more — the specific arrangement is the agreement with
        # that customer, not the best of several offers. A specific deal that
        # matched but computed ₹0 (slab target not met) still wins its tier: it
        # applied and paid nothing, which is not the same as not applying.
        if is_outbound and matches:
            best_tier = max(m.scope_tier or SCOPE_COMMON for m in matches)
            matches = [m for m in matches if (m.scope_tier or SCOPE_COMMON) == best_tier]

        matches.sort(key=lambda m: m.calculated_incentive or 0, reverse=True)
        return matches

    @staticmethod
    async def diagnose_match(
        db:                  AsyncSession,
        airline_name:        str,
        travel_date:         date,
        tenant_id:           int,
        created_by_id:       int,
        issue_date:          date | None = None,
        segment_type:        str | None = None,
        booking_class:       str | None = None,
        invoice_type:        str | None = None,
        sell_fare:           float | None = None,
        sell_tax_yq:         float | None = None,
        sale_yr:             float | None = None,
        ticket_sector:       str | None = None,
        ticket_date_raw:     str | None = None,
        ticket_departure_raw: str | None = None,
        ticket_airline_name: str | None = None,
        supplier_agency:     str | None = None,
        tour_code:           str | None = None,
        statement_type:      str | None = None,
        skip_criteria:       set[str] | None = None,
        rule_skip_fields:    set[str] | None = None,
        cumulative_provider: CumulativeProvider | None = None,
        direction:           DealDirection = DealDirection.INBOUND,
        customer_scope:      CustomerScope | None = None,
    ) -> list:
        """
        Return a full step-by-step diagnostic for every approved deal belonging to this
        airline+tenant.
        statement_type restricts which unified deals are shown in diagnosis (INBOUND only):
          "B2B"     → only deal_type="b2b"; supplier match enforced.
          "AIRLINE" → only deal_type="airline".
        Never short-circuits — every PLB step is evaluated.

        direction/customer_scope mirror find_all_deals, and MUST mirror what the
        runner passed: a diagnosis of the income side cannot explain a result the
        customer side produced. On OUTBOUND the supplier step is replaced by a
        Customer Scope step, and a common deal beaten by a customer-specific one
        is shown failing a Scope Priority step rather than quietly disappearing.

        skip_criteria mirrors find_all_deals: named criteria the source cannot
        supply are reported as skipped rather than failed.

        rule_skip_fields mirrors the incl/excl `skip_fields` the *runner* passes. Without
        it the diagnosis evaluates rule fields the run bypassed, so the popup would
        contradict the result it is explaining.
        """
        from app.schemas.uploaded_ticket import (
            MatchStepResult, PLBDiagnostic, DealDiagnostic,
        )

        airline_lower = airline_name.lower()
        is_outbound = direction == DealDirection.OUTBOUND
        party_label = _party_label(customer_scope)
        # deal_id → rung, so the ladder can be explained after every deal is scored.
        scope_tier_by_deal: dict[int, int] = {}
        skips = skip_criteria or set()
        if SKIP_CLASS in skips:
            cabin_groups = None
        else:
            cabin_groups, _ = await _resolve_cabin_groups_with_detail(db, airline_name, booking_class)
        cabin_label = "not printed" if cabin_groups is None else "/".join(sorted(cabin_groups))
        results: list[DealDiagnostic] = []

        # Contract validity keys off the ticket ISSUE date; travel-window + slab use
        # the departure date. Fall back to travel_date when no issue date is given.
        contract_date = issue_date or travel_date

        async def _diagnose_unified_deal(deal: UnifiedDeal) -> DealDiagnostic:
            from app.services.exclusion_evaluator import (
                diagnose_exclusion_for_payout, diagnose_inclusion_for_payout,
            )

            deal_type_str = deal.deal_type.value  # "airline" | "b2b"
            prefix = {"airline": "AIR", "b2b": "B2B"}.get(deal_type_str, "DEAL")
            deal_no = f"{prefix}-{deal.id:06d}"
            deal_name = deal.airline_name or airline_name

            # ── A: Deal-level validity (matched against the ticket ISSUE date) ─
            vf = deal.valid_from
            vt = deal.valid_to
            if vf and vt:
                val_pass = vf <= contract_date <= vt
                val_detail = (
                    f"issue_date={contract_date}, deal valid_from={vf}, valid_to={vt}; "
                    f"{'within range' if val_pass else 'OUTSIDE range — extend the deal validity'}"
                )
            else:
                val_pass = False
                val_detail = "deal has no valid_from/valid_to set — cannot match any ticket"

            deal_validity_step = MatchStepResult(
                step="Deal Validity",
                passed=val_pass,
                ticket_value=str(contract_date),
                deal_value=f"{vf or '—'} → {vt or '—'}",
                detail=val_detail,
            )

            # ── B: Per-incentive config steps ──────────────────────────────
            configs = deal.incentives or []
            plb_diagnostics: list[PLBDiagnostic] = []
            excl_diagnostic = None
            incl_diagnostic = None

            if not configs:
                plb_diagnostics.append(PLBDiagnostic(
                    plb_key="(no incentive configs)",
                    raw_plb={},
                    steps=[MatchStepResult(
                        step="Incentive Configs",
                        passed=False,
                        ticket_value="—",
                        deal_value="none",
                        detail="This deal has no incentive configs attached",
                    )],
                    incentive_breakdown={},
                    plb_overall_match=False,
                ))

            for config in configs:
                steps: list[MatchStepResult] = []

                # Flight type
                ft_val = config.flight_type
                ft_pass = _flight_type_matches(segment_type, ft_val)
                steps.append(MatchStepResult(
                    step="Flight Type",
                    passed=ft_pass,
                    ticket_value=segment_type or "—",
                    deal_value=ft_val or "Any",
                    detail=(
                        f"ticket segment_type='{segment_type}', config flight_type='{ft_val}'; "
                        + ("match" if ft_pass else f"MISMATCH — change config flight_type to '{segment_type}' or 'Both'")
                    ),
                ))

                # Booking class
                cls_key = config.class_
                if SKIP_CLASS in skips:
                    steps.append(MatchStepResult(
                        step="Booking Class",
                        passed=True,
                        ticket_value="not printed",
                        deal_value=cls_key or "Any",
                        detail="this statement does not print a cabin class — class filter skipped",
                    ))
                else:
                    cls_pass = _class_matches_groups(cabin_groups or set(), cls_key)
                    steps.append(MatchStepResult(
                        step="Booking Class",
                        passed=cls_pass,
                        ticket_value=f"{booking_class or '—'} → {cabin_label}",
                        deal_value=cls_key or "Any",
                        detail=(
                            f"booking_class='{booking_class}' resolved to {cabin_groups}; "
                            f"config class='{cls_key}'; "
                            + ("match" if cls_pass else f"MISMATCH — change config class to '{cabin_label}' or 'All'")
                        ),
                    ))

                # Trigger type (airline deals only)
                if deal_type_str == "airline":
                    tr_val = deal.trigger_type
                    tr_pass = _trigger_matches(invoice_type, tr_val)
                    steps.append(MatchStepResult(
                        step="Trigger Type",
                        passed=tr_pass,
                        ticket_value=invoice_type or "—",
                        deal_value=tr_val or "Any",
                        detail=(
                            f"ticket invoice_type='{invoice_type}', deal trigger_type='{tr_val}'; "
                            + ("match" if tr_pass else f"MISMATCH — change deal trigger_type to '{invoice_type}' or leave blank")
                        ),
                    ))

                # Customer scope (outgoing) — who this floated deal is aimed at.
                # Deals naming a different party never reach here; this step is
                # what tells the reader WHICH rung the surviving deal sits on.
                if is_outbound:
                    tier = scope_tier_by_deal.get(deal.id, SCOPE_COMMON)
                    steps.append(MatchStepResult(
                        step="Customer Scope",
                        passed=True,
                        ticket_value=party_label,
                        deal_value=_deal_scope_label(deal),
                        detail=(
                            f"ticket sold to {party_label}; deal floated to "
                            f"{_deal_scope_label(deal)} — reachable as the "
                            f"{_SCOPE_LABEL[tier]} deal"
                        ),
                    ))
                # Supplier (B2B only, income side)
                elif deal_type_str == "b2b" and supplier_agency and deal.supplier_name:
                    sup_pass = deal.supplier_name.lower() == supplier_agency.lower()
                    steps.append(MatchStepResult(
                        step="Supplier Match",
                        passed=sup_pass,
                        ticket_value=supplier_agency,
                        deal_value=deal.supplier_name,
                        detail=(
                            f"statement agency='{supplier_agency}', deal supplier='{deal.supplier_name}'; "
                            + ("match" if sup_pass else "MISMATCH — this deal is for a different supplier")
                        ),
                    ))

                # Config sub-validity (matched against the ticket ISSUE date)
                vf_cfg = config.contract_valid_from
                vt_cfg = config.contract_valid_to
                if vf_cfg and vt_cfg:
                    sv_pass = vf_cfg <= contract_date <= vt_cfg
                    sv_detail = (
                        f"config validFrom='{vf_cfg}', validTo='{vt_cfg}', issue_date={contract_date}; "
                        + ("within range" if sv_pass else "OUTSIDE range — extend config validFrom/validTo")
                    )
                else:
                    sv_pass = True
                    sv_detail = "no sub-validity constraint"
                steps.append(MatchStepResult(
                    step="Config Sub-Validity",
                    passed=sv_pass,
                    ticket_value=str(contract_date),
                    deal_value=f"{vf_cfg or '—'} → {vt_cfg or '—'}",
                    detail=sv_detail,
                ))

                # Travel Date validity (B2B Standard date-wise; matched against the
                # ticket TRAVEL/departure date). Enforced only when both bounds are set.
                tvf_cfg = config.travel_valid_from
                tvt_cfg = config.travel_valid_to
                if tvf_cfg and tvt_cfg and SKIP_TRAVEL_DATE in skips:
                    steps.append(MatchStepResult(
                        step="Travel Date Validity",
                        passed=True,
                        ticket_value="not printed",
                        deal_value=f"{tvf_cfg} → {tvt_cfg}",
                        detail="this statement does not print a travel date — travel window skipped",
                    ))
                elif tvf_cfg and tvt_cfg:
                    tv_pass = tvf_cfg <= travel_date <= tvt_cfg
                    tv_detail = (
                        f"config travelValidFrom='{tvf_cfg}', travelValidTo='{tvt_cfg}', travel_date={travel_date}; "
                        + ("within range" if tv_pass else "OUTSIDE range — extend config travel dates")
                    )
                    steps.append(MatchStepResult(
                        step="Travel Date Validity",
                        passed=tv_pass,
                        ticket_value=str(travel_date),
                        deal_value=f"{tvf_cfg} → {tvt_cfg}",
                        detail=tv_detail,
                    ))

                # Incentive computation — Slab gets the cumulative-band breakdown,
                # Fixed keeps its existing per-ticket formula (unchanged).
                base = _calc_base(sell_fare, sell_tax_yq, sale_yr, config.target_calc_cols)
                target_calc = config.target_calc_cols or "Basic"
                target_upper = target_calc.upper().replace(" ", "")
                yq_added = "YQ" in target_upper
                yr_added = "YR" in target_upper

                if _is_slab(config):
                    inc, det = await _compute_slab_cumulative_detailed(
                        db, config, deal, travel_date, segment_type, cabin_groups,
                        sell_fare, sell_tax_yq, sale_yr, tenant_id, created_by_id, airline_name,
                        cumulative_provider=cumulative_provider,
                    )
                    breakdown_diag = {
                        "incentive_type": config.incentive_type,
                        "target_based": "Slab Based",
                        "targetCalcCols": target_calc,
                        "sell_fare": sell_fare,
                        "sell_tax_yq_added": yq_added,
                        "sell_tax_yq_value": sell_tax_yq,
                        "sale_yr_added": yr_added,
                        "sale_yr_value": sale_yr,
                        "base_total": round(base, 2),
                        "incentiveAmtPct": det.get("cell_pct"),
                        "incentive_num_pct": det.get("num_pct", "Percentage"),
                        "formula": det.get("formula"),
                        "result": inc,
                        # ── slab-specific detail for the diagnosis popup ──
                        "is_slab": True,
                        "slab_period": det.get("period_label"),
                        "slab_period_range": det.get("period_range"),
                        "slab_achieved": det.get("achieved"),
                        "slab_target": det.get("target"),
                        "slab_cell": det.get("cell_label"),
                    }
                else:
                    inc = _compute_incentive_from_config(
                        config, sell_fare, sell_tax_yq, sale_yr, segment_type, cabin_groups,
                    )
                    num_pct_low = (config.incentive_num_pct or "Percentage").lower()
                    if "percent" in num_pct_low:
                        formula_str = f"{round(base, 2)} × {config.incentive_amt_pct}% = {inc}"
                    else:
                        formula_str = f"flat ₹{config.incentive_amt_pct} = {inc}"
                    breakdown_diag = {
                        "incentive_type": config.incentive_type,
                        "target_based": config.target_based or "Fixed",
                        # Keys matching the old PLB format so the frontend display works
                        "targetCalcCols": target_calc,
                        "sell_fare": sell_fare,
                        "sell_tax_yq_added": yq_added,
                        "sell_tax_yq_value": sell_tax_yq,
                        "sale_yr_added": yr_added,
                        "sale_yr_value": sale_yr,
                        "base_total": round(base, 2),
                        "incentiveAmtPct": config.incentive_amt_pct,
                        "incentive_num_pct": num_pct_low.title(),
                        "formula": formula_str,
                        "result": inc,
                    }

                config_overall = all(s.passed for s in steps)

                # Inclusion/Exclusion rules attached to this incentive config
                for rule in (config.rules or []):
                    rule_dict = build_rule_dict(rule.conditions)
                    if not rule_dict:
                        continue
                    if rule.rule_category == "payout_inclusion" and incl_diagnostic is None:
                        incl_diagnostic = await diagnose_inclusion_for_payout(
                            incl_data=rule_dict, db=db,
                            sector=ticket_sector,
                            booking_class=booking_class,
                            ticket_date_raw=ticket_date_raw,
                            departure_raw=ticket_departure_raw,
                            airline_name=ticket_airline_name or airline_name,
                            tour_code=tour_code,
                            skip_fields=rule_skip_fields,
                        )
                    elif rule.rule_category == "payout_exclusion" and excl_diagnostic is None:
                        excl_diagnostic = await diagnose_exclusion_for_payout(
                            excl_data=rule_dict, db=db,
                            sector=ticket_sector,
                            booking_class=booking_class,
                            ticket_date_raw=ticket_date_raw,
                            departure_raw=ticket_departure_raw,
                            airline_name=ticket_airline_name or airline_name,
                            tour_code=tour_code,
                            skip_fields=rule_skip_fields,
                        )

                plb_diagnostics.append(PLBDiagnostic(
                    plb_key=config.incentive_type or f"config-{config.id}",
                    raw_plb=breakdown_diag,
                    steps=steps,
                    incentive_breakdown=breakdown_diag,
                    plb_overall_match=config_overall and inc is not None,
                ))

            overall = deal_validity_step.passed and any(p.plb_overall_match for p in plb_diagnostics)
            # best_incentive = sum of all matched config results
            best_incentive: float | None = None
            total_matched = sum(
                float(p.incentive_breakdown.get("result") or 0)
                for p in plb_diagnostics
                if p.plb_overall_match and p.incentive_breakdown and p.incentive_breakdown.get("result") is not None
            )
            if total_matched > 0:
                best_incentive = round(total_matched, 2)

            lifecycle_str = (
                deal.deal_lifecycle_status.value
                if hasattr(deal.deal_lifecycle_status, "value")
                else str(deal.deal_lifecycle_status or "active")
            )

            return DealDiagnostic(
                deal_id=deal.id,
                deal_type=deal_type_str,
                deal_name=deal_name,
                deal_no=deal_no,
                valid_from=vf,
                valid_to=vt,
                trigger_type=deal.trigger_type,
                supplier_name=deal.supplier_name,
                deal_validity_step=deal_validity_step,
                plbs=plb_diagnostics,
                overall_match=overall,
                best_incentive=best_incentive,
                deal_lifecycle_status=lifecycle_str,
                exclusion_diagnostic=excl_diagnostic,
                inclusion_diagnostic=incl_diagnostic,
            )

        # ── Unified deals table (single source of truth) ───────────────────
        # deal_type is narrowed by statement_type on the income side only; every
        # outgoing deal is b2b, so narrowing an AIRLINE statement here would show
        # an empty diagnosis for a ticket the runner matched fine.
        _is_b2b     = not is_outbound and (statement_type or "").upper() == "B2B"
        _is_airline = not is_outbound and (statement_type or "").upper() == "AIRLINE"

        diag_where = [
            UnifiedDeal.tenant_id == tenant_id,
            UnifiedDeal.created_by_id == created_by_id,
            # Same side of the book the runner searched — see the docstring.
            UnifiedDeal.direction == direction,
            UnifiedDeal.status    == DealStatusType.APPROVED,
            func.lower(UnifiedDeal.airline_name) == airline_lower,
        ]
        if _is_b2b:
            diag_where.append(UnifiedDeal.deal_type == "b2b")
        elif _is_airline:
            diag_where.append(UnifiedDeal.deal_type == "airline")

        d_result = await db.execute(
            select(UnifiedDeal)
            .options(
                selectinload(UnifiedDeal.incentives).options(
                    selectinload(DealIncentiveConfig.slabs)
                    .selectinload(DealIncentiveSlab.values),
                    selectinload(DealIncentiveConfig.rules)
                    .selectinload(DealRule.conditions),
                )
            )
            .where(and_(*diag_where))
            .order_by(UnifiedDeal.created_at.desc())
        )
        for deal in d_result.scalars().all():
            deal_type_str = deal.deal_type.value
            if is_outbound:
                # Skip deals floated to somebody else — they explain nothing here.
                tier = _scope_tier(deal, customer_scope)
                if tier is None:
                    continue
                scope_tier_by_deal[deal.id] = tier
            # Skip wrong supplier for B2B (income side)
            elif deal_type_str == "b2b" and supplier_agency and deal.supplier_name:
                if deal.supplier_name.lower() != supplier_agency.lower():
                    continue
            results.append(await _diagnose_unified_deal(deal))

        # ── Explain the scope ladder ───────────────────────────────────────
        # The runner drops every common deal once a customer-specific one matches.
        # Say so on the dropped deals instead of leaving them looking like winners
        # the run inexplicably ignored.
        if is_outbound and any(
            d.overall_match and scope_tier_by_deal.get(d.deal_id) == SCOPE_SPECIFIC
            for d in results
        ):
            for d in results:
                if scope_tier_by_deal.get(d.deal_id) != SCOPE_COMMON or not d.overall_match:
                    continue
                note = MatchStepResult(
                    step="Scope Priority",
                    passed=False,
                    ticket_value=party_label,
                    deal_value="All Customers",
                    detail=(
                        f"a deal floated specifically to {party_label} also matched — "
                        "a common deal applies only when no customer-specific deal does"
                    ),
                )
                for p in d.plbs:
                    p.steps.append(note)
                    p.plb_overall_match = False
                d.overall_match  = False
                d.best_incentive = None

        return results

    @staticmethod
    async def find_best_deal(
        db:              AsyncSession,
        airline_name:    str,
        travel_date:     date,
        tenant_id:       int,
        created_by_id:   int,
        issue_date:      date | None = None,
        segment_type:    str | None = None,
        booking_class:   str | None = None,
        invoice_type:    str | None = None,
        sell_fare:       float | None = None,
        sell_tax_yq:     float | None = None,
        sale_yr:         float | None = None,
        seat_selection:  float | None = None,
        excess_baggage:  float | None = None,
        meals:           float | None = None,
        supplier_agency: str | None = None,
        statement_type:  str | None = None,
        skip_criteria:   set[str] | None = None,
        cumulative_provider: CumulativeProvider | None = None,
        direction:       DealDirection = DealDirection.INBOUND,
        customer_scope:  CustomerScope | None = None,
    ) -> DealMatchResult | None:
        """Return the single best (highest incentive) matching deal.

        On an OUTBOUND run "best" is read within the winning scope tier only —
        find_all_deals has already dropped the common deals when a deal naming
        this customer matched.
        """
        matches = await DealMatchingService.find_all_deals(
            db=db, airline_name=airline_name, travel_date=travel_date,
            tenant_id=tenant_id, created_by_id=created_by_id, issue_date=issue_date,
            segment_type=segment_type,
            booking_class=booking_class, invoice_type=invoice_type,
            sell_fare=sell_fare, sell_tax_yq=sell_tax_yq, sale_yr=sale_yr,
            seat_selection=seat_selection, excess_baggage=excess_baggage, meals=meals,
            supplier_agency=supplier_agency,
            statement_type=statement_type,
            skip_criteria=skip_criteria,
            cumulative_provider=cumulative_provider,
            direction=direction,
            customer_scope=customer_scope,
        )
        return matches[0] if matches else None


async def _resolve_cabin_groups_with_detail(
    db: AsyncSession,
    airline_name: str,
    booking_class: str | None,
) -> tuple[set[str], str]:
    """Like _resolve_cabin_groups but also returns a human-readable trace string."""
    if not booking_class:
        return {"Economy"}, "booking_class is empty → defaulted to Economy"

    codes = [p.strip().upper() for p in booking_class.replace(" ", "").split("/") if p.strip()]
    if not codes:
        return {"Economy"}, "booking_class parsed to no codes → defaulted to Economy"

    res = await db.execute(
        select(AirlineClassMaster).where(
            func.lower(AirlineClassMaster.airline_name) == airline_name.lower(),
            AirlineClassMaster.class_code.in_(codes),
            AirlineClassMaster.is_active == True,
        )
    )
    master_map = {row.class_code: _normalize_class_type(row.class_type) for row in res.scalars()}

    groups: set[str] = set()
    trace_parts: list[str] = []
    for code in codes:
        if code in master_map:
            groups.add(master_map[code])
            trace_parts.append(f"{code}→{master_map[code]} (AirlineClassMaster)")
        else:
            if code in _BUSINESS_CLASSES:
                g = "Business"
            elif code in _FIRST_CLASSES:
                g = "First"
            else:
                g = "Economy"
            groups.add(g)
            trace_parts.append(f"{code}→{g} (hardcoded fallback)")

    if not groups:
        groups = {"Economy"}
    detail = f"booking_class='{booking_class}'; codes={codes}; resolution: {', '.join(trace_parts)}"
    return groups, detail


