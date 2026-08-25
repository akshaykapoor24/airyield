"""The deletion registry must account for every table, and be able to finish.

Deleting a workspace is irreversible, so the failure mode this file guards is
not "a number looks wrong" — it is a delete that half-runs and aborts on a
foreign key, one that silently leaves rows behind under a NULL tenant_id, or a
selection that quietly removes more than the operator ticked. All three are
schema-drift bugs: someone adds a table or a column, and this module never
hears about it.

No DB, no network. Reflects the SQLAlchemy metadata only.

Run:  python -m unittest discover -s tests      (from backend/)
"""

import importlib
import os
import pkgutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.models  # noqa: F401,E402
from app.database import Base  # noqa: E402

# app.models.__init__ omits a few modules; import every one so no table can hide
# from the check (same reason as tests/test_tenant_usage.py).
for _mod in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_mod.name}")

from app.services.tenant_deletion import (  # noqa: E402
    ALL_GROUP_KEYS,
    CHILD_TABLES,
    DELETION_GROUPS,
    GROUP_REQUIREMENTS,
    GROUPS_BY_KEY,
    GroupCategory,
    expand_groups,
    tables_for_groups,
    tenant_predicate,
    validate_groups,
)
from app.services.tenant_usage import USAGE_SOURCES  # noqa: E402

# Master data shared by every workspace. Deleting one workspace must never touch
# these — that is the whole point of Master Governance owning them.
GLOBAL_TABLES = frozenset({
    "airlines", "airports", "routes", "airline_class_masters", "suppliers",
})

TENANT_SCOPED = frozenset(
    name for name, t in Base.metadata.tables.items() if "tenant_id" in t.c
)

OWNED = frozenset(t for g in DELETION_GROUPS for t in g.tables)
ALL_TABLES = frozenset(tables_for_groups(ALL_GROUP_KEYS))


class TestCoverage(unittest.TestCase):
    def test_every_tenant_scoped_table_belongs_to_a_group(self):
        """A tenant-scoped table no group owns is a workspace's rows surviving
        its own deletion."""
        missing = sorted(TENANT_SCOPED - OWNED)
        self.assertEqual(
            missing, [],
            "These tables carry a tenant_id but no group deletes them; add each "
            "to a DeletionGroup in app/services/tenant_deletion.py:\n  "
            + "\n  ".join(missing),
        )

    def test_every_other_table_is_global_or_has_a_route_to_a_tenant(self):
        """A table with no tenant_id must either be shared master data or say
        which tenant-scoped parent it hangs off."""
        known = TENANT_SCOPED | GLOBAL_TABLES | set(CHILD_TABLES) | {"tenants"}
        unclassified = sorted(set(Base.metadata.tables) - known)
        self.assertEqual(
            unclassified, [],
            "These tables are neither tenant-scoped, global master data, nor "
            "given a parent in CHILD_TABLES:\n  " + "\n  ".join(unclassified),
        )

    def test_no_table_is_owned_by_two_groups(self):
        seen: dict[str, str] = {}
        for group in DELETION_GROUPS:
            for table in group.tables:
                with self.subTest(table=table):
                    self.assertNotIn(
                        table, seen,
                        f"{table} is in both '{seen.get(table)}' and '{group.key}'",
                    )
                    seen[table] = group.key

    def test_group_tables_are_real(self):
        """A typo would quietly disable a table's deletion."""
        stale = sorted(OWNED - set(Base.metadata.tables))
        self.assertEqual(stale, [], f"groups name non-existent tables: {stale}")

    def test_group_keys_and_labels_are_unique(self):
        keys = [g.key for g in DELETION_GROUPS]
        labels = [g.label for g in DELETION_GROUPS]
        self.assertEqual(len(keys), len(set(keys)), "duplicate group key")
        self.assertEqual(len(labels), len(set(labels)), "duplicate group label")

    def test_every_child_resolves_to_a_tenant_scoped_ancestor(self):
        """Following the links must terminate at a table with a tenant_id, or
        the predicate recurses forever / raises KeyError at runtime."""
        for child in CHILD_TABLES:
            with self.subTest(child=child):
                seen = set()

                def resolve(name, depth=0):
                    self.assertLess(depth, 10, f"{child}: link chain does not terminate")
                    if "tenant_id" in Base.metadata.tables[name].c:
                        return True
                    self.assertIn(name, CHILD_TABLES, f"{child} -> {name} has no route to a tenant")
                    self.assertNotIn(name, seen, f"{child}: cyclic parent links")
                    seen.add(name)
                    return all(resolve(l.parent_table, depth + 1) for l in CHILD_TABLES[name].links)

                self.assertTrue(resolve(child))

    def test_child_links_point_at_real_columns(self):
        for child, spec in CHILD_TABLES.items():
            for link in spec.links:
                with self.subTest(child=child, fk=link.fk_column):
                    self.assertIn(link.fk_column, Base.metadata.tables[child].c)
                    self.assertIn(link.parent_table, Base.metadata.tables)
                    self.assertIn(link.parent_column, Base.metadata.tables[link.parent_table].c)


