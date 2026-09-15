"""Which source fields a generated report may contain.

A report is a file that leaves the application — it gets emailed, dropped in shared drives
and opened on laptops — so personal data is opt-in and card data is never exported:

  NEVER   card data (TGQ ``FOP_Details`` / ``CC_Auth`` / ``CC_DOExpiry`` and any card number
          or CVV a mapped file might carry). Refused even when the user ticks "include
          passenger contact details".
  GATED   identity and contact data — PAN, passport, mobile, phone, e-mail, address, date of
          birth, lodged-account numbers. Exported only with ``include_pii``.
  ALLOWED_SENSITIVE
          names that merely LOOK sensitive — GSTIN / GST amounts (a tax identity, not a
          person), the card SCHEME (Visa, not a number), GDS PCCs. Listed explicitly so a
          new field is never let through by accident.

Anything else that matches ``SENSITIVE_RE`` but is in none of the lists fails CLOSED (gated):
a supplier export that grows a "Passenger Mobile 2" column must not leak just because
nobody updated this file. ``tests/test_report_download_pii.py`` walks every spec field and
alias so the lists stay complete.

Matching is on tokens of the original key as well as on the squashed key, so ``pcc`` or
``gst_company_name`` are not mistaken for ``cc`` / ``pan``.
"""
from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def norm_key(k: str) -> str:
    """``"Passport No."`` → ``"passportno"``; ``"cc_doexpiry"`` → ``"ccdoexpiry"``."""
    return _NON_ALNUM.sub("", str(k or "").lower())


NEVER: frozenset[str] = frozenset({
    "fopdetails", "ccauth", "ccdoexpiry", "cardnumber", "creditcardnumber", "ccnumber",
    "cardno", "ccno", "cvv", "cvc", "cardexpiry", "cardexpirydate", "ccexpiry",
})
# Substrings that make a key NEVER regardless of prefix/suffix ("pax_card_number_2").
_NEVER_SUBSTR: tuple[str, ...] = ("fopdetail", "cardnumber", "creditcard", "ccauth", "ccdoexpiry", "cvv", "cvc")

GATED: frozenset[str] = frozenset({
    # identity documents
    "pan", "panno", "pannumber", "guardianpan", "passportno", "passportnumber",
    "passportissuedate", "passportexpirydate", "passportexpdate", "dob", "dateofbirth",
    "aadhaar", "aadhar",
    # contact
    "mobile", "mobilenumber", "mobileno", "phone", "phonenumber", "contactnumber", "homephone",
    "email", "emailaddress", "gstemail", "businessphonenumber", "businessemailaddress",
    "contactname", "contactemail", "contactphone", "entityaddressline1", "address",
    # lodged corporate account (CTA/BTA) numbers behave like card numbers
    "accountnumber",
})

ALLOWED_SENSITIVE: frozenset[str] = frozenset({
    "gstn", "gstin", "gstnumber", "gstcompanyname", "cliententityname",
    "cgstamount", "cgstrate", "sgstamount", "sgstrate", "igstamount", "igstrate",
    "totalgst", "gstonsf", "gstonservicefee", "ersgstinvoicenumber", "gstamount",
    "cardscheme", "pcc", "bookingpcc", "accountname", "accounttype", "accounttransactionid",
    "fop", "formofpayment", "formsofpayment",
})

# Tokens (of the lower-cased original key split on non-alphanumerics) and squashed substrings
# that make an unknown key sensitive.
_SENSITIVE_TOKENS: frozenset[str] = frozenset({"pan", "cc", "card", "cvv", "cvc", "dob"})
SENSITIVE_RE = re.compile(
    r"passport|mobile|phone|email|address|aadhaa?r|dateofbirth|cardnumber|creditcard|fopdetail",
)


def is_sensitive(key: str) -> bool:
    """True when a key looks like personal or card data, whatever list it is (or isn't) in."""
    tokens = [t for t in _NON_ALNUM.split(str(key or "").lower()) if t]
    if any(t in _SENSITIVE_TOKENS for t in tokens):
        return True
    return bool(SENSITIVE_RE.search(norm_key(key)))


def is_never(key: str) -> bool:
    nk = norm_key(key)
    return nk in NEVER or any(s in nk for s in _NEVER_SUBSTR)


def allowed(key: str, include_pii: bool) -> bool:
    """May this field appear in the workbook?"""
    if is_never(key):
        return False
    nk = norm_key(key)
    if nk in ALLOWED_SENSITIVE:
        return True
    if nk in GATED:
        return include_pii
    if is_sensitive(key):
        return include_pii          # fail closed for an unlisted look-alike
    return True
