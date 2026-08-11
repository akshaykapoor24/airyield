"""Give every workspace a subscription state

Until now the only thing between a stranger and the full product was an email
verification link: signup created a tenant + super_admin, the link flipped
is_verified, and from that moment the account had unrestricted access to deals,
tickets, BSP and billing. There was no notion of a paying customer anywhere in
the schema.

These four columns are the switch that a payment integration will eventually
drive. The plan lives on `tenants`, not `users`, because the tenant is the
sellable unit: one agency signs up as super_admin and invites its team, so the
subscription is bought once for the whole workspace. Flipping a per-user flag
instead would freeze a paying agency's new hire on their first day. Individual
accounts are already a one-person tenant, so they are covered by the same column.

`plan_status` stores the lowercase enum VALUE ("free", "active"), matching
Deal.status — NOT the enum NAME the way users.role does. That asymmetry in
users.role is why require_role has to compare seven case variants; there is no
reason to repeat it.

`plan_expires_at` is evaluated live in Tenant.has_active_plan rather than being
swept by a cron job, so a lapsed subscription starts refusing requests on the
next call with no scheduled task involved. NULL means "no expiry".

EXISTING TENANTS ARE GRANDFATHERED TO 'active'. The server_default is 'free', so
without the backfill below this migration would freeze every workspace already
using the system the moment it deployed. Only signups from here on start frozen.
If you are installing onto a database whose tenants are all throwaway test
accounts and you would rather start everyone frozen, delete the UPDATE — the
platform admin has no tenant and is exempt from the paywall, so you can always
sign in and activate the real ones from /admin/subscriptions.

Revision ID: tenant_subscription_01
Revises: user_password_security_01
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "tenant_subscription_01"
down_revision: Union[str, None] = "user_password_security_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("plan_status", sa.String(length=20), nullable=False, server_default="free"),
    )
    op.add_column("tenants", sa.Column("plan_expires_at", sa.DateTime(), nullable=True))
    op.add_column("tenants", sa.Column("plan_activated_at", sa.DateTime(), nullable=True))
    op.add_column("tenants", sa.Column("plan_note", sa.String(length=255), nullable=True))
    op.create_index("ix_tenants_plan_status", "tenants", ["plan_status"])

    # Grandfather everyone who is already here — see the note above.
    op.execute(
        "UPDATE tenants "
        "SET plan_status = 'active', "
        "    plan_activated_at = CURRENT_TIMESTAMP, "
        "    plan_note = 'Grandfathered on subscription launch' "
        "WHERE plan_status = 'free'"
    )


def downgrade() -> None:
    # Dropping these removes the paywall entirely: every verified account gets
    # the full product back, and which workspaces had paid is lost with the
    # columns. Export `SELECT id, plan_status, plan_expires_at, plan_note FROM
    # tenants` first if you intend to upgrade again.
    op.drop_index("ix_tenants_plan_status", table_name="tenants")
    op.drop_column("tenants", "plan_note")
    op.drop_column("tenants", "plan_activated_at")
    op.drop_column("tenants", "plan_expires_at")
    op.drop_column("tenants", "plan_status")
