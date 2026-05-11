from pydantic import BaseModel
from typing import Optional
from app.schemas.airport import AirportRead


class RouteCreate(BaseModel):
    origin_id: int
    destination_id: int
    airline_id: Optional[int] = None


class RouteRead(BaseModel):
    id: int
    origin_id: int
    destination_id: int
    airline_id: Optional[int]
    origin: Optional[AirportRead] = None
    destination: Optional[AirportRead] = None

    model_config = {"from_attributes": True}
