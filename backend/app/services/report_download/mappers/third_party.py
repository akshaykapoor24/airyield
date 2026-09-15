"""Third Party GDS / LCC / API rows → the Combined sheet and the TP detail sheets.

A third-party statement is the one source where the counterparty is not the airline: a
consolidator (GDS / LCC) or an aggregator (API: MakeMyTrip, TBO) sold to the agency and bills
it. Three decisions shape this module, and each is a reuse rather than a re-reading:

* **Type comes from the code that already bills.** GDS / LCC rows are typed by
  ``commission.third_party.classify`` (the commission run's own status policy, including its
  "unrecognised status is a sale, flagged" fall-through); API rows by
  ``tp_api_billing_projection.classify``, which is what decides what reaches a customer
  invoice. A report that typed rows differently from billing would total a different number
  than the money that actually moved, with nothing on screen to say why.

* **Amounts are type-signed.** Consolidators print refunds as positive magnitudes, so every S
  column goes through ``normalize.signed(v, canon)``; U columns are magnitudes. The API net is
  classify's own amount, which already carries TBO's MZ/RM credit-series negation and MMT's
  retained-on-cancel arithmetic (Total Paid − Refund).

* **classify() has one blind spot the report must fill.** A cancelled MakeMyTrip booking
  whose vendor kept part of the payment comes back from ``classify`` as an ordinary ``sale``
  of the retained amount. Billing is right to bill it, but calling it a SALE in a report next
  to its ₹15,508 Total Paid would read as a live booking. It is typed CANCELLATION instead,
  with Gross = Net = the retained amount (design M10); paid and refund stay on the detail sheet.

Everything here is pure: row views in, dicts / tuples out, no DB.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.models.statement_row import STATEMENT_MODELS
from app.services import flat_statement as flat
from app.services import markup_categories as mc
from app.services import tp_api_billing_projection as tpb
from app.services import tp_api_spec as tpspec
from app.services.commission import third_party as tpc
from app.services.report_download import columns as C
from app.services.report_download import normalize as N
from app.services.report_download import pii, registry
from app.services.report_download.mappers import base
from app.services.report_download.mappers.base import DetailCol
from app.services.report_download.types import DocKey, LinkResult, MapCtx
from app.services.statement_display import display_columns

__all__ = [
    "SOURCE_KEYS", "is_summary_line", "tp_classify", "tp_canon", "to_common", "detail_columns",
    "tp_natural_key", "tp_sale_key", "tp_refund_key", "gds_ticket_key",
]

SOURCE_KEYS: tuple[str, ...] = ("tp-gds", "tp-lcc", "tp-api")

GDS, LCC, API = SOURCE_KEYS

# The statuses commission.third_party skips that mean "the booking was undone" rather than
# "nothing was ever sold" (pending / hold / failed / expired / rejected).
_VOID_STATUSES = frozenset({"VOID", "VOIDED", "CANCELLED", "CANCELED", "CANCEL"})

# A voided consolidator line that still carries a net within a rupee of its own penalty is
# the penalty being billed, not a sale that was never reversed.
_VOID_PENALTY_SLACK = Decimal("1")

_PRODUCT_LABELS: dict[str, str] = {
    mc.CATEGORY_AIR: C.PRODUCT_AIR, mc.CATEGORY_HOTEL: "Hotel", mc.CATEGORY_TRAIN: "Train",
    mc.CATEGORY_BUS: "Bus", mc.CATEGORY_CAR: "Car", mc.CATEGORY_MICE: "MICE",
}

# Keys stamped into `data` at ingest (tp_airline_resolution, flat_statement._derive_tp_*,
# tp_api_spec.normalize / stamp_vendor) that no display column shows. Per slug, because each
# is only ever written for these types — a column that is blank on every row is noise.
_STAMPED_HEADERS: dict[str, str] = {
    "airline_master_name": "Airline (Master)",
    "airline_id": "Airline Master ID",
    "airline_conflict": "Airline Conflict",
    "issue_date_source": "Issue Date Source",
    "total_fare_source": "Total Fare Source",
    "date_parse_failed": "Date Parse Failed",
    "vendor": "Vendor",
    "booking_status_source": "Booking Status Source",
}
_STAMPED_BY_SLUG: dict[str, tuple[str, ...]] = {
    GDS: ("airline_master_name", "airline_id", "airline_conflict", "issue_date_source",
          "total_fare_source", "date_parse_failed"),
    LCC: ("airline_master_name", "airline_id", "airline_conflict", "issue_date_source",
          "date_parse_failed"),
    API: ("date_parse_failed", "vendor", "booking_status_source"),
}

# flat_statement normalises these to bare numeric strings, but only a few are declared money
# in the spec; the detail sheet shows all of them as numbers. Rate and count are not money.
_FLAT_MONEY = frozenset(flat._MONEY_FIELDS) - {"commission_rate", "passenger_count"}


# ── small readers ────────────────────────────────────────────────────────────

def _data(row_or_data: Any) -> dict:
    d = row_or_data if isinstance(row_or_data, dict) else getattr(row_or_data, "data", None)
    return d if isinstance(d, dict) else {}


class _Reader:
    """Reads one row's ``data`` and remembers whether any amount was unreadable."""
    __slots__ = ("data", "unparseable")

    def __init__(self, data: dict) -> None:
        self.data = data
        self.unparseable = False

    def m(self, key: str) -> Optional[Decimal]:
        value, bad = N.parse_money_checked(self.data.get(key))
        if bad:
            self.unparseable = True
        return value

    def t(self, *keys: str) -> Optional[str]:
        for k in keys:
            v = N.clean_text(self.data.get(k))
            if v is not None:
                return v
        return None


