"""Reproduce the PLB accrual spreadsheet end to end, then assert the engine agrees.

WHAT THIS PROVES

Every figure below is transcribed from the source workbook (AMJ-26, rows 5-35).
The script seeds only the INPUTS - airline master rows, deals with their PLB
periods and rates, and BSP settlement rows carrying the monthly flown revenue -
and then asks services/plb_accrual.build_board for the OUTPUT. The deflator is
never seeded: BSP fare components are laid down so the engine derives the sheet's
percentage on its own, which is the part most worth testing.

It also exercises the entity-attribution chain for real. Each (airline, entity)
pair gets its own BSP statement, paired with a summary statement carrying a
distinct agent code, and each deal lists that agent code in `login_ids`. Without
that chain LUFTHANSA's three entities would collapse into one NEEDS_SPLIT pool.

ABOUT THE GRAND TOTAL. The workbook's own total is 8,59,00,397 across every row;
the screenshot shows rows 5-35 only. This script seeds exactly those rows, so the
number to expect is their subtotal, 87,71,087 - not the workbook total.

SAFETY. Everything is owned by a dedicated demo user (PLB_DEMO_EMAIL) inside the
first tenant, so `--reset` can delete it all by created_by_id without touching
real data. It never writes to anything owned by anyone else.

    python -m scripts.seed_plb_demo            # seed, then verify
    python -m scripts.seed_plb_demo --reset    # delete the demo data and stop
    python -m scripts.seed_plb_demo --verify   # verify what is already seeded
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# app.database builds its engine from settings.DEBUG, which echoes every statement.
# This script prints a table; the SQL firehose would bury it.
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

from sqlalchemy import delete, select                                    # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker                    # noqa: E402

from app.database import engine                                          # noqa: E402
from app.models.airline import Airline                                   # noqa: E402
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup  # noqa: E402
from app.models.bsp_summary import BspSummaryStatement                   # noqa: E402
from app.models.deal import (                                            # noqa: E402
    Deal, DealDirection, DealIncentiveConfig, DealKind, DealLifecycleType,
    DealSourceType, DealStatement, DealStatusType,
)
from app.models.plb_accrual import (                                     # noqa: E402
    PlbAccrualInput, PlbAccrualSnapshot, PlbAirlineSetting,
)
from app.models.tenant import Tenant                                     # noqa: E402
from app.models.user import User                                         # noqa: E402
from app.services import plb_accrual as pa                               # noqa: E402

PLB_DEMO_EMAIL = "plb-demo@example.com"

# ── The airline master rows the BSP accounting codes resolve through ─────────
AIRLINES = [
    ("AMERICAN AIRLINES",    "AA",  "001"),
    ("AIR FRANCE",           "AF",  "057"),
    ("KLM ROYAL DUTCH AIRLINES", "KL", "074"),
    ("DELTA AIRLINES",       "DL",  "006"),
    ("AIR CANADA",           "AC",  "014"),
    ("LUFTHANSA",            "LH",  "220"),
    ("SWISS",                "LX",  "724"),
    ("UNITED AIRLINES",      "UA",  "016"),
    ("ITA-ROW",              "AZ",  "055"),
    ("ITA-CONT",             "AZC", "155"),
    ("SAUDI ARABIAN AIRLINES", "SV", "065"),
    ("GULF AIR",             "GF",  "072"),
    ("LOT POLISH AIRLINES",  "LO",  "080"),
    ("QANTASLINK",           "QF",  "081"),
]

# ── The board rows, straight off the sheet ───────────────────────────────────
# (airline, entity, period_from, period_to, basis, deflator%, rate%,
#  [Apr, May, Jun], expected Final PLB, confirmed_through)
D26 = (date(2026, 1, 1), date(2026, 12, 31))     # Jan 26- Dec 26
A25 = (date(2025, 4, 1), date(2026, 3, 31))      # Apr 25- Mar 26
J26 = (date(2026, 1, 1), date(2026, 6, 30))      # Jan 26- Jun 26
D25 = (date(2025, 1, 1), date(2025, 12, 31))     # Jan 25- Dec 25  (expired)
JUL = (date(2025, 7, 1), date(2026, 6, 30))      # July 25 - Jun 26
DEC25 = date(2025, 12, 1)

SHEET = [
    ("AMERICAN AIRLINES", "YFB", *A25, "Basic+YQ",     81.18, 2.0,  [15023897, 17155482,  9693218],  679863, None),
    ("AMERICAN AIRLINES", "YOL", *A25, "Basic+YQ",     81.18, 2.0,  [ 8369689,  7457790, 10253811],  423468, None),
    ("AIR FRANCE",        "YFB", *D26, "Basic+YQ+YR",  86.84, 2.0,  [22688756, 20050877, 14708731],  997806, None),
    ("KLM ROYAL DUTCH AIRLINES", "YFB", *D26, "Basic+YQ+YR", 86.84, 2.0, [56445762, 43416214, 19692609], 2076512, None),
    ("DELTA AIRLINES",    "YFB", *D26, "Basic+YQ+YR",  86.84, 2.0,  [16540876, 23270807, 10732993],  877897, None),
    ("AIR CANADA",        "YFB", *D26, "Basic+YQ",     55.99, 0.8,  [16940852, 14706625, 16049938],  213645, None),
    ("AIR CANADA",        "TSI", *D26, "Basic+YQ",     55.99, 0.8,  [       0,        0,   305610],    1369, None),
    ("AIR CANADA",        "YOL", *D26, "Basic+YQ",     55.99, 0.8,  [ 1301574,   601405,   601650],   11219, None),
    ("LUFTHANSA",         "YOL", *D26, "Basic+YQ",     55.99, 0.8,  [10988356, 15235991, 11344932],  168279, DEC25),
    ("LUFTHANSA",         "YFB", *D26, "Basic+YQ",     55.99, 0.8,  [68718594, 87699306, 63748340],  986161, DEC25),
    ("LUFTHANSA",         "TSI", *D26, "Basic+YQ",     55.99, 0.8,  [       0,        0,        0],       0, DEC25),
    ("SWISS",             "YOL", *D26, "Basic+YQ",     55.99, 0.8,  [ 5030280,  3370922,  3614808],   53822, None),
    ("SWISS",             "YFB", *D26, "Basic+YQ",     55.99, 0.8,  [35883225, 31946182, 15780356],  374502, None),
    ("SWISS",             "TSI", *D26, "Basic+YQ",     55.99, 0.8,  [       0,        0,        0],       0, None),
    ("UNITED AIRLINES",   "YFB", *J26, "Basic+YQ",     22.16, 1.4,  [19526827, 27057287, 25971658],  225077, None),
    ("UNITED AIRLINES",   "YOL", *J26, "Basic+YQ",     22.16, 1.4,  [ 3811048,  3972583,  4473348],   38023, None),
    ("UNITED AIRLINES",   "TSI", *J26, "Basic+YQ",     22.16, 0.0,  [       0,        0,        0],       0, None),
    ("ITA-ROW",           "YFB", *D26, "Basic+YQ+YR",  51.04, 3.4,  [ 4208109,  4054826,  2897283],  193661, None),
    ("ITA-ROW",           "TSI", *D26, "Basic+YQ+YR",  51.04, 3.4,  [ 2823140,  5315916,  3946411],  209717, None),
    ("ITA-ROW",           "YOL", *D26, "Basic+YQ+YR",  51.04, 3.4,  [ 1243516,   210228,   120083],   27310, None),
    ("ITA-CONT",          "YFB", *D26, "Basic+YQ+YR",   1.50, 0.0,  [ 4208109,  4054826,  2897283],       0, None),
    ("ITA-CONT",          "TSI", *D26, "Basic+YQ+YR",   1.50, 0.0,  [ 2823140,  5315916,  3946411],       0, None),
    ("ITA-CONT",          "YOL", *D26, "Basic+YQ+YR",   1.50, 0.0,  [ 1243516,   210228,   120083],       0, None),
    ("SAUDI ARABIAN AIRLINES", "YFB", *D26, "Basic+YQ+YR", 57.91, 2.0, [1756410, 1205964, 2706389],   65657, None),
    ("SAUDI ARABIAN AIRLINES", "YOL", *D26, "Basic+YQ+YR", 57.91, 2.0, [5096386, 3464450, 3105256],  135119, None),
    ("SAUDI ARABIAN AIRLINES", "TSI", *D26, "Basic+YQ+YR", 57.91, 2.0, [      0,       0,       0],       0, None),
    # GULF AIR: real flown revenue, but the sheet leaves BOTH the deflator and the
    # rate blank and shows "-" in the result. Its period also ended Dec-25, so this
    # row is the leakage case twice over — no rate AND no live contract.
    ("GULF AIR",          "YFB", *D25, "Basic+YQ+YR",  60.00, 0.0,  [ -182631,  4721892,  3772412],       0, None),
    ("GULF AIR",          "YOL", *D25, "Basic+YQ+YR",  60.00, 0.0,  [  557760,        0,   152310],       0, None),
    ("LOT POLISH AIRLINES", "YFB", *D26, "Basic",      79.49, 3.0,  [ 6207809,  3150472,  2136890],  274113, DEC25),
    ("QANTASLINK",        "YFB", *JUL, "Basic",       100.00, 3.0,  [ 7682240,  9291183,  3480586],  613620, DEC25),
    ("QANTASLINK",        "YOL", *JUL, "Basic",       100.00, 3.0,  [ 1684695,  1098764,  1358100],  124247, DEC25),
]

MONTHS = [(2026, 4), (2026, 5), (2026, 6)]
SHEET_SUBTOTAL = 8771087     # sum of the Final PLB column over the rows above


def agent_code(airline: str, entity: str) -> str:
    """A stable pseudo-IATA agent code per (airline, entity) — the identifier the
    BSP summary carries and the deal's login_ids echo back."""
    return f"{abs(hash((airline, entity))) % 9000000 + 1000000:07d}"


