// Central vocabulary for the three customer types the Customer Directory covers:
// a direct customer, a B2B agency, or a corporate. Each has its own master under
// User master, its own table and its own API — this file is the adapter that lets
// one screen show all three.
//
// DELIBERATELY SEPARATE FROM lib/party.ts. `PartyKind` there is
// "customer" | "corporate" and drives PARTY[kind].resource → /customers/ or
// /corporates/. An agency has none of first_name / markup_type / billing_type and
// a different API shape entirely, so widening that union would break
// PartyDirectory, PartyModal, PartyUploadModal and the four pages that render
// them. Only the `Party` type and partyName() are borrowed.
//
// Icon-free on purpose (like lib/party.ts and lib/statements.ts) — the lucide
// components live with the components that render them, so this stays plain data.

import type { Party } from "@/lib/party";
import { partyName } from "@/lib/party";

export type CounterpartyKind = "direct" | "agency" | "corporate";

/** Order the type tabs and the table's secondary sort. */
export const COUNTERPARTY_KINDS: CounterpartyKind[] = ["direct", "agency", "corporate"];

export const COUNTERPARTY: Record<CounterpartyKind, {
  label: string;
  plural: string;
  /** Badge classes — one hue per type, matching the app's existing chip styling. */
  badge: string;
  masterHref: string;
  masterLabel: string;
}> = {
  direct: {
    label: "Direct",
    plural: "Direct customers",
    badge: "bg-emerald-50 text-emerald-700 border-emerald-200",
    masterHref: "/user-master/employee-master",
    masterLabel: "Employee Master",
  },
  agency: {
    label: "Agency",
    plural: "Agencies",
    badge: "bg-sky-50 text-sky-700 border-sky-200",
    masterHref: "/user-master/agency-master",
    masterLabel: "Agency Master",
  },
  corporate: {
    label: "Corporate",
    plural: "Corporates",
    badge: "bg-violet-50 text-violet-700 border-violet-200",
    masterHref: "/user-master/corporate-master",
    masterLabel: "Corporate Master",
  },
};

// ── Source row shapes ───────────────────────────────────────────────────────

/** One row of GET /agencies/ (AgencyRead) — only the fields the directory reads. */
export type AgencyRow = {
  id: number;
  name: string;
  branch_code: string;
  branch_name: string | null;
  channels: string;                 // GDS | LCC | BOTH
  contact_phone: string | null;
  contact_email: string | null;
  gst_registered: boolean;
  gst_number: string | null;
  pan_number: string | null;
  is_active: boolean;
};

/** One row of GET /agencies/overview — the counts, which /agencies/ does not carry. */
export type AgencyCounts = {
  id: number;
  entity_count: number;
  login_id_count: number;
};

// ── The unified row ─────────────────────────────────────────────────────────

export type Counterparty = {
  kind: CounterpartyKind;
  id: number;
  /**
   * The three source tables have independent id sequences, so ids collide across
   * them. This is what identifies a row — never the bare id.
   */
  key: string;
  name: string;
  company: string | null;
  phone: string | null;
  email: string | null;
  gstRegistered: boolean;
  gstNo: string | null;
  panNo: string | null;
  isActive: boolean;
  // ── agency only ──
  branchCode: string | null;
  branchName: string | null;
  channels: string | null;
  entityCount: number | null;
  loginIdCount: number | null;
  // ── direct / corporate only ──
  markupType: Party["markup_type"];
  markupValue: number | null;
  billingType: Party["billing_type"];
};

// ── Adapters ────────────────────────────────────────────────────────────────
// The three models name identical concepts differently (phone/contact_phone,
// gst_no/gst_number, pan_no/pan_number) and models/customer.py:25-26 says that
// split is intentional. Normalise here; never rename a column.

export function fromAgency(a: AgencyRow, counts?: AgencyCounts): Counterparty {
  return {
    kind: "agency",
    id: a.id,
    key: `agency-${a.id}`,
    name: a.name,
    company: null,               // an agency's `name` IS the company
    phone: a.contact_phone,
    email: a.contact_email,
    gstRegistered: a.gst_registered,
    gstNo: a.gst_number,
    panNo: a.pan_number,
    isActive: a.is_active,
    branchCode: a.branch_code,
    branchName: a.branch_name,
    channels: a.channels,
    entityCount: counts?.entity_count ?? 0,
    loginIdCount: counts?.login_id_count ?? 0,
    markupType: null,
    markupValue: null,
    billingType: null,
  };
}

export function fromParty(p: Party, kind: "direct" | "corporate"): Counterparty {
  return {
    kind,
    id: p.id,
    key: `${kind}-${p.id}`,
    name: partyName(p),
    company: p.company,
    phone: p.phone,
    email: p.email,
    gstRegistered: p.gst_registered,
    gstNo: p.gst_no,
    panNo: p.pan_no,
    isActive: p.is_active,
    branchCode: null,
    branchName: null,
    channels: null,
    entityCount: null,
    loginIdCount: null,
    markupType: p.markup_type,
    markupValue: p.markup_value,
    billingType: p.billing_type,
  };
}

// ── Display helpers ─────────────────────────────────────────────────────────

/**
 * The ONLY safe label for an agency in a list or a dropdown.
 *
 * An agency row is one branch on one channel (models/agency.py:61-86): a vendor
 * working both GDS and LCC is onboarded twice, and Lords Delhi and Lords Mumbai
 * are separate commercial relationships. A label that stops at the name — or even
 * at the branch — renders two identical options the user cannot tell apart.
 */
export function agencyLabel(a: Pick<AgencyRow, "name" | "branch_name" | "branch_code" | "channels">): string {
  return `${a.name} — ${a.branch_name || a.branch_code} · ${a.channels}`;
}

/** "BOTH" is two badges, not one — it predates the one-row-per-channel split. */
export function channelBadges(channels: string | null): string[] {
  if (!channels) return [];
  return channels === "BOTH" ? ["GDS", "LCC"] : [channels];
}

/** What the directory's search box matches against. */
export function searchBlob(c: Counterparty): string {
  return [c.name, c.company, c.branchName, c.branchCode, c.email, c.phone]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

/** Company for a direct/corporate row; branch · channel for an agency. */
export function subtitleOf(c: Counterparty): string | null {
  if (c.kind !== "agency") return c.company;
  const branch = c.branchName || c.branchCode;
  return branch ? `${branch} · ${c.channels}` : c.channels;
}
