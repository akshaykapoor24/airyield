from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    origin_id: Mapped[int] = mapped_column(ForeignKey("airports.id"), nullable=False)
    destination_id: Mapped[int] = mapped_column(ForeignKey("airports.id"), nullable=False)
    airline_id: Mapped[int | None] = mapped_column(ForeignKey("airlines.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    origin: Mapped["Airport"] = relationship("Airport", foreign_keys=[origin_id])  # noqa: F821
    destination: Mapped["Airport"] = relationship("Airport", foreign_keys=[destination_id])  # noqa: F821
    airline: Mapped["Airline"] = relationship("Airline")  # noqa: F821