def split_components(gross: int, deflator_pct: float, basis: str) -> tuple[float, float, float]:
    """Lay fare / YQ / YR down so the engine DERIVES this deflator.

    The commissionable share must come to `deflator_pct` of gross under the deal's
    own base definition, so the split differs per basis: a Basic deal puts it all
    in the fare, a Basic+YQ deal splits it, and the remainder of gross is ordinary
    tax that never counts.
    """
    want = gross * deflator_pct / 100
    if basis == "Basic":
        return round(want, 2), 0.0, 0.0
    if basis == "Basic+YQ":
        return round(want * 0.6, 2), round(want * 0.4, 2), 0.0
    return round(want * 0.55, 2), round(want * 0.35, 2), round(want * 0.10, 2)


async def get_demo_user(db) -> User:
    tenant = (await db.execute(select(Tenant).order_by(Tenant.id))).scalars().first()
    if tenant is None:
        raise SystemExit("No tenant in this database — sign up once, then re-run.")
    user = (await db.execute(
        select(User).where(User.email == PLB_DEMO_EMAIL)
    )).scalar_one_or_none()
    if user is None:
        user = User(
            email=PLB_DEMO_EMAIL,
            hashed_password="!seed-only-no-login",
            full_name="PLB Accrual Demo",
            tenant_id=tenant.id,
            is_active=True,
        )
        db.add(user)
        await db.flush()
    return user


