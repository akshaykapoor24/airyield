"use client";

// The party half of an outgoing deal's scope: WHO it is floated to.
//
// Shared by Create Deal and Upload Deal so the two cannot disagree about what an
// outgoing deal names. Each page owns the "Deal Type" cards in its own layout and
// hands the resolved scope down here; this component owns everything below it —
// the agency or corporate picker, and for an agency its entities and login IDs.
//
// Renders nothing at all for the three "all" scopes: a deal for every agency has
// no branch, no entity and no credential to choose.

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle } from "lucide-react";
import api from "@/lib/api";
import { agencyLabel, type AgencyRow } from "@/lib/counterparty";
import { corporateLabel, type Party } from "@/lib/party";
import { SearchSelectField, MultiSearchSelectField } from "@/components/deals/IncentiveInclExclShared";
import type { DealScopeType } from "@/lib/dealScope";

type EntityRow = { id: number; name: string; code: string; is_active: boolean };
type LoginRow  = { id: number; login_id: string; entity_id: number | null; entity_name: string | null; is_active: boolean };

export type ScopeSelection = {
  agencyId: number | null;
  corporateId: number | null;
  agencyEntityId: number | null;
  /** Entity NAME — what Deal.entity stores. */
  entity: string;
  /** Login-id STRINGS — what Deal.login_ids stores. */
  loginIds: string[];
};

