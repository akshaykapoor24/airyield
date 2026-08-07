from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


# The base groups an airport can belong to. An airport may belong to several at
# once, so these are the options a multi-select offers; combinations such as
# "MEAI/SAARC" are produced by selecting more than one, not picked from a list.
CATEGORIZATION_GROUPS = [
    "APAC", "EUROPEAN NATIONS", "GCC/MIDDLE EAST", "LATIN AMERICA",
    "MEAI", "NAM", "OTHER", "SAARC",
]

# Kept for callers that still want the historical flat list of values seen in
# the data (base groups plus the combinations that were pre-baked as options).
CATEGORIZATIONS = [
    "APAC", "EUROPEAN NATIONS", "GCC/MIDDLE EAST", "LATIN AMERICA",
    "MEAI", "MEAI/APAC", "MEAI/SAARC", "MEAI/SAARC/APAC",
    "NAM", "OTHER", "SAARC", "SAARC/APAC",
]

CONTINENTS = [
    "Africa", "Asia", "Europe",
    "North America", "Oceania", "South America", "Antarctica",
]

# Longest first: "GCC/MIDDLE EAST" must win before a bare "GCC" prefix is tried.
_GROUPS_LONGEST_FIRST = sorted(CATEGORIZATION_GROUPS, key=len, reverse=True)
_CANONICAL_BY_KEY = {g.upper(): g for g in CATEGORIZATION_GROUPS}


def split_categorization(value: str | None) -> list[str]:
    """Split a stored categorization into the base groups it represents.

    Values are slash-joined — "MEAI/SAARC" means the airport is in both. One
    canonical name ("GCC/MIDDLE EAST") contains a slash itself, so splitting on
    "/" is wrong; we greedily match the longest known group at each position and
    fall back to taking the next slash-delimited token verbatim for anything
    unrecognised, so hand-entered data is never silently dropped.
    """
    if not value:
        return []
    text = value.strip()
    length = len(text)
    groups: list[str] = []
    seen: set[str] = set()
    pos = 0
    while pos < length:
        token = None
        for group in _GROUPS_LONGEST_FIRST:
            end = pos + len(group)
            if text[pos:end].upper() == group and (end == length or text[end] == "/"):
                token = group
                pos = end + 1
                break
        if token is None:
            nxt = text.find("/", pos)
            token = (text[pos:] if nxt < 0 else text[pos:nxt]).strip()
            pos = length if nxt < 0 else nxt + 1
        key = token.upper()
        if token and key not in seen:
            seen.add(key)
            groups.append(token)
    return groups


def join_categorization(groups) -> str | None:
    """Join base groups back into the slash-joined form stored in the column.

    Selection order is preserved so that reading a record and saving it again
    without touching the field produces the identical string — an update request
    should not show a spurious change just because the value was re-serialised.
    """
    if groups is None:
        return None
    if isinstance(groups, str):
        groups = split_categorization(groups)
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in groups:
        name = (raw or "").strip()
        if not name:
            continue
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(_CANONICAL_BY_KEY.get(key, name))
    return "/".join(ordered) or None


class Airport(Base):
    __tablename__ = "airports"

    id:               Mapped[int]      = mapped_column(primary_key=True)
    apt_id:           Mapped[str|None] = mapped_column(String(20),  unique=True, nullable=True)
    iata_code:        Mapped[str]      = mapped_column(String(3),   unique=True, nullable=False)
    country:          Mapped[str]      = mapped_column(String(100), nullable=False)
    # Slash-joined base groups (see split/join_categorization). Selecting every
    # group produces ~72 chars, so this must be wider than the old String(50).
    categorization:   Mapped[str|None] = mapped_column(String(255), nullable=True)
    continent:        Mapped[str|None] = mapped_column(String(50),  nullable=True)
    city_airport_name:Mapped[str]      = mapped_column(String(255), nullable=False)
    is_active:        Mapped[bool]     = mapped_column(Boolean, default=True)
    created_by_id:    Mapped[int|None] = mapped_column(
                          Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
                      )
    created_at:       Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
