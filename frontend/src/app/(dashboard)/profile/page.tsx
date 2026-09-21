"use client";

// My Profile — who you are, the entities you trade as, and the login IDs / IATA numbers
// each one holds.
//
// The header is the identity card: logo (or initials), name, company, the badges that
// describe the account, and live counts of entities and login IDs. It keeps its own copy
// of the profile because it stays on screen on every tab, while the My Info form (which
// also loads it) only exists on the first; the form reports every change back through
// onProfileChange, so a saved name or a replaced logo shows up here at once.

import { useCallback, useEffect, useState } from "react";
import { User, Building2, KeyRound, BadgeCheck, Mail, Receipt, ShieldCheck } from "lucide-react";
import api from "@/lib/api";
import { useCompanyLogo } from "@/lib/companyLogo";
import { ROLE_LABELS } from "@/lib/auth";
import { schemeByKey } from "@/lib/gstSchemes";
import ProfileInfoSection, { type Profile } from "@/components/profile/ProfileInfoSection";
import EntitiesSection from "@/components/profile/EntitiesSection";
import LoginIdsSection from "@/components/profile/LoginIdsSection";

const TABS = [
  { key: "info", label: "My Info", icon: User },
  { key: "entities", label: "Entities", icon: Building2 },
  { key: "logins", label: "Login IDs / IATA", icon: KeyRound },
] as const;

type TabKey = (typeof TABS)[number]["key"];

/** How many entities and login IDs the user has, or null if either count failed — the
 *  header then just shows no numbers rather than a wrong one. */
async function countBoth(): Promise<{ entities: number; logins: number } | null> {
  try {
    const [e, l] = await Promise.all([
      api.get<unknown[]>("/user-entities/", { params: { limit: 1000 } }),
      api.get<unknown[]>("/user-login-ids/", { params: { limit: 1000 } }),
    ]);
    return { entities: e.data.length, logins: l.data.length };
  } catch {
    return null;
  }
}

const initialsOf = (name: string | null | undefined) =>
  (name ?? "").split(/\s+/).filter(Boolean).map(w => w[0]).join("").toUpperCase().slice(0, 2) || "?";