async def wipe(db, user: User) -> None:
    """Remove everything this script owns. Ordered so FKs never block."""
    batches = (await db.execute(
        select(BspStatement.batch_id).where(BspStatement.created_by_id == user.id)
    )).scalars().all()
    if batches:
        row_ids = (await db.execute(
            select(BspStatementRow.id).where(BspStatementRow.statement_id.in_(batches))
        )).scalars().all()
        if row_ids:
            await db.execute(delete(BspTaxBreakup).where(BspTaxBreakup.bsp_row_id.in_(row_ids)))
        await db.execute(delete(BspStatementRow).where(BspStatementRow.statement_id.in_(batches)))
        await db.execute(delete(BspStatement).where(BspStatement.batch_id.in_(batches)))
    await db.execute(delete(BspSummaryStatement).where(BspSummaryStatement.created_by_id == user.id))

    stmt_ids = (await db.execute(
        select(DealStatement.id).where(DealStatement.created_by_id == user.id)
    )).scalars().all()
    if stmt_ids:
        # deals -> deal_incentives cascade at the DB level
        await db.execute(delete(Deal).where(Deal.statement_id.in_(stmt_ids)))
        await db.execute(delete(DealStatement).where(DealStatement.id.in_(stmt_ids)))

    for model in (PlbAccrualInput, PlbAirlineSetting, PlbAccrualSnapshot):
        await db.execute(delete(model).where(model.created_by_id == user.id))
    await db.commit()


