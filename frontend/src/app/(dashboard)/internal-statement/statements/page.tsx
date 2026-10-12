"use client";

// Internal Statement → Statements.
//
// Two tabs over Internal Statement's OWN tables (internal_ticket_statements /
// internal_uploaded_tickets), separate from Customer data → Statement:
//
//   Statement-wise  the statements you UPLOADED — one row per file, opening into
//                   that file's tickets.
//   All tickets     every ticket, uploaded or hand-punched, in one list.
//
// A hand-punched ticket is not a statement the desk ever made: Create Ticket files
// it under a per-customer, per-month "Manual Entry" batch only because every ticket
// row needs one. Those batches are plumbing, so the statement tab leaves them out
// and the tickets appear under All tickets.

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FilePlus, Layers, List, Upload } from "lucide-react";
import StatementsView from "@/components/tickets/StatementsView";
import InternalTicketsView from "@/components/tickets/InternalTicketsView";

type Tab = "statements" | "tickets";

const TABS: { id: Tab; label: string; hint: string; icon: typeof Layers }[] = [
  { id: "statements", label: "Statement-wise", icon: Layers,
    hint: "Statements you uploaded — open one to see its tickets" },
  { id: "tickets", label: "All tickets", icon: List,
    hint: "Every ticket, uploaded or punched in Create Ticket" },
];

function InternalStatementsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTabState] = useState<Tab>(params.get("tab") === "tickets" ? "tickets" : "statements");
  // Kept in the URL, so Back from a statement and Create Ticket's Save land on the right tab.
  const setTab = (t: Tab) => {
    setTabState(t);
    router.replace(t === "tickets" ? "?tab=tickets" : "?", { scroll: false });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg font-bold text-gray-900 leading-tight">Internal Statements</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Uploaded statements, and every ticket — uploaded or punched — kept apart from Customer data.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/internal-statement/upload"
            className="flex items-center gap-1.5 px-3 py-2 bg-[#1e3a5f] text-white rounded-lg text-xs font-semibold hover:bg-[#16304f]">
            <Upload className="w-3.5 h-3.5" /> Upload Statement
          </Link>
          <Link href="/internal-statement/create"
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
            <FilePlus className="w-3.5 h-3.5" /> Create Ticket
          </Link>
        </div>
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
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"}`}
          >
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === "statements" ? (
        <StatementsView
          showCustomer
          apiBase="/internal-tickets"
          entryOverride="/internal-statement"
          excludeManual
          detailBaseOverride="/internal-statement/statements"
          allowDelete
        />
      ) : (
        <InternalTicketsView />
      )}
    </div>
  );
}

export default function InternalStatementsPage() {
  // useSearchParams needs a Suspense boundary under the app router.
  return (
    <Suspense>
      <InternalStatementsInner />
    </Suspense>
  );
}
