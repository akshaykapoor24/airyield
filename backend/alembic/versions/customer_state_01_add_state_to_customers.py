"""A direct customer needs a state, or their tax cannot be worked out.

Place of supply decides whether a sale carries CGST + SGST or IGST, and it is
settled by comparing the supplier's state with the recipient's. For a corporate
that comparison has an input: `corporates` carries a full address block and a
GSTIN. For a CUSTOMER it had neither — `customers` held `gst_no` and nothing
geographic at all, no state, city, address or pincode.

So a direct customer with no GSTIN (9 of 16 live rows) had NOTHING from which to
derive a place of supply, and the business's rule for exactly that case is "ask
the state; same as ours means CGST and SGST, otherwise IGST". This is that field.

Only `state` is added, not the whole address block `corporates` has. State is the
only part place of supply reads, and a column that is not needed is a column that
goes stale — the rest can follow if invoices ever have to print a customer's
address.

Nullable, and nothing is backfilled. A blank state is honest for the rows that
have never been asked, and the resolver falls back to the linked corporate's
state first anyway — an employee inherits their employer's place of supply
because it is the employer being billed.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: customer_state_01
Revises: tenant_gst_scheme_02
"""
from alembic import op
import sqlalchemy as sa


revision = "customer_state_01"
down_revision = "tenant_gst_scheme_02"
branch_labels = None
depends_on = None


# (column, type) pairs, so upgrade and downgrade cannot drift apart.
# Named and sized to match corporates.state, which is the other side of the same
# comparison — a mismatch there would be a bug waiting for a long state name.
_COLUMNS = (
    ("state", sa.String(length=100)),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("customers", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("customers", name)
