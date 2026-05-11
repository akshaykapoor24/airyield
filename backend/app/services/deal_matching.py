"""
DealMatchingService — finds the best approved deal for a given ticket.

Match criteria (in order):
  1. Airline name (case-insensitive, resolved from IATA code)
  2. Deal validity: valid_from <= travel_date <= valid_to
  3. Flight type (PLB): Domestic / International / Both vs ticket segment_type DOM/INT
  4. Booking class (PLB): Economy / Business / Premium vs ticket booking_class
  5. Trigger type (airline_deals only): Sales / Flown vs ticket invoice_type
  6. PLB sub-validity dates (if set inside PLB data)

Priority: airline_deals checked first, then b2b_deals.
Incentive computed from PLB targetCalcCols + incentiveAmtPct.
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.airline_deal import AirlineDeal, ManualDealStatus
from app.models.b2b_deal import B2BDeal
from app.models.airline_class_master import AirlineClassMaster

# ── Cabin class groupings ──────────────────────────────────────────────────
_BUSINESS_CLASSES = {"C", "J", "D", "I"}
_FIRST_CLASSES    = {"F", "A", "P"}
# Everything else → Economy


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
    """Query AirlineClassMaster for per-airline class mapping; fall back to hardcoded sets."""
    if not booking_class:
        return {"Economy"}
    codes = [p.strip().upper() for p in booking_class.replace(" ", "").split("/") if p.strip()]
    if not codes:
        return {"Economy"}

    res = await db.execute(
        select(AirlineClassMaster).where(
            func.lower(AirlineClassMaster.airline_name) == airline_name.lower(),
            AirlineClassMaster.class_code.in_(codes),
            AirlineClassMaster.is_active == True,
        )
    )
    master_map = {row.class_code: _normalize_class_type(row.class_type) for row in res.scalars()}

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
    """DOM/INT segment vs PLB flightType (Domestic / International / Both / null)."""
    if not plb_flight_type or plb_flight_type.lower() in ("both", "all", ""):
        return True
    if not segment_type:
        return True  # can't determine, allow
    seg = segment_type.strip().upper()
    ft  = plb_flight_type.strip().lower()
    if seg == "DOM" and ft in ("domestic", "dom"):
        return True
    if seg == "INT" and ft in ("international", "int"):
        return True
    return False



def _trigger_matches(invoice_type: str | None, trigger_type: str | None) -> bool:
    """Ticket invoice_type (Sales/Flown) vs deal trigger_type."""
    if not trigger_type:
        return True
    if not invoice_type:
        return True
    return invoice_type.strip().lower() == trigger_type.strip().lower()


def _plb_dates_match(travel_date: date, plb: dict) -> bool:
    """Optional PLB-level sub-validity dates."""
    vf_raw = plb.get("validFrom")
    vt_raw = plb.get("validTo")
    if not vf_raw or not vt_raw:
        return True  # not constrained
    try:
        vf = date.fromisoformat(str(vf_raw)[:10])
        vt = date.fromisoformat(str(vt_raw)[:10])
        return vf <= travel_date <= vt
    except Exception:
        return True  # unparseable → don't block


# ── Incentive calculation ──────────────────────────────────────────────────

def _compute_incentive(
    sell_fare:    float | None,
    sell_tax_yq:  float | None,
    sale_yr:      float | None,
    plb:          dict,
) -> float | None:
    """
    targetCalcCols variants:
      Basic        → sell_fare
      Basic+YQ     → sell_fare + sell_tax_yq
      Basic+YQ+YR  → sell_fare + sell_tax_yq + sale_yr
      Basic+YR     → sell_fare + sale_yr
    """
    pct_raw = plb.get("incentiveAmtPct")
    if pct_raw is None:
        return None
    try:
        pct = float(pct_raw)
    except (TypeError, ValueError):
        return None

    target = (plb.get("targetCalcCols") or "Basic").upper().replace(" ", "")
    base   = float(sell_fare or 0)
    if "YQ" in target:
        base += float(sell_tax_yq or 0)
    if "YR" in target:
        base += float(sale_yr or 0)

    return round(base * pct / 100, 2)


# ── Result type ────────────────────────────────────────────────────────────

@dataclass
class DealMatchResult:
    deal_id:              int
    deal_type:            str          # 'airline' | 'b2b'
    deal_name:            str
    deal_no:              str          # e.g. "AIR-0014", "B2B-0001"
    calculated_incentive: float | None
    valid_from:           date | None = None
    valid_to:             date | None = None
    deal_maker_name:      str | None  = None


# ── Main service ───────────────────────────────────────────────────────────

class DealMatchingService:

    @staticmethod
    async def find_all_deals(
        db:            AsyncSession,
        airline_name:  str,
        travel_date:   date,
        tenant_id:     int,
        segment_type:  str | None = None,
        booking_class: str | None = None,
        invoice_type:  str | None = None,
        sell_fare:     float | None = None,
        sell_tax_yq:   float | None = None,
        sale_yr:       float | None = None,
    ) -> list[DealMatchResult]:
        """
        Search airline_deals and b2b_deals, return ALL matching deals.
        Results are sorted by calculated_incentive descending (highest first).
        """
        airline_lower = airline_name.lower()
        cabin_groups = await _resolve_cabin_groups(db, airline_name, booking_class)
        matches: list[DealMatchResult] = []

        # ── 1. airline_deals ──────────────────────────────────────────────
        a_result = await db.execute(
            select(AirlineDeal).where(
                and_(
                    AirlineDeal.tenant_id == tenant_id,
                    AirlineDeal.status    == ManualDealStatus.APPROVED,
                    func.lower(AirlineDeal.airline_name) == airline_lower,
                    AirlineDeal.valid_from.is_not(None),
                    AirlineDeal.valid_to.is_not(None),
                    AirlineDeal.valid_from <= travel_date,
                    AirlineDeal.valid_to   >= travel_date,
                )
            ).order_by(AirlineDeal.created_at.desc())
        )
        for deal in a_result.scalars().all():
            match = _try_match(
                deal, "airline", travel_date,
                segment_type, cabin_groups, invoice_type,
                sell_fare, sell_tax_yq, sale_yr, airline_name,
            )
            if match:
                matches.append(match)

        # ── 2. b2b_deals ──────────────────────────────────────────────────
        b_result = await db.execute(
            select(B2BDeal).where(
                and_(
                    B2BDeal.tenant_id == tenant_id,
                    B2BDeal.status    == ManualDealStatus.APPROVED,
                    func.lower(B2BDeal.airline_name) == airline_lower,
                    B2BDeal.valid_from.is_not(None),
                    B2BDeal.valid_to.is_not(None),
                    B2BDeal.valid_from <= travel_date,
                    B2BDeal.valid_to   >= travel_date,
                )
            ).order_by(B2BDeal.created_at.desc())
        )
        for deal in b_result.scalars().all():
            match = _try_match(
                deal, "b2b", travel_date,
                segment_type, cabin_groups, None,   # b2b has no trigger_type
                sell_fare, sell_tax_yq, sale_yr, airline_name,
            )
            if match:
                matches.append(match)

        matches.sort(key=lambda m: m.calculated_incentive or 0, reverse=True)
        return matches

    @staticmethod
    async def find_best_deal(
        db:            AsyncSession,
        airline_name:  str,
        travel_date:   date,
        tenant_id:     int,
        segment_type:  str | None = None,
        booking_class: str | None = None,
        invoice_type:  str | None = None,
        sell_fare:     float | None = None,
        sell_tax_yq:   float | None = None,
        sale_yr:       float | None = None,
    ) -> DealMatchResult | None:
        """Return the single best (highest incentive) matching deal."""
        matches = await DealMatchingService.find_all_deals(
            db=db, airline_name=airline_name, travel_date=travel_date,
            tenant_id=tenant_id, segment_type=segment_type,
            booking_class=booking_class, invoice_type=invoice_type,
            sell_fare=sell_fare, sell_tax_yq=sell_tax_yq, sale_yr=sale_yr,
        )
        return matches[0] if matches else None


def _try_match(
    deal,
    deal_type:     str,
    travel_date:   date,
    segment_type:  str | None,
    cabin_groups:  set[str],
    invoice_type:  str | None,
    sell_fare:     float | None,
    sell_tax_yq:   float | None,
    sale_yr:       float | None,
    fallback_name: str,
) -> DealMatchResult | None:
    """Apply PLB-level filters and compute incentive. Returns None if no match."""
    incentive_data: dict = deal.incentive_data or {}

    # Get the first (and only) PLB entry
    plb: dict = {}
    for val in incentive_data.values():
        if isinstance(val, dict):
            plb = val
            break

    # Filter: flight type
    if not _flight_type_matches(segment_type, plb.get("flightType")):
        return None

    # Filter: booking class (uses class master resolved cabin groups)
    if not _class_matches_groups(cabin_groups, plb.get("class") or plb.get("classType")):
        return None

    # Filter: trigger type (airline deals only)
    if deal_type == "airline" and not _trigger_matches(invoice_type, getattr(deal, "trigger_type", None)):
        return None

    # Filter: PLB sub-validity
    if not _plb_dates_match(travel_date, plb):
        return None

    incentive = _compute_incentive(sell_fare, sell_tax_yq, sale_yr, plb)
    name      = deal.airline_name or fallback_name
    prefix    = {"airline": "AIR", "b2b": "B2B"}.get(deal_type, "UPL")

    return DealMatchResult(
        deal_id=deal.id,
        deal_type=deal_type,
        deal_name=name,
        deal_no=f"{prefix}-{deal.id:04d}",
        calculated_incentive=incentive,
        valid_from=deal.valid_from,
        valid_to=deal.valid_to,
        deal_maker_name=getattr(deal, "deal_maker_name", None),
    )
