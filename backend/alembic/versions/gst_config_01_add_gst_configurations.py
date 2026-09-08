"""GST is a rule, not a constant: hold it as data.

`services/billing_calc.py` has carried GST as `GST_RATE = 0.18` since customer
billing was written, applied by `compute_gst` two ways — tax on the markup for an
'agency' bill, tax on (base + markup) for a 'reseller' one. Those two ARE the
business's "Normal" category, but frozen in Python: the rate cannot be changed
without a deploy, the CGST / SGST / IGST split does not exist, and the abatement
rule (Rule 32(3) of the CGST Rules — GST on a deemed 5% of basic fare rather than
on the commission) has nowhere to live at all.

This table is that missing configuration. Every rule reduces to the same shape

    taxable_value = <basis amount> × taxable_value_pct / 100
    tax           = taxable_value × <rate> / 100

so one row covers all three cases and none of them is code:

    AB   abatement            basis=basic_fare      taxable_value_pct=5    9 / 9 / 18
    NA   normal · agency      basis=service_charge  taxable_value_pct=100  9 / 9 / 18
    NR   normal · reseller    basis=total_cost      taxable_value_pct=100  9 / 9 / 18

ALL THREE RATE COLUMNS EXIST ON EVERY ROW, AND NEVER APPLY TOGETHER. CGST + SGST
is the intra-state pair, IGST the inter-state alternative; the row cannot know
where a supply lands, so it carries both and `services/gst_calc.compute_gst`
takes the place-of-supply decision and zeroes the pair that does not apply.
Summing the three columns would tax every rupee twice.

`created_by_id` is nullable here, unlike `iata_commissions.created_by_id`: the
three rows below are seeded by this migration and there is no user account to
attribute them to.

Nothing is rewired. `billing_calc.compute_gst` and its callers in customers.py /
corporates.py / agency_billing.py are untouched, so no existing invoice changes
value — this migration only makes the configuration available to move onto.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: gst_config_01
Revises: ticket_stmt_cols_01
"""
from alembic import op
import sqlalchemy as sa


revision = "gst_config_01"
down_revision = "ticket_stmt_cols_01"
branch_labels = None
depends_on = None


TABLE = "gst_configurations"

# The seed. Deliberately a literal list rather than an import from app.models:
# a migration has to keep describing the schema as it was on the day it ran, and
# would break the moment the model's defaults were edited.
_SEED = (
    {
        "code": "AB",
        "name": "Abatement",
        "category": "abatement",
        "sub_category": None,
        "basis": "basic_fare",
        "taxable_value_pct": 5,
        "cgst_pct": 9,
        "sgst_pct": 9,
        "igst_pct": 18,
        "notes": (
            "GST on a deemed 5% of basic fare (Rule 32(3), CGST Rules). "
            "Rule 32(3) sets 10% for international bookings — change "
            "taxable_value_pct on this row, or add a second row, if the "
            "business starts billing international separately."
        ),
    },
    {
        "code": "NA",
        "name": "Normal — Agency",
        "category": "normal",
        "sub_category": "agency",
        "basis": "service_charge",
        "taxable_value_pct": 100,
        "cgst_pct": 9,
        "sgst_pct": 9,
        "igst_pct": 18,
        "notes": (
            "GST on the agency's own service charge / service fee only. "
            "Matches billing_calc.compute_gst's 'agency' branch, which taxes "
            "the markup rather than the fare."
        ),
    },
    {
        "code": "NR",
        "name": "Normal — Reseller",
        "category": "normal",
        "sub_category": "reseller",
        "basis": "total_cost",
        "taxable_value_pct": 100,
        "cgst_pct": 9,
        "sgst_pct": 9,
        "igst_pct": 18,
        "notes": (
            "GST on the whole sale: fare + taxes + service charge. Matches "
            "billing_calc.compute_gst's 'reseller' branch."
        ),
    },
)


def upgrade() -> None:
    table = op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),

        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("sub_category", sa.String(length=20), nullable=True),

        sa.Column("basis", sa.String(length=30), nullable=False),
        sa.Column("taxable_value_pct", sa.Numeric(7, 3), nullable=False, server_default="100"),

        sa.Column("cgst_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("sgst_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),
        sa.Column("igst_pct", sa.Numeric(6, 3), nullable=False, server_default="0"),

        sa.Column("sac_code", sa.String(length=20), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),

        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),

        sa.UniqueConstraint("tenant_id", "code", "valid_from", name="uq_gst_config_scope_code_from"),
    )
    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_code", TABLE, ["code"])
    op.create_index(f"ix_{TABLE}_category", TABLE, ["category"])

    # Seeded global (tenant_id NULL) and open-ended (valid_from NULL) so the rules
    # are in force from the moment the table exists — a platform admin editing a
    # rate is then an edit, not a first-time setup.
    op.bulk_insert(
        table,
        [
            {
                "tenant_id": None,
                "created_by_id": None,
                "sac_code": None,
                "valid_from": None,
                "valid_to": None,
                "is_active": True,
                **row,
            }
            for row in _SEED
        ],
    )


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_category", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_code", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
