"use client";

// Customer data → Statement → Upload Statement.
//
// The same wizard as Internal Statement's upload, in "customer" mode: the
// statement-details panel asks WHO the tickets were sold to (B2B agency, B2E
// corporate, or a direct customer) instead of which vendor file they came from,
// and that tag is written to the ticket rows for the commission run.
//
// Deliberately the same component rather than a fork — the drop step, the column
// mapping and the review grid are identical work, and two copies would drift.

import UploadTicketsPage from "@/app/(dashboard)/tickets/upload/page";

export default function CustomerUploadStatementPage() {
  return <UploadTicketsPage mode="customer" />;
}
