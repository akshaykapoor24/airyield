"""uploaded_tickets: split the airline accounting code out of the ticket number

A statement prints a ticket as "607 5808583279" — the airline's 3-digit IATA accounting
code, then the document serial. `ticket_extraction` used to join the two into a 13-digit
value, which left `uploaded_tickets` the only table in the schema holding a ticket that
way:

  * `third_party_gds` stores the serial in `ticket_number` with `ticket_prefix` beside it;
  * every one of the 15,204 `bsp_statement_rows` carries the bare 10-digit serial.

So the joined value matched NEITHER, and a ticket bought through a consolidator and sold to
a customer could not be paired with itself. This adds the column and backfills it by
splitting what is already stored.

THE BACKFILL IS THE SAME PREDICATE THE PARSER USES — `^(\\d{3})(\\d{10})$`, mirroring
`sector_split._TKT_JOINED_RE`. Nothing else is touched: a 10-digit value is already a bare
serial, and anything that is not 13 digits ("157 ABC", a booking reference) is left exactly
as it is rather than guessed at. That makes this migration safe to run twice — a row it has
already split no longer matches.

Revision ID: tkt_prefix_01
Revises: sell_recon_01
Create Date: 2026-09-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "tkt_prefix_01"
down_revision: Union[str, None] = "sell_recon_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 3-digit accounting code followed by a 10-digit serial, and nothing else.
JOINED = r"^([0-9]{3})([0-9]{10})$"


def upgrade() -> None:
    op.add_column("uploaded_tickets",
                  sa.Column("ticket_prefix", sa.String(length=4), nullable=True))

    op.execute(sa.text(f"""
        UPDATE uploaded_tickets
           SET ticket_prefix = substring(ticket_number from 1 for 3),
               ticket_number = substring(ticket_number from 4)
         WHERE ticket_number ~ '{JOINED}'
           AND ticket_prefix IS NULL
    """))


def downgrade() -> None:
    # Re-join before dropping the column, so the value is not silently truncated to a
    # serial that no longer says which carrier issued it.
    op.execute(sa.text("""
        UPDATE uploaded_tickets
           SET ticket_number = ticket_prefix || ticket_number
         WHERE ticket_prefix IS NOT NULL
           AND ticket_number IS NOT NULL
    """))
    op.drop_column("uploaded_tickets", "ticket_prefix")
