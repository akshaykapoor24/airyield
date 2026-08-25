"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { ArrowRight, Building2, KeyRound, Landmark } from "lucide-react";
import AgencyInfoSection from "@/components/agency/AgencyInfoSection";
import AgencyEntitiesSection from "@/components/agency/AgencyEntitiesSection";
import AgencyLoginIdsSection from "@/components/agency/AgencyLoginIdsSection";

const TABS = [
  { key: "info", label: "Agency Info", icon: Landmark },
  { key: "entities", label: "Agency Entities", icon: Building2 },
  { key: "logins", label: "Agency Login IDs", icon: KeyRound },
] as const;

// Agency Master content — hosted by app/(dashboard)/user-master/layout.tsx,
// which supplies the page heading. Reviewing what has been onboarded lives in
// Customer data → Customer Directory.
export default function AgencyOnboarding() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("info");
  // Carries the agency just created on Agency Info across to Entities / Login
  // IDs, so "Agency added → Add Entities" lands on a form that already knows
  // which agency it is for. Cleared once the target tab has consumed it.
  const [handoffAgencyId, setHandoffAgencyId] = useState<number | null>(null);

  const goTo = useCallback((next: "entities" | "logins", agencyId: number) => {
    setHandoffAgencyId(agencyId);
    setTab(next);
  }, []);
  const clearHandoff = useCallback(() => setHandoffAgencyId(null), []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 border-b border-gray-200">
        <div className="flex items-center gap-1">
          {TABS.map((t) => {
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                onClick={() => { setTab(t.key); setHandoffAgencyId(null); }}
                className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-colors ${
                  active ? "border-[#1e3a5f] text-[#1e3a5f]" : "border-transparent text-gray-400 hover:text-gray-600"
                }`}>
                <t.icon className="w-3.5 h-3.5" /> {t.label}
              </button>
            );
          })}
        </div>

        <Link
          href="/customers/directory"
          className="flex items-center gap-1.5 text-gray-500 hover:text-[#1e3a5f] text-xs font-semibold pb-2">
          View directory <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {tab === "info" && <AgencyInfoSection onGoTo={goTo} />}
        {tab === "entities" && (
          <AgencyEntitiesSection initialAgencyId={handoffAgencyId} onConsumeInitial={clearHandoff} />
        )}
        {tab === "logins" && (
          <AgencyLoginIdsSection initialAgencyId={handoffAgencyId} onConsumeInitial={clearHandoff} />
        )}
      </div>
    </div>
  );
}
