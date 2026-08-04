"""
Celery tasks for async BSP statement parsing.

A BSP settlement PDF (1000-2000 pages, ~50k transactions) is far too large to
parse inside an HTTP request, so `POST /bsp/upload` stores the PDF to GCS, creates
a `BspStatement(status='pending')`, and enqueues `parse_bsp_statement`. This worker
streams the PDF page-by-page (constant memory), bulk-inserts rows + tax breakups in
chunks, and advances the progress counters the frontend polls.

Notes:
  * Uses a per-task NullPool async engine — the FastAPI engine's asyncpg pool is not
    safe to reuse across the fresh event loop `asyncio.run` builds each task, nor
    across a prefork.
  * Idempotent: every run re-claims the statement and deletes its existing rows
    first, so a retry can never duplicate data.
  * Run a worker with:  celery -A app.workers.celery_app.celery_app worker -l info -Q bsp
    (add --pool=solo on Windows dev).
"""
import asyncio
import logging
from datetime import datetime
from decimal import Decimal

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

CHUNK_ROWS = 800           # bulk-insert parents in batches of this size
PAGE_FLUSH_INTERVAL = 100  # ...or at least every N pages, to keep progress moving

# The grand-total lines reconciled between a BSP summary and its detailed statement.
GT_LINES = (
    "issues", "refunds", "debit_memos", "credit_memos",
    "std_comm", "sup_comm", "tax_on_comm", "balance_payable",
)
GT_TOLERANCE = Decimal("1")   # ±₹1 per line

# Section-banner keyword → the grand-total line it feeds. First match wins (the keywords
# are disjoint in practice). Mirrors the SQL bucketing in
# ``api/v1/bsp.py::bsp_detailed_summary``, which aggregates the same rows live.
_SECTION_BUCKETS = (
    ("ISSUE",  "issues"),
    ("REFUND", "refunds"),
    ("DEBIT",  "debit_memos"),
    ("CREDIT", "credit_memos"),
)


def _section_bucket(raw_data) -> str | None:
    """Which grand-total line a row's section banner falls under, else None.

    ``settlement_section`` wins over the printed ``section`` when present: a CANX row is
    *listed* under ISSUES but its cancellation charge is *settled* as a debit memo, so once
    the charge is distributed onto it (see ``_distribute_spdr_canx``) it must total with the
    parent SPDR's section or the per-bucket reconciliation breaks."""
    raw = raw_data or {}
    sec = (raw.get("settlement_section") or raw.get("section") or "").upper()
    return next((line for kw, line in _SECTION_BUCKETS if kw in sec), None)


def _new_gt() -> dict:
    return {k: Decimal("0") for k in GT_LINES} | {"doc_count": 0}


def _accumulate_gt(gt: dict, transactions) -> None:
    """Fold a page's transactions into the running detailed grand totals. Issues /
    refunds / memos are the per-section transaction-amount totals; commissions and
    balance are plain column sums (matches the statement's printed COMBINED TOTALS)."""
    for t in transactions:
        line = _section_bucket(t.raw_data)
        if line:
            gt[line] += t.transaction_amount or Decimal("0")
        gt["std_comm"] += t.standard_commission_amount or Decimal("0")
        gt["sup_comm"] += t.supplier_discount_amount or Decimal("0")
        gt["tax_on_comm"] += t.tax_on_commission or Decimal("0")
        gt["balance_payable"] += t.balance_payable or Decimal("0")
        gt["doc_count"] += 1


@celery_app.task(bind=True, max_retries=3, acks_late=True, queue="bsp")
def parse_bsp_statement(self, batch_id: str, tenant_id: int, user_id: int):
    try:
        asyncio.run(_parse_bsp_statement(batch_id, tenant_id, user_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("BSP parse failed for batch %s", batch_id)
        try:
            asyncio.run(_mark_failed(batch_id, tenant_id, str(exc)))
        except Exception:  # noqa: BLE001
            logger.exception("could not mark BSP statement %s failed", batch_id)
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 600))