export default function MyProfilePage() {
  const [tab, setTab] = useState<TabKey>("info");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [counts, setCounts] = useState<{ entities: number | null; logins: number | null }>({ entities: null, logins: null });

  // The same logo the sidebar shows, from lib/companyLogo — one fetch, one object URL,
  // and it changes here the moment My Info replaces or removes it.
  const logoUrl = useCompanyLogo();

  useEffect(() => {
    api.get<Profile>("/users/me/profile").then(r => setProfile(r.data)).catch(() => {});
  }, []);

  // Counted directly rather than from the tabs' own lists, which are filtered by their
  // search boxes. Re-counted whenever either tab reports a change — deleting an entity
  // also deletes its login IDs, so both numbers move together.
  const recount = useCallback(() => {
    countBoth().then(c => { if (c) setCounts(c); });
  }, []);
  useEffect(() => {
    let cancelled = false;
    countBoth().then(c => { if (c && !cancelled) setCounts(c); });
    return () => { cancelled = true; };
  }, []);

  const scheme = profile?.gst_scheme ? schemeByKey(profile.gst_scheme) : undefined;
  const countFor = (key: TabKey) => key === "entities" ? counts.entities : key === "logins" ? counts.logins : null;

  return (
    <div className="space-y-5 max-w-6xl">
      {/* ── Identity header ─────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden shadow-sm">
        <div className="h-24 relative bg-gradient-to-r from-[#16304f] via-[#1e4d8c] to-[#2d6cb5]">
          {/* A faint grid, so the band reads as a surface rather than a flat fill. */}
          <div className="absolute inset-0 opacity-[0.08]"
            style={{ backgroundImage: "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)", backgroundSize: "24px 24px" }} />
          <p className="absolute left-6 top-4 text-[10px] font-semibold text-white/70 uppercase tracking-[0.2em]">Account · My Profile</p>
        </div>

        <div className="px-6 pb-5 flex flex-wrap items-start justify-between gap-5">
          <div className="flex items-start gap-5 min-w-0">
            {/* Straddles the band's bottom edge — half on the band, half below it.
                `relative z-10` IS THE FIX, not decoration: the band is position:relative,
                and a positioned element paints above an unpositioned one, so without it
                the band covered the top half of the logo. */}
            <div className="relative z-10 -mt-12 w-24 h-24 shrink-0 rounded-2xl bg-white ring-4 ring-white shadow-lg overflow-hidden flex items-center justify-center">
              {logoUrl ? (
                // A blob: URL from an auth-gated fetch — next/image cannot load it.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={logoUrl} alt="Company logo" className="max-w-full max-h-full object-contain p-2" />
              ) : (
                <span className="w-full h-full flex items-center justify-center bg-gradient-to-br from-[#1e4d8c] to-[#2d6cb5] text-white text-2xl font-bold">
                  {initialsOf(profile?.company_name || profile?.full_name)}
                </span>
              )}
            </div>

            <div className="pt-4 min-w-0">
              <h1 className="text-lg font-bold text-gray-900 truncate">{profile?.full_name || "My Profile"}</h1>
              <p className="text-xs text-gray-500 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5">
                {profile?.company_name && <span className="font-semibold text-gray-700">{profile.company_name}</span>}
                {profile?.email && <span className="flex items-center gap-1"><Mail className="w-3 h-3" />{profile.email}</span>}
              </p>
              <div className="flex flex-wrap items-center gap-1.5 mt-2">
                {profile && (
                  <Badge tone="slate">{profile.tenant_type === "individual" ? "Individual" : "Corporate"}</Badge>
                )}
                {profile?.role && (
                  <Badge tone="blue" icon={ShieldCheck}>{ROLE_LABELS[profile.role] ?? profile.role}</Badge>
                )}
                {profile?.is_verified && <Badge tone="green" icon={BadgeCheck}>Verified</Badge>}
                {profile && (scheme
                  ? <Badge tone="violet" icon={Receipt}>GST · {scheme.label}</Badge>
                  : <Badge tone="amber" icon={Receipt}>GST scheme not set</Badge>)}
              </div>
            </div>
          </div>

          <div className="flex gap-3 pt-4">
            <Stat label="Entities" value={counts.entities} onClick={() => setTab("entities")} />
            <Stat label="Login IDs / IATA" value={counts.logins} onClick={() => setTab("logins")} />
          </div>
        </div>

        {/* ── Tabs ─────────────────────────────────────────────────────────── */}
        <div className="px-4 border-t border-gray-100 flex items-center gap-1 overflow-x-auto">
          {TABS.map(t => {
            const active = tab === t.key;
            const n = countFor(t.key);
            return (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`flex items-center gap-1.5 px-3.5 py-3 text-xs font-semibold border-b-2 -mb-px whitespace-nowrap transition-colors ${
                  active ? "border-[#1e4d8c] text-[#1e4d8c]" : "border-transparent text-gray-400 hover:text-gray-700"
                }`}>
                <t.icon className="w-3.5 h-3.5" /> {t.label}
                {n != null && (
                  <span className={`ml-0.5 min-w-5 px-1.5 py-px rounded-full text-[10px] font-bold ${
                    active ? "bg-[#1e4d8c] text-white" : "bg-gray-100 text-gray-500"
                  }`}>{n}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab body ────────────────────────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 p-6 shadow-sm">
        {tab === "info" && <ProfileInfoSection onProfileChange={setProfile} />}
        {tab === "entities" && <EntitiesSection onChange={recount} />}
        {tab === "logins" && <LoginIdsSection onChange={recount} />}
      </div>
    </div>
  );
}

const TONES = {
  slate: "bg-slate-50 text-slate-600 border-slate-200",
  blue: "bg-blue-50 text-blue-700 border-blue-200",
  green: "bg-emerald-50 text-emerald-700 border-emerald-200",
  violet: "bg-violet-50 text-violet-700 border-violet-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
} as const;

function Badge({ tone, icon: Icon, children }: {
  tone: keyof typeof TONES;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] font-semibold ${TONES[tone]}`}>
      {Icon && <Icon className="w-3 h-3" />}{children}
    </span>
  );
}

/** A count in the header that is also a shortcut to its tab. */
function Stat({ label, value, onClick }: { label: string; value: number | null; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className="text-left rounded-xl border border-gray-200 bg-gray-50/60 hover:bg-white hover:border-gray-300 hover:shadow-sm transition-all px-4 py-2.5 min-w-[120px]">
      <p className="text-xl font-bold text-gray-900 leading-none">{value ?? "—"}</p>
      <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide mt-1.5">{label}</p>
    </button>
  );
}
