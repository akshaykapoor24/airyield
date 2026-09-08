"""A workspace elects a GST scheme; record which one.

`gst_configurations` (gst_config_01/02) holds the RULES — abatement at a deemed
5% domestic / 10% international, normal-agency on the service charge,
normal-reseller on the whole sale. Nothing recorded which of them a given
workspace actually bills under, so the master was a set of options nobody had
chosen from.

Rule 32(3) of the CGST Rules is an ELECTION made by the registered person: a
business opts into the abatement basis or stays on the normal one, and that
choice governs every invoice it raises. So the column belongs on `tenants`,
beside pan_number / gst_number, which are the workspace's other tax identity
fields — not on `users`, since two people in one company cannot bill differently.

STORED AS A SLUG, NOT A ROW ID. Two reasons:
  * abatement is ONE scheme spanning TWO rows (ABD and ABI), and a single
    gst_configuration_id cannot name it;
  * the rows are effective-dated, so an id would pin the workspace to one dated
    row and a later rate revision would silently never reach it.
`SCHEME_MAP` in models/gst_configuration.py resolves the slug to rows at read
time, which is what keeps a platform-side rate change flowing through.

NULL means "not elected yet" and must never be read as a scheme — a caller that
finds NULL should say the workspace has not chosen one, never assume a default.
Nothing is backfilled for exactly that reason: guessing an election is worse
than admitting it is unmade.

Nothing is wired to billing. services/billing_calc.py keeps GST_RATE = 0.18 and
keeps deciding agency-vs-reseller from customers.billing_type, so no existing
invoice changes value. This only makes the election recordable.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: tenant_gst_scheme_01
Revises: gst_config_02
"""
from alembic import op
import sqlalchemy as sa


revision = "tenant_gst_scheme_01"
down_revision = "gst_config_02"
branch_labels = None
depends_on = None


# (column, type) pairs, so upgrade and downgrade cannot drift apart — the shape
# tenant_profile_01 established for adding columns to `tenants`.
_COLUMNS = (
    ("gst_scheme", sa.String(length=20)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("tenants", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("tenants", name)
