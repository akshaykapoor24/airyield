"use client";

// Customer data → Statement.
//
// The selling-side view of the ticket book, laid out like Vendors data → Statements:
// one tab per kind of customer the tickets were sold to — B2B (agencies), Corporate and
// Direct — each with its own uploads list, Template and Upload Statement. Same data as
// Internal Statement (one `ticket_statements` / `uploaded_tickets` pair, not a copy),
// entered through the wizard in "customer" mode, which records WHO the tickets were sold
// to; that tag is what the customer-side commission run prices against.
//
// Statements are only added by upload here. Punching single tickets in by hand stays in
// the sidebar's Internal Statement module.

import { useState } from "react";
import { Briefcase, Building2, Ticket, User } from "lucide-react";
import StatementsView, { type StatementCustomerType } from "@/components/tickets/StatementsView";

const TABS: { id: StatementCustomerType; label: string; hint: string; icon: typeof Ticket }[] = [
  { id: "agency",    label: "B2B",         hint: "Tickets sold to your sub-agencies (Agency Master)", icon: Building2 },
  { id: "corporate", label: "Corporate",   hint: "Tickets sold to corporates (Corporate Master)",     icon: Briefcase },
  { id: "direct",    label: "Direct",      hint: "Tickets sold to direct customers (Employee Master)", icon: User },
];

export default function CustomerStatementPage() {
  const [tab, setTab] = useState<StatementCustomerType>("agency");

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-bold text-gray-900 leading-tight">Statement</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Tickets you sold, one statement per upload — by who they were sold to
        </p>
      </div>

      <div className="flex items-center gap-1 border-b border-gray-200">
        {TABS.map(({ id, label, hint, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            title={hint}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === id
                ? "border-[#1e3a5f] text-[#1e3a5f]"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* One list, re-filtered per tab — keyed so each tab starts with clean filters. */}
      <StatementsView key={tab} showCustomer customerType={tab} allowDelete apiBase="/tickets" />
    </div>
  );
}
