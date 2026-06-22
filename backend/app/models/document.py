import enum
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Text, Enum as SAEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DocumentCategory(str, enum.Enum):
    DEAL_PDF = "deal_pdf"
    DEAL_EXCEL = "deal_excel"
    EMAIL = "email"
    SCREENSHOT = "screenshot"
    TICKET_UPLOAD = "ticket_upload"
    OTHER = "other"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)  # bytes
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[DocumentCategory] = mapped_column(SAEnum(DocumentCategory), default=DocumentCategory.OTHER)

    # Optional links
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("legacy_deals.id"), nullable=True)
    ticket_batch_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    uploaded_by: Mapped["User"] = relationship("User")  # noqa: F821
    deal: Mapped["UploadedDeal"] = relationship("UploadedDeal")  # noqa: F821
