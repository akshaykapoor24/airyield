"use client";

import { useState } from "react";
import { User, Building2, KeyRound } from "lucide-react";
import ProfileInfoSection from "@/components/profile/ProfileInfoSection";
import EntitiesSection from "@/components/profile/EntitiesSection";
import LoginIdsSection from "@/components/profile/LoginIdsSection";

const TABS = [
  { key: "info", label: "My Info", icon: User },
  { key: "entities", label: "Entities", icon: Building2 },
  { key: "logins", label: "Login IDs / IATA", icon: KeyRound },
] as const;

export default function MyProfilePage() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("info");

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Account</p>
        <h1 className="text-xl font-bold text-gray-900">My Profile</h1>
        <p className="text-xs text-gray-500 mt-0.5">Your information, entities, and airline login IDs / IATA codes.</p>
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

      <div className="bg-white rounded-xl border border-gray-200 p-5">
        {tab === "info" && <ProfileInfoSection />}
        {tab === "entities" && <EntitiesSection />}
        {tab === "logins" && <LoginIdsSection />}
      </div>
    </div>
  );
}
