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
    async def diagnose_match(
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
    ) -> list:
        """
        Return a full step-by-step diagnostic for every approved deal belonging to this
        airline+tenant, regardless of validity dates, so the user can see exactly which
        filter caused the ticket not to match.  Never short-circuits — every step is
        evaluated for every deal and every PLB entry.
        """
        from app.schemas.uploaded_ticket import (
            MatchStepResult, PLBDiagnostic, DealDiagnostic,
        )

        airline_lower = airline_name.lower()
        cabin_groups, _ = await _resolve_cabin_groups_with_detail(db, airline_name, booking_class)
        results: list[DealDiagnostic] = []

        async def _diagnose_deal(deal, deal_type: str) -> DealDiagnostic:
            prefix = {"airline": "AIR", "b2b": "B2B"}.get(deal_type, "UPL")
            deal_no = f"{prefix}-{deal.id:04d}"
            deal_name = deal.airline_name or airline_name

            # ── A: Deal-level validity ─────────────────────────────────────
            vf = deal.valid_from
            vt = deal.valid_to
            if vf and vt:
                val_pass = vf <= travel_date <= vt
                val_detail = (
                    f"travel_date={travel_date}, deal valid_from={vf}, valid_to={vt}; "
                    f"{'within range' if val_pass else 'OUTSIDE range — extend the deal validity'}"
                )
            else:
                val_pass = False
                val_detail = f"deal has no valid_from/valid_to set — cannot match any ticket"

            deal_validity_step = MatchStepResult(
                step="Deal Validity",
                passed=val_pass,
                ticket_value=str(travel_date),
                deal_value=f"{vf or '—'} → {vt or '—'}",
                detail=val_detail,
            )

            # ── B: Per-PLB steps ───────────────────────────────────────────
            incentive_data: dict = deal.incentive_data or {}
            plb_diagnostics: list[PLBDiagnostic] = []

            # If no PLB entries exist at all, add a synthetic placeholder
            plb_items = [(k, v) for k, v in incentive_data.items() if isinstance(v, dict)]
            if not plb_items:
                plb_items = [("(no PLB)", {})]

            for plb_key, plb in plb_items:
                steps: list[MatchStepResult] = []

                # Flight type
                ft_val = plb.get("flightType")
                ft_pass = _flight_type_matches(segment_type, ft_val)
                steps.append(MatchStepResult(
                    step="Flight Type",
                    passed=ft_pass,
                    ticket_value=segment_type or "—",
                    deal_value=ft_val or "Any",
                    detail=(
                        f"ticket segment_type='{segment_type}', PLB flightType='{ft_val}'; "
                        + ("match" if ft_pass else f"MISMATCH — change PLB flightType to '{segment_type}' or 'Both'")
                    ),
                ))

                # Booking class
                cls_key = plb.get("class") or plb.get("classType")
                cls_pass = _class_matches_groups(cabin_groups, cls_key)
                steps.append(MatchStepResult(
                    step="Booking Class",
                    passed=cls_pass,
                    ticket_value=f"{booking_class or '—'} → resolved: {'/'.join(sorted(cabin_groups))}",
                    deal_value=cls_key or "Any",
                    detail=(
                        f"booking_class='{booking_class}' resolved to {cabin_groups} via AirlineClassMaster; "
                        f"PLB requires '{cls_key}'; "
                        + ("match" if cls_pass else f"MISMATCH — change PLB class to '{'/'.join(sorted(cabin_groups))}' or 'All'")
                    ),
                ))

                # Trigger type (airline deals only)
                if deal_type == "airline":
                    tr_val = getattr(deal, "trigger_type", None)
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

                # PLB sub-validity
                vf_plb = plb.get("validFrom")
                vt_plb = plb.get("validTo")
                sv_pass = _plb_dates_match(travel_date, plb)
                if not vf_plb or not vt_plb:
                    sv_detail = "no PLB-level sub-validity constraint — not blocked by this step"
                else:
                    sv_detail = (
                        f"PLB validFrom='{vf_plb}', validTo='{vt_plb}', travel_date={travel_date}; "
                        + ("within PLB sub-range" if sv_pass else "OUTSIDE PLB sub-range — extend PLB validFrom/validTo")
                    )
                steps.append(MatchStepResult(
                    step="PLB Sub-Validity",
                    passed=sv_pass,
                    ticket_value=str(travel_date),
                    deal_value=f"{vf_plb or '—'} → {vt_plb or '—'}",
                    detail=sv_detail,
                ))

                # ── Incentive breakdown (always computed, even if steps failed) ──
                pct_raw = plb.get("incentiveAmtPct")
                target = (plb.get("targetCalcCols") or "Basic").upper().replace(" ", "")
                base = float(sell_fare or 0)
                yq_added = "YQ" in target
                yr_added = "YR" in target
                if yq_added:
                    base += float(sell_tax_yq or 0)
                if yr_added:
                    base += float(sale_yr or 0)
                try:
                    pct = float(pct_raw)
                    incentive_result: float | None = round(base * pct / 100, 2)
                except (TypeError, ValueError):
                    pct = None
                    incentive_result = None

                breakdown = {
                    "targetCalcCols": target,
                    "sell_fare": sell_fare,
                    "sell_tax_yq_added": yq_added,
                    "sell_tax_yq_value": sell_tax_yq,
                    "sale_yr_added": yr_added,
                    "sale_yr_value": sale_yr,
                    "base_total": round(base, 2),
                    "incentiveAmtPct": pct_raw,
                    "formula": f"{round(base, 2)} × {pct_raw}% = {incentive_result}" if pct_raw is not None else "incentiveAmtPct not set in PLB",
                    "result": incentive_result,
                }

                plb_overall = all(s.passed for s in steps)
                plb_diagnostics.append(PLBDiagnostic(
                    plb_key=plb_key,
                    raw_plb=plb,
                    steps=steps,
                    incentive_breakdown=breakdown,
                    plb_overall_match=plb_overall,
                ))

            overall = deal_validity_step.passed and any(p.plb_overall_match for p in plb_diagnostics)
            best_incentive: float | None = None
            for p in plb_diagnostics:
                if p.plb_overall_match and p.incentive_breakdown:
                    v = p.incentive_breakdown.get("result")
                    if v is not None and (best_incentive is None or v > best_incentive):
                        best_incentive = v

            return DealDiagnostic(
                deal_id=deal.id,
                deal_type=deal_type,
                deal_name=deal_name,
                deal_no=deal_no,
                valid_from=vf,
                valid_to=vt,
                trigger_type=getattr(deal, "trigger_type", None),
                deal_validity_step=deal_validity_step,
                plbs=plb_diagnostics,
                overall_match=overall,
                best_incentive=best_incentive,
            )

        # ── Query airline_deals (no date filter) ──────────────────────────
        a_result = await db.execute(
            select(AirlineDeal).where(
                AirlineDeal.tenant_id == tenant_id,
                AirlineDeal.status    == ManualDealStatus.APPROVED,
                func.lower(AirlineDeal.airline_name) == airline_lower,
            ).order_by(AirlineDeal.created_at.desc())
        )
        for deal in a_result.scalars().all():
            results.append(await _diagnose_deal(deal, "airline"))

        # ── Query b2b_deals (no date filter) ─────────────────────────────
        b_result = await db.execute(
            select(B2BDeal).where(
                B2BDeal.tenant_id == tenant_id,
                B2BDeal.status    == ManualDealStatus.APPROVED,
                func.lower(B2BDeal.airline_name) == airline_lower,
            ).order_by(B2BDeal.created_at.desc())
        )
        for deal in b_result.scalars().all():
            results.append(await _diagnose_deal(deal, "b2b"))

        return results

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
