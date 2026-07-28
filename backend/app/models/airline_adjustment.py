"""Airline adjustment upload tables — ADM / ACM / RA.

One table per IATA BSPlink document type. Each row is one line from an uploaded
ADM/ACM/RA export (.xls/.xlsx/.csv). Every export column is stored verbatim as
text (fidelity over coercion — dates/amounts arrive locale-formatted), plus
per-upload provenance (``batch_id``, ``source_file``, ``uploaded_at``) and the
usual tenant/user scoping. The column set for each type is the source-of-truth
list in ``app.services.airline_adjustment_spec``.
"""
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class _AdjustmentBase:
    """Shared scaffolding for every adjustment table (mixed into each model)."""

    id:            Mapped[int]        = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Provenance — one batch_id per uploaded file, so a whole upload can be listed/deleted together.
    batch_id:      Mapped[str]        = mapped_column(String(100), nullable=False, index=True)
    source_file:   Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url:      Mapped[str | None] = mapped_column(String(1000), nullable=True)   # GCS blob path of the uploaded XLS
    uploaded_at:   Mapped[datetime]   = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AirlineADM(_AdjustmentBase, Base):
    """Agency Debit Memo rows (airline bills the agency)."""
    __tablename__ = "airline_adm"

    iso_country_code:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    type:                              Mapped[str | None] = mapped_column(Text, nullable=True)
    country_territory:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_for_issue:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    document_number:                   Mapped[str | None] = mapped_column(Text, nullable=True)
    status:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_ticket_issue:              Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_code:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_code:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_fare:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_fare:                       Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_tax:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_tax:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_commission:               Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_commission:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_supplementary_commission: Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_supplementary_commission:   Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_tax_on_commission:        Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_tax_on_commission:          Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_cancellation_penalty:     Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_cancellation_penalty:       Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_miscellaneous_fee:        Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_miscellaneous_fee:          Mapped[str | None] = mapped_column(Text, nullable=True)
    amount:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    currency:                          Mapped[str | None] = mapped_column(Text, nullable=True)
    statistical_code:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    rtdn_type:                         Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_reason:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_reason:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    reporting_date:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    period:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_date:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_to_gds:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_to_gds_date:               Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_reason:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    forward_to_gds_reason:             Mapped[str | None] = mapped_column(Text, nullable=True)
    related_document:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_rejection_reason:          Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_approval_remark:           Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to_dpc:                       Mapped[str | None] = mapped_column(Text, nullable=True)


class AirlineACM(_AdjustmentBase, Base):
    """Agency Credit Memo rows (airline credits the agency)."""
    __tablename__ = "airline_acm"

    iso_country_code:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    type:                              Mapped[str | None] = mapped_column(Text, nullable=True)
    country_territory:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_for_issue:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    document_number:                   Mapped[str | None] = mapped_column(Text, nullable=True)
    status:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    date_of_ticket_issue:              Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_code:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_code:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_fare:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_fare:                       Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_tax:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_tax:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_commission:               Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_commission:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_supplementary_commission: Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_supplementary_commission:   Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_tax_on_commission:        Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_tax_on_commission:          Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_cancellation_penalty:     Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_cancellation_penalty:       Mapped[str | None] = mapped_column(Text, nullable=True)
    airlines_miscellaneous_fee:        Mapped[str | None] = mapped_column(Text, nullable=True)
    agents_miscellaneous_fee:          Mapped[str | None] = mapped_column(Text, nullable=True)
    amount:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    currency:                          Mapped[str | None] = mapped_column(Text, nullable=True)
    statistical_code:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    rtdn_type:                         Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_reason:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    reporting_date:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    period:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_date:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone:                     Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_reason:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    related_document:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_rejection_reason:          Mapped[str | None] = mapped_column(Text, nullable=True)
    dispute_approval_remark:           Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to_dpc:                       Mapped[str | None] = mapped_column(Text, nullable=True)


class AirlineRA(_AdjustmentBase, Base):
    """Refund Application rows."""
    __tablename__ = "airline_ra"

    iso_country_code:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    country_territory:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    document_number:                   Mapped[str | None] = mapped_column(Text, nullable=True)
    rtdn_number:                       Mapped[str | None] = mapped_column(Text, nullable=True)
    status:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_code:                      Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_code:                        Mapped[str | None] = mapped_column(Text, nullable=True)
    application_date:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization_date:                Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_date:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    reporting_date:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    period:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    currency:                          Mapped[str | None] = mapped_column(Text, nullable=True)
    forms_of_payment:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    amount:                            Mapped[str | None] = mapped_column(Text, nullable=True)
    passenger:                         Mapped[str | None] = mapped_column(Text, nullable=True)
    et:                                Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to_dpc:                       Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_remark:                    Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_for_refund:                 Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason:                  Mapped[str | None] = mapped_column(Text, nullable=True)
    deletion_reason:                   Mapped[str | None] = mapped_column(Text, nullable=True)
    final:                             Mapped[str | None] = mapped_column(Text, nullable=True)
    days_left:                         Mapped[str | None] = mapped_column(Text, nullable=True)
    process_stopped:                   Mapped[str | None] = mapped_column(Text, nullable=True)


# Map the URL slug used everywhere (adm/acm/ra) to its model.
ADJUSTMENT_MODELS = {
    "adm": AirlineADM,
    "acm": AirlineACM,
    "ra":  AirlineRA,
}
