from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.user import User, UserRole
from app.schemas.route import RouteRead, RouteCreate

router = APIRouter()


@router.get("/", response_model=list[RouteRead])
async def list_routes(skip: int = 0, limit: int = 200, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    from app import crud
    return await crud.route.get_multi(db, skip=skip, limit=limit)


@router.post("/", response_model=RouteRead, status_code=status.HTTP_201_CREATED)
async def create_route(payload: RouteCreate, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_role(UserRole.PLATFORM_ADMIN))):
    from app import crud
    return await crud.route.create(db, obj_in=payload)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: int, db: AsyncSession = Depends(get_db),
                       _: User = Depends(require_role(UserRole.PLATFORM_ADMIN))):
    from app import crud
    await crud.route.remove(db, id=route_id)
