"""Column mapping for the verbatim, spec-driven statement types (NDC).

The map → review → confirm wizard in api/v1/statements.py was built against the
``flat_statement`` builders, which normalize a consolidator's ledger into canonical fields
and store ``segments``/``ssr``/``raw_data``/``source_format`` alongside. The spec-driven
types are a different shape — an ordered column list stored verbatim in ``data`` — and
their tables carry none of those columns.

Rather than force one shape onto the other, this module gives the router the same three
methods it already calls on a builder (``build_col_map``, ``suggest_mapping``,
``build_row_mapped``), backed by the spec's own columns and aliases. So one wizard, one set
of endpoints, and two row-writing branches at the end of ``/confirm`` — which is where the
two genuinely differ.

Taxes are NOT folded here even for a ``fold_taxes`` type: folding needs every column in the
file, mapped or not, and the router already has ``_fold_taxes`` for exactly that. Keeping
it there means the mapped path and the verbatim ``/upload`` path fold identically.
"""
from __future__ import annotations

from app.services import statement_spec as spec


def _clean(value) -> str | None:
    """Same rule as the router's ``_clean``: blanks, NaN and the string "nan" are absent.

    Duplicated rather than imported because importing the router from a service would
    invert the dependency — services are what the router is built out of.
    """
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    # pandas hands back the float NaN for an empty numeric cell; str() makes it "nan",
    # which the check above already caught. Anything else is a real value.
    return s


class SpecMapper:
    """Maps an arbitrary spreadsheet onto one spec's ordered columns.

    ``build_col_map`` is source-column → field (what the file has); ``suggest_mapping`` is
    field → source-column (what the mapping UI asks: "which of my columns is this field").
    Both directions are needed and neither is the other's inverse once the user has edited
    it, which is why the router carries the map in the UI's direction.
    """

    def __init__(self, slug: str):
        self.slug = slug
        self.display_columns = spec.columns(slug)
        self._fields = [c["field"] for c in self.display_columns]
        # {normalized alias: field}. Built once; first alias wins so a canonical header can
        # never be stolen by another field's loose synonym.
        self._alias_to_field: dict[str, str] = {}
        for field in self._fields:
            for alias in spec.aliases(slug).get(field, [field]):
                self._alias_to_field.setdefault(spec.norm(alias), field)

    def build_col_map(self, columns: list[str]) -> dict[str, str]:
        """{source column: field} for the columns this spec recognises by name.

        A field is claimed once: if a file has both "Ticket No" and "Document No" they
        both normalize onto ``document_no``, and taking the second would silently
        overwrite the first. The user resolves that on the mapping screen.
        """
        out: dict[str, str] = {}
        claimed: set[str] = set()
        for col in columns:
            field = self._alias_to_field.get(spec.norm(col))
            if field and field not in claimed:
                out[str(col)] = field
                claimed.add(field)
        return out

    def suggest_mapping(self, columns: list[str]) -> dict[str, str]:
        """{field: source column} — the starting point the mapping screen is seeded with."""
        return {field: col for col, field in self.build_col_map(columns).items()}

    def build_row_mapped(self, row, columns: list[str], column_map: dict[str, str],
                         overrides: dict[str, str] | None = None) -> dict:
        """One source line → ``{"data": {field: value}}`` under the user's mapping.

        A field mapped to a column the file does not have is dropped rather than stored
        empty — the mapping may have been built against a different export.

        ``overrides`` are the per-row corrections made on the review step, applied AFTER
        the mapping so a corrected cell wins over the file. An override of "" clears the
        field: that is how a reviewer deletes a value the sheet got wrong.

        Values are stored verbatim as strings, exactly as the ``/upload`` path stores them
        — these types are a faithful copy of the vendor's file, and the numeric reading
        happens at query time (``_num`` in the router).
        """
        vals = {c: _clean(row.get(c)) for c in columns}
        present = set(columns)
        data: dict[str, str] = {}
        for field, col in (column_map or {}).items():
            if col in present and vals.get(col) is not None:
                data[field] = vals[col]
        for field, value in (overrides or {}).items():
            cleaned = _clean(value)
            if cleaned is None:
                data.pop(field, None)
            else:
                data[field] = cleaned
        return {"data": data}


_CACHE: dict[str, SpecMapper] = {}


def mapper_for(slug: str) -> SpecMapper:
    """The (cached) mapper for a spec-driven type. Specs are static, so one instance each."""
    m = _CACHE.get(slug)
    if m is None:
        m = _CACHE[slug] = SpecMapper(slug)
    return m


def column_groups(slug: str) -> list[dict]:
    """The spec's columns grouped and ordered for the mapping screen.

    Sixty-nine dropdowns in one list is not a form anybody can fill in; grouped by what the
    columns are FOR, a user maps the money block and stops.
    """
    by_group: dict[str, list[dict]] = {}
    for c in spec.columns(slug):
        by_group.setdefault(c.get("group") or "Other", []).append(c)
    order = spec.group_order(slug)
    ordered = [g for g in order if g in by_group]
    ordered += [g for g in by_group if g not in order]
    return [{"group": g, "columns": by_group[g]} for g in ordered]
