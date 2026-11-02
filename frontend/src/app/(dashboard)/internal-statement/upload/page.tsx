"use client";

// Internal Statement → Upload Statement.
//
// The same wizard as Customer data → Statement's upload, in "customer" mode: the
// statement-details panel asks WHO the tickets were sold to (B2B agency, B2E
// corporate, or a direct customer) instead of which vendor file they came from,
// and that tag is written to the ticket rows. Saved statements are listed under
// Internal Statement → Statements.
//
// Deliberately the same component rather than a fork — the drop step, the column
// mapping and the review grid are identical work, and two copies would drift.

import UploadTicketsPage from "@/app/(dashboard)/tickets/upload/page";

export default function InternalUploadStatementPage() {
  // Its own tables now (internal_ticket_statements / internal_uploaded_tickets), so what
  // it saves is listed under Internal Statement → Statements, not Customer data.
  //
  // `fillFromFile`: an attached file fills the customer and the name in, and the upload step
  // waits for Next so they are checked before mapping.
  //
  // `askDateFormats`: the details ask how the sheet writes its Ticket Date and Travel Date —
  // filled in from the file, else the customer's last statement — and every date is read that
  // way (backend services/ticket_extraction.py DATE_FORMAT_FIELDS); the server requires it.
  //
  // `duplicateCheck`: the one check an upload makes. A row whose Booked Date, Ticket No, Pax
  // Name, Amount and Travel Date match a ticket already loaded — any uploaded statement or
  // Create Ticket entry, any period — is a duplicate: shown on the preview and not saved. The
  // file is not checked against itself (backend services/ticket_duplicates.py).
  //
  // `standardFormat`: the columns are mapped onto Internal Statement's standard record
  // (lib/ticketFields INTERNAL_STANDARD) — the user's list; what is left unmapped is skipped.
  //
  // B2B is picked to start with, and `allowAllVendors` adds "All vendors — multi-vendor file"
  // above the agencies: one file of every vendor's tickets (Yatra's fortnightly sales report),
  // each row's vendor found from its Supplier Name on the preview.
  //
  // `rememberMapping`: the column mapping a statement is saved with is remembered, and the next
  // file with the same columns — this customer's first — opens already mapped, as Third Party
  // GDS does (backend services/saved_mapping.py).
  //
  // `askCategory`: the details ask the Statement Type — Booking / MO statement (picked to start
  // with) or Accounting statement — kept on the statement and written into its name.
  //
  // `periodFromTickets`: no Valid From / To. A sales report runs to 30–50k lines over many
  // days; the statement is filed under the first and last Booking Date of its tickets, and the
  // name — customer type, customer, statement type — ends with the first one.
  //
  // `serverImport`: a sales report runs to a lakh of lines. The file is uploaded once and its
  // lines stay on the server — a worker reads them, the review pages through them there, and a
  // worker saves the statement (backend api/v1/internal_imports.py, services/internal_import.py).
  return (
    <UploadTicketsPage mode="customer" apiBase="/internal-tickets" listHref="/internal-statement/statements"
      fillFromFile askDateFormats duplicateCheck standardFormat allowAllVendors defaultCustomerType="agency"
      rememberMapping askCategory periodFromTickets serverImport />
  );
}
