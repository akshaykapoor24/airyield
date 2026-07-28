"use client";

import { useState } from "react";
import { Building2, KeyRound, Landmark } from "lucide-react";
import AgencyInfoSection from "@/components/agency/AgencyInfoSection";
import AgencyEntitiesSection from "@/components/agency/AgencyEntitiesSection";
import AgencyLoginIdsSection from "@/components/agency/AgencyLoginIdsSection";

const TABS = [
  { key: "info", label: "Agency Info", icon: Landmark },
  { key: "entities", label: "Agency Entities", icon: Building2 },
  { key: "logins", label: "Agency Login IDs", icon: KeyRound },
] as const;

// Onboarding content. `embedded` hides the page header so it can be hosted inside
// the Customer Directory tabbed page (which supplies its own header).
export default function AgencyOnboarding({ embedded = false }: { embedded?: boolean }) {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("info");

  return (
    <div className="space-y-4">
      {!embedded && (
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Agency Profile</p>
          <h1 className="text-xl font-bold text-gray-900">Agency Onboarding</h1>
          <p className="text-xs text-gray-500 mt-0.5">Add your agencies from the Supplier Master, then their entities and airline login IDs / IATA codes.</p>
        </div>
      )}

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

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {tab === "info" && <AgencyInfoSection />}
        {tab === "entities" && <AgencyEntitiesSection />}
        {tab === "logins" && <AgencyLoginIdsSection />}
      </div>
    </div>
  );
}
