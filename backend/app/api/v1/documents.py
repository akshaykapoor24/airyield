from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid, aiofiles, os

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.document import DocumentCategory
from app.schemas.document import DocumentRead
from app.config import settings

router = APIRouter()


@router.get("/", response_model=list[DocumentRead])
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    deal_id: Optional[int] = Query(None),
    category: Optional[DocumentCategory] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app import crud
    return await crud.document.get_multi_filtered(db, skip=skip, limit=limit, deal_id=deal_id, category=category)


@router.post("/", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    category: DocumentCategory = Form(DocumentCategory.OTHER),
    deal_id: Optional[int] = Form(None),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file_id = str(uuid.uuid4())
    dest_dir = os.path.join(settings.UPLOAD_DIR, "documents")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{file_id}_{file.filename}")

    content = await file.read()
    async with aiofiles.open(dest, "wb") as f:
        await f.write(content)

    from app import crud
    return await crud.document.create(db, obj_in={
        "file_name": file.filename,
        "file_path": dest,
        "file_size": len(content),
        "mime_type": file.content_type or "application/octet-stream",
        "category": category,
        "deal_id": deal_id,
        "description": description,
        "uploaded_by_id": current_user.id,
    })


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app import crud
    await crud.document.remove(db, id=doc_id)