def _prefer(primary: Optional[Decimal], fallback: Optional[Decimal]) -> Optional[Decimal]:
    """``primary`` unless it is absent, or a bare 0 while the fallback has a figure."""
    if primary is not None and (primary != 0 or fallback is None):
        return primary
    return fallback


def _ident(v: Any) -> Optional[str]:
    """Identifier text for keys: trimmed, upper-cased, inner spaces removed."""
    s = N.clean_text(v)
    return "".join(s.split()).upper() if s is not None else None


def _name_key(v: Any) -> Optional[str]:
    s = N.clean_text(v)
    return " ".join(s.split()).upper() if s is not None else None


def _int(v: Any) -> Optional[int]:
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    d = N.parse_money(v)
    if d is None or d != d.to_integral_value():
        return None
    return int(d)


def _table(slug: str) -> str:
    return STATEMENT_MODELS[slug].__tablename__


def _supplier(ctx: MapCtx):
    return ctx.upload.supplier if ctx is not None and ctx.upload is not None else None


def _vendor(data: dict, source_format: Any) -> Optional[str]:
    return (N.clean_text(data.get("vendor")) or tpspec.format_label(source_format)
            or N.clean_text(source_format))


# ── classification ───────────────────────────────────────────────────────────

def _retained_on_cancel(data: dict, kind: str) -> bool:
    """Did classify take its MMT "cancelled, bill what the vendor kept" branch?

    Mirrors the exact conditions of that branch; it can only yield a positive ``sale``, so a
    negative residue (refund above paid) stays the REFUND classify called it.
    """
    if kind != tpb.SALE or tpb.is_tbo_credit(data):
        return False
    if tpspec._flat._clean(data.get("booking_status")) not in tpb._CANCELLED_STATUSES:
        return False
    refund = tpspec.to_decimal(data.get("refund_amount"))
    return refund is not None and refund > 0 and tpb._paid_is_a_tender_total(data)