async def seed(db, user: User) -> None:
    tid = user.tenant_id

    code_of: dict[str, str] = {}
    for name, iata, numeric in AIRLINES:
        row = (await db.execute(select(Airline).where(Airline.iata_code == iata))).scalar_one_or_none()
        if row is None:
            row = Airline(name=name, iata_code=iata, iata_numeric_code=numeric, is_active=True)
            db.add(row)
        else:
            row.name, row.iata_numeric_code, row.is_active = name, numeric, True
        code_of[name] = numeric
    await db.flush()

    ds = DealStatement(
        tenant_id=tid, source_type=DealSourceType.MANUAL, deal_type=DealKind.AIRLINE,
        direction=DealDirection.INBOUND, batch_id=str(uuid.uuid4()),
        file_name="PLB accrual demo", created_by_id=user.id,
    )
    db.add(ds)
    await db.flush()

    for (airline, entity, pfrom, pto, basis, deflator, rate, flown, _expected, confirmed) in SHEET:
        code = agent_code(airline, entity)
        deal = Deal(
            statement_id=ds.id, tenant_id=tid, deal_type=DealKind.AIRLINE,
            direction=DealDirection.INBOUND, source_agent="seed",
            airline_type="GDS", airline_name=airline,
            valid_from=pfrom, valid_to=pto, entity=entity,
            contract_year="Calendar Year",
            trigger_type="Flown", payout_type="Flown",
            login_ids=[code], login_id=code,
            status=DealStatusType.APPROVED,
            deal_lifecycle_status=DealLifecycleType.ACTIVE,
            created_by_id=user.id,
        )
        db.add(deal)
        await db.flush()
        db.add(DealIncentiveConfig(
            deal_id=deal.id, incentive_type="PLB", incentive_order=0,
            contract_valid_from=pfrom, contract_valid_to=pto,
            frequency="Quarterly", flight_type="Both", class_="Economy",
            target_based="Fixed", target_calc_cols=basis, payout_calc_cols=basis,
            incentive_num_pct="Percentage", incentive_amt_pct=rate,
        ))

        if confirmed:
            existing = (await db.execute(select(PlbAirlineSetting).filter_by(
                tenant_id=tid, created_by_id=user.id,
                airline_key=pa.norm_key(airline), entity_key=pa.norm_key(entity),
                channel_key=pa.norm_key("GDS"),
            ))).scalar_one_or_none()
            if existing is None:
                db.add(PlbAirlineSetting(
                    tenant_id=tid, created_by_id=user.id,
                    airline_key=pa.norm_key(airline), entity_key=pa.norm_key(entity),
                    channel_key=pa.norm_key("GDS"),
                    flown_confirmed_through=confirmed, updated_by_id=user.id,
                ))

        # One BSP statement per (airline, entity), paired with a summary that
        # carries the agent code — the chain the engine walks to find the entity.
        if not any(flown):
            continue
        batch = str(uuid.uuid4())
        group = str(uuid.uuid4())
        db.add(BspStatement(
            batch_id=batch, tenant_id=tid, created_by_id=user.id,
            statement_name=f"{airline} / {entity}", airline_name=airline,
            airline_code=code_of[airline],
            period_from=date(2026, 4, 1), period_to=date(2026, 6, 30),
            status="completed", group_id=group, row_count=len(MONTHS),
        ))
        db.add(BspSummaryStatement(
            batch_id=str(uuid.uuid4()), tenant_id=tid, created_by_id=user.id,
            group_id=group, agent_code=code, agent_name=f"{entity} demo",
            period_from=date(2026, 4, 1), period_to=date(2026, 6, 30),
            status="completed",
        ))

        for (y, m), gross in zip(MONTHS, flown):
            if not gross:
                continue
            fare, yq, yr = split_components(abs(gross), deflator, basis)
            sign = 1 if gross > 0 else -1
            row = BspStatementRow(
                statement_id=batch, tenant_id=tid, created_by_id=user.id,
                ticket_number=f"{code_of[airline]}{y}{m:02d}{entity}",
                document_number=f"{code_of[airline]}{y}{m:02d}",
                airline_code=code_of[airline],
                airline_accounting_code=code_of[airline],
                airline_name=airline,
                # A negative month is a net refund, so it is booked as one — the
                # engine's own sign rule then reproduces it rather than being told.
                transaction_type="TKTT" if sign > 0 else "RFND",
                issue_date=date(y, m, 1),
                enriched_travel_date=date(y, m, 1),
                enrichment_source="tgq_hmpr",
                stat="I",
                transaction_amount=abs(gross),
                fare_amount=fare,
                commission_status="pending",
            )
            db.add(row)
            await db.flush()
            for comp, amt in (("YQ", yq), ("YR", yr)):
                if amt:
                    db.add(BspTaxBreakup(
                        bsp_row_id=row.id, tenant_id=tid,
                        component_type="TAX", component_code=comp, amount=amt,
                    ))
    await db.commit()


def inr(v: float) -> str:
    """Indian digit grouping, so the output can be diffed against the sheet."""
    neg, n = v < 0, f"{abs(round(v)):.0f}"
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        n = ",".join(parts) + "," + tail
    return ("-" if neg else "") + n


