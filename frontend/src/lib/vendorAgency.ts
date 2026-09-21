// The Supplier Name on an INCOMING B2B deal, picked from the user's own Agency Master.
//
// It used to be picked from the platform-admin supplier master. It now lists the agencies
// the user onboarded in User master → Agency Master — the parties they actually buy from,
// with their branch, channel, entities, login ids and vendor service charge.
//
// WHAT THE DEAL IS MATCHED BY DOES NOT CHANGE. The form sends `vendor_agency_id`; the server
// derives `supplier_name` AND `supplier_id` from that agency (backend api/v1/deals.py
// ::_resolve_vendor_agency). `supplier_id` is the supplier-master row the agency was copied
// from, which is still what a third-party statement is matched against — so the commission
// matcher never learns the form changed.
//
// Shared by Create Deal (/deals/new) and Upload (/deals/upload) so the two pickers can never
// label, order or resolve an agency differently.

import api from "@/lib/api";

export type VendorAgency = {
  id: number;
  name: string;
  branch_name: string | null;
  branch_code: string;
  channels: string;             // GDS | LCC (| legacy BOTH)
  supplier_id: number | null;   // the supplier-master row it was copied from; null if typed by hand
  is_active: boolean;
};

/** "Lords Travels — Delhi · GDS".
 *
 *  BRANCH AND CHANNEL, ALWAYS. One vendor is onboarded once per branch and once per
 *  channel, so "Lords Travels" alone is up to several rows with different terms, entities
 *  and credentials — the same label rule every agency dropdown in this app follows
 *  (see models/agency.py). */
function baseLabel(a: VendorAgency): string {
  return `${a.name} — ${a.branch_name || a.branch_code} · ${a.channels}`;
}

export type VendorAgencyOptions = {
  /** Labels in display order, for a string-based SearchSelect. */
  labels: string[];
  /** Label → agency. Every label is unique, so this never loses a row. */
  byLabel: Map<string, VendorAgency>;
  /** Agency id → its label, for pre-selecting a saved deal. */
  labelOf: (id: number | null | undefined) => string;
};

/** Build the picker's options from the user's agencies.
 *
 *  LABELS ARE MADE UNIQUE, because the picker hands back a string and two rows must never
 *  collapse into one option. `branch_name` is display text copied from the master and two
 *  branches of one vendor can share it (two offices in one city), so on a clash the branch
 *  CODE is added — it is part of the agencies' own unique key, so that settles it.
 *
 *  Inactive agencies are left out of a NEW pick, but `keepId` — the agency a saved deal
 *  already names — is always kept, so editing an old deal never silently empties the field
 *  because its agency has since been deactivated. */
export function vendorAgencyOptions(all: VendorAgency[], keepId?: number | null): VendorAgencyOptions {
  const rows = all
    .filter(a => a.is_active || a.id === keepId)
    .sort((x, y) => baseLabel(x).localeCompare(baseLabel(y)));

  const counts = new Map<string, number>();
  for (const a of rows) counts.set(baseLabel(a), (counts.get(baseLabel(a)) ?? 0) + 1);

  const byLabel = new Map<string, VendorAgency>();
  const byId = new Map<number, string>();
  for (const a of rows) {
    let label = baseLabel(a);
    if ((counts.get(label) ?? 0) > 1) label = `${a.name} — ${a.branch_name || a.branch_code} (${a.branch_code}) · ${a.channels}`;
    if (!a.is_active) label += " (inactive)";
    byLabel.set(label, a);
    byId.set(a.id, label);
  }
  return {
    labels: Array.from(byLabel.keys()),
    byLabel,
    labelOf: id => (id != null ? byId.get(id) ?? "" : ""),
  };
}

/** The agency a deal saved BEFORE this field listed agencies most likely meant, or null.
 *
 *  Such a deal carries only a supplier-master name (and maybe a supplier_id). It is linked
 *  only when EXACTLY ONE agency fits — the same conservative rule the backend migrations use.
 *  A vendor onboarded on both GDS and LCC fits twice, and picking one of those would be
 *  choosing a channel on the user's behalf; returning null leaves them to pick it, and until
 *  they do the deal keeps its name and supplier id and matches exactly as it always has. */
export function matchSavedVendor(
  all: VendorAgency[], supplierName: string | null | undefined, supplierId: number | null | undefined,
): VendorAgency | null {
  const name = (supplierName ?? "").trim().toLowerCase();
  if (!name) return null;
  const hits = all.filter(a =>
    a.name.trim().toLowerCase() === name
    // A saved supplier id narrows it to the right BRANCH when the vendor has several.
    && (supplierId == null || a.supplier_id == null || a.supplier_id === supplierId),
  );
  return hits.length === 1 ? hits[0] : null;
}

/** The user's agencies (User master → Agency Master). User-scoped on the server. */
export async function loadVendorAgencies(): Promise<VendorAgency[]> {
  const r = await api.get<VendorAgency[]>("/agencies/", { params: { limit: 1000 } });
  return r.data;
}