def _classify_api(data: dict) -> tuple[str, tuple[str, ...], Optional[Decimal]]:
    kind, amt = tpb.classify(data)
    flags: list[str] = []
    tbo_credit = tpb.is_tbo_credit(data)
    if tbo_credit:
        flags.append("API_TBO_CREDIT")

    if kind == tpb.SALE:
        if _retained_on_cancel(data, kind):
            flags.append("API_RETAINED_ON_CANCEL")
            return C.CANCELLATION, tuple(flags), amt
        return C.SALE, tuple(flags), amt
    if kind == tpb.REFUND:
        return C.REFUND, tuple(flags), amt
    if kind == tpb.CANCELLED:
        return C.VOID, tuple(flags), amt
    if kind in (tpb.PENDING, tpb.NO_AMOUNT):
        return C.NON_BILLABLE, tuple(flags), amt
    if kind == tpb.NEEDS_REVIEW:
        flags.append("API_NEEDS_REVIEW")
        return C.REFUND, tuple(flags), amt
    if kind == tpb.NO_CATEGORY:
        flags.append("API_NO_CATEGORY")
        # classify stops at the category test before its credit-series negation; a TBO MZ/RM
        # line is a credit whatever product it names.
        if tbo_credit and amt is not None and amt != 0:
            amt = -abs(amt)
        if amt is None or amt == 0:
            return C.NON_BILLABLE, tuple(flags), amt
        return (C.REFUND if amt < 0 else C.SALE), tuple(flags), amt
    flags.append("TXN_UNMAPPED")
    return C.UNKNOWN, tuple(flags), amt


# A consolidator file ends with its own footer — "TOTAL", "LESS PAYMENT", "BALANCE" — which the
# importer stores as rows carrying a Net Amount and nothing else (seen on the real GDS export).
# commission.third_party.classify reads a blank status as an issue, so without this test the
# report would add the statement's total AND its balance to Net as if they were sales.
_IDENTITY_FIELDS = ("ticket_number", "pnr", "airline_pnr", "gds_pnr", "booking_reference", "invoice_number")
_DATE_FIELDS = ("issue_date", "booking_date", "travel_date", "transaction_date")


def is_summary_line(data: dict) -> bool:
    """A GDS / LCC statement footer: no booking identifier, no status and no date at all."""
    return not any(N.clean_text(data.get(k)) for k in (*_IDENTITY_FIELDS, "ticket_status", *_DATE_FIELDS))


def tp_classify(slug: str, data: dict) -> tuple[str, tuple[str, ...], Optional[Decimal]]:
    """``(canonical type, flags, amount)`` for one TP row's ``data``.

    GDS / LCC: the amount is the stored ``net_amount`` (unsigned, as printed). API: classify's
    billing amount, already signed. Flags are the classification's own (unrecognised status,
    TBO credit, retained on cancel, needs review, no category). A GDS / LCC footer line
    (``is_summary_line``) is NON_BILLABLE.
    """
    data = data if isinstance(data, dict) else {}
    if slug == API:
        return _classify_api(data)
    if slug not in (GDS, LCC):
        raise KeyError(f"Not a third-party source: {slug!r}")

    amount = N.parse_money(data.get("net_amount"))
    if is_summary_line(data):
        return C.NON_BILLABLE, (), amount
    kind, reason = tpc.classify(data)
    if kind == tpc.KIND_REFUND:
        return C.REFUND, (), amount
    if kind == tpc.KIND_SKIP:
        status = (N.clean_text(data.get("ticket_status")) or "").upper()
        if status in _VOID_STATUSES and amount is not None and amount < 0:
            # A consolidator that prints the cancellation as its OWN negative line (−86,399
            # against the +89,437 sale) is crediting the agency: the pair nets to what was
            # retained. Excluding the credit would overstate what the agency owes, so it is a
            # REFUND and counts. A cancelled line still carrying the positive sale amount is
            # the other export style and stays VOID ("verify").
            return C.REFUND, (), amount
        return (C.VOID if status in _VOID_STATUSES else C.NON_BILLABLE), (), amount
    # classify gives an ISSUE a reason only for a status outside its vocabulary.
    return C.SALE, (("TP_UNRECOGNISED_STATUS",) if reason else ()), amount