class TestDeleteCanFinish(unittest.TestCase):
    def test_no_foreign_key_outside_the_delete_set_can_block_it(self):
        """The scenario this catches: a table that is NOT deleted holds a
        reference to one that IS, with no ON DELETE to clear it. Postgres would
        abort the whole delete on a foreign-key violation.

        `tickets.created_by_id -> users` was exactly this — three dead
        pre-tenant tables with no ON DELETE, which is why the Legacy group
        exists at all.
        """
        blockers = []
        for name, table in Base.metadata.tables.items():
            if name in ALL_TABLES:
                continue
            for col in table.c:
                for fk in col.foreign_keys:
                    if fk.column.table.name in ALL_TABLES and fk.ondelete not in ("CASCADE", "SET NULL"):
                        blockers.append(f"{name}.{col.name} -> {fk.column.table.name} (ondelete={fk.ondelete!r})")
        self.assertEqual(
            sorted(blockers), [],
            "These foreign keys would abort a workspace delete. Either give the "
            "column an ON DELETE, or delete its table too:\n  " + "\n  ".join(sorted(blockers)),
        )

    def test_children_are_deleted_before_their_parents(self):
        """Order is what makes the delete safe whatever the database's ON DELETE
        clauses actually say."""
        order = tables_for_groups(ALL_GROUP_KEYS)
        position = {name: i for i, name in enumerate(order)}
        for name in order:
            for col in Base.metadata.tables[name].c:
                for fk in col.foreign_keys:
                    parent = fk.column.table.name
                    if parent in position and parent != name:
                        with self.subTest(child=name, parent=parent):
                            self.assertLess(
                                position[name], position[parent],
                                f"{name} is deleted after {parent} it points at",
                            )

    def test_child_parents_are_deleted_after_the_child(self):
        """tenant_predicate reads the parent table in a subquery, so the parent
        rows must still exist when the child is deleted."""
        order = tables_for_groups(ALL_GROUP_KEYS)
        position = {name: i for i, name in enumerate(order)}
        for child, spec in CHILD_TABLES.items():
            for link in spec.links:
                if link.parent_table in position:
                    with self.subTest(child=child, parent=link.parent_table):
                        self.assertLess(position[child], position[link.parent_table])

    def test_any_single_group_selection_is_closed_and_finishable(self):
        """Every one-tick selection an operator can make must expand to a set
        no foreign key outside it can block. This is the real guarantee behind
        the checkboxes."""
        for key in ALL_GROUP_KEYS:
            with self.subTest(group=key):
                chosen = expand_groups({key})
                tables = set(tables_for_groups(chosen))
                blockers = []
                for name in set(Base.metadata.tables) - tables:
                    for col in Base.metadata.tables[name].c:
                        for fk in col.foreign_keys:
                            if fk.column.table.name in tables and fk.ondelete not in ("CASCADE", "SET NULL"):
                                blockers.append(f"{name}.{col.name} -> {fk.column.table.name}")
                self.assertEqual(
                    sorted(set(blockers)), [],
                    f"selecting '{key}' expands to {sorted(chosen)}, which these "
                    f"foreign keys would block: {sorted(set(blockers))}",
                )

    def test_no_selection_silently_cascades_beyond_itself(self):
        """A CASCADE into a group that was not selected would delete rows the
        preview never mentioned. expand_groups must pull those groups in."""
        for key in ALL_GROUP_KEYS:
            with self.subTest(group=key):
                chosen = expand_groups({key})
                tables = set(tables_for_groups(chosen))
                surprises = []
                for name in set(Base.metadata.tables) - tables:
                    for col in Base.metadata.tables[name].c:
                        for fk in col.foreign_keys:
                            if fk.column.table.name in tables and fk.ondelete == "CASCADE":
                                surprises.append(f"{name} -> {fk.column.table.name}")
                self.assertEqual(
                    sorted(set(surprises)), [],
                    f"selecting '{key}' would silently cascade into: {sorted(set(surprises))}",
                )


