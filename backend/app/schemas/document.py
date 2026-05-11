from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.document import DocumentCategory


class DocumentRead(BaseModel):
    id: int
    file_name: str
    file_path: str
    file_size: int
    mime_type: str
    category: DocumentCategory
    deal_id: Optional[int]
    description: Optional[str]
    uploaded_by_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
