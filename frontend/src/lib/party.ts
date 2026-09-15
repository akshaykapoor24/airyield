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
/** Slugs, not labels — see MARKUP_CATEGORIES below and the server twin. */
export type MarkupCategory = "air" | "hotel" | "train" | "bus" | "car" | "mice";
/** Per-category overrides of a party's default markup. Absent = "as usual", never "free". */
export type CategoryMarkups = Partial<
  Record<MarkupCategory, { type: MarkupType; value: number }>
>;

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
  /** Per-category overrides of the two above. Null/absent means "no overrides". */
  category_markups?: CategoryMarkups | null;
  billing_type: BillingType | null;
  /** Customer only — the customer's own id for this person (a payroll or staff number).
   *  Optional, unique per workspace when set, and the ONLY field that can tell two
   *  employees of one name apart: everything else is either the name or inherited from
   *  their corporate. */
  employee_code?: string | null;
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
      "FIRST_NAME, LAST_NAME, EMPLOYEE_CODE, COMPANY, TITLE, PHONE, EMAIL, GST_REGISTERED (Registered|Unregistered), GST_NO, PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency), then optional AIR / HOTEL / TRAIN / BUS / CAR / MICE _MARKUP_TYPE + _MARKUP_VALUE",
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
      "COMPANY, CORPORATE_TYPE, PHONE, EMAIL, ADDRESS, CITY, STATE (required), PINCODE, COUNTRY, GST_REGISTERED (Registered|Unregistered), GST_NO (required when Registered), PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency), then optional AIR / HOTEL / TRAIN / BUS / CAR / MICE _MARKUP_TYPE + _MARKUP_VALUE",
    emailPlaceholder: "corporate@email.com",
  },
};

/**
 * Legal form of a corporate entity. The slugs are what the column stores — keep
 * them in step with backend/app/api/v1/corporates.py:_CORPORATE_TYPES, which
 * also maps the spellings people type into an Excel import onto these.
 */
export const CORPORATE_TYPES: { value: string; label: string; short: string }[] = [
  { value: "proprietorship",  label: "Proprietorship / Proprietary Firm",   short: "Proprietorship" },
  { value: "partnership",     label: "Partnership Firm",                    short: "Partnership" },
  { value: "llp",             label: "LLP (Limited Liability Partnership)", short: "LLP" },
  { value: "private_limited", label: "Private Limited Company",             short: "Pvt Ltd" },
  { value: "public_limited",  label: "Public Limited Company",              short: "Public Ltd" },
  { value: "opc",             label: "One Person Company (OPC)",            short: "OPC" },
  { value: "huf",             label: "HUF (Hindu Undivided Family)",        short: "HUF" },
  { value: "trust",           label: "Trust",                               short: "Trust" },
  { value: "society",         label: "Society / NGO",                       short: "Society / NGO" },
  { value: "government",      label: "Government / PSU",                    short: "Govt / PSU" },
  { value: "other",           label: "Other",                               short: "Other" },
];

export function corporateTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return CORPORATE_TYPES.find((t) => t.value === value)?.label ?? value;
}

/** The legal form in a word or two, for a list cell. "" when unset. */
export function corporateTypeShortLabel(value: string | null | undefined): string {
  if (!value) return "";
  return CORPORATE_TYPES.find((t) => t.value === value)?.short ?? value;
}

// Shared with ProfileInfoSection / signup: GSTIN = 15 chars, PAN = 10 chars.
export const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
export const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

/**
 * The six things a party can be quoted a different markup on.
 *
 * Keep them in step with backend/app/services/markup_categories.py:MARKUP_CATEGORIES,
 * exactly as CORPORATE_TYPES is kept in step with corporates.py:_CORPORATE_TYPES. The
 * SLUGS are what travel on the wire and are stored as the keys of `category_markups`;
 * the labels are only ever displayed.
 *
 * "air", not "flight": the statement parser's PRODUCT_VALUES uses Title-Case "Flight" as
 * display text, but every config slug in this product is lowercase. The server's
 * CATEGORY_ALIASES maps between them.
 */
export const MARKUP_CATEGORIES: { value: MarkupCategory; label: string }[] = [
  { value: "air", label: "Air" },
  { value: "hotel", label: "Hotel" },
  { value: "train", label: "Train" },
  { value: "bus", label: "Bus" },
  { value: "car", label: "Car" },
  { value: "mice", label: "MICE" },
];

/** Each override as its own "Hotel ₹500", in form order — for chips. */
export function categoryMarkupParts(p: Party): string[] {
  const set = p.category_markups ?? {};
  return MARKUP_CATEGORIES.flatMap(({ value, label }) => {
    const entry = set[value];
    if (!entry || entry.value == null || !entry.type) return [];
    return [`${label} ${entry.type === "percentage" ? `${entry.value}%` : `₹${entry.value}`}`];
  });
}

