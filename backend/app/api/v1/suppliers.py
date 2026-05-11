from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User, UserRole
from app.schemas.supplier import SupplierRead, SupplierCreate, SupplierUpdate

router = APIRouter()


@router.get("/", response_model=list[SupplierRead])
async def list_suppliers(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    from app import crud
    return await crud.supplier.get_multi(db, skip=skip, limit=limit)


@router.post("/", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS_USER))):
    from app import crud
    return await crud.supplier.create(db, obj_in=payload)


@router.get("/{supplier_id}", response_model=SupplierRead)
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    from app import crud
    obj = await crud.supplier.get(db, id=supplier_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return obj


@router.patch("/{supplier_id}", response_model=SupplierRead)
async def update_supplier(supplier_id: int, payload: SupplierUpdate, db: AsyncSession = Depends(get_db),
                          _: User = Depends(require_role(UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN, UserRole.OPERATIONS_USER))):
    from app import crud
    obj = await crud.supplier.get(db, id=supplier_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return await crud.supplier.update(db, db_obj=obj, obj_in=payload)