def tp_canon(slug: str, data: dict) -> str:
    return tp_classify(slug, data)[0]


# ── Combined row ─────────────────────────────────────────────────────────────

def _settled_with(slug: str, sup, vendor: Optional[str]) -> str:
    name = N.clean_text(sup.name) if sup is not None else None
    if slug == API:
        out = "Aggregator" + (f" – {name}" if name else "")
        return out + (f" ({vendor})" if vendor else "")
    code = N.clean_text(sup.code) if sup is not None else None
    label = name or code
    out = "Consolidator" + (f" – {label}" if label else "")
    return out + (f" ({code})" if code and code != label else "")


def _join(*parts: Optional[str], sep: str = " / ") -> Optional[str]:
    vals = [p for p in parts if p]
    return sep.join(vals) if vals else None


def _money(row: dict, canon: str, **values: Optional[Decimal]) -> None:
    """Write S columns type-signed."""
    for key, v in values.items():
        row[key] = N.signed(v, canon)


def to_common(slug: str, row: Any, ctx: MapCtx, link: Optional[LinkResult] = None,
              **extra: Any) -> dict[str, Any]:
    """One TP row view → a Combined row (design §B.4 TP columns, §B.3 rules 8-9)."""
    data = _data(row)
    r = _Reader(data)
    source = registry.get_source(slug)
    out = C.new_common_row(ctx, category=C.CAT_TP, source_type=source.label,
                           row_ref=base.row_ref(_table(slug), getattr(row, "id", None)))
    canon, cls_flags, amount = tp_classify(slug, data)
    out["transaction_type"] = canon
    if cls_flags:
        C.add_flag(out, *cls_flags)
    if source.schema_unverified:
        C.add_flag(out, "SCHEMA_UNVERIFIED")

    sup = _supplier(ctx)
    source_format = getattr(row, "source_format", None)
    if data.get("date_parse_failed"):
        C.add_flag(out, "TP_DATE_PARSE_FAILED")

    if slug == API:
        _api_columns(out, r, row, sup, canon, amount, source_format)
    else:
        _flat_columns(slug, out, r, sup, canon, source_format)

    if out["issue_date"] is None:
        C.add_flag(out, "DATE_UNREADABLE")
    if r.unparseable:
        C.add_flag(out, "AMOUNT_UNPARSEABLE")
    return C.apply_link(out, link)


