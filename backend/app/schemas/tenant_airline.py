from typing import Optional

from pydantic import BaseModel, Field


class TenantAirlineCreate(BaseModel):
    airline_id: int
    ref_id: str = Field(min_length=1, max_length=100)
    is_active: Optional[bool] = True


class TenantAirlineUpdate(BaseModel):
    # Changing airline_id re-snapshots name/code/numeric/contract year from the master.
    airline_id: Optional[int] = None
    ref_id: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class TenantAirlineRead(BaseModel):
    id: int
    airline_id: int
    ref_id: str
    airline_name: Optional[str] = None
    airline_code: Optional[str] = None
    iata_numeric_code: Optional[str] = None
    contract_year: Optional[str] = None
    is_active: bool
    # The master's current name, when it has drifted from the snapshot taken at add time.
    live_airline_name: Optional[str] = None

    model_config = {"from_attributes": True}
