from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Numeric, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from typing import Any


class UploadedTicket(Base):
    """One row from a supplier statement XLS upload.
    All XLS columns are stored as-is for audit; numerics are nullable (dash rows → None).
    """
    __tablename__ = "uploaded_tickets"

    id:             Mapped[int]      = mapped_column(primary_key=True)
    batch_id:       Mapped[str]      = mapped_column(String(100), nullable=False, index=True)
    file_name:      Mapped[str]      = mapped_column(String(500), nullable=False)
    tenant_id:      Mapped[int]      = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    statement_type: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # ── XLS columns ───────────────────────────────────────────────────────
    booking_ref:         Mapped[str | None] = mapped_column(String(100), nullable=True)
    segment_type:        Mapped[str | None] = mapped_column(String(50),  nullable=True)
    invoice_type:        Mapped[str | None] = mapped_column(String(50),  nullable=True)
    invoice_no:          Mapped[str | None] = mapped_column(String(100), nullable=True)
    ticket_date:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    last_name:           Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_name:          Mapped[str | None] = mapped_column(String(200), nullable=True)
    sector:              Mapped[str | None] = mapped_column(String(200), nullable=True)
    booking_class:       Mapped[str | None] = mapped_column(String(20),  nullable=True)
    departure_datetime:  Mapped[str | None] = mapped_column(String(100), nullable=True)
    gds_pnr:             Mapped[str | None] = mapped_column(String(50),  nullable=True)
    airlines_code:       Mapped[str | None] = mapped_column(String(20),  nullable=True)
    ticket_number:       Mapped[str | None] = mapped_column(String(50),  nullable=True)

    # ── Fare / Charge columns ──────────────────────────────────────────────
    sell_fare:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_tax:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sell_tax_yq:         Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_yr:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sale_k3:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rei_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    seat_selection:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    excess_baggage:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    meals:               Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    rfd_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    can_charge:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    booking_fee_sell:    Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cgst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    sgst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    igst_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    comm_sell:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    adm:                 Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    incentive_sell:      Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    dis_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    tds_sell:            Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_amt:           Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    paid_by_credit_card: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_amt:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cc:                  Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    acc_code:            Mapped[str | None]   = mapped_column(String(100), nullable=True)
    sold_to:             Mapped[str | None]   = mapped_column(String(20),  nullable=True)   # 'customer' | 'agency'
    customer_name:       Mapped[str | None]   = mapped_column(String(300), nullable=True)
    tour_code:           Mapped[str | None]   = mapped_column(String(100), nullable=True)

    # ── Airline: passenger ────────────────────────────────────────────────────
    pax_name:              Mapped[str | None]   = mapped_column(String(300), nullable=True)
    air_pnr:               Mapped[str | None]   = mapped_column(String(50),  nullable=True)

    # ── Airline: BSP booking metadata ─────────────────────────────────────────
    pcc:                   Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    booking_signon:        Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    booking_pcc:           Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    booking_agency_name:   Mapped[str | None]   = mapped_column(String(200), nullable=True)
    ticketing_signon:      Mapped[str | None]   = mapped_column(String(50),  nullable=True)

    # ── Airline: document / trip ──────────────────────────────────────────────
    document_type:         Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    fare_basis:            Mapped[str | None]   = mapped_column(String(100), nullable=True)
    fare_const_type:       Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    base_fare_currency:    Mapped[str | None]   = mapped_column(String(10),  nullable=True)
    transaction_type:      Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    exchanged_for:         Mapped[str | None]   = mapped_column(String(100), nullable=True)
    stock_control_no:      Mapped[str | None]   = mapped_column(String(100), nullable=True)
    stp_no:                Mapped[str | None]   = mapped_column(String(100), nullable=True)
    void_date:             Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    coupon_status:         Mapped[str | None]   = mapped_column(String(200), nullable=True)
    refund_type:           Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    trip_id:               Mapped[str | None]   = mapped_column(String(100), nullable=True)
    ai_code:               Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    value_code:            Mapped[str | None]   = mapped_column(String(100), nullable=True)
    multiple_receivables:  Mapped[str | None]   = mapped_column(String(100), nullable=True)

    # ── Airline: financials ───────────────────────────────────────────────────
    wo_tax:                Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    other_tax:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    comm_percent:          Mapped[float | None] = mapped_column(Numeric(8,  4), nullable=True)
    net_remit:             Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_fare:              Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    invoice_fare:          Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_refund_amount:   Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    roe:                   Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    nuc:                   Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)

    # ── Airline: form of payment ──────────────────────────────────────────────
    fop:                   Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    fop_details:           Mapped[str | None]   = mapped_column(String(200), nullable=True)
    cc_auth:               Mapped[str | None]   = mapped_column(String(100), nullable=True)
    cc_do_expiry:          Mapped[str | None]   = mapped_column(String(50),  nullable=True)

    # ── Airline: flight details ───────────────────────────────────────────────
    flight_no:             Mapped[str | None]   = mapped_column(String(200), nullable=True)
    travel_dt:             Mapped[str | None]   = mapped_column(String(100), nullable=True)
    fare_ladder:           Mapped[str | None]   = mapped_column(Text,        nullable=True)

    # ── Airline: customer / GST ───────────────────────────────────────────────
    gstn:                  Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    business_phone:        Mapped[str | None]   = mapped_column(String(50),  nullable=True)
    business_email:        Mapped[str | None]   = mapped_column(String(200), nullable=True)
    entity_address:        Mapped[str | None]   = mapped_column(String(500), nullable=True)

    # ── JSONB ─────────────────────────────────────────────────────────────────
    tax_breakup:           Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    segments:              Mapped[list | None]  = mapped_column(JSONB, nullable=True)
    raw_data:              Mapped[dict | None]  = mapped_column(JSONB, nullable=True)

    # ── Derived / calculation columns ─────────────────────────────────────────
    airline_name:          Mapped[str | None]   = mapped_column(String(200), nullable=True)
    matched_deal_id:       Mapped[int | None]   = mapped_column(Integer, nullable=True)
    matched_deal_type:     Mapped[str | None]   = mapped_column(String(20), nullable=True)   # 'airline' | 'b2b'
    matched_deal_name:     Mapped[str | None]   = mapped_column(String(300), nullable=True)
    calculated_incentive:  Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    iata_commission:       Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)   # deal IATA comm % applied to sell fare
    incentive_breakdown:   Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    ticket_status:         Mapped[str]          = mapped_column(String(10), nullable=False, server_default="draft")
    split_type:            Mapped[str | None]   = mapped_column(String(10), nullable=True)
    exclusion_reason:      Mapped[str | None]   = mapped_column(String(500), nullable=True)
    adm_acm_ra:            Mapped[str | None]   = mapped_column(String(10), nullable=True)   # 'ADM' | 'ACM' | 'RA'

    created_by: Mapped["User"] = relationship("User")  # noqa: F821
