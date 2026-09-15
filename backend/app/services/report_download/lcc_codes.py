"""LCC Detailed charge codes → tax / ancillary / penalty / fee.

``lcc_detailed.taxes`` holds every named charge an LCC export prints as ``[{code, amount}]``,
and ``taxes_total`` sums ALL of them (services/lcc_detailed_spec.py) — seats, baggage and
meals included. Reporting that as "Total Taxes" would overstate tax and hide the ancillary
revenue, so the report classifies each code:

  tax        statutory: GST / IGT / SG (Indian GST), UDF / PSF / ASF airport charges (+ refund
             variants), and the foreign government codes an international LCC ticket carries.
             YQ / YR / K3 are accepted too, although the standard template has no such code.
  ancillary  SSR products: seat, baggage (XBP*), infant, meals, insurance, fast-forward …
  penalty    cancellation / change charges (CNX, CXL, SXL, CHG)
  fee        convenience, booking, payment-handling and service fees
  unclassified
             codes whose meaning is not established from a real sample (NMV, NXT, OVG, XXPN).
             They are flagged LCC_CODE_UNCLASSIFIED and shown in Other Taxes & Fees rather
             than silently guessed.

Every entry of ``lcc_detailed_spec._TAX_CODES`` must appear here —
``tests/test_report_download_lcc_codes.py`` fails the day a new code is added unclassified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Optional

CodeClass = Literal["tax", "ancillary", "penalty", "fee", "unclassified"]

TAX: frozenset[str] = frozenset({
    "GST", "IGT", "SG", "UDF", "UDFR", "PSF", "PSFR", "ASF", "YQ", "YR", "K3",
    "AE", "BD", "BQ", "C4", "D5", "E3", "E5", "E7", "F6", "G1", "G4", "G8", "GZ", "H8", "H9",
    "I2", "IO", "JC", "KW", "L7", "LK", "M6", "MY", "N4", "NP", "NQ", "OM", "OP", "OW", "P7",
    "P8", "PZ", "QA", "R9", "S6", "T2", "T6", "TP", "TR", "TS", "UT", "YX", "ZR",
})
ANCILLARY: frozenset[str] = frozenset({
    "SEAT", "XBPA", "XBPB", "INFT", "JNML", "LCML", "VGAN", "CPML", "PROT", "FFWD", "UPMA",
    "VBIR", "ABHF", "AGSW", "CJSW", "NUSW", "PTSW", "VCSW", "FRCK",
})
PENALTY: frozenset[str] = frozenset({"CNX", "CXL", "SXL", "CHG"})
FEE: frozenset[str] = frozenset({"CCF", "CFB", "BKF", "RCF", "TF", "FEE", "COS", "PHF", "RAF"})
UNCLASSIFIED: frozenset[str] = frozenset({"NMV", "NXT", "OVG", "XXPN"})

# The order the detail sheet lays the pivot columns out in.
CLASS_ORDER: tuple[CodeClass, ...] = ("tax", "ancillary", "penalty", "fee", "unclassified")


def classify(code: Optional[str]) -> CodeClass:
    c = (code or "").strip().upper()
    if c in TAX:
        return "tax"
    if c in ANCILLARY:
        return "ancillary"
    if c in PENALTY:
        return "penalty"
    if c in FEE:
        return "fee"
    return "unclassified"


def sort_codes(codes) -> list[str]:
    """Pivot-column order: by class (CLASS_ORDER), then alphabetically."""
    uniq = {(c or "").strip().upper() for c in codes if (c or "").strip()}
    return sorted(uniq, key=lambda c: (CLASS_ORDER.index(classify(c)), c))


def _amount(v) -> Optional[Decimal]:
    """The report's one money parser, so ``₹ 1,234`` / ``(50)`` read the same as everywhere else."""
    if isinstance(v, bool):
        return None
    from app.services.report_download.normalize import parse_money
    return parse_money(v)


@dataclass(frozen=True)
class LccCodeSums:
    tax_total: Optional[Decimal] = None
    ancillary: Optional[Decimal] = None
    penalty: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    unclassified: Optional[Decimal] = None
    by_code: dict[str, Decimal] = field(default_factory=dict)
    unclassified_codes: tuple[str, ...] = ()
    # Codes printed with an amount that could not be read (left out of every sum).
    unreadable_codes: tuple[str, ...] = ()

    @property
    def has_codes(self) -> bool:
        return bool(self.by_code)

    def code(self, c: str) -> Optional[Decimal]:
        return self.by_code.get((c or "").strip().upper())


def sums(taxes_json) -> LccCodeSums:
    """Sum ``[{code, amount}]`` by code and by class. JSON null / non-list → empty sums.

    A class with no code present stays None (blank), so "no seat charge" is distinguishable
    from "seat charge of 0".
    """
    if not isinstance(taxes_json, list):
        return LccCodeSums()
    by_code: dict[str, Decimal] = {}
    unreadable: list[str] = []
    for item in taxes_json:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        raw = item.get("amount")
        amt = _amount(raw)
        if not code:
            continue
        if amt is None:
            if raw is not None and str(raw).strip():
                unreadable.append(code)
            continue
        by_code[code] = by_code.get(code, Decimal("0")) + amt

    totals: dict[str, Optional[Decimal]] = {k: None for k in CLASS_ORDER}
    unclassified_codes: list[str] = []
    for code, amt in by_code.items():
        cls = classify(code)
        totals[cls] = (totals[cls] or Decimal("0")) + amt
        if cls == "unclassified":
            unclassified_codes.append(code)

    return LccCodeSums(
        tax_total=totals["tax"], ancillary=totals["ancillary"], penalty=totals["penalty"],
        fee=totals["fee"], unclassified=totals["unclassified"], by_code=by_code,
        unclassified_codes=tuple(sorted(unclassified_codes)),
        unreadable_codes=tuple(sorted(set(unreadable))),
    )
