"""
IncomeCalculatorService — applies deal commercial terms to a ticket
and produces an IncomeRecord.
"""
from decimal import Decimal
from app.models.ticket import Ticket
from app.models.uploaded_deal import UploadedDeal


class IncomeCalculatorService:
    @staticmethod
    def _parse_percent(value: str | None) -> Decimal:
        if not value:
            return Decimal("0")
        cleaned = str(value).replace("%", "").strip()
        try:
            return Decimal(cleaned)
        except Exception:
            return Decimal("0")

    @staticmethod
    def calculate(ticket: Ticket, deal: UploadedDeal) -> dict:
        base = Decimal(str(ticket.base_fare))

        commission_pct = IncomeCalculatorService._parse_percent(deal.eco_commission)
        override_pct = Decimal("0")
        incentive = Decimal("0")

        commission_amount = (base * commission_pct / 100).quantize(Decimal("0.01"))
        override_amount = (base * override_pct / 100).quantize(Decimal("0.01"))
        total_income = (commission_amount + override_amount + incentive).quantize(Decimal("0.01"))

        return {
            "ticket_id": ticket.id,
            "deal_id": deal.id,
            "base_fare": float(base),
            "commission_amount": float(commission_amount),
            "override_amount": float(override_amount),
            "incentive_amount": float(incentive),
            "total_income": float(total_income),
            "currency": ticket.currency,
        }
