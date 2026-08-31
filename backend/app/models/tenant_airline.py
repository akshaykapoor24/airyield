"""Airline Master — the airlines a tenant works with ("User Master → Airline Master").

The platform admin owns the global `airlines` master (name / IATA code / IATA numeric
code / contract year). A tenant registers the subset it actually deals with and gives
each one **its own id** — the handle a user recognises, e.g. an airline-portal agent
code like ``KTDEL471``.

That id is the selection key when uploading an LCC Detailed statement: an LCC export
carries no airline anywhere (not on the batch, not on the row, not in any of the 129
standard columns), and its flight numbers are bare, so the carrier cannot be derived
from the file. The user picks their id at upload and the airline is stamped onto the
batch and every row from there — see ``api/v1/lcc_detailed.py`` and ``workers/lcc_tasks.py``.

Deliberately NOT ``models/login_id.py``: that table holds free-text airline names with
no FK to the master, no numeric code and no contract year, and it already feeds the deal
form's "Login ID / IATA Code" multi-select and ``Deal.login_ids`` attribution in
``services/plb_accrual.py``. Writing Airline Master rows into it would change both.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint,
    inspect as sa_inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TenantAirline(Base):
    __tablename__ = "tenant_airlines"
    __table_args__ = (
        # The id is what a user picks at upload, so it must be unambiguous per tenant.
        UniqueConstraint("tenant_id", "ref_id", name="uq_tenant_airlines_tenant_ref"),
    )

    id:            Mapped[int]  = mapped_column(primary_key=True)
    tenant_id:     Mapped[int]  = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int]  = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # RESTRICT, not SET NULL: deleting a platform airline a tenant has registered and
    # stamped onto statement rows should fail loudly rather than silently orphan them.
    airline_id:    Mapped[int]  = mapped_column(Integer, ForeignKey("airlines.id", ondelete="RESTRICT"), nullable=False, index=True)

    # The user's own id for this airline. Free text — it is a handle they recognise.
    ref_id:        Mapped[str]  = mapped_column(String(100), nullable=False, index=True)

    # Snapshots of the master at the moment the airline was registered. A statement
    # uploaded in August must keep saying what it said in August even if an admin later
    # renames the airline or corrects its numeric code. Same pattern as Deal.scope_party_name.
    airline_name:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    airline_code:      Mapped[str | None] = mapped_column(String(20), nullable=True)
    iata_numeric_code: Mapped[str | None] = mapped_column(String(3), nullable=True)
    contract_year:     Mapped[str | None] = mapped_column(String(2), nullable=True)

    is_active:  Mapped[bool]     = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    airline: Mapped["Airline"] = relationship("Airline", lazy="raise")  # noqa: F821

    def apply_master(self, airline) -> None:
        """Copy the platform master's values into this row's snapshot columns."""
        self.airline_id = airline.id
        self.airline_name = airline.name
        self.airline_code = airline.iata_code
        self.iata_numeric_code = airline.iata_numeric_code
        self.contract_year = airline.contract_year

    @property
    def live_airline_name(self) -> str | None:
        """The master's CURRENT name; None when `airline` isn't eager-loaded (avoids an
        illegal async lazy-load). Load with selectinload(TenantAirline.airline)."""
        if "airline" in sa_inspect(self).unloaded:
            return None
        return self.airline.name if self.airline else None