def _flat_columns(slug: str, out: dict, r: _Reader, sup, canon: str, source_format: Any) -> None:
    data = r.data
    is_gds = slug == GDS

    out["settled_with"] = _settled_with(slug, sup, None)
    out["agent_signon"] = r.t("username", "issuing_office", "agency_code") if is_gds else r.t("agency_code")
    if is_gds:
        out["airline_numeric"] = N.zfill3(data.get("ticket_prefix"))
    out["airline_code"] = N.clean_text(data.get("airline_code"))
    out["airline_name"] = r.t("airline_master_name", "airline_name")
    out["product"] = C.PRODUCT_AIR

    status = r.t("ticket_status")
    out["source_txn_type"] = _join(status, r.t("transaction_type"))
    out["document_number"] = r.t("ticket_number")
    if is_gds:
        ticket, nonstandard = N.ticket13(data.get("ticket_prefix"), data.get("ticket_number"))
        out["ticket_number"] = ticket
        if ticket is not None and nonstandard:
            C.add_flag(out, "TICKET_NO_NONSTANDARD")
    else:
        out["ticket_number"] = r.t("ticket_number")
    out["status"] = status

    out["airline_pnr"] = r.t("airline_pnr", "pnr")
    out["gds_ref"] = r.t("gds_pnr") if is_gds else r.t("booking_reference")
    out["invoice_ref"] = r.t("invoice_number", "pnr")
    out["passenger_name"] = r.t("passenger_name") or _join(r.t("first_name"), r.t("last_name"), sep=" ")
    out["pax_count"] = _int(data.get("passenger_count"))

    out["issue_date"] = N.parse_report_date(data.get("issue_date"))
    out["booking_date"] = N.parse_report_date(data.get("booking_date"))
    out["travel_date"] = N.parse_report_date(data.get("travel_date"))
    out["settlement_period"] = r.t("week")
    out["sector"] = r.t("sector")
    out["dom_intl"] = N.stat_segment(data.get("segment_type"))
    out["flight_no"] = r.t("flight_number")
    out["booking_class"] = r.t("booking_class")

    currency = r.t("currency")
    if currency:
        out["currency"] = currency.upper()
    else:
        out["currency"] = "INR"
        C.add_flag(out, "CURRENCY_ASSUMED")
    out["form_of_payment"] = r.t("payment_method")

    # ── money
    yq = r.m("yq") if is_gds else None
    other = r.m("other_taxes")
    net = r.m("net_amount")
    # Read on both slugs for the void test below; only the GDS export prints them today.
    penalty_pair = N.dsum(r.m("agent_penalty"), r.m("cancellation_markup"))
    if is_gds:
        ancillary = r.m("ssr_amount")
        service = N.dsum(r.m("service_fee"), r.m("service_charge"))
        out["penalty"] = N.magnitude(N.dsum(penalty_pair, r.m("reschedule_charges")))
    else:
        ancillary = N.dsum(r.m("ssr_amount"), r.m("other_charges"))
        service = N.dsum(r.m("service_fee"), r.m("convenience_fee"))

    _money(
        out, canon,
        base_fare=r.m("base_fare"),
        yq=yq,
        other_taxes=other,
        total_taxes=_prefer(r.m("taxes"), N.dsum(yq, other)),
        gross_amount=r.m("total_fare"),
        ancillary=ancillary,
        commission=r.m("commission_amount"),
        incentive_declared=r.m("incentive_amount"),
        net_payable=net,
    )
    out["service_fee"] = N.magnitude(service)
    out["gst_on_service"] = N.magnitude(r.m("gst_on_sf"))
    out["tds"] = N.magnitude(r.m("tds"))

    if out["gross_amount"] is not None and data.get("total_fare_source") == "derived":
        C.add_flag(out, "TP_TOTAL_FARE_DERIVED")

    # ── checks / flags
    if data.get("airline_conflict"):
        C.add_flag(out, "TP_AIRLINE_CONFLICT")
    if (source_format or "") != flat.CURRENT_SOURCE_FORMATS.get(slug):
        C.add_flag(out, "TP_STALE_FORMAT")
    if is_gds and tpc.build_declared(data).net_ok is False:
        C.add_flag(out, "TP_NET_IDENTITY_MISMATCH")

    # ── Counts In Net (§B.3 rule 8)
    if canon == C.NON_BILLABLE:
        out["counts_in_net"] = C.NET_SUMMARY_ONLY if is_summary_line(data) else C.NET_NOT_A_SALE
    elif canon == C.VOID:
        allowed = abs(penalty_pair or Decimal(0)) + _VOID_PENALTY_SLACK
        out["counts_in_net"] = C.NET_YES if abs(net or Decimal(0)) <= allowed else C.NET_CANCELLED_VERIFY
    else:
        out["counts_in_net"] = C.NET_YES


