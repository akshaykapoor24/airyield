"""Internal Statement's own ticket tables — a structural copy of the customer ones.

Customer data → Statement owns `ticket_statements` + `uploaded_tickets`. Internal Statement
(the sidebar module: Upload Statement, Create Ticket) used to write into the same pair; it
now has its own, `internal_ticket_statements` + `internal_uploaded_tickets`, so the two
sections' data never mix and Internal Statement can be changed without touching Customer
data.

THE COLUMNS ARE NOT RESTATED HERE. Each table is the customer table's own definition,
copied under the new name (`Table.to_metadata`), so the two can never drift column by
column: add a column to UploadedTicket and the internal model has it too — the migration
that adds it must then add it to both tables.

IDs SHARE THE CUSTOMER SEQUENCES (the migration copies the column defaults). An internal
ticket and a customer ticket therefore never have the same id, so a query that wrongly
joins one table's id to the other's rows finds nothing instead of the wrong ticket.
"""
from app.database import Base
from app.models.ticket_statement import TicketStatement
from app.models.uploaded_ticket import UploadedTicket


class InternalTicketStatement(Base):
    __table__ = TicketStatement.__table__.to_metadata(Base.metadata, name="internal_ticket_statements")


class InternalUploadedTicket(Base):
    __table__ = UploadedTicket.__table__.to_metadata(Base.metadata, name="internal_uploaded_tickets")


# Code elsewhere (tenant usage / deletion registries) reads `__tablename__`, which a class
# mapped through `__table__` does not get by itself. Same name as the table, always.
InternalTicketStatement.__tablename__ = InternalTicketStatement.__table__.name
InternalUploadedTicket.__tablename__ = InternalUploadedTicket.__table__.name
