"use client";

// Customer data → Statement → one statement's tickets.
//
// The same detail screen as Internal Statement's: both routes read the same
// `ticket_statements` / `uploaded_tickets` rows, so a second copy would only be
// somewhere for the two to disagree. batch_id comes from the route params, which
// resolve identically under either path.

import StatementDetailPage from "@/app/(dashboard)/tickets/[batch_id]/page";

export default function CustomerStatementDetailPage() {
  return <StatementDetailPage />;
}
