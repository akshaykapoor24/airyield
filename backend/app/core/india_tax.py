"""Indian tax identifiers — PAN, GSTIN, and the state codes that tie them together.

ONE COPY, because these checks have to agree everywhere. PAN and GSTIN were being
re-declared in app/schemas/user.py and app/schemas/user_entity.py; both now import
from here. `frontend/src/lib/indiaTax.ts` is a deliberate mirror of this file, so a
form can reject a bad GSTIN before posting it and the API refuses the same value
for the same stated reason rather than a differently worded one.

WHAT A GSTIN ACTUALLY IS. Fifteen characters, and every part of it is checkable
against something else on the form:

    2 7 A A P F U 0 9 3 9 F 1 Z V
    ^^^ ^^^^^^^^^^^^^^^^^ ^ ^ ^
     |         |          | | └─ check digit — mod-36 over the first fourteen
     |         |          | └─── 'Z', fixed by the notification
     |         |          └───── which registration this is for that PAN in that state
     |         └──────────────── the holder's PAN, character for character
     └────────────────────────── state code — 27 is Maharashtra, 07 is Delhi

So a GSTIN is NOT an independent field. Given a state and a PAN, ten of its
fifteen characters are already determined, and a typo in any of them is
detectable without calling anyone. That is the whole reason the Add Agency form
asks for state and PAN first and only then offers the GSTIN box: by the time it
is typed, three of the four checks below already have something to compare with.

PAN HAS NO USABLE CHECK DIGIT. Its tenth character is one, but the algorithm has
never been published, so format plus the fourth-character holder type is the
honest limit — do not let anyone "fix" that by inventing a checksum for it.
"""
import re
from typing import Optional

# ── formats ────────────────────────────────────────────────────────────────
PAN_RE   = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")                            # 10 chars
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")   # 15 chars

# PAN's 4th character is the holder type. Deliberately the BROAD assigned set —
# a PAN wrongly refused blocks a user completely, while the letters left out
# (D, I, M, N, O, Q, R, S, U, V, W, X, Y, Z) are not issued at all, so this still
# catches a transposition without risking a false negative.
#   P individual · C company · H HUF · F firm/LLP · A AOP · T trust · B BOI
#   L local authority · J artificial juridical person · G government · E LLP · K trust
PAN_HOLDER_TYPES = set("ABCEFGHJKLPT")

# ── state codes ────────────────────────────────────────────────────────────
# The first two characters of a GSTIN. Current codes only — these are what the
# Add Agency state picker offers, so a state chosen here always has a code to
# check the GSTIN against.
GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

# Codes that were retired but still appear on registrations issued before the
# change — 25 (Daman and Diu) folded into 26 in 2020, and 28 was Andhra Pradesh
# before Telangana was carved out of it and new registrations moved to 37. A
# GSTIN carrying one of these is not wrong, it is old, so it is accepted for the
# state its code became rather than refused.
LEGACY_STATE_CODE_SUCCESSOR: dict[str, str] = {"25": "26", "28": "37"}

# Spellings people actually type or that arrive in a spreadsheet. Matching is
# already case- and punctuation-insensitive (see `_key`), so this only needs the
# genuinely different names.
STATE_ALIASES: dict[str, str] = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "uttaranchal": "Uttarakhand",
    "new delhi": "Delhi",
    "nct of delhi": "Delhi",
    "delhi ncr": "Delhi",
    "tamilnadu": "Tamil Nadu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "andaman and nicobar": "Andaman and Nicobar Islands",
    "jk": "Jammu and Kashmir",
}

# What the Add Agency form lists, and the only values it will accept.
STATE_NAMES: list[str] = sorted(GST_STATE_CODES.values())


