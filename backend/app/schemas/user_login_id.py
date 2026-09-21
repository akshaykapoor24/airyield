from pydantic import BaseModel
from typing import Optional


class UserLoginIdCreate(BaseModel):
    login_id: str
    # Required — a login ID / IATA number belongs to an entity and is located by it.
    # Typed Optional so a missing one gets a readable 400 from the handler, not a 422.
    entity_id: Optional[int] = None
    # The office's city when it differs from the entity's. Blank, or the same as the
    # entity's, is stored as NULL — "follows the entity".
    city: Optional[str] = None
    is_active: Optional[bool] = True


class UserLoginIdUpdate(BaseModel):
    login_id: Optional[str] = None
    entity_id: Optional[int] = None
    city: Optional[str] = None
    is_active: Optional[bool] = None


class UserLoginIdRead(BaseModel):
    id: int
    login_id: str
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    entity_code: Optional[str] = None
    # The login's STATE is always its entity's; there is no column of its own.
    entity_state: Optional[str] = None
    # `city` is the login's own override (NULL = none); `entity_city` is what it falls
    # back to. A screen shows `city ?? entity_city`.
    city: Optional[str] = None
    entity_city: Optional[str] = None
    is_active: bool

    model_config = {"from_attributes": True}


class BulkUploadResult(BaseModel):
    total: int
    success: int
    failed: int
    errors: list[str]
