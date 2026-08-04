"use client";

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

export default function TicketRepositoryPage() {
  const [view, setView] = useState<View>("statements");

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Internal Statement</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            {view === "statements"
              ? "Ticket statements for your organisation"
              : "Every ticket across all statements"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/tickets/create"
            className="flex items-center gap-1.5 px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50"
          >
            <FilePlus className="w-3.5 h-3.5" />
            Create Ticket
          </Link>
          <Link
            href="/tickets/upload"
            className="flex items-center gap-1.5 px-4 py-2 bg-[#1e3a5f] text-white rounded-lg text-sm font-semibold hover:bg-[#16304f]"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload Statement
          </Link>
        </div>
      </div>

      {/* view toggle */}
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

      {/* Both views stay mounted so switching back keeps filters and page position. */}
      <div className={view === "statements" ? "" : "hidden"}>
        <StatementsView />
      </div>
      <div className={view === "tickets" ? "" : "hidden"}>
        <AllTicketsView />
      </div>
    </div>
  );
}
