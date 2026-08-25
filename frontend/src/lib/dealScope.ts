// WHO an outgoing (floated) deal is for.
//
// Three flat choices, no sub-questions:
//
//   B2B         → one named agency      (its entities and login IDs follow)
//   Corporate   → one named corporate   (a B2E customer)
//   Common Deal → every customer, of any type
//
// So "B2B" IS agency-specific and "Corporate" IS corporate-specific — picking one
// means picking a party. A deal that should reach everyone is a Common Deal; there
// is deliberately no per-type "all agencies" / "all corporates" middle rung.
//
// The backend stores the answer as a single `scope_type`, because one indexable
// scalar is what the commission engine has to match a ticket against:
//
//     scope_type = 'all'                      -- reaches everyone
//     OR (scope_type = 'agency'    AND agency_id    = :party)
//     OR (scope_type = 'corporate' AND corporate_id = :party)
//
// This file is the only place the form's shape and the stored shape are converted,
// so the two deal forms cannot drift apart.
//
// Incoming deals have no customer and are always `all`.

export type DealScopeType =
  | "agency"      // one named agency
  | "corporate"   // one named corporate
  | "all";        // every customer, of any kind

/** The three cards the outgoing form shows as "Deal Type". */
export type OutgoingDealKind = "b2b" | "corporate" | "common";

export const OUTGOING_DEAL_KINDS: {
  key: OutgoingDealKind; label: string; blurb: string;
}[] = [
  { key: "b2b",       label: "B2B",         blurb: "For one agency you float deals to" },
  { key: "corporate", label: "Corporate",   blurb: "For one B2E corporate customer" },
  { key: "common",    label: "Common Deal", blurb: "For every customer, of any type" },
];

/**
 * The Line of Business each kind implies, used to pre-fill Business Type.
 * A corporate customer is B2E. Left editable on the form — this is a default,
 * not a constraint.
 */
export const KIND_BUSINESS_TYPE: Record<OutgoingDealKind, string> = {
  b2b:       "B2B",
  corporate: "B2E",
  common:    "",
};

/** Form answer → what the API stores. */
export function toScopeType(kind: OutgoingDealKind): DealScopeType {
  if (kind === "b2b") return "agency";
  if (kind === "corporate") return "corporate";
  return "all";
}

/** What the API stored → the form answer, for re-opening a saved deal. */
export function fromScopeType(scope: DealScopeType | string | null | undefined): OutgoingDealKind {
  if (scope === "agency") return "b2b";
  if (scope === "corporate") return "corporate";
  return "common";
}

/**
 * The repository a deal belongs to. `/deals` alone is the INCOMING repo, so every
 * exit from an outgoing form — save, cancel, back — has to carry the direction or
 * the user lands in the wrong list and thinks the deal vanished.
 */
export function dealsHref(direction: string | null | undefined): string {
  return direction === "outbound" ? "/deals?direction=outbound" : "/deals";
}

/** Direction badge text. The repos are "Incoming" and "Outgoing". */
export function directionLabel(direction: string | null | undefined): string {
  return direction === "outbound" ? "Outgoing" : "Incoming";
}

/** Short human label — repository chips, summaries. */
export function scopeLabel(scope: DealScopeType | string | null | undefined): string {
  if (scope === "agency") return "Agency";
  if (scope === "corporate") return "Corporate";
  return "All Customers";
}

/** Does this scope name a single party the user has to pick? */
export function needsParty(scope: DealScopeType): boolean {
  return scope === "agency" || scope === "corporate";
}

/** The scope block every deal-writing payload carries. */
export type DealScopePayload = {
  scope_type: DealScopeType;
  agency_id: number | null;
  corporate_id: number | null;
  agency_entity_id: number | null;
};

/**
 * Build the payload block. Mirrors the server's own re-derivation, so a stale id
 * left in component state can never reach the API attached to the wrong scope —
 * which is exactly what the database CHECK would reject.
 */
export function buildScopePayload(
  scope: DealScopeType,
  agencyId: number | null,
  corporateId: number | null,
  agencyEntityId: number | null,
): DealScopePayload {
  return {
    scope_type: scope,
    agency_id:        scope === "agency"    ? agencyId    : null,
    corporate_id:     scope === "corporate" ? corporateId : null,
    agency_entity_id: scope === "agency"    ? agencyEntityId : null,
  };
}
