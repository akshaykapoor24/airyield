// WHO a ticket was sold to.
//
// Three kinds, matching the three masters under User master:
//
//   agency     a B2B customer  — an agency onboarded in Agency Master
//   corporate  a B2E customer  — a company in Corporate Master
//   direct     anyone else     — a walk-in, optionally in Customer Master
//
// This is the CUSTOMER axis, and it is not the same thing as the statement's
// `statement_type` (B2B | AIRLINE), which describes the shape of the FILE the
// rows came from. The customer-side commission run matches an outgoing deal
// against this; it never looks at statement_type.
//
// "direct" needs no id: a walk-in who is not in Customer Master is still not an
// agency and not a corporate, and that alone is enough to price the ticket.

export type CustomerType = "agency" | "corporate" | "direct";

export const CUSTOMER_TYPES: {
  key: CustomerType; label: string; short: string; blurb: string; badge: string;
}[] = [
  // `short` is for the narrow 3-up control on the Create Ticket filing row,
  // where the full label wraps to three lines.
  { key: "agency",    label: "B2B (Agency)",    short: "B2B",       blurb: "An agency you onboarded", badge: "bg-sky-50 text-sky-700 border-sky-200" },
  { key: "corporate", label: "B2E (Corporate)", short: "B2E",       blurb: "A corporate customer",    badge: "bg-violet-50 text-violet-700 border-violet-200" },
  { key: "direct",    label: "Direct Customer", short: "Direct",    blurb: "A walk-in or individual", badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
];

export const CUSTOMER_TYPE_LABEL: Record<CustomerType, string> = {
  agency: "B2B", corporate: "Corporate", direct: "Direct",
};

export const CUSTOMER_TYPE_BADGE: Record<CustomerType, string> =
  Object.fromEntries(CUSTOMER_TYPES.map(t => [t.key, t.badge])) as Record<CustomerType, string>;

/** The master each type is picked from. */
export const CUSTOMER_TYPE_MASTER: Record<CustomerType, { href: string; label: string }> = {
  agency:    { href: "/user-master/agency-master",    label: "Agency Master" },
  corporate: { href: "/user-master/corporate-master", label: "Corporate Master" },
  direct:    { href: "/user-master/customer-master",  label: "Customer Master" },
};

/** What a statement/ticket sends to the API. */
export type CustomerTag = {
  customerType: CustomerType | null;
  agencyId: number | null;
  corporateId: number | null;
  customerId: number | null;
  /** Display name of the picked party — shown in the form, derived server-side on save. */
  partyName: string;
};

export const EMPTY_TAG: CustomerTag = {
  customerType: null, agencyId: null, corporateId: null, customerId: null, partyName: "",
};

/**
 * Is the tag answerable? Agency and corporate must name a party; a direct
 * customer need not, because a walk-in may have no master record.
 */
export function isTagComplete(t: CustomerTag): boolean {
  if (!t.customerType) return false;
  if (t.customerType === "agency")    return t.agencyId != null;
  if (t.customerType === "corporate") return t.corporateId != null;
  return true;
}

/** The scope block sent to the API. Mirrors the server's own re-derivation, so a
 *  stale id from a previous type can never travel attached to the wrong one. */
export function buildTagPayload(t: CustomerTag) {
  return {
    customer_type:      t.customerType,
    customer_agency_id: t.customerType === "agency"    ? t.agencyId    : null,
    corporate_id:       t.customerType === "corporate" ? t.corporateId : null,
    customer_id:        t.customerType === "direct"    ? t.customerId  : null,
  };
}
