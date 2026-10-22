"use client";

// Internal Statement → Upload Statement.
//
// The same wizard as Customer data → Statement's upload, in "customer" mode: the
// statement-details panel asks WHO the tickets were sold to (B2B agency, B2E
// corporate, or a direct customer) instead of which vendor file they came from,
// and that tag is written to the ticket rows for the commission run. Saved
// statements are listed under Customer data → Statement.
//
// Deliberately the same component rather than a fork — the drop step, the column
// mapping and the review grid are identical work, and two copies would drift.

import UploadTicketsPage from "@/app/(dashboard)/tickets/upload/page";

export default function InternalUploadStatementPage() {
  // Its own tables now (internal_ticket_statements / internal_uploaded_tickets), so what
  // it saves is listed under Internal Statement → Statements, not Customer data.
  //
  // `fillFromFile`: an attached file fills the customer, the period and the name in, and the
  // upload step waits for Next so they are checked before mapping.
  //
  // `askDateFormats`: the details ask how the sheet writes its Ticket Date and Travel Date —
  // filled in from the file, else the customer's last statement — and every date is read that
  // way (backend services/ticket_extraction.py DATE_FORMAT_FIELDS); the server requires it.
  //
  // `duplicateCheck`: the one check an upload makes. A row whose Booked Date, Ticket No, Pax
  // Name, Amount and Travel Date match a ticket already loaded — any uploaded statement or
  // Create Ticket entry, any period — is a duplicate: shown on the preview and not saved. The
  // file is not checked against itself (backend services/ticket_duplicates.py).
  return (
    <UploadTicketsPage mode="customer" apiBase="/internal-tickets" listHref="/internal-statement/statements"
      fillFromFile askDateFormats duplicateCheck />
  );
}