def _api_columns(out: dict, r: _Reader, row: Any, sup, canon: str,
                 amount: Optional[Decimal], source_format: Any) -> None:
    data = r.data
    category = tpb.row_category(data)
    air = category == mc.CATEGORY_AIR

    out["settled_with"] = _settled_with(API, sup, _vendor(data, source_format))
    out["agent_signon"] = r.t("booked_by")
    if air:
        out["airline_name"] = r.t("airline_property_name")
    out["booking_party_gstin"] = r.t("gstin")
    out["product"] = _PRODUCT_LABELS.get(category) if category else r.t("product_type")

    status = r.t("booking_status")
    out["source_txn_type"] = _join(status, r.t("amendment_type"))
    out["document_number"] = r.t("invoice_number")
    out["status"] = status

    if air:
        out["airline_pnr"] = r.t("pnr")
        out["flight_no"] = r.t("flight_number")
    out["gds_ref"] = r.t("confirmation_no", "tbo_confirmation_no", "reference_no")
    out["invoice_ref"] = r.t("booking_id", "invoice_number")
    out["passenger_name"] = tpspec.strip_pax_suffix(data.get("passenger_name"))
    stamped_pax = getattr(row, "bill_pax_count", None)
    out["pax_count"] = int(stamped_pax) if stamped_pax else _int(data.get("pax_count"))

    out["issue_date"] = N.parse_report_date(r.t("transaction_date", "booking_date"))
    out["booking_date"] = N.parse_report_date(data.get("booking_date"))
    out["travel_date"] = N.parse_report_date(r.t("travel_date", "start_date"))
    out["settlement_period"] = r.t("payment_due_date")
    out["sector"] = tpb._sector(data)
    out["dom_intl"] = tpb._intl_dom(data.get("intl_dom"))
    out["booking_class"] = r.t("booking_class")

    # The aggregator exports carry no currency column.
    out["currency"] = "INR"
    C.add_flag(out, "CURRENCY_ASSUMED")
    out["form_of_payment"] = r.t("payment_mode")

    # ── money
    base_fare = r.m("base_fare")
    taxes = r.m("taxes")
    if canon == C.CANCELLATION:
        gross = amount
    else:
        paid = r.m("total_paid_amount")
        if paid is not None and paid != 0:
            gross = paid
        else:
            derived = N.dsum(base_fare, taxes)
            gross = derived if derived is not None else paid
            if derived is not None:
                C.add_flag(out, "API_GROSS_DERIVED")

    _money(
        out, canon,
        base_fare=base_fare,
        total_taxes=taxes,
        gross_amount=gross,
        ancillary=r.m("travel_insurance"),
        net_payable=amount,
    )
    out["penalty"] = N.magnitude(r.m("cancellation_fee"))
    # agent_markup is the agency's own margin, not the aggregator's charge — excluded.
    out["service_fee"] = N.magnitude(
        N.dsum(r.m("service_charges"), r.m("convenience_fee"), r.m("pg_charges")))
    out["discount"] = N.magnitude(r.m("discount"))
    gst = _prefer(r.m("total_gst"), N.dsum(r.m("sgst_amount"), r.m("cgst_amount"), r.m("igst_amount")))
    legacy = N.dsum(r.m("service_tax_amount"), r.m("legacy_cess"))
    out["gst_on_service"] = N.dsum(N.magnitude(gst), N.magnitude(legacy))
    out["tds"] = N.magnitude(r.m("tds"))
    out["tcs"] = N.magnitude(r.m("tcs_amount"))

    # ── Counts In Net (§B.3 rule 9)
    if canon == C.NON_BILLABLE:
        out["counts_in_net"] = C.NET_NOT_A_SALE
    elif canon == C.VOID:
        out["counts_in_net"] = C.NET_CANCELLED
    elif "API_NEEDS_REVIEW" in out["data_flags"]:
        out["counts_in_net"] = C.NET_NEEDS_REVIEW
    else:
        out["counts_in_net"] = C.NET_YES


# ── detail sheet ─────────────────────────────────────────────────────────────

def _detail_money(field: str):
    """As stored, but a readable amount becomes a number; unreadable text is kept."""
    def _get(row: Any, ctx: MapCtx) -> Any:
        raw = _data(row).get(field)
        value, _bad = N.parse_money_checked(raw)
        return value if value is not None else raw
    return _get


def _supplier_attr(name: str):
    def _get(row: Any, ctx: MapCtx) -> Any:
        sup = _supplier(ctx)
        return getattr(sup, name, None) if sup is not None else None
    return _get


