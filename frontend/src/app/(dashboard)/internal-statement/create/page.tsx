"use client";

// Internal Statement → Create Ticket.
// A one-screen, desk-style layout (see CompactTicketForm) built for punching
// tickets one after another. Same data path as tickets/create/page.tsx — which
// the vendor side still uses unchanged — against Internal Statement's own tables.

import CompactTicketForm from "@/components/tickets/CompactTicketForm";

export default function InternalCreateTicketPage() {
  return (
    <CompactTicketForm
      apiBase="/internal-tickets"
      listHref="/internal-statement/statements?tab=tickets"
      uploadHref="/internal-statement/upload"
    />
  );
}