async def verify(db, user: User) -> int:
    period = pa.resolve_period("AMJ-26")
    board = await pa.build_board(db, user.tenant_id, user.id, period, "auto")
    by_key = {(pa.norm_key(r.airline_name), pa.norm_key(r.entity)): r for r in board["rows"]}

    print(f"\n  {period.label}   {len(board['rows'])} rows\n")
    print(f"  {'Airline':<26} {'Ent':<4} {'Deflator':>9} {'Rate':>6} "
          f"{'Computed':>12} {'Sheet':>12}  {'Check':>7}  Status")
    print("  " + "-" * 104)

    failures: list[str] = []
    total = 0.0
    for (airline, entity, _pf, _pt, basis, deflator, rate, _flown, expected, _c) in SHEET:
        r = by_key.get((pa.norm_key(airline), pa.norm_key(entity)))
        if r is None:
            failures.append(f"{airline} / {entity}: no board row produced")
            continue
        delta = r.accrual - expected
        total += r.accrual
        ok = abs(delta) <= max(2.0, expected * 0.0005)
        if not ok:
            failures.append(
                f"{airline} / {entity}: computed {r.accrual:,.2f} vs sheet {expected:,}"
            )
        # The deflator is DERIVED, never seeded — this is the assertion that matters.
        if abs(sum(_flown)) > 0 and abs(r.deflator_pct - deflator) > 0.02:
            failures.append(
                f"{airline} / {entity}: derived deflator {r.deflator_pct}% vs sheet {deflator}%"
            )
        print(f"  {airline[:26]:<26} {entity:<4} {r.deflator_pct:>8.2f}% {r.plb_rate_pct:>5.2f}% "
              f"{inr(r.accrual):>12} {inr(expected):>12}  {'ok' if ok else 'FAIL':>7}  {r.status}")

    print("  " + "-" * 104)
    print(f"  {'TOTAL':<31} {'':>9} {'':>6} {inr(total):>12} {inr(SHEET_SUBTOTAL):>12}")

    checks = [
        ("grand total matches the sheet subtotal",
         abs(total - SHEET_SUBTOTAL) <= 200,
         f"{inr(total)} vs {inr(SHEET_SUBTOTAL)}"),
        ("GULF AIR flags EXPIRED_WITH_FLOWN despite real flown revenue",
         all("EXPIRED_WITH_FLOWN" in by_key[(pa.norm_key("GULF AIR"), pa.norm_key(e))].status_flags
             for e in ("YFB", "YOL")),
         str([by_key[(pa.norm_key("GULF AIR"), pa.norm_key(e))].status_flags for e in ("YFB", "YOL")])),
        ("GULF AIR accrues nothing",
         all(by_key[(pa.norm_key("GULF AIR"), pa.norm_key(e))].accrual == 0 for e in ("YFB", "YOL")),
         ""),
        ("ITA-CONT flags NO_RATE on live volume",
         all("NO_RATE" in by_key[(pa.norm_key("ITA-CONT"), pa.norm_key(e))].status_flags
             for e in ("YFB", "TSI", "YOL")),
         ""),
        ("UNITED expires this quarter",
         all("EXPIRING" in by_key[(pa.norm_key("UNITED AIRLINES"), pa.norm_key(e))].status_flags
             for e in ("YFB", "YOL")),
         ""),
        ("LUFTHANSA months after Dec-25 are UNCONFIRMED",
         "UNCONFIRMED" in by_key[(pa.norm_key("LUFTHANSA"), pa.norm_key("YFB"))].status_flags,
         ""),
        ("entity attribution worked - no NEEDS_SPLIT rows",
         not any("NEEDS_SPLIT" in r.status_flags for r in board["rows"]),
         str(sorted({r.airline_name for r in board["rows"] if "NEEDS_SPLIT" in r.status_flags}))),
        ("negative April for GULF AIR survives as a refund",
         by_key[(pa.norm_key("GULF AIR"), pa.norm_key("YFB"))].months["2026-04"].flown < 0,
         str(by_key[(pa.norm_key("GULF AIR"), pa.norm_key("YFB"))].months["2026-04"].flown)),
    ]
    print()
    for label, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}" + (f"   {detail}" if not passed and detail else ""))
        if not passed:
            failures.append(label)

    print()
    if failures:
        print(f"  {len(failures)} FAILURE(S):")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  All checks passed - the engine reproduces the spreadsheet.")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete the demo data and exit")
    ap.add_argument("--verify", action="store_true", help="verify without re-seeding")
    args = ap.parse_args()

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        user = await get_demo_user(db)
        await db.commit()
        if args.reset:
            await wipe(db, user)
            print("Demo data removed.")
            return 0
        if not args.verify:
            await wipe(db, user)
            await seed(db, user)
            print(f"Seeded {len(SHEET)} deal lines for {PLB_DEMO_EMAIL}.")
        return await verify(db, user)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