class TestRequirements(unittest.TestCase):
    def test_restrict_dependencies_are_captured(self):
        """deals.agency_id is RESTRICT: deleting agencies without deals aborts."""
        self.assertIn("deals", GROUP_REQUIREMENTS["agencies"])
        self.assertIn("deals", GROUP_REQUIREMENTS["corporates"])

    def test_cascade_dependencies_are_captured(self):
        """billings.customer_id is CASCADE: deleting customers takes billings
        whether or not they were ticked, so the tick must say so."""
        self.assertIn("billing", GROUP_REQUIREMENTS["customers"])
        self.assertIn("billing", GROUP_REQUIREMENTS["agencies"])

    def test_deleting_users_takes_everything_they_created(self):
        required = expand_groups({"users"})
        for key in ALL_GROUP_KEYS:
            if key == "workspace":
                continue
            with self.subTest(group=key):
                self.assertIn(key, required)

    def test_deleting_the_workspace_takes_all_of_it(self):
        """tenant_id is CASCADE on 36 tables and SET NULL on 13, so this row can
        never go on its own."""
        self.assertEqual(expand_groups({"workspace"}), set(ALL_GROUP_KEYS))

    def test_a_plain_records_group_pulls_in_nothing_surprising(self):
        """Deleting deals must not require deleting the customers."""
        self.assertEqual(expand_groups({"deals"}), {"deals"})
        self.assertEqual(expand_groups({"bsp"}), {"bsp"})
        self.assertEqual(expand_groups({"adjustments"}), {"adjustments"})

    def test_expand_is_idempotent(self):
        for key in ALL_GROUP_KEYS:
            with self.subTest(group=key):
                once = expand_groups({key})
                self.assertEqual(expand_groups(once), once)

    def test_no_group_requires_itself_only_to_grow_forever(self):
        """A cycle in the requirement graph would loop expand_groups; it
        terminates because it grows monotonically, but assert it anyway."""
        self.assertEqual(expand_groups(set(ALL_GROUP_KEYS)), set(ALL_GROUP_KEYS))


class TestValidation(unittest.TestCase):
    def test_unknown_group_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_groups(["deals", "not_a_group"])
        self.assertIn("not_a_group", str(ctx.exception))

    def test_empty_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_groups([])

    def test_valid_selection_comes_back_expanded(self):
        self.assertEqual(validate_groups(["agencies"]), expand_groups({"agencies"}))


class TestGroupShape(unittest.TestCase):
    def test_every_usage_source_is_in_a_records_group(self):
        """A workspace wiped of every records group must read as 0 records."""
        records = {t for g in DELETION_GROUPS if g.category is GroupCategory.RECORDS for t in g.tables}
        for src in USAGE_SOURCES:
            with self.subTest(table=src.model.__tablename__):
                self.assertIn(src.model.__tablename__, records)

    def test_setup_groups_hold_no_usage_source(self):
        """Ticking only records groups must leave the workspace configured."""
        setup = {t for g in DELETION_GROUPS if g.category is GroupCategory.SETUP for t in g.tables}
        for src in USAGE_SOURCES:
            with self.subTest(table=src.model.__tablename__):
                self.assertNotIn(src.model.__tablename__, setup)

    def test_no_global_master_is_ever_deleted(self):
        for table in GLOBAL_TABLES:
            with self.subTest(table=table):
                self.assertNotIn(table, ALL_TABLES)

    def test_every_group_has_a_blurb(self):
        """The dialog shows it under the label; an empty one reads as a bug."""
        for group in DELETION_GROUPS:
            with self.subTest(group=group.key):
                self.assertTrue(group.blurb.strip())
                self.assertTrue(group.tables)

    def test_users_and_workspace_are_last_in_the_setup_list(self):
        """They are the two that take everything with them; the dialog reads
        top-to-bottom in increasing severity."""
        setup = [g.key for g in DELETION_GROUPS if g.category is GroupCategory.SETUP]
        self.assertEqual(setup[-2:], ["users", "workspace"])


class TestPredicate(unittest.TestCase):
    def test_tenant_scoped_table_compiles_to_a_plain_equality(self):
        sql = str(tenant_predicate("deals", 7))
        self.assertIn("deals.tenant_id", sql)
        self.assertNotIn("SELECT", sql.upper())

    def test_grandchild_chains_all_the_way_to_the_tenant(self):
        sql = str(tenant_predicate("deal_incentive_slab_values", 7)).upper()
        for expected in ("DEAL_INCENTIVE_SLABS", "DEAL_INCENTIVES", "DEALS.TENANT_ID"):
            with self.subTest(expected=expected):
                self.assertIn(expected, sql)

    def test_bsp_parse_errors_join_on_batch_id_not_the_primary_key(self):
        sql = str(tenant_predicate("bsp_parse_errors", 7)).upper()
        self.assertIn("BSP_STATEMENTS.BATCH_ID", sql)

    def test_multi_parent_child_ors_its_links(self):
        sql = str(tenant_predicate("income_records", 7)).upper()
        self.assertIn(" OR ", sql)


if __name__ == "__main__":
    unittest.main()
