from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AirlineClassMaster(Base):
    __tablename__ = "airline_class_masters"

    __table_args__ = (
        UniqueConstraint(
            "airline_name",
            "class_type",
            "class_code",
            name="uq_airline_class_masters_airline_class",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    airline_name: Mapped[str] = mapped_column(String(255), nullable=False)
    class_type: Mapped[str] = mapped_column(String(50), nullable=False)
    class_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # GDS / LCC (optional)
    airline_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    class_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