def detail_columns(slug: str, ctx: MapCtx) -> list[DetailCol]:
    """Provenance + the drill-in's own columns + ingest-stamped keys + extra JSONB keys +
    the declared supplier. Identity fields (tp-api PAN, passport, mobile) need include_pii."""
    if slug not in SOURCE_KEYS:
        raise KeyError(f"Not a third-party source: {slug!r}")
    include_pii = ctx.options.include_pii
    table = _table(slug)
    cols = base.provenance_cols(lambda row: base.row_ref(table, getattr(row, "id", None)))

    shown: set[str] = set()
    for c in display_columns(slug):
        field = c["field"]
        shown.add(field)
        if field == "__format__":
            cols.append(DetailCol(c["header"], base.attr("source_format")))
            continue
        if not pii.allowed(field, include_pii):
            continue
        if c.get("kind") == "money" or (slug != API and field in _FLAT_MONEY):
            cols.append(DetailCol(c["header"], _detail_money(field), "money", 12))
        else:
            cols.append(DetailCol(c["header"], base.data_key(field)))

    for key in _STAMPED_BY_SLUG[slug]:
        if key in shown:
            continue
        shown.add(key)
        cols.append(DetailCol(_STAMPED_HEADERS[key], base.data_key(key)))

    for key in ctx.extra_keys:
        if key in shown or not pii.allowed(key, include_pii):
            continue
        shown.add(key)
        cols.append(DetailCol(f"data.{key}", base.data_key(key)))

    cols += [
        DetailCol("Supplier Name", _supplier_attr("name"), "text", 24),
        DetailCol("Supplier Code", _supplier_attr("code")),
        DetailCol("Supplier Branch", _supplier_attr("branch")),
    ]
    return cols


# ── keys for de-duplication and linking ──────────────────────────────────────

def tp_natural_key(slug: str, row: Any, ctx: MapCtx) -> tuple:
    """The DuplicateTracker identity (design §C.10): the same line re-uploaded yields the
    same tuple whatever formatting its amounts / dates / spacing arrived in."""
    data = _data(row)
    sup = _supplier(ctx)
    supplier_id = sup.supplier_id if sup is not None else None
    if slug == API:
        return (
            supplier_id,
            _ident(data.get("invoice_number")),
            _ident(data.get("booking_id")),
            _name_key(data.get("product_type")),
            tpb.bill_base(data),
            N.date_key_py(data.get("transaction_date")),
        )
    r = _Reader(data)
    return (
        supplier_id,
        _ident(r.t("ticket_number", "pnr")),
        _name_key(r.t("passenger_name") or _join(r.t("first_name"), r.t("last_name"), sep=" ")),
        _name_key(data.get("ticket_status")),
        _ident(data.get("invoice_number")),
        N.parse_money(data.get("net_amount")),
        N.date_key_py(data.get("issue_date")),
    )


def _doc_key_of(slug: str, row: Any, ctx: MapCtx, want: str) -> Optional[tuple]:
    if slug not in (GDS, LCC):
        return None
    data = _data(row)
    if tp_canon(slug, data) != want:
        return None
    ref = _ident(N.clean_text(data.get("ticket_number")) or data.get("pnr"))
    if ref is None:
        return None
    sup = _supplier(ctx)
    return (sup.supplier_id if sup is not None else None, ref)


def tp_sale_key(slug: str, row: Any, ctx: MapCtx) -> Optional[tuple]:
    """``(supplier_id, ticket_number or pnr)`` for a GDS / LCC SALE row, else None."""
    return _doc_key_of(slug, row, ctx, C.SALE)


def tp_refund_key(slug: str, row: Any, ctx: MapCtx) -> Optional[tuple]:
    """Same shape as ``tp_sale_key``, for REFUND rows (``TP_REFUND_WITHOUT_SALE`` probe)."""
    return _doc_key_of(slug, row, ctx, C.REFUND)


def gds_ticket_key(row: Any) -> Optional[DocKey]:
    """The GDS ticket as a DocKey, for the ``ALSO_IN_BSP`` / ``ALSO_IN_TP_GDS`` probes."""
    data = _data(row)
    return N.doc_key(data.get("ticket_prefix"), data.get("ticket_number"))
