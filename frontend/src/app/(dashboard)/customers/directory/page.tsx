"use client";

// Customer Directory — every counterparty we sell to, of all three kinds:
// direct customers, B2B agencies and corporates. Read-only; onboarding and
// editing live in the matching master under User master, which each row links to.

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import CounterpartyDirectory from "@/components/party/CounterpartyDirectory";
import { COUNTERPARTY, COUNTERPARTY_KINDS } from "@/lib/counterparty";

export default function CustomerDirectoryPage() {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Customer Data</p>
          <h1 className="text-xl font-bold text-gray-900">Customer Directory</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Every customer you sell to — direct customers, B2B agencies and corporates. Click an
            agency&rsquo;s counts to drill into its entities and login IDs.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {COUNTERPARTY_KINDS.map((kind) => (
            <Link
              key={kind}
              href={COUNTERPARTY[kind].masterHref}
              className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-semibold hover:bg-gray-50 whitespace-nowrap"
            >
              {COUNTERPARTY[kind].masterLabel} <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          ))}
        </div>
      </div>

      <CounterpartyDirectory />
    </div>
  );
}
