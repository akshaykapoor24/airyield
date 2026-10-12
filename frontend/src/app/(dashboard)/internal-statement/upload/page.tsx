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
  return <UploadTicketsPage mode="customer" apiBase="/internal-tickets" listHref="/internal-statement/statements" />;
}
