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

statement_type restricts which deal_type is searched:
  "B2B"     → only deals with deal_type="b2b"; supplier enforced
  "AIRLINE" → only deals with deal_type="airline"
  None      → both

Incentive is computed from DealIncentiveConfig:
  Fixed/Percentage → base × incentive_amt_pct / 100
  Fixed/Number     → flat incentive_amt_pct amount
  Slab             → find right band in DealIncentiveSlab, read from DealIncentiveSlabValue
"""
from __future__ import annotations

from datetime import date
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from app.models.airline_class_master import AirlineClassMaster
from app.models.deal import (
    Deal as UnifiedDeal,
    DealIncentiveConfig,
    DealIncentiveSlab,
    DealRule,
    DealStatusType,
    DealLifecycleType,
    build_rule_dict,
)

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


# ── Main service ───────────────────────────────────────────────────────────

class DealMatchingService:

    @staticmethod
    async def find_all_deals(
        db:              AsyncSession,
        airline_name:    str,
        travel_date:     date,
        tenant_id:       int,
        created_by_id:   int,
        segment_type:    str | None = None,
        booking_class:   str | None = None,
        invoice_type:    str | None = None,
        sell_fare:       float | None = None,
        sell_tax_yq:     float | None = None,
        sale_yr:         float | None = None,
        supplier_agency: str | None = None,
        statement_type:  str | None = None,
    ) -> list[DealMatchResult]:
        """
        Search the unified deals table, return ALL matching deals sorted by
        calculated_incentive descending (highest first).

        statement_type restricts which deal_type is searched:
          "B2B"     → only deals with deal_type="b2b"; supplier match enforced.
          "AIRLINE" → only deals with deal_type="airline".
          None/other → both deal types.
        """
        airline_lower = airline_name.lower()
        is_b2b     = (statement_type or "").upper() == "B2B"
        is_airline = (statement_type or "").upper() == "AIRLINE"
        cabin_groups = await _resolve_cabin_groups(db, airline_name, booking_class)
        matches: list[DealMatchResult] = []

        # ── Unified deals table (single source of truth) ───────────────────
        where_clauses = [
            UnifiedDeal.tenant_id             == tenant_id,
            UnifiedDeal.created_by_id         == created_by_id,
            UnifiedDeal.status                == DealStatusType.APPROVED,
            UnifiedDeal.deal_lifecycle_status == DealLifecycleType.ACTIVE,
            func.lower(UnifiedDeal.airline_name) == airline_lower,
            UnifiedDeal.valid_from.is_not(None),
            UnifiedDeal.valid_to.is_not(None),
            UnifiedDeal.valid_from <= travel_date,
            UnifiedDeal.valid_to   >= travel_date,
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
                if not _class_matches_groups(cabin_groups, config.class_):
                    continue
                vf = config.contract_valid_from
                vt = config.contract_valid_to
                if vf and vt and not (vf <= travel_date <= vt):
                    continue
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
                    deal_no=f"{'B2B' if deal_type_str == 'b2b' else 'AIR'}-{deal.id:04d}",
                    calculated_incentive=total_inc,
                    incentive_breakdown=breakdown,
                    is_unified=True,
                    valid_from=deal.valid_from,
                    valid_to=deal.valid_to,
                    deal_maker_name=deal.deal_maker_name,
                ))

        matches.sort(key=lambda m: m.calculated_incentive or 0, reverse=True)
        return matches

    @staticmethod
    async def diagnose_match(
        db:                  AsyncSession,
        airline_name:        str,
        travel_date:         date,
        tenant_id:           int,
        created_by_id:       int,
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
    ) -> list:
        """
        Return a full step-by-step diagnostic for every approved deal belonging to this
        airline+tenant.
        statement_type restricts which deal tables are shown in diagnosis:
          "B2B"     → only b2b_deals; supplier match enforced.
          "AIRLINE" → only airline_deals.
        Never short-circuits — every PLB step is evaluated.
        """
        from app.schemas.uploaded_ticket import (
            MatchStepResult, PLBDiagnostic, DealDiagnostic,
        )

        airline_lower = airline_name.lower()
        cabin_groups, _ = await _resolve_cabin_groups_with_detail(db, airline_name, booking_class)
        results: list[DealDiagnostic] = []

        async def _diagnose_unified_deal(deal: UnifiedDeal) -> DealDiagnostic:
            from app.services.exclusion_evaluator import (
                diagnose_exclusion_for_payout, diagnose_inclusion_for_payout,
            )

            deal_type_str = deal.deal_type.value  # "airline" | "b2b"
            prefix = {"airline": "AIR", "b2b": "B2B"}.get(deal_type_str, "DEAL")
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
                val_detail = "deal has no valid_from/valid_to set — cannot match any ticket"

            deal_validity_step = MatchStepResult(
                step="Deal Validity",
                passed=val_pass,
                ticket_value=str(travel_date),
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
                cls_pass = _class_matches_groups(cabin_groups, cls_key)
                steps.append(MatchStepResult(
                    step="Booking Class",
                    passed=cls_pass,
                    ticket_value=f"{booking_class or '—'} → {'/'.join(sorted(cabin_groups))}",
                    deal_value=cls_key or "Any",
                    detail=(
                        f"booking_class='{booking_class}' resolved to {cabin_groups}; "
                        f"config class='{cls_key}'; "
                        + ("match" if cls_pass else f"MISMATCH — change config class to '{'/'.join(sorted(cabin_groups))}' or 'All'")
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

                # Supplier (B2B only)
                if deal_type_str == "b2b" and supplier_agency and deal.supplier_name:
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

                # Config sub-validity
                vf_cfg = config.contract_valid_from
                vt_cfg = config.contract_valid_to
                if vf_cfg and vt_cfg:
                    sv_pass = vf_cfg <= travel_date <= vt_cfg
                    sv_detail = (
                        f"config validFrom='{vf_cfg}', validTo='{vt_cfg}', travel_date={travel_date}; "
                        + ("within range" if sv_pass else "OUTSIDE range — extend config validFrom/validTo")
                    )
                else:
                    sv_pass = True
                    sv_detail = "no sub-validity constraint"
                steps.append(MatchStepResult(
                    step="Config Sub-Validity",
                    passed=sv_pass,
                    ticket_value=str(travel_date),
                    deal_value=f"{vf_cfg or '—'} → {vt_cfg or '—'}",
                    detail=sv_detail,
                ))

                # Incentive computation
                inc = _compute_incentive_from_config(
                    config, sell_fare, sell_tax_yq, sale_yr, segment_type, cabin_groups,
                )
                base = _calc_base(sell_fare, sell_tax_yq, sale_yr, config.target_calc_cols)
                target_calc = config.target_calc_cols or "Basic"
                target_upper = target_calc.upper().replace(" ", "")
                yq_added = "YQ" in target_upper
                yr_added = "YR" in target_upper

                # Build human-readable formula
                target_based_low = (config.target_based or "Fixed").lower()
                num_pct_low = (config.incentive_num_pct or "Percentage").lower()
                if target_based_low == "slab":
                    formula_str = f"slab(base={round(base, 2)}) = {inc}"
                elif "percent" in num_pct_low:
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
        _is_b2b     = (statement_type or "").upper() == "B2B"
        _is_airline = (statement_type or "").upper() == "AIRLINE"

        diag_where = [
            UnifiedDeal.tenant_id == tenant_id,
            UnifiedDeal.created_by_id == created_by_id,
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
            # Skip wrong supplier for B2B
            if deal_type_str == "b2b" and supplier_agency and deal.supplier_name:
                if deal.supplier_name.lower() != supplier_agency.lower():
                    continue
            results.append(await _diagnose_unified_deal(deal))

        return results

    @staticmethod
    async def find_best_deal(
        db:              AsyncSession,
        airline_name:    str,
        travel_date:     date,
        tenant_id:       int,
        created_by_id:   int,
        segment_type:    str | None = None,
        booking_class:   str | None = None,
        invoice_type:    str | None = None,
        sell_fare:       float | None = None,
        sell_tax_yq:     float | None = None,
        sale_yr:         float | None = None,
        supplier_agency: str | None = None,
        statement_type:  str | None = None,
    ) -> DealMatchResult | None:
        """Return the single best (highest incentive) matching deal."""
        matches = await DealMatchingService.find_all_deals(
            db=db, airline_name=airline_name, travel_date=travel_date,
            tenant_id=tenant_id, created_by_id=created_by_id, segment_type=segment_type,
            booking_class=booking_class, invoice_type=invoice_type,
            sell_fare=sell_fare, sell_tax_yq=sell_tax_yq, sale_yr=sale_yr,
            supplier_agency=supplier_agency,
            statement_type=statement_type,
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


