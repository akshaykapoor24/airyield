// Central registry for the two billable counter-party directories.
//
// `customers` and `corporates` are separate backend tables sharing MOST of their
// shape (see backend/app/models/{customer,corporate}.py) and near-identical
// routers. One `Party` type, one config record, two resources.
//
// WHERE THE TWO DIVERGE. A customer is a PERSON — first_name / last_name / title.
// A corporate is an ORGANISATION: its `company` IS its name, it has a
// `corporate_type` (legal form) and a registered address, and it has no person
// name at all. `Party` is the union of both, so every field either side lacks is
// optional here, and `kind` is what decides which half a screen renders.
//
// Each party lives on two pages:
//   master  — User master → Customer/Corporate Master: add, edit, import, delete
//   billing — Billing → Customer/Corporate Billing: pick one and bill it
// Both render <PartyDirectory kind mode />; `mode` is what makes them differ.
//
// Icon-free on purpose (like lib/statements.ts) — the lucide components live in
// components/party/icons.ts so this stays plain data.

export type MarkupType = "percentage" | "fixed";
export type BillingType = "reseller" | "agency";

export type Party = {
  id: number;
  /** Customer: the person's name. Corporate: absent — see `company`. Pre-split
   *  corporate rows may still carry one (backend migration corp_entity_01). */
  first_name?: string | null;
  last_name?: string | null;
  /**
   * Customer: the corporate they work for — set together with `company`, null
   * when they are an individual / direct. Never present on a corporate.
   */
  corporate_id?: number | null;
  /**
   * Customer: their employer's name, mirroring the linked corporate (a value
   * with no `corporate_id` is pre-link free text). Corporate: THE name, required.
   */
  company: string | null;
  title?: string | null;
  /** Corporate only — legal form; one of CORPORATE_TYPES below. */
  corporate_type?: string | null;
  // ── Corporate only: registered address ──
  address?: string | null;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
  country?: string | null;
  phone: string | null;
  email: string | null;
  // Party-local naming (gst_no / pan_no) — the profile/supplier modules use
  // gst_number / pan_number; intentionally kept separate. Only the regexes are shared.
  gst_registered: boolean;
  gst_no: string | null;
  pan_no: string | null;
  markup_type: MarkupType | null;
  markup_value: number | null;
  billing_type: BillingType | null;
  is_active: boolean;
  /**
   * Tickets HARD-LINKED to this party — uploaded_tickets.customer_id for a customer,
   * .corporate_id for a corporate. Sent by the LIST endpoints only, hence optional.
   *
   * Untagged tickets that the billing screen additionally reaches by passenger name are
   * NOT counted here: that half of the rule is per-party and cannot be a grouped
   * aggregate (backend/app/services/billing_calc.py). So this can read lower than the
   * drill-down. It is exact for LCC-sourced tickets, which always carry the link.
   */
  ticket_count?: number;
  unbilled_ticket_count?: number;
};

export type PartyKind = "customer" | "corporate";
export type PartyMode = "master" | "billing";

export type PartyConfig = {
  kind: PartyKind;
  /** API segment — also drives /{resource}/template and /{resource}/bulk-upload. */
  resource: "customers" | "corporates";
  /** What Billing calls one of these. */
  singular: string;
  plural: string;
  /**
   * What USER MASTER calls one of these, which is not always the same word: the
   * `customers` table is maintained as Employee Master (people, each either an
   * employee of a corporate or an individual) and billed as Customer Billing.
   * Every string on a master-mode screen uses this pair; Billing uses the one
   * above. For a corporate the two are identical.
   */
  masterSingular: string;
  masterPlural: string;
  masterHref: string;
  masterLabel: string;
  billingHref: string;
  billingLabel: string;
  detailHref: (id: number) => string;
  templateFile: string;
  templateColumns: string;
  /** Anything about the import that the column list alone does not explain. */
  templateNote?: string;
  emailPlaceholder: string;
};

export const PARTY: Record<PartyKind, PartyConfig> = {
  customer: {
    kind: "customer",
    resource: "customers",
    singular: "Customer",
    plural: "Customers",
    masterSingular: "Employee",
    masterPlural: "Employees",
    masterHref: "/user-master/employee-master",
    masterLabel: "Employee Master",
    billingHref: "/customers",
    billingLabel: "Customer Billing",
    detailHref: (id) => `/customers/${id}`,
    templateFile: "customer_template.xlsx",
    templateColumns:
      "FIRST_NAME, LAST_NAME, COMPANY, TITLE, PHONE, EMAIL, GST_REGISTERED (Registered|Unregistered), GST_NO, PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency)",
    templateNote:
      "COMPANY is matched to Corporate Master by name — an exact match links the employee to that corporate AND fills in any markup, billing, GST, PAN, phone or email you left blank, from that corporate. Anything you do fill in is kept. No match is left as an individual.",
    emailPlaceholder: "customer@email.com",
  },
  corporate: {
    kind: "corporate",
    resource: "corporates",
    singular: "Corporate",
    plural: "Corporates",
    masterSingular: "Corporate",
    masterPlural: "Corporates",
    masterHref: "/user-master/corporate-master",
    masterLabel: "Corporate Master",
    billingHref: "/corporates",
    billingLabel: "Corporate Billing",
    detailHref: (id) => `/corporates/${id}`,
    templateFile: "corporate_template.xlsx",
    templateColumns:
      "COMPANY, CORPORATE_TYPE, PHONE, EMAIL, ADDRESS, CITY, STATE, PINCODE, COUNTRY, GST_REGISTERED (Registered|Unregistered), GST_NO, PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency)",
    emailPlaceholder: "corporate@email.com",
  },
};

