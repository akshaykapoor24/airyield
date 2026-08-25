"use client";

// Customer data → Statement → Create Ticket.
// Same form as Internal Statement's, in "customer" mode — see the note on the
// sibling upload page.

import CreateTicketPage from "@/app/(dashboard)/tickets/create/page";

export default function CustomerCreateTicketPage() {
  return <CreateTicketPage mode="customer" />;
}
