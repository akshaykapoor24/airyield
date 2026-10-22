"""`data` for a statement table whose fields are real columns rather than a JSONB blob.

Most spec-driven statement tables keep a line's fields in one JSONB `data` column keyed by
the spec's field names, and about fifteen readers — the statements router, commission,
the income board, payment reconciliation, the report download, ticket search — read them
as `row.data["net_amount"]` in Python or `model.data["net_amount"].astext` in SQL. A table
that stores each field in its own typed column (`third_party_gds`, first) mixes in
`TypedData` and keeps that interface without storing any JSON:

  * in Python, `row.data` is a dict BUILT from the columns on every read, and assigning a
    dict to it writes each key into its column — `ThirdPartyGds(data={...})` at upload and
    `obj.data = data` on a cell edit both go through it;
  * in SQL, `Model.data` is a `jsonb_build_object(...)` over the columns, so
    `Model.data["net_amount"].astext` keeps meaning what it meant;
  * raw `text()` SQL, which names a table rather than a model, selects FROM
    `sql_relation(Model)` — the table plus that same expression as a `data` column.

THE VALUES COME BACK AS STRINGS, exactly as the JSONB held them: an ISO date, an amount
as its plain digits ("-104166.9572", "99090.00"), a count as "1". Every reader was
written against that shape — `to_decimal(data.get(...))`, a regex-guarded cast in SQL —
and an absent key still means "no value", because NULL columns are left out of the dict
and stripped from the JSONB.

A VALUE THAT DOES NOT FIT ITS COLUMN IS NOT KEPT. "LESS PAYMENT" in an amount column, or
a date the parser could not read, stores as NULL and its field name is listed in
`unparsed_fields`, so the gap is on the record rather than silent. The uploaded file
itself (`file_url`) is where the original cell can still be read.

AN UNKNOWN KEY IS REFUSED, not dropped. A field with no column would otherwise vanish on
write, and a missing column is a schema change to make on purpose.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import NamedTuple

from sqlalchemy import Date, Integer, Numeric, Text, cast, func, literal_column, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property

# The `data` key that lists the fields whose value could not be stored as its column's type.
UNPARSED_KEY = "unparsed_fields"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d*\.?\d+$")
# jsonb_build_object takes at most 100 arguments: 50 key/value pairs per call.
_PAIRS_PER_CALL = 50


class DataField(NamedTuple):
    key: str    # the `data` key — the spec's field name
    attr: str   # the mapped attribute / column holding it
    kind: str   # text | date | number | int


def _kind(column) -> str:
    t = column.type
    if isinstance(t, Date):
        return "date"
    if isinstance(t, Numeric):
        return "number"
    if isinstance(t, Integer):
        return "int"
    return "text"


def _coerce(value, kind: str):
    """(stored value, fitted). Blank is a fit — it stores as NULL and is simply absent."""
    if value is None:
        return None, True
    if kind == "text":
        s = str(value)
        return (s if s.strip() else None), True
    if kind == "date" and isinstance(value, date):
        return value, True
    s = str(value).strip().replace(",", "")
    if not s:
        return None, True
    if kind == "date":
        if _ISO_DATE.match(s):
            try:
                return date.fromisoformat(s[:10]), True
            except ValueError:
                pass
        return None, False
    if not _PLAIN_NUMBER.match(s):
        return None, False
    n = Decimal(s)
    if kind == "int":
        return (int(n), True) if n == n.to_integral_value() else (None, False)
    return n, True


def _as_text(value, kind: str) -> str:
    """A stored value as the string the JSONB used to hold — and as Postgres prints it."""
    if kind == "date":
        return value.isoformat()
    if kind == "number":
        return format(value, "f")
    return str(value)


class TypedData:
    """Mixin: a `data` interface over typed columns. See the module docstring.

    The class declares `DATA_EXCLUDE` (mapped columns that are NOT `data` fields — ids and
    provenance) and may declare `DATA_KEYS` ({attr: key}) for the few columns whose
    attribute name differs from the key, e.g. `total_tax` holding `taxes`.
    """

    DATA_EXCLUDE: frozenset[str] = frozenset()
    DATA_KEYS: dict[str, str] = {}

    @classmethod
    def data_fields(cls) -> tuple[DataField, ...]:
        return _fields_of(cls)

    def _data_get(self) -> dict:
        out = {}
        for f in self.data_fields():
            v = getattr(self, f.attr)
            if v is not None:
                out[f.key] = _as_text(v, f.kind)
        return out

    def _data_set(self, value: dict | None) -> None:
        value = dict(value or {})
        fields = self.data_fields()
        known = {f.key for f in fields}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError(
                f"{type(self).__tablename__} has no column for {', '.join(unknown)}. Add one "
                f"(and a migration) rather than letting the value go unstored.")
        # Still unparsed: listed before AND still blank — a cell edited to a good value drops out.
        carried = {k for k in str(value.get(UNPARSED_KEY) or "").split(",")
                   if k in known and value.get(k) is None}
        failed: set[str] = set()
        for f in fields:
            if f.key == UNPARSED_KEY:
                continue
            stored, fits = _coerce(value.get(f.key), f.kind)
            if not fits:
                failed.add(f.key)
            setattr(self, f.attr, stored)
        unparsed = sorted(failed | carried)
        setattr(self, _attr_for(type(self), UNPARSED_KEY), ",".join(unparsed) or None)

    @classmethod
    def _data_sql(cls):
        pairs = []
        for f in cls.data_fields():
            # Keys inlined, not bound: a bound key renders as a different parameter in
            # SELECT and GROUP BY, which Postgres then refuses to treat as one expression.
            pairs.append((literal_column(f"'{f.key}'"), cast(getattr(cls, f.attr), Text)))
        calls = [
            func.jsonb_build_object(*[x for p in pairs[i:i + _PAIRS_PER_CALL] for x in p], type_=JSONB)
            for i in range(0, len(pairs), _PAIRS_PER_CALL)
        ]
        expr = calls[0]
        for c in calls[1:]:
            expr = expr.op("||", return_type=JSONB)(c)
        return func.jsonb_strip_nulls(expr, type_=JSONB)

    data = hybrid_property(_data_get, _data_set, expr=lambda cls: cls._data_sql())


@lru_cache(maxsize=None)
def _fields_of(cls) -> tuple[DataField, ...]:
    keys = cls.DATA_KEYS
    out = []
    for col in cls.__table__.columns:
        if col.key in cls.DATA_EXCLUDE:
            continue
        out.append(DataField(keys.get(col.key, col.key), col.key, _kind(col)))
    if not any(f.key == UNPARSED_KEY for f in out):
        raise TypeError(f"{cls.__name__} mixes in TypedData but has no '{UNPARSED_KEY}' column.")
    return tuple(out)


def _attr_for(cls, key: str) -> str:
    return next(f.attr for f in cls.data_fields() if f.key == key)


def is_typed(model) -> bool:
    return isinstance(model, type) and issubclass(model, TypedData)


@lru_cache(maxsize=None)
def sql_relation(model) -> str:
    """What raw `text()` SQL selects FROM to read `<alias>.data` off this model's rows.

    The bare table name for a JSONB table; for a typed one, a derived table carrying every
    column plus the rebuilt `data`. Contains no `:` — `text()` would read one as a bind.
    """
    if not is_typed(model):
        return model.__tablename__
    stmt = select(*model.__table__.columns, model._data_sql().label("data"))
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    if ":" in sql:
        raise ValueError(f"sql_relation({model.__name__}) would put a ':' into text() SQL.")
    return f"({sql})"
