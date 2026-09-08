from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.gst_configuration import (
    GST_BASES, GST_CATEGORIES, GST_SUB_CATEGORIES, SUB_CATEGORIES_BY_CATEGORY,
)


def _one_of(value: Optional[str], allowed: tuple[str, ...], label: str) -> Optional[str]:
    """Normalise a choice column to its canonical lowercase slug, or 422."""
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return v


class _GstConfigBase(BaseModel):
    """The business fields, shared by create and update.

    Percentages are Decimal rather than float so they compare cleanly against the
    Numeric columns — a float would make 9.0 differ from Decimal("9.000") and
    make every no-op save look like a change.
    """
    code:              Optional[str] = Field(default=None, max_length=10)
    name:              Optional[str] = Field(default=None, max_length=120)
    category:          Optional[str] = None
    sub_category:      Optional[str] = None
    basis:             Optional[str] = None
    taxable_value_pct: Optional[Decimal] = None
    cgst_pct:          Optional[Decimal] = None
    sgst_pct:          Optional[Decimal] = None
    igst_pct:          Optional[Decimal] = None
    sac_code:          Optional[str] = Field(default=None, max_length=20)
    valid_from:        Optional[date] = None
    valid_to:          Optional[date] = None
    notes:             Optional[str] = None
    is_active:         Optional[bool] = None

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        return _one_of(v, GST_CATEGORIES, "category")

    @field_validator("sub_category")
    @classmethod
    def _sub_category(cls, v):
        return _one_of(v, GST_SUB_CATEGORIES, "sub_category")

    @field_validator("basis")
    @classmethod
    def _basis(cls, v):
        return _one_of(v, GST_BASES, "basis")

    @field_validator("code", "name", "sac_code")
    @classmethod
    def _trim(cls, v):
        return (v.strip() or None) if v else None

    @field_validator("taxable_value_pct", "cgst_pct", "sgst_pct", "igst_pct", mode="before")
    @classmethod
    def _pct_via_str(cls, v):
        # Decimal(0.7) is 0.6999…; Decimal("0.7") is exact and equals the
        # Decimal("0.700") the Numeric column round-trips.
        return Decimal(str(v)) if isinstance(v, float) else v

    @field_validator("taxable_value_pct", "cgst_pct", "sgst_pct", "igst_pct")
    @classmethod
    def _pct_in_range(cls, v):
        # A negative rate is never a real tax, and anything past 100 is a typo
        # (a slipped decimal point) rather than a rate anyone meant to enter.
        if v is not None and not (Decimal(0) <= v <= Decimal(100)):
            raise ValueError("Percentages must be between 0 and 100.")
        return v


class GstConfigurationCreate(_GstConfigBase):
    """A new rule. The identity fields and the formula are all required here —
    only on update may they be omitted."""
    code:              str = Field(max_length=10)
    name:              str = Field(max_length=120)
    category:          str
    basis:             str
    taxable_value_pct: Decimal = Decimal(100)
    cgst_pct:          Decimal = Decimal(0)
    sgst_pct:          Decimal = Decimal(0)
    igst_pct:          Decimal = Decimal(0)
    is_active:         bool = True

    @model_validator(mode="after")
    def _sub_matches_category(self):
        """Both categories are subdivided, but along different axes.

        abatement → domestic | international (what the trip is)
        normal    → agency | reseller       (who the customer is)

        A model validator rather than a field one: a field_validator on
        `sub_category` does NOT run when the field is absent from the payload
        (it inherits a None default from _GstConfigBase), so POSTing an
        abatement row with no sub_category at all would slip past it. Creating a
        row needs BOTH halves checked together, present or not.
        """
        allowed = SUB_CATEGORIES_BY_CATEGORY.get(self.category)
        # A bad `category` already raised on its own field; say nothing more here.
        if allowed is None:
            return self
        if not self.sub_category:
            raise ValueError(
                f"sub_category is required for the '{self.category}' category "
                f"({' or '.join(allowed)})."
            )
        if self.sub_category not in allowed:
            raise ValueError(
                f"The '{self.category}' category takes a sub_category of "
                f"{' or '.join(allowed)}, not '{self.sub_category}'."
            )
        return self


class GstConfigurationUpdate(_GstConfigBase):
    """A partial edit. Every field optional; unset fields are left alone."""
    pass


class GstConfigurationRead(BaseModel):
    id: int
    code: str
    name: str
    category: str
    sub_category: Optional[str] = None
    basis: str
    taxable_value_pct: Decimal
    cgst_pct: Decimal
    sgst_pct: Decimal
    igst_pct: Decimal
    sac_code: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Rendered by services/gst_calc.formula_text and attached by the router, so
    # the screen, an export and the API all describe a row identically.
    formula: Optional[str] = None

    model_config = {"from_attributes": True}


# ── the preview calculator ─────────────────────────────────────────────────────

class GstPreviewRequest(BaseModel):
    """Sample amounts to run a rule against, for the screen's live preview.

    `interstate` is the place-of-supply decision: True bills IGST, False bills
    CGST + SGST. The two are mutually exclusive and the response proves it by
    returning both scenarios computed separately.
    """
    basic_fare:     Decimal = Decimal(0)
    taxes:          Decimal = Decimal(0)
    service_charge: Decimal = Decimal(0)

    @field_validator("basic_fare", "taxes", "service_charge", mode="before")
    @classmethod
    def _via_str(cls, v):
        return Decimal(str(v)) if isinstance(v, float) else v


class GstBreakdown(BaseModel):
    config_id: Optional[int] = None
    code: Optional[str] = None
    basis: str
    basis_amount: float
    taxable_value_pct: float
    taxable_value: float
    interstate: bool
    applied: str
    effective_gst_pct: float
    cgst: float
    sgst: float
    igst: float
    total_gst: float


class GstPreviewResponse(BaseModel):
    """Both place-of-supply scenarios, side by side.

    Deliberately NOT one blended figure: showing intra-state and inter-state as
    two separate results is what stops a reader from adding CGST + SGST + IGST
    into a single 36% tax.
    """
    formula: str
    intrastate: GstBreakdown
    interstate: GstBreakdown