/**
 * Legal form of a corporate entity. The slugs are what the column stores — keep
 * them in step with backend/app/api/v1/corporates.py:_CORPORATE_TYPES, which
 * also maps the spellings people type into an Excel import onto these.
 */
export const CORPORATE_TYPES: { value: string; label: string }[] = [
  { value: "proprietorship",  label: "Proprietorship / Proprietary Firm" },
  { value: "partnership",     label: "Partnership Firm" },
  { value: "llp",             label: "LLP (Limited Liability Partnership)" },
  { value: "private_limited", label: "Private Limited Company" },
  { value: "public_limited",  label: "Public Limited Company" },
  { value: "opc",             label: "One Person Company (OPC)" },
  { value: "huf",             label: "HUF (Hindu Undivided Family)" },
  { value: "trust",           label: "Trust" },
  { value: "society",         label: "Society / NGO" },
  { value: "government",      label: "Government / PSU" },
  { value: "other",           label: "Other" },
];

export function corporateTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return CORPORATE_TYPES.find((t) => t.value === value)?.label ?? value;
}

// Shared with ProfileInfoSection / signup: GSTIN = 15 chars, PAN = 10 chars.
export const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export function markupTypeLabel(p: Party): string {
  if (!p.markup_type) return "—";
  return p.markup_type === "percentage" ? "Percentage" : "Fixed";
}

export function markupValueLabel(p: Party): string {
  if (p.markup_value == null || !p.markup_type) return "—";
  return p.markup_type === "percentage" ? `${p.markup_value}%` : `₹${p.markup_value}`;
}

export function billingTypeLabel(p: Party): string {
  if (!p.billing_type) return "—";
  return p.billing_type.charAt(0).toUpperCase() + p.billing_type.slice(1);
}

/**
 * What to call a party in a list, a heading or a dropdown.
 *
 * A customer is a person, so it is their name. A corporate has none, so it falls
 * back to `company` — which for a corporate is the name, not a fallback.
 */
export function partyName(p: Party): string {
  const person = `${p.first_name ?? ""} ${p.last_name ?? ""}`.trim();
  return person || (p.company ?? "").trim() || "—";
}

/**
 * A corporate in a picker. `company` IS the name, so it leads; a pre-split row
 * that also carries a contact name shows it after the dash. Never renders the
 * same string twice, which a naive `name — company` does now that partyName()
 * falls back to company.
 */
export function corporateLabel(p: Party): string {
  const org = (p.company ?? "").trim();
  const person = `${p.first_name ?? ""} ${p.last_name ?? ""}`.trim();
  if (org && person) return `${org} — ${person}`;
  return org || person || "—";
}

// ── What an employee inherits from their corporate ───────────────────────────

/**
 * The fields an employee picks up from the corporate they are attached to.
 *
 * These are terms of the relationship with the employer, not facts about the
 * person: the markup and billing type were agreed with the corporate, and when
 * the corporate is the party being invoiced, the GSTIN, PAN and billing contact
 * on that invoice are the corporate's too. Retyping them per employee is how
 * fifty people under one company end up on three different markups.
 *
 * INHERITED IS A DEFAULT, NOT A BINDING. Each value is copied into the
 * employee's own columns and can be edited straight after; nothing re-reads the
 * corporate later, so changing a corporate's markup does NOT move the employees
 * already on file. That is deliberate — a per-employee override has to survive
 * an edit to the parent, or it is not an override. (`company` is the exception
 * and really is kept in sync; see models/customer.py for why.)
 */
export const INHERITED_FIELDS = [
  "phone", "email", "markup_type", "markup_value",
  "billing_type", "gst_registered", "gst_no", "pan_no",
] as const;

export type InheritedField = (typeof INHERITED_FIELDS)[number];

/** Form values are all strings; GST Registration's empty state is "false", not "". */
export function isBlankInherited(key: InheritedField, value: string): boolean {
  return key === "gst_registered" ? value !== "true" : value.trim() === "";
}

/**
 * Re-seed the inherited fields after the user picks a different employer.
 *
 * A field is overwritten only when it is still blank, or when it is still
 * holding the LAST corporate's value (`held`) — anything the user typed is
 * theirs and survives. Picking Individual / Direct (corporate `null`) clears
 * what was inherited and leaves everything else alone.
 *
 * Returns the new values and the new held-set; nothing is mutated.
 */
export function seedFromCorporate(
  current: Record<InheritedField, string>,
  held: ReadonlySet<string>,
  corporate: Party | null,
): { values: Record<InheritedField, string>; held: Set<InheritedField> } {
  const source: Record<InheritedField, string> = {
    phone: corporate?.phone ?? "",
    email: corporate?.email ?? "",
    markup_type: corporate?.markup_type ?? "",
    markup_value: corporate?.markup_value != null ? String(corporate.markup_value) : "",
    billing_type: corporate?.billing_type ?? "",
    gst_registered: corporate?.gst_registered ? "true" : "false",
    gst_no: corporate?.gst_no ?? "",
    pan_no: corporate?.pan_no ?? "",
  };
  const values = { ...current };
  const nextHeld = new Set<InheritedField>();
  for (const key of INHERITED_FIELDS) {
    if (!held.has(key) && !isBlankInherited(key, current[key])) continue;   // theirs, not ours
    values[key] = source[key];
    if (corporate) nextHeld.add(key);
  }
  return { values, held: nextHeld };
}

/** "12 MG Road, Mumbai, Maharashtra - 400069, India" — blanks dropped. */
export function partyAddress(p: Party): string {
  const locality = [p.city, p.state].filter(Boolean).join(", ");
  const withPin = locality && p.pincode ? `${locality} - ${p.pincode}` : locality || p.pincode || "";
  return [p.address, withPin, p.country].map((s) => (s ?? "").trim()).filter(Boolean).join(", ");
}
