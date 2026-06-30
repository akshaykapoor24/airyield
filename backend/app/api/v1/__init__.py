from fastapi import APIRouter

from app.api.v1 import auth, users, airlines, suppliers, airports, routes, deals, tickets, income, documents, reports, classes, approval_workflows, dashboard, customers, entities, login_ids, iata_commissions

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Auth"])
router.include_router(users.router, prefix="/users", tags=["Users"])
router.include_router(airlines.router, prefix="/airlines", tags=["Airlines"])
router.include_router(suppliers.router, prefix="/suppliers", tags=["Suppliers"])
router.include_router(airports.router, prefix="/airports", tags=["Airports"])
router.include_router(routes.router, prefix="/routes", tags=["Routes"])
router.include_router(deals.router, prefix="/deals", tags=["Deals"])
router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
router.include_router(income.router, prefix="/income", tags=["Income"])
router.include_router(documents.router, prefix="/documents", tags=["Documents"])
router.include_router(reports.router, prefix="/reports", tags=["Reports"])
router.include_router(classes.router, prefix="/classes", tags=["Classes"])
router.include_router(approval_workflows.router, prefix="/approval-workflows", tags=["Approval Workflows"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
router.include_router(customers.router, prefix="/customers", tags=["Customers"])
router.include_router(entities.router, prefix="/entities", tags=["User Master - Entities"])
router.include_router(login_ids.router, prefix="/login-ids", tags=["User Master - Login IDs"])
router.include_router(iata_commissions.router, prefix="/iata-commissions", tags=["User Master - IATA Commission"])
