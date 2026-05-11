import enum
from datetime import datetime, date
from sqlalchemy import String, DateTime, ForeignKey, Numeric, Date, Enum as SAEnum, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class BookingClass(str, enum.Enum):
    ECONOMY = "Y"
    PREMIUM_ECONOMY = "W"
    BUSINESS = "J"
    FIRST = "F"


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    pnr: Mapped[str | None] = mapped_column(String(20), nullable=True)

    airline_id: Mapped[int] = mapped_column(ForeignKey("airlines.id"), nullable=False)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)

    booking_class: Mapped[str] = mapped_column(String(5), nullable=False)
    travel_date: Mapped[date] = mapped_column(Date, nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)

    passenger_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin_code: Mapped[str] = mapped_column(String(3), nullable=False)
    destination_code: Mapped[str] = mapped_column(String(3), nullable=False)

    base_fare: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    taxes: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total_fare: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Matched deal
    matched_deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    is_manually_matched: Mapped[bool] = mapped_column(Boolean, default=False)

    upload_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # group uploads together
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    airline: Mapped["Airline"] = relationship("Airline")  # noqa: F821
    route: Mapped["Route"] = relationship("Route")  # noqa: F821
    supplier: Mapped["Supplier"] = relationship("Supplier")  # noqa: F821
    matched_deal: Mapped["UploadedDeal"] = relationship("UploadedDeal")  # noqa: F821
    income_record: Mapped["IncomeRecord"] = relationship("IncomeRecord", back_populates="ticket", uselist=False)  # noqa: F821
