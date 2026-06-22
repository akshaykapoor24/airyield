import enum
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, Integer, SmallInteger, String, Text, Date, DateTime,
    Boolean, Numeric, ForeignKey, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# ── Enums ────────────────────────────────────────────────────────────────────

class DealSourceType(str, enum.Enum):
    MANUAL = "manual"
    UPLOAD = "upload"


class DealKind(str, enum.Enum):
    AIRLINE = "airline"
    B2B = "b2b"


class DealTagType(str, enum.Enum):
    STANDARD = "standard"
    ADHOC = "adhoc"


class DealCategoryType(str, enum.Enum):
    ENTERPRISE = "enterprise"
    PROPRIETARY = "proprietary"


class DealStatusType(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class DealLifecycleType(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class SlabTypeEnum(str, enum.Enum):
    AMOUNT = "amount"
    SEGMENT = "segment"
    SI = "si"


class SlabValueTypeEnum(str, enum.Enum):
    NUMBER = "number"
    PERCENTAGE = "percentage"


class RuleOperatorEnum(str, enum.Enum):
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"
    EQUALS = "equals"
    STARTS_WITH = "starts_with"


def _vals(e):
    return [m.value for m in e]


# ── Models ───────────────────────────────────────────────────────────────────

class DealStatement(Base):
    """
    One statement = one upload session (PDF/Excel/etc.) or one manual form submit.
    Groups all deals created from the same document or form action.
    """
    __tablename__ = "deal_statements"

    id            : Mapped[int]              = mapped_column(BigInteger, primary_key=True)
    tenant_id     : Mapped[int]              = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type   : Mapped[DealSourceType]   = mapped_column(SAEnum(DealSourceType, native_enum=False, values_callable=_vals), default=DealSourceType.MANUAL)
    deal_type     : Mapped[DealKind]         = mapped_column(SAEnum(DealKind, native_enum=False, values_callable=_vals), default=DealKind.AIRLINE)
    deal_tag      : Mapped[DealTagType]      = mapped_column(SAEnum(DealTagType, native_enum=False, values_callable=_vals), default=DealTagType.STANDARD)
    deal_category : Mapped[DealCategoryType] = mapped_column(SAEnum(DealCategoryType, native_enum=False, values_callable=_vals), default=DealCategoryType.ENTERPRISE)

    # File metadata (NULL for manual source_type)
    file_name  : Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type  : Mapped[str | None] = mapped_column(String(20), nullable=True)   # pdf / excel / word / image / manual
    file_url   : Mapped[str | None] = mapped_column(String(1000), nullable=True)  # GCS path

    # UUID string that groups multiple deals from one upload session
    batch_id   : Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # AI extraction metadata (NULL for manual)
    ai_confidence : Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)  # 0.0000–1.0000
    column_map    : Mapped[dict | None]  = mapped_column(JSONB, nullable=True)           # {our_col: doc_col}

    # B2B batch supplier
    supplier_name : Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Migration audit trail — references the old table and PK this row was migrated from
    legacy_table : Mapped[str | None] = mapped_column(String(50), nullable=True)   # 'airline_deals'|'b2b_deals'|'legacy_deals'
    legacy_id    : Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    created_by_id : Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deals      : Mapped[list["Deal"]] = relationship("Deal", back_populates="statement", cascade="all, delete-orphan")
    created_by : Mapped["User"]       = relationship("User", foreign_keys=[created_by_id])  # noqa: F821


class Deal(Base):
    """
    Unified deal record — replaces airline_deals, b2b_deals, and legacy_deals.
    One row per contract (airline × class × flight-type variant), regardless of
    whether it was entered manually or uploaded from a file.
    """
    __tablename__ = "deals"

    id           : Mapped[int]       = mapped_column(BigInteger, primary_key=True)
    statement_id : Mapped[int]       = mapped_column(BigInteger, ForeignKey("deal_statements.id", ondelete="CASCADE"), nullable=False)
    tenant_id    : Mapped[int]       = mapped_column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    deal_type    : Mapped[DealKind]  = mapped_column(SAEnum(DealKind, native_enum=False, values_callable=_vals), default=DealKind.AIRLINE)

    # ── Shared header fields ─────────────────────────────────────────────────
    source_agent    : Mapped[str]      = mapped_column(String(255), nullable=False, server_default="manual")
    deal_maker_name : Mapped[str | None] = mapped_column(String(255), nullable=True)
    remark          : Mapped[str | None] = mapped_column(Text, nullable=True)
    airline_type    : Mapped[str | None] = mapped_column(String(20), nullable=True)   # GDS | LCC
    airline_name    : Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_from      : Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to        : Mapped[date | None] = mapped_column(Date, nullable=True)
    entity          : Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Airline-only fields ──────────────────────────────────────────────────
    contract_year : Mapped[str | None] = mapped_column(String(50), nullable=True)   # FY | CY
    trigger_type  : Mapped[str | None] = mapped_column(String(50), nullable=True)
    payout_type   : Mapped[str | None] = mapped_column(String(50), nullable=True)
    iata_number   : Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── B2B-only fields ──────────────────────────────────────────────────────
    supplier_name : Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── LCC fields (airline or B2B can be LCC) ───────────────────────────────
    business_type  : Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_lcc     : Mapped[str | None] = mapped_column(String(50), nullable=True)
    login_id       : Mapped[str | None] = mapped_column(String(100), nullable=True)
    variant        : Mapped[str | None] = mapped_column(String(100), nullable=True)
    eco_commission : Mapped[str | None] = mapped_column(String(50), nullable=True)
    peco_commission: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bus_commission : Mapped[str | None] = mapped_column(String(50), nullable=True)
    base_type      : Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_on       : Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Approval & lifecycle ─────────────────────────────────────────────────
    status                : Mapped[DealStatusType]   = mapped_column(SAEnum(DealStatusType, native_enum=False, values_callable=_vals), default=DealStatusType.PENDING_APPROVAL)
    deal_lifecycle_status : Mapped[DealLifecycleType] = mapped_column(SAEnum(DealLifecycleType, native_enum=False, values_callable=_vals), default=DealLifecycleType.DRAFT, server_default="draft")

    created_by_id : Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    statement  : Mapped["DealStatement"]          = relationship("DealStatement", back_populates="deals")
    incentives : Mapped[list["DealIncentiveConfig"]] = relationship(
        "DealIncentiveConfig", back_populates="deal",
        cascade="all, delete-orphan",
        order_by="DealIncentiveConfig.incentive_order",
    )
    created_by : Mapped["User"] = relationship("User", foreign_keys=[created_by_id])  # noqa: F821


class DealIncentiveConfig(Base):
    """
    One row per incentive type per deal. All structured fields are real columns —
    no JSON blobs for data that is queried or filtered.

    Ancillary sub-types and DI tranches are kept as JSONB because they are
    fixed-width or variable-length blobs never queried field-by-field.
    """
    __tablename__ = "deal_incentives"
    __table_args__ = (
        UniqueConstraint("deal_id", "incentive_type", name="uq_deal_incentives_deal_type"),
    )

    id             : Mapped[int] = mapped_column(BigInteger, primary_key=True)
    deal_id        : Mapped[int] = mapped_column(BigInteger, ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    incentive_type : Mapped[str] = mapped_column(String(100), nullable=False)
    # e.g. 'PLB', 'Super PLB', 'Transaction Fee', 'Frontend', 'Backend',
    #      'Push Action', 'Ancillary', 'Cashback', 'Marketing Fund',
    #      'Deposit Incentive', 'Segment Incentive'
    incentive_order : Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    # ── Common header (PLB / Super PLB / Transaction Fee / Frontend /
    #    Backend / Push Action / Marketing Fund) ──────────────────────────────
    contract_valid_from : Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_valid_to   : Mapped[date | None] = mapped_column(Date, nullable=True)
    frequency           : Mapped[str | None]  = mapped_column(String(50), nullable=True)   # Yearly | Quarterly | Half-Yearly
    flight_type         : Mapped[str | None]  = mapped_column(String(30), nullable=True)   # Both | Domestic | International
    class_              : Mapped[str | None]  = mapped_column("class", String(30), nullable=True)  # Economy | Premium | Business
    route_type          : Mapped[str | None]  = mapped_column(String(30), nullable=True)
    trigger_based       : Mapped[str | None]  = mapped_column(String(50), nullable=True)
    target_based        : Mapped[str | None]  = mapped_column(String(50), nullable=True)   # Fixed | Slab
    target_calc_cols    : Mapped[str | None]  = mapped_column(String(100), nullable=True)
    payout_calc_cols    : Mapped[str | None]  = mapped_column(String(100), nullable=True)

    # ── Fixed-path payout ────────────────────────────────────────────────────
    amount_based_type  : Mapped[str | None]   = mapped_column(String(50), nullable=True)
    base_target_amount : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    incentive_num_pct  : Mapped[str | None]   = mapped_column(String(50), nullable=True)  # Number | Percentage
    incentive_amt_pct  : Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    capped_incentive        : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    capped_incentive_amount : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # ── Marketing Fund extras ────────────────────────────────────────────────
    market_fund_type : Mapped[str | None]   = mapped_column(String(100), nullable=True)
    exchange_rate    : Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    # ── Cashback ─────────────────────────────────────────────────────────────
    cashback_period_from  : Mapped[date | None]  = mapped_column(Date, nullable=True)
    cashback_period_to    : Mapped[date | None]  = mapped_column(Date, nullable=True)
    cashback_target_type  : Mapped[str | None]   = mapped_column(String(100), nullable=True)
    cashback_target_value : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # ── Deposit Incentive (DI) ───────────────────────────────────────────────
    di_type           : Mapped[str | None] = mapped_column(String(20), nullable=True)   # Bulk | Normal
    di_currency       : Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Bulk → Single
    bulk_deposit_type   : Mapped[str | None]   = mapped_column(String(20), nullable=True)   # Single | Tranches
    bulk_single_num_pct : Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    bulk_single_amt     : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    bulk_single_capped  : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # Bulk → Tranches: [{from, to, num_pct, amt, capped}]  — variable-length array
    bulk_tranches : Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Normal → Bank Transfer
    normal_deposit_type   : Mapped[str | None]   = mapped_column(String(30), nullable=True)   # Bank Transfer | Credit Card
    bank_transfer_num_pct : Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    bank_transfer_amt     : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # Normal → Credit Card
    credit_card_type    : Mapped[str | None]   = mapped_column(String(50), nullable=True)
    bank_name           : Mapped[str | None]   = mapped_column(String(200), nullable=True)
    credit_card_num_pct : Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    credit_card_amt     : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # ── Ancillary (7 fixed sub-types, each: withType + numPct + amount) ──────
    # {"Baggage": {"withType": "With Baggage", "numPct": "Percentage", "amount": 200}, "Meals": {...}, ...}
    ancillary_items : Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    deal  : Mapped["Deal"]                    = relationship("Deal", back_populates="incentives")
    slabs : Mapped[list["DealIncentiveSlab"]]  = relationship(
        "DealIncentiveSlab", back_populates="incentive",
        cascade="all, delete-orphan",
        order_by="DealIncentiveSlab.slab_order",
    )
    rules : Mapped[list["DealRule"]] = relationship(
        "DealRule", back_populates="incentive",
        cascade="all, delete-orphan",
        order_by="DealRule.rule_order",
    )


class DealIncentiveSlab(Base):
    """
    One row per slab band. Covers amount-based slabs (PLB/Super PLB/Transaction Fee/
    Marketing Fund), segment slabs, and Segment Incentive (SI) slabs.
    Dynamic column values (e.g., domestic_economy, international_business) are stored
    in DealIncentiveSlabValue to avoid schema changes when new class/segment combos appear.
    """
    __tablename__ = "deal_incentive_slabs"

    id           : Mapped[int]          = mapped_column(BigInteger, primary_key=True)
    incentive_id : Mapped[int]          = mapped_column(BigInteger, ForeignKey("deal_incentives.id", ondelete="CASCADE"), nullable=False, index=True)
    slab_type    : Mapped[SlabTypeEnum] = mapped_column(SAEnum(SlabTypeEnum, native_enum=False, values_callable=_vals), nullable=False)
    slab_order   : Mapped[int]          = mapped_column(SmallInteger, nullable=False, default=0)

    # Frequency qualifiers (amount slabs)
    quarterly_freq    : Mapped[str | None] = mapped_column(String(20), nullable=True)  # Q1 | Q2 | Q3 | Q4
    half_yearly_freq  : Mapped[str | None] = mapped_column(String(20), nullable=True)  # H1 | H2

    # Amount-slab fields
    base_target_amt_num_pct : Mapped[str | None]   = mapped_column(String(50), nullable=True)  # Percentage | Amount
    base_target_amount      : Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # SI slab date range
    target_from : Mapped[date | None] = mapped_column(Date, nullable=True)
    target_to   : Mapped[date | None] = mapped_column(Date, nullable=True)

    # Segment / class qualifiers
    segment : Mapped[str | None] = mapped_column(String(30), nullable=True)  # Domestic | International | Both
    class_  : Mapped[str | None] = mapped_column("class", String(30), nullable=True)  # Economy | Premium | Business | All

    created_at : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incentive : Mapped["DealIncentiveConfig"]          = relationship("DealIncentiveConfig", back_populates="slabs")
    values    : Mapped[list["DealIncentiveSlabValue"]] = relationship(
        "DealIncentiveSlabValue", back_populates="slab",
        cascade="all, delete-orphan",
    )


class DealIncentiveSlabValue(Base):
    """
    One row per numeric column per slab. Handles the dynamic columns of Segment Incentive
    (e.g., domestic_economy, international_business, capped) without schema changes.
    """
    __tablename__ = "deal_incentive_slab_values"
    __table_args__ = (
        UniqueConstraint("slab_id", "value_key", name="uq_slab_value_key"),
    )

    id         : Mapped[int]               = mapped_column(BigInteger, primary_key=True)
    slab_id    : Mapped[int]               = mapped_column(BigInteger, ForeignKey("deal_incentive_slabs.id", ondelete="CASCADE"), nullable=False, index=True)
    value_key  : Mapped[str]               = mapped_column(String(100), nullable=False)   # e.g. 'domestic_economy', 'capped'
    value_type : Mapped[SlabValueTypeEnum] = mapped_column(SAEnum(SlabValueTypeEnum, native_enum=False, values_callable=_vals), default=SlabValueTypeEnum.NUMBER)
    value      : Mapped[float | None]      = mapped_column(Numeric(18, 4), nullable=True)

    slab : Mapped["DealIncentiveSlab"] = relationship("DealIncentiveSlab", back_populates="values")


class DealRule(Base):
    """
    Per-incentive-type inclusion/exclusion rule set.
    A deal with PLB + Transaction Fee gets SEPARATE rule sets for each incentive,
    unlike the legacy deal_incl_excl_rules which was deal-level (shared across all incentives).
    """
    __tablename__ = "deal_rules"

    id            : Mapped[int]      = mapped_column(BigInteger, primary_key=True)
    incentive_id  : Mapped[int]      = mapped_column(BigInteger, ForeignKey("deal_incentives.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_category : Mapped[str]      = mapped_column(String(60), nullable=False)
    # e.g. 'trigger_inclusion', 'trigger_exclusion', 'payout_inclusion', 'payout_exclusion'
    vice_versa    : Mapped[bool]     = mapped_column(Boolean, nullable=False, default=False)
    rule_order    : Mapped[int]      = mapped_column(SmallInteger, nullable=False, default=0)
    created_at    : Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incentive  : Mapped["DealIncentiveConfig"]       = relationship("DealIncentiveConfig", back_populates="rules")
    conditions : Mapped[list["DealRuleCondition"]]   = relationship(
        "DealRuleCondition", back_populates="rule",
        cascade="all, delete-orphan",
        order_by="DealRuleCondition.condition_order",
    )


class DealRuleCondition(Base):
    """
    Individual field condition within a rule. Field names map directly to the
    keys consumed by exclusion_evaluator.py so the evaluator needs no changes —
    call build_rule_dict(conditions) to convert rows to the flat dict it expects.
    """
    __tablename__ = "deal_rule_conditions"

    id              : Mapped[int]               = mapped_column(BigInteger, primary_key=True)
    rule_id         : Mapped[int]               = mapped_column(BigInteger, ForeignKey("deal_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    condition_field : Mapped[str]               = mapped_column(String(100), nullable=False)
    # e.g. 'continent', 'originAirport', 'destCountry', 'class', 'segment',
    #      'tourCode', 'fareTypeCategory', 'validFrom', 'validTo', 'dateExclusionTicket'
    operator        : Mapped[RuleOperatorEnum]  = mapped_column(SAEnum(RuleOperatorEnum, native_enum=False, values_callable=_vals), default=RuleOperatorEnum.IN)
    value_list      : Mapped[list | None]       = mapped_column(JSONB, nullable=True)    # for 'in' / 'not_in': ["Domestic", "India"]
    value_from      : Mapped[str | None]        = mapped_column(String(100), nullable=True)  # for 'between'
    value_to        : Mapped[str | None]        = mapped_column(String(100), nullable=True)  # for 'between'
    value_text      : Mapped[str | None]        = mapped_column(String(500), nullable=True)  # for 'equals' / 'starts_with'
    condition_order : Mapped[int]               = mapped_column(SmallInteger, nullable=False, default=0)

    rule : Mapped["DealRule"] = relationship("DealRule", back_populates="conditions")


# ── Helper for exclusion_evaluator.py compatibility ──────────────────────────

def build_rule_dict(conditions: list[DealRuleCondition]) -> dict:
    """
    Converts normalized DealRuleCondition rows to the flat dict shape that
    exclusion_evaluator.py expects — so the evaluator itself needs no changes.
    Call once per DealRule before passing to evaluate_exclusion_for_payout().
    """
    result: dict = {}
    for cond in conditions:
        if cond.operator in (RuleOperatorEnum.IN, RuleOperatorEnum.NOT_IN):
            result[cond.condition_field] = cond.value_list or []
        elif cond.operator == RuleOperatorEnum.BETWEEN:
            result[cond.condition_field + "From"] = cond.value_from
            result[cond.condition_field + "To"] = cond.value_to
        elif cond.operator in (RuleOperatorEnum.EQUALS, RuleOperatorEnum.STARTS_WITH):
            result[cond.condition_field] = cond.value_text
    return result
