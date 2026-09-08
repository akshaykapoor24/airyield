"""A workspace carries the letterhead it prints on: an address and a logo.

My Profile already held the three things an invoice needs to NAME the issuing
company — company name, PAN, GSTIN — but nothing that says where it is or what
it looks like. Both belong on `tenants` rather than `users`: an invoice is
issued by the company, so every member of the workspace must print the same
letterhead, exactly as they already share company_name / pan_number / gst_number.

The address columns are named to match `corporates` (address / city / state /
pincode / country), which is the BILL TO side of the same document.

The logo IMAGE is deliberately NOT a column here. `get_current_user`
selectinloads User.tenant on every authenticated request, so a base64 image on
this row would be re-read on all of them; `logo_path` instead holds a
services/file_store locator (a GCS blob name, or "local://…" when GCS is
unavailable) and the bytes are fetched only by the endpoint that serves them.
`logo_name` / `logo_mime` / `logo_size` describe the file so the UI and the
download response need no such fetch.

Nothing is backfilled — an address cannot be guessed from a domain, and every
existing workspace simply reads as blank until someone fills it in.

NOTE ON REVISION IDS: this repo has reused hex-pattern ids that collide, so this
uses a descriptive one, matching the `<feature>_<NN>` convention of the recent
migrations.

Revision ID: tenant_profile_01
Revises: tp_supplier_link_01
"""
from alembic import op
import sqlalchemy as sa


revision = "tenant_profile_01"
down_revision = "tp_supplier_link_01"
branch_labels = None
depends_on = None


# (column, type) pairs, so upgrade and downgrade cannot drift apart.
_COLUMNS = (
    ("address", sa.Text()),
    ("city", sa.String(length=120)),
    ("state", sa.String(length=100)),
    ("pincode", sa.String(length=20)),
    ("country", sa.String(length=100)),
    ("logo_path", sa.String(length=500)),
    ("logo_name", sa.String(length=255)),
    ("logo_mime", sa.String(length=100)),
    ("logo_size", sa.Integer()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column("tenants", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column("tenants", name)
