"""Every workspace has a deals approval workflow — Proprietary unless it chose otherwise

A workspace with NO workflow is not a neutral starting point: api/v1/deals.py refuses
every deal with "Deals approval workflow is not configured. Ask Super Admin to configure
it first." New accounts now get the Proprietary one at signup
(services/auth_service._ensure_default_deal_workflow); this gives the same to the
workspaces that already exist and never configured one, so no account is left in the
blocked state.

PROPRIETARY = deals are approved the moment they are created, no steps. It is what a Super
Admin would have to pick anyway to get started, and the one arrangement that cannot
half-work: an Enterprise workflow with no steps is refused at deal creation too.

ONLY WHERE THERE IS NONE. uq_approval_workflows_tenant_module allows one workflow per
module per tenant, and a workspace that already configured Enterprise steps keeps them —
the insert skips any tenant that already has a deals row.

`created_by_id` IS NOT NULL, so each row is attributed to that tenant's earliest user
(its Super Admin, in practice). A tenant with no users at all is skipped: there is nobody
to attribute it to, and nobody to create a deal either.

Revision ID: default_deal_workflow_01
Revises: profile_login_cascade_01
Create Date: 2026-09-21 00:00:00.000000
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "default_deal_workflow_01"
down_revision: Union[str, None] = "profile_login_cascade_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# `module` is SAEnum(native_enum=False, values_callable=…), so the stored value is the
# lowercase string, not the enum name.
_MODULE = "deals"
_CATEGORY = "proprietary"


def upgrade() -> None:
    bind = op.get_bind()
    inserted = bind.execute(sa.text("""
        INSERT INTO approval_workflows (tenant_id, module, is_active, deal_category, created_by_id,
                                        created_at, updated_at)
        SELECT t.id, :module, true, :category,
               (SELECT u.id FROM users u WHERE u.tenant_id = t.id ORDER BY u.id LIMIT 1),
               now(), now()
          FROM tenants t
         WHERE NOT EXISTS (
                   SELECT 1 FROM approval_workflows w
                    WHERE w.tenant_id = t.id AND w.module = :module
               )
           AND EXISTS (SELECT 1 FROM users u WHERE u.tenant_id = t.id)
    """), {"module": _MODULE, "category": _CATEGORY}).rowcount
    logger.info(
        "default_deal_workflow_01: %s workspace(s) given the Proprietary deals workflow; "
        "workspaces that already had one were left alone.", inserted,
    )


def downgrade() -> None:
    # Only the ones this added could be identified, and nothing records that — a
    # Proprietary workflow is indistinguishable from one a Super Admin chose. Deleting by
    # category would throw away real configuration, so the rows stay.
    pass
