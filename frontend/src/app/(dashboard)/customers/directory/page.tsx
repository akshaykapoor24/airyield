"use client";

// Customer Directory — the sub-agencies we onboard and float deals to. Both the
// Onboarding flow and the Overview drill-down live here as in-page tabs (the
// standalone /agency-profile/* routes render the same components with their own header).

import { useState } from "react";
import { Building2, LayoutGrid } from "lucide-react";
import AgencyOnboarding from "@/components/agency/AgencyOnboarding";
import AgencyOverview from "@/components/agency/AgencyOverview";

const TABS = [
  { key: "onboarding", label: "Onboarding", icon: Building2 },
  { key: "overview", label: "Overview", icon: LayoutGrid },
] as const;

export default function CustomerDirectoryPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("onboarding");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Customer Data</p>
        <h1 className="text-xl font-bold text-gray-900">Customer Directory</h1>
        <p className="text-xs text-gray-500 mt-0.5">Onboard the agencies you float deals to, then review their entities and airline login IDs.</p>
      </div>

      <div className="flex items-center gap-1 border-b border-gray-200">
        {TABS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-colors ${
                active ? "border-[#1e3a5f] text-[#1e3a5f]" : "border-transparent text-gray-400 hover:text-gray-600"
              }`}>
              <t.icon className="w-3.5 h-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "onboarding" && <AgencyOnboarding embedded />}
      {tab === "overview" && <AgencyOverview embedded />}
    </div>
  );
}
