from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


CATEGORIZATIONS = [
    "APAC", "EUROPEAN NATIONS", "GCC/MIDDLE EAST", "LATIN AMERICA",
    "MEAI", "MEAI/APAC", "MEAI/SAARC", "MEAI/SAARC/APAC",
    "NAM", "OTHER", "SAARC", "SAARC/APAC",
]

CONTINENTS = [
    "Africa", "Asia", "Europe",
    "North America", "Oceania", "South America", "Antarctica",
]


class Airport(Base):
    __tablename__ = "airports"

    id:               Mapped[int]      = mapped_column(primary_key=True)
    apt_id:           Mapped[str|None] = mapped_column(String(20),  unique=True, nullable=True)
    iata_code:        Mapped[str]      = mapped_column(String(3),   unique=True, nullable=False)
    country:          Mapped[str]      = mapped_column(String(100), nullable=False)
    categorization:   Mapped[str|None] = mapped_column(String(50),  nullable=True)
    continent:        Mapped[str|None] = mapped_column(String(50),  nullable=True)
    city_airport_name:Mapped[str]      = mapped_column(String(255), nullable=False)
    is_active:        Mapped[bool]     = mapped_column(Boolean, default=True)
    created_by_id:    Mapped[int|None] = mapped_column(
                          Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
                      )
    created_at:       Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
