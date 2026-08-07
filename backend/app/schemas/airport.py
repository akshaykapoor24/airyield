from pydantic import BaseModel, Field, field_validator, computed_field
from typing import Optional, Union
from datetime import datetime

from app.models.airport import split_categorization, join_categorization


# An airport can sit in several country groups, so the client may send a list.
# It is normalised to the slash-joined string the column stores and the
# exclusion evaluator already understands.
CategorizationInput = Optional[Union[list[str], str]]


def _normalise_categorization(v):
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, str):
        return join_categorization(split_categorization(v))
    if isinstance(v, (list, tuple, set)):
        return join_categorization(list(v))
    return v


class _CategorizationGroupsMixin:
    """Exposes the parsed groups alongside the stored string.

    The frontend needs the list to hydrate its multi-select; every existing
    consumer (tables, diffs, exclusion rules) still reads `categorization`.
    """

    @computed_field
    @property
    def categorization_groups(self) -> list[str]:
        return split_categorization(self.categorization)


class AirportCreate(BaseModel):
    iata_code:         str
    country:           str
    categorization:    CategorizationInput = None
    continent:         Optional[str] = None
    city_airport_name: str
    request_type:      str = "new"
    target_id:         Optional[int] = None

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("categorization", mode="before")
    @classmethod
    def normalise_categorization(cls, v):
        return _normalise_categorization(v)


class AirportUpdate(BaseModel):
    country:           Optional[str] = None
    categorization:    CategorizationInput = None
    continent:         Optional[str] = None
    city_airport_name: Optional[str] = None
    is_active:         Optional[bool] = None

    @field_validator("categorization", mode="before")
    @classmethod
    def normalise_categorization(cls, v):
        return _normalise_categorization(v)


class AirportRead(_CategorizationGroupsMixin, BaseModel):
    id:               int
    apt_id:           Optional[str]
    iata_code:        str
    country:          str
    categorization:   Optional[str]
    continent:        Optional[str]
    city_airport_name:str
    is_active:        bool
    created_at:       datetime

    model_config = {"from_attributes": True}


# ── Approval schemas ───────────────────────────────────────────────────────

class AirportApprovalCreate(BaseModel):
    iata_code:         str
    country:           str
    categorization:    CategorizationInput = None
    continent:         Optional[str] = None
    city_airport_name: str

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("categorization", mode="before")
    @classmethod
    def normalise_categorization(cls, v):
        return _normalise_categorization(v)


class SubmitterInfo(BaseModel):
    id:        int
    full_name: str
    email:     str
    model_config = {"from_attributes": True}


class AirportApprovalRead(_CategorizationGroupsMixin, BaseModel):
    id:               int
    iata_code:        str
    country:          str
    categorization:   Optional[str]
    continent:        Optional[str]
    city_airport_name:str
    status:           str
    submitted_by:     SubmitterInfo
    submitted_at:     datetime
    reviewed_at:      Optional[datetime]
    rejection_reason: Optional[str]
    request_type:     str = "new"
    target_id:        Optional[int] = Field(default=None, validation_alias="target_airport_id")

    # ── platform-admin edit state ──────────────────────────────────────────
    original_payload: Optional[dict] = None
    edited_by:        Optional[SubmitterInfo] = None
    edited_at:        Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @computed_field
    @property
    def edited(self) -> bool:
        """True only when an admin changed something the submitter should see."""
        return self.original_payload is not None

    @computed_field
    @property
    def original_categorization_groups(self) -> Optional[list[str]]:
        """Parsed groups of the submitter's original value, for the edit diff.

        The stored form is slash-joined and one canonical group name contains a
        slash ("GCC/MIDDLE EAST"), so the client cannot split it correctly on
        its own — parse it here rather than porting that logic to TypeScript.
        """
        if not self.original_payload:
            return None
        return split_categorization(self.original_payload.get("categorization"))


class AirportApprovalEdit(BaseModel):
    """What a platform admin may change on a pending airport request.

    Every field is optional so a caller can PATCH one value; exclude_unset in
    the endpoint is what separates "not sent" from "explicitly cleared". The
    length bounds the create schema omits are enforced here — the columns are
    String(3)/String(50), and an oversized value would otherwise surface as a
    psycopg 500 rather than a 422.
    """
    iata_code:         Optional[str] = Field(default=None, min_length=3, max_length=3)
    country:           Optional[str] = Field(default=None, max_length=100)
    categorization:    CategorizationInput = None
    continent:         Optional[str] = Field(default=None, max_length=50)
    city_airport_name: Optional[str] = Field(default=None, max_length=255)

    @field_validator("iata_code")
    @classmethod
    def iata_upper(cls, v: Optional[str]) -> Optional[str]:
        # Tolerates None, unlike AirportCreate's validator.
        return v.strip().upper() if v else v

    @field_validator("categorization", mode="before")
    @classmethod
    def normalise_categorization(cls, v):
        return _normalise_categorization(v)


class ApprovalAction(BaseModel):
    rejection_reason: Optional[str] = None


class BulkUploadResult(BaseModel):
    total:    int
    success:  int
    failed:   int
    errors:   list[str] = []
