"use client";

// Customer data → Statement.
//
// The selling-side view of the ticket book: every statement, and every ticket
// across them. Same data as Internal Statement — one `ticket_statements` /
// `uploaded_tickets` pair, not a second copy — but entered through a form that
// asks WHO the tickets were sold to instead of which vendor file they came from.
// That tag is what the customer-side commission run prices against.

import { useState } from "react";
import Link from "next/link";
import { FilePlus, Layers, Ticket, Upload } from "lucide-react";
import StatementsView from "@/components/tickets/StatementsView";
import AllTicketsView from "@/components/tickets/AllTicketsView";

type View = "statements" | "tickets";

const VIEWS: { id: View; label: string; hint: string; icon: typeof Layers }[] = [
  { id: "statements", label: "Statement wise", hint: "Grouped by upload or entry batch", icon: Layers },
  { id: "tickets",    label: "All tickets",    hint: "Every ticket, flat across statements", icon: Ticket },
];

export default function CustomerStatementPage() {
  const [view, setView] = useState<View>("statements");

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Customer Data</p>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Statement</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {view === "statements"
              ? "Tickets you sold, grouped by statement — tagged B2B, corporate or direct"
              : "Every ticket you sold, across all statements"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/customers/statements/create"
            className="flex items-center gap-1.5 px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            <FilePlus className="w-3.5 h-3.5" />
            Create Ticket
          </Link>
          <Link
            href="/customers/statements/upload"
            className="flex items-center gap-1.5 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f]"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload Statement
          </Link>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-gray-200">
        {VIEWS.map(({ id, label, hint, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setView(id)}
            title={hint}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              view === id
                ? "border-[#1e3a5f] text-[#1e3a5f]"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Both stay mounted so switching back keeps filters and page position. */}
      <div className={view === "statements" ? "" : "hidden"}>
        <StatementsView showCustomer />
      </div>
      <div className={view === "tickets" ? "" : "hidden"}>
        <AllTicketsView />
      </div>
    </div>
  );
}
