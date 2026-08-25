from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.airline import Airline
from app.models.airline_approval import AirlineApproval
from app.models.supplier import Supplier
from app.models.supplier_approval import SupplierApproval
from app.models.airport import Airport
from app.models.airport_approval import AirportApproval
from app.models.route import Route
from app.models.approval_workflow import (
    ApprovalWorkflow,
    ApprovalWorkflowStep,
    ApprovalWorkflowStepApprover,
    DealApproval,
    DealApprovalStep,
    WorkflowModule,
    ApprovalActionStatus,
)
from app.models.ticket import Ticket, BookingClass
from app.models.income import IncomeRecord
from app.models.document import Document
from app.models.airline_class_master import AirlineClassMaster
from app.models.class_approval import ClassApproval
from app.models.customer import Customer
from app.models.corporate import Corporate
from app.models.series_contract import SeriesContract
from app.models.billing import Billing
from app.models.uploaded_ticket import UploadedTicket
from app.models.ticket_statement import TicketStatement
from app.models.customer_statement import CustomerStatement, CustomerStatementTicket
from app.models.income_summary import IncomeSummary
from app.models.ticket_calculation import TicketCalculation
from app.models.ticket_adjustment import TicketAdjustment
from app.models.airline_adjustment import AirlineADM, AirlineACM, AirlineRA, ADJUSTMENT_MODELS
from app.models.statement_row import (
    TgqHmpr, Ndc, LccDi, LccDividedPnr, LccFlownReport, LccCtaBta,
    ThirdPartyGds, ThirdPartyLcc, STATEMENT_MODELS,
)
from app.models.lcc_detailed import LccDetailed, LccDetailedBatch
from app.models.bsp_statement import BspStatement, BspStatementRow, BspTaxBreakup, BspParseError
from app.models.bsp_summary import BspSummaryStatement, BspSummaryRow
from app.models.ticket_reconciliation import TicketReconciliation
from app.models.deal_batch import DealBatch
from app.models.agency import Agency
from app.models.agency_entity import AgencyEntity
from app.models.agency_login_id import AgencyLoginId
from app.models.agency_terms import AgencyTerms
from app.models.agency_ledger import AgencyLedger
# Per-user profile data (My Profile → Entities / Login IDs) and the grants that
# share an admin's entities with the team members they add.
from app.models.user_entity import UserEntity
from app.models.user_login_id import UserLoginId
from app.models.user_entity_access import UserEntityAccess
# Tenant-level masters. These were missing here, which mattered more than it
# looks: alembic/env.py builds `target_metadata` from `from app.models import *`,
# so with these three absent an `alembic revision --autogenerate` saw live tables
# with no model behind them and proposed DROP TABLE for all three.
from app.models.entity import Entity
from app.models.login_id import LoginId
from app.models.iata_commission import IataCommission
from app.models.iata_commission_approval import IataCommissionApproval
from app.models.deal import (
    DealStatement,
    Deal,
    DealIncentiveConfig,
    DealIncentiveSlab,
    DealIncentiveSlabValue,
    DealRule,
    DealRuleCondition,
    DealSourceType,
    DealKind,
    DealTagType,
    DealCategoryType,
    DealStatusType,
    DealLifecycleType,
    SlabTypeEnum,
    SlabValueTypeEnum,
    RuleOperatorEnum,
    build_rule_dict,
)

__all__ = [
    "Tenant",
    "User", "UserRole",
    "UserEntity", "UserLoginId", "UserEntityAccess",
    "Airline", "AirlineApproval",
    "Supplier", "SupplierApproval",
    "Airport", "AirportApproval",
    "Route",
    "ApprovalWorkflow", "ApprovalWorkflowStep", "ApprovalWorkflowStepApprover", "DealApproval", "DealApprovalStep",
    "WorkflowModule", "ApprovalActionStatus",
    "Ticket", "BookingClass",
    "IncomeRecord",
    "Document",
    "AirlineClassMaster", "ClassApproval",
    "Customer",
    "Corporate",
    "SeriesContract",
    "Billing",
    "UploadedTicket",
    "TicketStatement",
    "CustomerStatement", "CustomerStatementTicket",
    "IncomeSummary",
    "TicketCalculation",
    "TicketAdjustment",
    "AirlineADM", "AirlineACM", "AirlineRA", "ADJUSTMENT_MODELS",
    "TgqHmpr", "Ndc", "LccDi", "LccDividedPnr", "LccFlownReport", "LccCtaBta",
    "ThirdPartyGds", "ThirdPartyLcc", "STATEMENT_MODELS",
    "LccDetailed", "LccDetailedBatch",
    "BspStatement", "BspStatementRow", "BspTaxBreakup", "BspParseError",
    "BspSummaryStatement", "BspSummaryRow",
    "TicketReconciliation",
    "DealBatch",
    "Agency", "AgencyEntity", "AgencyLoginId", "AgencyTerms", "AgencyLedger",
    "Entity", "LoginId", "IataCommission", "IataCommissionApproval",
    # New unified deal schema
    "DealStatement", "Deal",
    "DealIncentiveConfig", "DealIncentiveSlab", "DealIncentiveSlabValue",
    "DealRule", "DealRuleCondition",
    "DealSourceType", "DealKind", "DealTagType", "DealCategoryType",
    "DealStatusType", "DealLifecycleType",
    "SlabTypeEnum", "SlabValueTypeEnum", "RuleOperatorEnum",
    "build_rule_dict",
]