export default function OutgoingScopeFields({
  scope, value, onChange, touched,
}: {
  scope: DealScopeType;
  value: ScopeSelection;
  onChange: (next: ScopeSelection) => void;
  touched?: boolean;
}) {
  const [agencies,   setAgencies]   = useState<AgencyRow[]>([]);
  const [corporates, setCorporates] = useState<Party[]>([]);
  const [entities,   setEntities]   = useState<EntityRow[]>([]);
  const [logins,     setLogins]     = useState<LoginRow[]>([]);
  const [loadedParties, setLoadedParties] = useState(false);

  const needsAgency    = scope === "agency";
  const needsCorporate = scope === "corporate";

  // Both master lists, once. Neither endpoint filters is_active, so that is done
  // here — an agency you have retired should not be offered a new deal.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [a, c] = await Promise.allSettled([
        api.get<AgencyRow[]>("/agencies/", { params: { limit: 1000 } }),
        api.get<Party[]>("/corporates/", { params: { limit: 1000 } }),
      ]);
      if (cancelled) return;
      if (a.status === "fulfilled") setAgencies(a.value.data.filter(x => x.is_active));
      if (c.status === "fulfilled") setCorporates(c.value.data.filter(x => x.is_active));
      setLoadedParties(true);
    })();
    return () => { cancelled = true; };
  }, []);

  // Entities AND login IDs together, both keyed on the agency alone.
  //
  // Deliberately NOT "entity first, then its login IDs": agency_login_ids.entity_id
  // is nullable and the Agency Master lets you add a credential without an entity,
  // so requiring one hid every such credential from every deal. The entity below
  // narrows the list; it does not gate it.
  const agencyId = value.agencyId;
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  useEffect(() => {
    if (!needsAgency || !agencyId) return;
    let cancelled = false;
    (async () => {
      const [e, l] = await Promise.allSettled([
        api.get<EntityRow[]>("/agency-entities/", { params: { agency_id: agencyId, limit: 1000 } }),
        api.get<LoginRow[]>("/agency-login-ids/", { params: { agency_id: agencyId, limit: 1000 } }),
      ]);
      if (cancelled) return;
      setEntities(e.status === "fulfilled" ? e.value.data.filter(x => x.is_active) : []);
      setLogins(l.status === "fulfilled" ? l.value.data.filter(x => x.is_active) : []);
      setLoadedFor(agencyId);
    })();
    return () => { cancelled = true; };
  }, [needsAgency, agencyId]);

  // Derived rather than cleared in the effect above: `entities` still holds the
  // PREVIOUS agency's rows for the moment between picking a new one and its
  // fetch landing, and offering those would attach one agency's entity to
  // another's deal. Gating on loadedFor closes that window.
  const ready = needsAgency && !!agencyId && loadedFor === agencyId;
  const agencyEntities = ready ? entities : [];
  const agencyLogins   = ready ? logins   : [];

  if (!needsAgency && !needsCorporate) return null;

  const set = (patch: Partial<ScopeSelection>) => onChange({ ...value, ...patch });

  // ── Corporate ──
  if (needsCorporate) {
    const byLabel = new Map(corporates.map(c => [corporateLabel(c), c]));
    const selected = corporates.find(c => c.id === value.corporateId);
    if (loadedParties && corporates.length === 0) {
      return <EmptyMaster what="corporates" href="/user-master/corporate-master" label="Corporate Master" />;
    }
    return (
      <SearchSelectField
        label="Corporate"
        required
        placeholder={loadedParties ? "Search and select" : "Loading corporates..."}
        options={[...byLabel.keys()]}
        value={selected ? corporateLabel(selected) : ""}
        onChange={(v) => set({ corporateId: byLabel.get(v)?.id ?? null })}
      />
    );
  }

  // ── Agency ──
  // Agencies MUST be labelled name — branch · channel: one vendor is onboarded
  // once per branch AND once per channel, so a bare name renders two identical
  // options the user cannot tell apart.
  const byLabel = new Map(agencies.map(a => [agencyLabel(a), a]));
  const selected = agencies.find(a => a.id === value.agencyId);
  const selectedEntity = agencyEntities.find(e => e.id === value.agencyEntityId);

  if (loadedParties && agencies.length === 0) {
    return <EmptyMaster what="agencies" href="/user-master/agency-master" label="Agency Master" />;
  }

  // The entity narrows the credential list without gating it; credentials with no
  // entity stay visible either way, or they would be unreachable.
  const visibleLogins = value.agencyEntityId
    ? agencyLogins.filter(l => l.entity_id === value.agencyEntityId || l.entity_id == null)
    : agencyLogins;

  return (
    <>
      <SearchSelectField
        label="Agency"
        required
        placeholder={loadedParties ? "Search and select" : "Loading agencies..."}
        options={[...byLabel.keys()]}
        value={selected ? agencyLabel(selected) : ""}
        onChange={(v) => {
          // Changing the agency invalidates everything under it.
          const a = byLabel.get(v);
          set({ agencyId: a?.id ?? null, agencyEntityId: null, entity: "", loginIds: [] });
        }}
      />

      <SearchSelectField
        label="Agency Entity"
        placeholder={
          !value.agencyId ? "Select an agency first"
          : agencyEntities.length === 0 ? "No entities for this agency"
          : "Search and select"
        }
        options={agencyEntities.map(e => e.name)}
        value={selectedEntity?.name ?? value.entity}
        onChange={(v) => {
          const e = agencyEntities.find(x => x.name === v);
          set({
            agencyEntityId: e?.id ?? null,
            entity: v,
            // Drop any credential that the newly-chosen entity does not cover.
            loginIds: value.loginIds.filter(id => {
              const l = agencyLogins.find(x => x.login_id === id);
              return !e || !l || l.entity_id === e.id || l.entity_id == null;
            }),
          });
        }}
      />

      <MultiSearchSelectField
        label="Agency Login ID"
        placeholder={
          !value.agencyId ? "Select an agency first"
          : visibleLogins.length === 0 ? "No login IDs for this agency"
          : "Search and select"
        }
        options={visibleLogins.map(l => l.login_id)}
        values={value.loginIds}
        onChange={(v) => set({ loginIds: v })}
      />

      {touched && !value.agencyId && (
        <p className="text-[11px] text-red-500 -mt-1">Agency is required for an agency-specific deal.</p>
      )}
    </>
  );
}

function EmptyMaster({ what, href, label }: { what: string; href: string; label: string }) {
  return (
    <div className="col-span-2 flex items-start gap-2 px-3 py-2.5 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800">
      <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-px" />
      <span>
        You have not onboarded any {what} yet.{" "}
        <Link href={href} className="font-semibold underline">Add them in {label}</Link>, then come back
        — or choose a Common deal, which needs no party.
      </span>
    </div>
  );
}
