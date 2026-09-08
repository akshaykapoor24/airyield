"""One 'normal' scheme, not one per billing type.

tenant_gst_scheme_01 offered three elections — abatement, normal_agency,
normal_reseller — which mixed up two different questions. Which BASIS a workspace
taxes on ('normal', i.e. actual consideration, versus the Rule 32(3) deemed
value) is the workspace's election. Whether a given customer is billed as an
agency or as a reseller is a property of that CUSTOMER, already recorded in
customers.billing_type / corporates.billing_type and already what
services/billing_calc.compute_gst reads.

Making the workspace choose 'normal_agency' therefore asked it to answer, once
and globally, a question that is answered per customer. So the two collapse into
'normal', which — exactly like 'abatement' — spans two rules, with the party's
own billing_type selecting between them the way the sector selects between the
two abatement rules.

Purely a fold of the stored value; the underlying gst_configurations rows (NA and
NR) are untouched and both remain in force.

At the time of writing NO row holds either old value, so this is defensive. It
still has to run: once GST_SCHEMES stops accepting them, a tenant carrying one
would fail validation on every profile save with no way to correct it, because
the dropdown could not display the value it needed to replace.

Revision ID: tenant_gst_scheme_02
Revises: ticket_retag_01
"""
from alembic import op
import sqlalchemy as sa


revision = "tenant_gst_scheme_02"
down_revision = "ticket_retag_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE tenants SET gst_scheme = 'normal' "
            "WHERE gst_scheme IN ('normal_agency', 'normal_reseller')"
        )
    )


def downgrade() -> None:
    # 'normal' cannot be split back into the sub-type it came from — that
    # information was never the workspace's to hold. Everything folded forward
    # lands on 'normal_agency', which was the old default reading.
    op.execute(
        sa.text("UPDATE tenants SET gst_scheme = 'normal_agency' WHERE gst_scheme = 'normal'")
    )
