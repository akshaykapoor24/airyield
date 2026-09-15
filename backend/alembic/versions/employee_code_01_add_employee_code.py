"""Employee Code — the second way to tell two employees apart

Until now the only identity an employee had was `(name, employer)`, enforced in Python by
services/party_dedupe and by nothing at all in the database. Two people genuinely called
Rahul Sharma at one corporate could not both be saved: the register refused the second with
"Give them a last name, or a different employer, to tell the two apart."

`employee_code` is the third option that message was missing. Optional, and the one field on
this row that is NOT inherited from the corporate — phone, email, gst_no and pan_no all are
(services/party_inherit), which is exactly why none of them can identify a person.

NOTHING IS BACKFILLED. Inventing `EMP-0001` for the 23 live employees would put a fabricated
identifier on real records. Uncoded namesakes stay refused, as they are today.

THE INDEX IS THE BACKSTOP, NOT THE RULE. `party_dedupe` produces a sentence naming who
already holds the code; this catches a concurrent insert that the register, loaded before
either transaction committed, cannot see. Partial because the column is optional, and
workspace-scoped rather than per-corporate: a code meaning two people in one workspace is not
an identifier, and it would also make UNLINKING an employee fail on a *code* constraint as
the row moved into the `corporate_id IS NULL` bucket.

Values are stored trimmed and uppercased by the router (as gst_no and pan_no already are), so
a plain index is case-insensitive in effect and the stored value is the canonical one.

Revision ID: employee_code_01
Revises: party_cat_markup_01
Create Date: 2026-09-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'employee_code_01'
down_revision: Union[str, None] = 'party_cat_markup_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'customers'
_INDEX = 'uq_customers_employee_code'


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column('employee_code', sa.String(length=50), nullable=True))
    op.create_index(
        _INDEX, _TABLE, ['tenant_id', 'created_by_id', 'employee_code'],
        unique=True, postgresql_where=sa.text('employee_code IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, 'employee_code')