def _key(value: Optional[str]) -> str:
    """'  Jammu & Kashmir ' -> 'jammu and kashmir'. Punctuation-blind on purpose."""
    text = (value or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


_STATE_BY_KEY: dict[str, str] = {_key(n): n for n in GST_STATE_CODES.values()}
_STATE_BY_KEY.update({_key(k): v for k, v in STATE_ALIASES.items()})
_CODE_BY_STATE: dict[str, str] = {name: code for code, name in GST_STATE_CODES.items()}


def canonical_state(value: Optional[str]) -> Optional[str]:
    """The name this state is filed under, or None if it is not one we know."""
    return _STATE_BY_KEY.get(_key(value))


def state_code(value: Optional[str]) -> Optional[str]:
    """'Maharashtra' -> '27'. None when the state is unrecognised."""
    name = canonical_state(value)
    return _CODE_BY_STATE.get(name) if name else None


def normalise(value: Optional[str]) -> Optional[str]:
    """'  27aapfu0939f1zv ' -> '27AAPFU0939F1ZV'; blank -> None."""
    return (value or "").strip().upper().replace(" ", "") or None


# ── check digit ────────────────────────────────────────────────────────────
_GST_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first_14: str) -> str:
    """The 15th character GSTN would have issued for these fourteen.

    Mod-36 with alternating weights 1 and 2, each weighted value folded as
    quotient + remainder over 36. Catches every single-character typo and most
    transpositions, which is exactly the mistake this form has to survive.
    """
    total = 0
    for i, ch in enumerate(first_14):
        weighted = _GST_ALPHABET.index(ch) * (2 if i % 2 else 1)
        total += weighted // 36 + weighted % 36
    return _GST_ALPHABET[(36 - total % 36) % 36]


# ── the four checks ────────────────────────────────────────────────────────
def pan_error(pan: Optional[str]) -> Optional[str]:
    """A readable problem with this PAN, or None. Blank is not a problem here —
    whether PAN is required is the caller's rule, not the format's."""
    if not pan:
        return None
    if not PAN_RE.match(pan):
        return f"Invalid PAN '{pan}' — expected 10 characters, e.g. AAPFU0939F."
    if pan[3] not in PAN_HOLDER_TYPES:
        return (
            f"Invalid PAN '{pan}' — the 4th character says who holds it "
            f"(P individual, C company, F firm, H HUF, T trust…), and '{pan[3]}' is not one of them."
        )
    return None


def gstin_error(
    gstin: Optional[str],
    *,
    pan: Optional[str] = None,
    state: Optional[str] = None,
) -> Optional[str]:
    """A readable problem with this GSTIN, or None.

    Checks it against itself (format, check digit) and against the rest of the
    form (state code, embedded PAN). `pan` and `state` are optional so a caller
    that genuinely has neither still gets the format and checksum checks.
    """
    if not gstin:
        return None
    if not GSTIN_RE.match(gstin):
        return f"Invalid GSTIN '{gstin}' — expected 15 characters, e.g. 27AAPFU0939F1ZV."

    code = gstin[:2]
    canonical_code = LEGACY_STATE_CODE_SUCCESSOR.get(code, code)
    if canonical_code not in GST_STATE_CODES:
        return f"Invalid GSTIN '{gstin}' — '{code}' is not an Indian state code."

    if state:
        want = state_code(state)
        if want is None:
            return f"'{state}' is not a state we can check a GSTIN against — pick one from the list."
        if canonical_code != want:
            return (
                f"GSTIN starts with '{code}' ({GST_STATE_CODES[canonical_code]}) but the state is "
                f"{canonical_state(state)}, whose code is '{want}'. Fix whichever is wrong."
            )

    if pan and gstin[2:12] != pan:
        return (
            f"GSTIN carries PAN '{gstin[2:12]}' but the PAN field says '{pan}'. "
            "A GSTIN is issued against one PAN — characters 3 to 12 must match it exactly."
        )

    expected = gstin_check_digit(gstin[:14])
    if gstin[14] != expected:
        return (
            f"Invalid GSTIN '{gstin}' — the last character is a check digit and should be "
            f"'{expected}', not '{gstin[14]}'. Something earlier in it is mistyped."
        )
    return None


def tax_id_error(
    gst: Optional[str],
    pan: Optional[str],
    state: Optional[str] = None,
) -> Optional[str]:
    """First problem across both ids, or None if they are fine together.

    Deliberately NOT a pydantic validator: bulk create needs to attribute a bad
    value to one row and still save the others, which a schema-level raise makes
    impossible (pydantic rejects the whole list before the handler runs).
    PAN is checked first — a bad PAN makes the GSTIN's PAN check meaningless.
    """
    return pan_error(pan) or gstin_error(gst, pan=pan, state=state)
