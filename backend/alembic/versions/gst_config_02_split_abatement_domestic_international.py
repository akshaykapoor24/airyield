"""Abatement is two figures, not one: 5% domestic, 10% international.

Rule 32(3) of the CGST Rules deems the value of an air travel agent's service to
be 5% of basic fare for a DOMESTIC booking and 10% for an INTERNATIONAL one. The
gst_config_01 seed carried only the 5% case, which silently under-taxes every
international ticket by half the moment the rule is wired into billing.

Rather than add a third column that is NULL on three rows out of four, this
subdivides abatement the same way normal is already subdivided — `sub_category`
is simply read against its own category:

    abatement → domestic | international     what the TRIP is
    normal    → agency | reseller            who the CUSTOMER is

The normal route taxes actual consideration (the service charge, or the whole
sale) and does not vary by sector, so domestic/international genuinely applies to
abatement alone. See SUB_CATEGORIES_BY_CATEGORY in models/gst_configuration.py.

THE NEW ROW INHERITS ITS RATES FROM THE EXISTING ONE. International abatement
differs from domestic in the deemed percentage and nothing else, so the CGST /
SGST / IGST figures are copied across rather than re-seeded at 9/9/18. If an
admin had already moved domestic off the default before upgrading, the two rows
still agree afterwards.

Renaming 'AB' to 'ABD' is safe: nothing reads these rows by code. The screen
looks a rule up by (category, sub_category), and no billing code consumes the
master yet.

Revision ID: gst_config_02
Revises: gst_config_01
"""
from alembic import op
import sqlalchemy as sa


revision = "gst_config_02"
down_revision = "gst_config_01"
branch_labels = None
depends_on = None


TABLE = "gst_configurations"


def upgrade() -> None:
    op.create_index(f"ix_{TABLE}_sub_category", TABLE, ["sub_category"])

    # 1. The row seeded as plain "Abatement" becomes the DOMESTIC one. Only its
    #    identity changes — rates and validity are left exactly as they are, in
    #    case they have already been edited.
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
               SET code = 'ABD',
                   name = 'Abatement — Domestic',
                   sub_category = 'domestic'
             WHERE category = 'abatement'
               AND sub_category IS NULL
            """
        )
    )

    # 2. The INTERNATIONAL twin: same basis and same rates, 10% deemed value.
    #    INSERT…SELECT so it inherits from whatever the domestic row now holds,
    #    and NOT EXISTS so re-running against a hand-patched database is a no-op.
    op.execute(
        sa.text(
            f"""
            INSERT INTO {TABLE} (
                tenant_id, created_by_id, code, name, category, sub_category,
                basis, taxable_value_pct, cgst_pct, sgst_pct, igst_pct,
                sac_code, valid_from, valid_to, notes, is_active,
                created_at, updated_at
            )
            SELECT d.tenant_id,
                   NULL,
                   'ABI',
                   'Abatement — International',
                   'abatement',
                   'international',
                   d.basis,
                   10,
                   d.cgst_pct, d.sgst_pct, d.igst_pct,
                   d.sac_code, d.valid_from, d.valid_to,
                   'GST on a deemed 10% of basic fare for international bookings '
                   '(Rule 32(3), CGST Rules). The domestic twin is ABD, at 5%.',
                   d.is_active,
                   d.created_at, d.updated_at
              FROM {TABLE} d
             WHERE d.category = 'abatement'
               AND d.sub_category = 'domestic'
               AND NOT EXISTS (
                     SELECT 1 FROM {TABLE} x
                      WHERE x.category = 'abatement'
                        AND x.sub_category = 'international'
                        AND x.tenant_id IS NOT DISTINCT FROM d.tenant_id
                   )
            """
        )
    )

    # 3. The domestic row's note still describes the pre-split world.
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
               SET notes = 'GST on a deemed 5% of basic fare for domestic bookings '
                           '(Rule 32(3), CGST Rules). The international twin is ABI, at 10%.'
             WHERE code = 'ABD'
               AND notes LIKE 'GST on a deemed 5%% of basic fare (Rule 32(3)%%'
            """
        )
    )


def downgrade() -> None:
    # Drop the international rows, then fold domestic back to the single
    # sub-category-less "Abatement" gst_config_01 created.
    op.execute(
        sa.text(
            f"DELETE FROM {TABLE} WHERE category = 'abatement' AND sub_category = 'international'"
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
               SET code = 'AB',
                   name = 'Abatement',
                   sub_category = NULL
             WHERE category = 'abatement'
               AND sub_category = 'domestic'
            """
        )
    )
    op.drop_index(f"ix_{TABLE}_sub_category", table_name=TABLE)