/** "Hotel ₹500 · Train 0%" — the overrides in one line, for a list cell or a detail row. */
export function categoryMarkupLabel(p: Party): string {
  return categoryMarkupParts(p).join(" · ");
}

/**
 * An employee in a picker. The same problem `agencyLabel` solves, and the same shape of
 * answer: two people of one name under one employer are legal now (they were refused
 * outright before services/party_dedupe grew the code facet), and a dropdown keyed on the
 * DISPLAY STRING resolves both to whichever `find` reaches first — silently tagging the
 * ticket to the wrong person. The code is what separates them.
 */
export function customerLabel(p: Party): string {
  const name = partyName(p);
  return p.employee_code ? `${name} · ${p.employee_code}` : name;
}

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
  "phone", "email", "markup_type", "markup_value", "category_markups",
  "billing_type", "gst_registered", "gst_no", "pan_no",
] as const;

export type InheritedField = (typeof INHERITED_FIELDS)[number];

/** Inherited together or not at all — party_inherit._PAIRED_FIELDS. */
const PAIRED_FIELDS: ReadonlySet<InheritedField> = new Set([
  "gst_registered", "gst_no", "markup_type", "markup_value",
]);

/**
 * Form values are strings — except `category_markups`, the one inherited field that is not
 * a text input. Keeping it in the same record is what lets `seedFromCorporate`'s loop stay
 * a single generic pass over INHERITED_FIELDS, exactly as the server's does.
 */
export type InheritedValues =
  Record<Exclude<InheritedField, "category_markups">, string> &
  { category_markups: CategoryMarkups };

/** GST Registration's empty state is "false", not ""; category markups' is an empty object.
 *  Mirrors party_inherit.is_blank, including its dict branch. */
export function isBlankInherited(
  key: InheritedField, value: string | CategoryMarkups,
): boolean {
  if (key === "category_markups") {
    return Object.keys((value as CategoryMarkups) ?? {}).length === 0;
  }
  if (key === "gst_registered") return value !== "true";
  return (value as string).trim() === "";
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
  current: InheritedValues,
  held: ReadonlySet<string>,
  corporate: Party | null,
): { values: InheritedValues; held: Set<InheritedField> } {
  const source: InheritedValues = {
    phone: corporate?.phone ?? "",
    email: corporate?.email ?? "",
    markup_type: corporate?.markup_type ?? "",
    markup_value: corporate?.markup_value != null ? String(corporate.markup_value) : "",
    // CLONED, not shared — the same reason party_inherit.py deep-copies it. Handing over
    // the corporate's own object would have the form and the loaded corporate pointing at
    // one dict, so editing a cell here would silently edit the corporate in the list.
    category_markups: corporate?.category_markups
      ? (structuredClone(corporate.category_markups) as CategoryMarkups)
      : {},
    billing_type: corporate?.billing_type ?? "",
    gst_registered: corporate?.gst_registered ? "true" : "false",
    gst_no: corporate?.gst_no ?? "",
    pan_no: corporate?.pan_no ?? "",
  };
  const values = { ...current };
  const nextHeld = new Set<InheritedField>();
  /** Still blank, or still holding the last corporate's value — ours to replace. */
  const free = (key: InheritedField) => held.has(key) || isBlankInherited(key, current[key]);
  const take = (key: InheritedField) => {
    (values as Record<string, unknown>)[key] = source[key];
    if (corporate) nextHeld.add(key);
  };

  for (const key of INHERITED_FIELDS) {
    if (PAIRED_FIELDS.has(key) || !free(key)) continue;
    // `category_markups` travels WHOLE, so an employee who set any override keeps all of
    // theirs — no per-key merge, matching the server.
    take(key);
  }

  // THE TWO PAIRS are decided together, exactly as party_inherit.inherit_from_corporate
  // decides them — the form and the import must give one employee the same terms.
  //
  // GST: only when NEITHER half is the user's own. Someone already marked Registered keeps
  // their registration, and is not handed the employer's GSTIN to go with it.
  if (free("gst_registered") && free("gst_no")) {
    take("gst_registered");
    take("gst_no");
  }
  // Markup: the type as usual, but the VALUE only under the corporate's own type. An
  // employee on "Fixed" taking a "Percentage 10" corporate's 10 would bill ₹10 a ticket
  // instead of 10%. A value held from the previous corporate is cleared rather than kept
  // under a type it was never quoted in.
  if (free("markup_type")) take("markup_type");
  if (free("markup_value")) {
    if (values.markup_type && values.markup_type === source.markup_type) take("markup_value");
    else values.markup_value = "";
  }
  return { values, held: nextHeld };
}

/** "12 MG Road, Mumbai, Maharashtra - 400069, India" — blanks dropped. */
export function partyAddress(p: Party): string {
  const locality = [p.city, p.state].filter(Boolean).join(", ");
  const withPin = locality && p.pincode ? `${locality} - ${p.pincode}` : locality || p.pincode || "";
  return [p.address, withPin, p.country].map((s) => (s ?? "").trim()).filter(Boolean).join(", ");
}