# ── helpers ─────────────────────────────────────────────────────────────────
def _new_engine():
    """Fresh NullPool async engine, safe inside this task's own event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


def _bsp_bucket() -> str:
    from app.config import settings
    return settings.GCS_BSP_BUCKET_NAME or settings.GCS_TICKETS_BUCKET_NAME


def _parse_date(value):
    if not value:
        return None
    from datetime import date
    s = str(value).strip()
    try:
        return date.fromisoformat(s)   # PDF parser already normalises to ISO
    except ValueError:
        pass
    try:
        from dateutil import parser as dateparser
        return dateparser.parse(s, dayfirst=True).date()
    except Exception:  # noqa: BLE001
        return None


async def _load_airline_map(db) -> dict:
    """{3-digit code → airline name} from the global airline master, keyed by the IATA
    numeric code (falling back to icao_code, which historically held the numeric code)."""
    from sqlalchemy import select
    from app.models.airline import Airline
    # Wrap the read in its own transaction so it doesn't leave an autobegun transaction
    # open on the session — the streaming loop's _flush_chunk uses `async with db.begin()`.
    async with db.begin():
        rows = (await db.execute(
            select(Airline.iata_numeric_code, Airline.icao_code, Airline.name)
        )).all()
    out: dict[str, str] = {}
    for numeric, icao, name in rows:
        code = (numeric or icao or "").strip()
        if not code or not name:
            continue
        key = code.zfill(3) if code.isdigit() else code
        out.setdefault(key, name)
    return out


CANX_UNIT = {"I": Decimal("300"), "D": Decimal("100")}   # flat charge per cancellation


def _stat_norm(stat) -> str | None:
    """'I' / 'D' from the STAT column, or None when it is blank or unrecognised. Never
    guesses — an unknown STAT means we cannot know the per-cancellation unit."""
    s = (stat or "").strip().upper()
    return "I" if s.startswith("I") else "D" if s.startswith("D") else None


async def _distribute_spdr_canx(db, batch_id: str) -> None:
    """Push an SPDR's bulk cancellation charge down onto the CANX rows it covers.

    BSP prints the charge ONCE on a bulk ``SPDR`` row while the individual ``CANX`` rows it
    covers print ₹0. A cancellation costs a flat ₹300 (International) / ₹100 (Domestic), so
    ``spdr_amount ÷ unit`` = how many CANX rows the charge covers — matched within the same
    ``(airline, I/D)`` group, oldest CANX first.

    The distribution is ALL-OR-NOTHING and SUM-PRESERVING, which is the whole point:

      * Split only when the amount is an EXACT multiple of the unit AND the group holds at
        least that many zero-amount CANX rows. Each covered CANX row then takes one unit and
        is stamped with the parent's ``spdr_no`` / ``document_number``, **and the SPDR's own
        ``transaction_amount`` is zeroed**.
      * Otherwise write nothing at all — the charge stays whole on the SPDR and the CANX rows
        stay at ₹0 with their own document numbers.

    Either way ``SUM(transaction_amount)`` over the statement is unchanged. Filling the CANX
    rows *without* zeroing the SPDR — or filling only some of them — double-counts the
    charge, which is what made the two Summary tabs differ.

    The pairing is inherently CROSS-SECTION: the charge is billed under ``DEBIT MEMOS`` (the
    SPDR) while the CANX documents are listed under ``ISSUES`` — and a CANX can even sit in a
    different category (WEBSALES-EDIS) from its SPDR (BSP). Moving the amount would therefore
    shift it between summary groups, so each filled CANX also gets
    ``raw_data['settlement_section']`` / ``['settlement_category']`` set to the parent SPDR's.
    ``_section_bucket`` and ``api/v1/bsp.py::bsp_detailed_summary`` both honour those, keeping
    the charge counted in the group the uploaded summary reports it under.

    Idempotent: on a re-run a split SPDR sits at ₹0 (nothing to allocate) and its CANX rows
    are non-zero (never re-queued), so the pass is a no-op.
    """
    from collections import defaultdict, deque
    from sqlalchemy import func, literal, select, update
    from sqlalchemy.dialects.postgresql import JSONB
    from app.models.bsp_statement import BspStatementRow

    def _merge_raw(patch: dict):
        """``raw_data || patch`` in SQL, so one UPDATE can patch many rows without having to
        read and rewrite each row's JSON individually.

        Bind the dict through ``literal(..., JSONB)`` — the JSONB type serialises it exactly
        once. Passing a pre-dumped string instead would be encoded a second time, yielding a
        JSON *string* rather than an object, and ``object || string`` concatenates into an
        ARRAY in Postgres, which silently destroys raw_data."""
        return func.coalesce(BspStatementRow.raw_data, literal({}, JSONB)).op("||")(
            literal(patch, JSONB)
        )

    filled = 0
    split_docs: list = []
    kept: list = []                            # [(spdr_doc, amount, reason), ...]

    async with db.begin():
        rows = (await db.execute(
            select(
                BspStatementRow.id, BspStatementRow.airline_accounting_code,
                BspStatementRow.stat, BspStatementRow.transaction_type,
                BspStatementRow.transaction_amount, BspStatementRow.document_number,
                BspStatementRow.raw_data,
            ).where(
                BspStatementRow.statement_id == batch_id,
                BspStatementRow.transaction_type.in_(("SPDR", "CANX")),
            ).order_by(BspStatementRow.id)
        )).all()

        spdrs: list = []                       # ordered [(id, key, doc, amount, raw_data), ...]
        canx_zero: dict = defaultdict(deque)   # key -> FIFO queue of zero-amount CANX ids
        for rid, air, stat, ttype, amt, doc, raw in rows:
            stat_norm = _stat_norm(stat)
            key = (air, stat_norm)
            if ttype == "SPDR":
                spdrs.append((rid, key, doc, Decimal(str(amt or 0)), raw))
            elif ttype == "CANX" and not amt and stat_norm:   # amount 0 or NULL
                canx_zero[key].append(rid)

        for rid, key, spdr_doc, total, raw in spdrs:
            _air, stat_norm = key
            if not total:
                continue                       # ₹0 SPDR — nothing to distribute (or already split)
            unit_base = CANX_UNIT.get(stat_norm)
            if unit_base is None:
                kept.append((spdr_doc, total, "unknown STAT"))
                continue
            count, remainder = divmod(abs(total), unit_base)
            count = int(count)
            q = canx_zero[key]
            if remainder:
                kept.append((spdr_doc, total, f"not a multiple of {unit_base}"))
                continue
            if len(q) < count:
                kept.append((spdr_doc, total, f"needs {count} CANX rows, {len(q)} available"))
                continue

            # Committed to the split — only now do we consume CANX rows from the queue.
            unit = unit_base.copy_sign(total)   # a negative SPDR distributes negative units
            canx_ids = [q.popleft() for _ in range(count)]
            # For a covered CANX the real document number IS the parent SPDR's (so
            # document_number == spdr_no); ticket_number keeps the printed cancelled-ticket
            # value already set at flush (do NOT re-derive it here — that would overwrite it).
            # settlement_section / settlement_category keep the charge totalling under the
            # parent's summary group — the derived summary groups by both.
            await db.execute(
                update(BspStatementRow).where(BspStatementRow.id.in_(canx_ids))
                .values(
                    transaction_amount=unit, spdr_no=spdr_doc, document_number=spdr_doc,
                    raw_data=_merge_raw({
                        "settlement_section":  (raw or {}).get("section"),
                        "settlement_category": (raw or {}).get("category"),
                    }),
                )
            )
            # The charge now lives on the CANX rows — zero it here so it is not counted twice.
            # The breadcrumb explains the ₹0 in the detailed grid / XLSX export, and lets the
            # backfill script put the amount back if the distribution is ever reverted.
            await db.execute(
                update(BspStatementRow).where(BspStatementRow.id == rid)
                .values(
                    transaction_amount=Decimal("0"),
                    raw_data=_merge_raw({"spdr_split": {
                        "amount": str(total), "unit": str(unit), "count": count,
                    }}),
                )
            )
            filled += count
            split_docs.append(spdr_doc)

    if split_docs:
        logger.info("BSP %s SPDR→CANX: split %d SPDR rows across %d CANX rows",
                    batch_id, len(split_docs), filled)
    for spdr_doc, total, reason in kept:
        logger.warning("BSP %s SPDR→CANX: kept %s whole on SPDR %s (%s)",
                       batch_id, total, spdr_doc, reason)


async def _mark_failed(batch_id: str, tenant_id: int, message: str):
    from sqlalchemy import update
    from app.models.bsp_statement import BspStatement

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                await db.execute(
                    update(BspStatement)
                    .where(BspStatement.batch_id == batch_id, BspStatement.tenant_id == tenant_id)
                    .values(status="failed", error=(message or "")[:2000])
                )
    finally:
        await engine.dispose()


async def _flush_chunk(db, txns, errs, batch_id, tenant_id, user_id, processed_pages, processed_rows, airline_by_code=None):
    """Atomically insert a chunk of rows + their tax children + any parse errors,
    and advance the progress counters — all in ONE transaction so the frontend can
    never see progress ahead of durable rows."""
    from sqlalchemy import insert, update
    from app.models.bsp_statement import (
        BspStatement, BspStatementRow, BspTaxBreakup, BspParseError,
    )
    from app.services.bsp_pdf_parser import derive_ticket_number
    airline_by_code = airline_by_code or {}

    async with db.begin():
        orm_rows = []
        for t in txns:
            orm_rows.append(BspStatementRow(
                statement_id=batch_id, tenant_id=tenant_id, created_by_id=user_id,
                # Ticket number is derived per transaction type (memos/EMDs/40x-refunds
                # carry none). Reconciliation matches on `document_number or ticket_number`
                # (document first), so blanking ticket_number never drops a match.
                ticket_number=derive_ticket_number(t.transaction_type, t.document_number),
                document_number=t.document_number,
                airline_accounting_code=t.airline_accounting_code,
                airline_code=t.airline_code,
                airline_name=airline_by_code.get(t.airline_accounting_code),
                transaction_type=t.transaction_type,
                issue_date=_parse_date(t.issue_date),
                cpui=t.cpui, nr_code=t.nr_code, stat=t.stat,
                form_of_payment=t.form_of_payment,
                transaction_amount=t.transaction_amount, fare_amount=t.fare_amount,
                penalty_amount=t.penalty_amount, net_sales=t.net_sales,
                standard_commission_rate=t.standard_commission_rate,
                standard_commission_amount=t.standard_commission_amount,
                supplier_discount_rate=t.supplier_discount_rate,
                supplier_discount_amount=t.supplier_discount_amount,
                tax_on_commission=t.tax_on_commission,
                balance_payable=t.balance_payable,
                tour=(t.tour or None),
                alt_document_numbers=(t.alt_document_numbers or None),
                rtdn=t.rtdn, esac=t.esac, wavr=t.wavr,
                associated_docs=(t.associated_docs or None),
                match_status="unmatched",
                raw_data=t.raw_data or None,
            ))
        if orm_rows:
            db.add_all(orm_rows)
            await db.flush()   # RETURNING id -> orm_rows[i].id populated (ORM-guaranteed mapping)

            child_dicts = [
                {"bsp_row_id": row.id, "tenant_id": tenant_id,
                 "component_type": c.component_type, "component_code": c.component_code,
                 "amount": c.amount}
                for row, t in zip(orm_rows, txns) for c in t.tax_components
            ]
            if child_dicts:
                await db.execute(insert(BspTaxBreakup), child_dicts)

        if errs:
            await db.execute(insert(BspParseError), errs)

        await db.execute(
            update(BspStatement)
            .where(BspStatement.batch_id == batch_id)
            .values(processed_pages=processed_pages, processed_rows=processed_rows,
                    total_rows=processed_rows)
        )


async def _parse_bsp_statement(batch_id: str, tenant_id: int, user_id: int):
    from sqlalchemy import select, delete
    from app.models.bsp_statement import BspStatement, BspStatementRow, BspParseError
    from app.services import file_store
    from app.services.bsp_pdf_parser import iter_page_results, has_text_layer

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            # ── Claim + idempotent reset (one tx) ───────────────────────────
            async with db.begin():
                stmt = (await db.execute(
                    select(BspStatement).where(
                        BspStatement.batch_id == batch_id,
                        BspStatement.tenant_id == tenant_id,
                    ).with_for_update()
                )).scalar_one_or_none()
                if stmt is None:
                    logger.warning("BSP statement %s not found (tenant %s)", batch_id, tenant_id)
                    return
                if stmt.status == "completed":
                    logger.info("BSP statement %s already completed — skipping", batch_id)
                    return
                file_url = stmt.file_url
                group_id = stmt.group_id
                stmt.status = "processing"
                stmt.error = None
                stmt.total_pages = 0
                stmt.processed_pages = 0
                stmt.total_rows = 0
                stmt.processed_rows = 0
                await db.execute(delete(BspStatementRow).where(BspStatementRow.statement_id == batch_id))
                await db.execute(delete(BspParseError).where(BspParseError.statement_id == batch_id))

            if not file_url:
                await _fail(db, batch_id, "No file attached to this statement.")
                return

            # ── Download the PDF from GCS ───────────────────────────────────
            pdf_bytes = await file_store.load(file_url, _bsp_bucket())

            # ── Guard: scanned/image PDFs have no text layer ────────────────
            if not has_text_layer(pdf_bytes):
                await _fail(db, batch_id,
                            "PDF has no extractable text (looks scanned/image-only). OCR is not supported.")
                return

            # ── Header (agent/period) straight from the PDF — never asked at upload ─
            header = _extract_header(pdf_bytes)

            # Airline master map (3-digit code → name), loaded once for row enrichment.
            airline_by_code = await _load_airline_map(db)

            # ── Stream pages, buffer, chunk-commit; accumulate grand totals ──
            buf = []                 # list[ParsedTransaction]
            errs = []                # list[dict] for BspParseError
            gt = _new_gt()           # running detailed grand totals (for reconciliation)
            processed_rows = 0
            total_pages = 0
            last_flushed_page = 0
            now = datetime.utcnow()

            for outcome in iter_page_results(pdf_bytes):
                total_pages = outcome.total_pages
                _accumulate_gt(gt, outcome.result.transactions)
                buf.extend(outcome.result.transactions)
                for e in outcome.result.errors:
                    errs.append({
                        "statement_id": batch_id, "page_number": outcome.page_number,
                        "error": (e or "")[:4000], "raw_snippet": None, "created_at": now,
                    })

                pages_since_flush = outcome.page_number - last_flushed_page
                if len(buf) >= CHUNK_ROWS or (pages_since_flush >= PAGE_FLUSH_INTERVAL and (buf or errs)):
                    processed_rows += len(buf)
                    await _flush_chunk(db, buf, errs, batch_id, tenant_id, user_id,
                                       processed_pages=outcome.page_number, processed_rows=processed_rows,
                                       airline_by_code=airline_by_code)
                    buf, errs = [], []
                    last_flushed_page = outcome.page_number

            # final flush of the remainder
            if buf or errs or last_flushed_page < total_pages:
                processed_rows += len(buf)
                await _flush_chunk(db, buf, errs, batch_id, tenant_id, user_id,
                                   processed_pages=total_pages, processed_rows=processed_rows,
                                   airline_by_code=airline_by_code)

            # ── Mark completed (with printed grand totals + PDF-derived period) ─
            from sqlalchemy import update
            vals = dict(
                status="completed", total_pages=total_pages, processed_pages=total_pages,
                total_rows=processed_rows, processed_rows=processed_rows, row_count=processed_rows,
                gt_issues=gt["issues"], gt_refunds=gt["refunds"],
                gt_debit_memos=gt["debit_memos"], gt_credit_memos=gt["credit_memos"],
                gt_std_comm=gt["std_comm"], gt_sup_comm=gt["sup_comm"],
                gt_tax_on_comm=gt["tax_on_comm"], gt_balance_payable=gt["balance_payable"],
                gt_doc_count=gt["doc_count"],
            )
            if header.get("period_from"):
                vals["period_from"] = _parse_date(header["period_from"])
            if header.get("period_to"):
                vals["period_to"] = _parse_date(header["period_to"])
            async with db.begin():
                await db.execute(
                    update(BspStatement).where(BspStatement.batch_id == batch_id).values(**vals)
                )
            logger.info("BSP statement %s completed: %d pages, %d rows", batch_id, total_pages, processed_rows)

            # Fill zero-amount CANX rows from paired SPDR cancellation charges — best-effort.
            try:
                await _distribute_spdr_canx(db, batch_id)
            except Exception as sx:  # noqa: BLE001
                logger.warning("SPDR→CANX distribution failed for %s: %s", batch_id, sx)

            # Auto-reconcile against internal tickets — best-effort, never fail the parse.
            try:
                from app.services.bsp_reconciliation import BspReconciliationService
                summary = await BspReconciliationService.run(
                    db, tenant_id=tenant_id, created_by_id=user_id, statement_id=batch_id,
                )
                logger.info("BSP statement %s reconciled: %d rows", batch_id, summary.total)
            except Exception as rex:   # noqa: BLE001
                logger.warning("Auto-reconciliation failed for %s: %s", batch_id, rex)

            # Reconcile the summary↔detailed grand totals if this is a paired upload.
            if group_id:
                try:
                    await _reconcile_group(db, group_id, tenant_id)
                except Exception as gex:   # noqa: BLE001
                    logger.warning("Group reconcile failed for %s: %s", group_id, gex)
    finally:
        await engine.dispose()


async def _fail(db, batch_id: str, message: str):
    from sqlalchemy import update
    from app.models.bsp_statement import BspStatement
    async with db.begin():
        await db.execute(
            update(BspStatement).where(BspStatement.batch_id == batch_id)
            .values(status="failed", error=message[:2000])
        )
    logger.warning("BSP statement %s failed: %s", batch_id, message)


def _extract_header(pdf_bytes: bytes) -> dict:
    """Agent code / billing period / reference from page 1 (cheap — page 1 only)."""
    import fitz
    from app.services.bsp_pdf_parser import parse_statement_header
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return parse_statement_header(doc.load_page(0).get_text("text"))
    finally:
        doc.close()


# ══════════════════════════════════════════════════════════════════════════════
# BSP Summary (FCAGBILLSUMNG) — small doc, parsed whole
# ══════════════════════════════════════════════════════════════════════════════
@celery_app.task(bind=True, max_retries=3, acks_late=True, queue="bsp")
def parse_bsp_summary(self, batch_id: str, tenant_id: int, user_id: int):
    try:
        asyncio.run(_parse_bsp_summary(batch_id, tenant_id, user_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("BSP summary parse failed for batch %s", batch_id)
        try:
            asyncio.run(_mark_failed_summary(batch_id, tenant_id, str(exc)))
        except Exception:  # noqa: BLE001
            logger.exception("could not mark BSP summary %s failed", batch_id)
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 600))


async def _parse_bsp_summary(batch_id: str, tenant_id: int, user_id: int):
    from sqlalchemy import select, delete, update, insert
    from app.models.bsp_summary import BspSummaryStatement, BspSummaryRow
    from app.services import file_store
    from app.services.bsp_pdf_parser import parse_bsp_summary_pdf, has_text_layer

    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                stmt = (await db.execute(
                    select(BspSummaryStatement).where(
                        BspSummaryStatement.batch_id == batch_id,
                        BspSummaryStatement.tenant_id == tenant_id,
                    ).with_for_update()
                )).scalar_one_or_none()
                if stmt is None:
                    logger.warning("BSP summary %s not found (tenant %s)", batch_id, tenant_id)
                    return
                if stmt.status == "completed":
                    return
                file_url = stmt.file_url
                group_id = stmt.group_id
                stmt.status = "processing"
                stmt.error = None
                await db.execute(delete(BspSummaryRow).where(BspSummaryRow.summary_id == batch_id))

            if not file_url:
                await _fail_summary(db, batch_id, "No file attached to this summary.")
                return

            pdf_bytes = await file_store.load(file_url, _bsp_bucket())
            if not has_text_layer(pdf_bytes):
                await _fail_summary(db, batch_id,
                                    "PDF has no extractable text (looks scanned/image-only). OCR is not supported.")
                return

            parsed = parse_bsp_summary_pdf(pdf_bytes)
            g = parsed.grand_total
            rows = [{
                "summary_id": batch_id, "tenant_id": tenant_id, "created_by_id": user_id,
                "category": ln.category, "airline_code": ln.airline_code, "airline_iata": ln.airline_iata,
                "airline_name": ln.airline_name, "fop": ln.fop,
                "issues": ln.issues, "refunds": ln.refunds, "debit_memos": ln.debit_memos,
                "credit_memos": ln.credit_memos, "std_comm": ln.std_comm, "sup_comm": ln.sup_comm,
                "tax_on_comm": ln.tax_on_comm, "balance_payable": ln.balance_payable, "doc_count": ln.doc_count,
            } for ln in parsed.lines]

            async with db.begin():
                if rows:
                    await db.execute(insert(BspSummaryRow), rows)
                vals = dict(
                    status="completed", total_pages=parsed.total_pages, processed_pages=parsed.total_pages,
                    agent_code=parsed.agent_code, agent_name=parsed.agent_name, reference=parsed.reference,
                    billing_period_code=parsed.billing_period_code,
                    period_from=_parse_date(parsed.period_from), period_to=_parse_date(parsed.period_to),
                    currency=parsed.currency,
                )
                if g is not None:
                    vals.update(
                        gt_issues=g.issues, gt_refunds=g.refunds, gt_debit_memos=g.debit_memos,
                        gt_credit_memos=g.credit_memos, gt_std_comm=g.std_comm, gt_sup_comm=g.sup_comm,
                        gt_tax_on_comm=g.tax_on_comm, gt_balance_payable=g.balance_payable, gt_doc_count=g.doc_count,
                    )
                await db.execute(
                    update(BspSummaryStatement).where(BspSummaryStatement.batch_id == batch_id).values(**vals)
                )
            logger.info("BSP summary %s completed: %d airline lines", batch_id, len(rows))

            if group_id:
                try:
                    await _reconcile_group(db, group_id, tenant_id)
                except Exception as gex:  # noqa: BLE001
                    logger.warning("Group reconcile failed for %s: %s", group_id, gex)
    finally:
        await engine.dispose()


async def _fail_summary(db, batch_id: str, message: str):
    from sqlalchemy import update
    from app.models.bsp_summary import BspSummaryStatement
    async with db.begin():
        await db.execute(
            update(BspSummaryStatement).where(BspSummaryStatement.batch_id == batch_id)
            .values(status="failed", error=message[:2000])
        )
    logger.warning("BSP summary %s failed: %s", batch_id, message)


async def _mark_failed_summary(batch_id: str, tenant_id: int, message: str):
    from sqlalchemy import update
    from app.models.bsp_summary import BspSummaryStatement
    engine, Session = _new_engine()
    try:
        async with Session() as db:
            async with db.begin():
                await db.execute(
                    update(BspSummaryStatement)
                    .where(BspSummaryStatement.batch_id == batch_id, BspSummaryStatement.tenant_id == tenant_id)
                    .values(status="failed", error=(message or "")[:2000])
                )
    finally:
        await engine.dispose()


async def _reconcile_group(db, group_id: str, tenant_id: int):
    """Compare the summary's grand totals against the detailed statement's, line by
    line (±₹1). Runs only when BOTH legs are completed; writes match_status +
    per-line match_detail onto the summary statement."""
    from sqlalchemy import select, update
    from app.models.bsp_statement import BspStatement
    from app.models.bsp_summary import BspSummaryStatement

    async with db.begin():
        summ = (await db.execute(select(BspSummaryStatement).where(
            BspSummaryStatement.group_id == group_id,
            BspSummaryStatement.tenant_id == tenant_id,
        ))).scalars().first()
        det = (await db.execute(select(BspStatement).where(
            BspStatement.group_id == group_id,
            BspStatement.tenant_id == tenant_id,
        ))).scalars().first()
        if summ is None or det is None:
            return
        if summ.status != "completed" or det.status != "completed":
            return   # one leg still parsing — reconcile when the second finishes

        detail, ok_all = {}, True
        for name in GT_LINES:
            s = Decimal(str(getattr(summ, f"gt_{name}") or 0))
            d = Decimal(str(getattr(det, f"gt_{name}") or 0))
            var = s - d
            ok = abs(var) <= GT_TOLERANCE
            ok_all = ok_all and ok
            detail[name] = {"summary": str(s), "detail": str(d), "variance": str(var), "ok": ok}

        await db.execute(update(BspSummaryStatement).where(
            BspSummaryStatement.batch_id == summ.batch_id
        ).values(match_status=("matched" if ok_all else "mismatch"),
                 matched_at=datetime.utcnow(), match_detail=detail))
        logger.info("BSP group %s reconcile: %s", group_id, "matched" if ok_all else "mismatch")
