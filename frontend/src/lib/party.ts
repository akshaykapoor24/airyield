// Central registry for the two billable counter-party directories.
//
// `customers` and `corporates` are separate backend tables with byte-identical
// shapes (see backend/app/models/{customer,corporate}.py) and byte-identical
// routers. One `Party` type, one config record, two resources.
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
  first_name: string;
  last_name: string | null;
  company: string | null;
  title: string | null;
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
};

export type PartyKind = "customer" | "corporate";
export type PartyMode = "master" | "billing";

export type PartyConfig = {
  kind: PartyKind;
  /** API segment — also drives /{resource}/template and /{resource}/bulk-upload. */
  resource: "customers" | "corporates";
  singular: string;
  plural: string;
  masterHref: string;
  masterLabel: string;
  billingHref: string;
  billingLabel: string;
  detailHref: (id: number) => string;
  templateFile: string;
  templateColumns: string;
  emailPlaceholder: string;
};

export const PARTY: Record<PartyKind, PartyConfig> = {
  customer: {
    kind: "customer",
    resource: "customers",
    singular: "Customer",
    plural: "Customers",
    masterHref: "/user-master/customer-master",
    masterLabel: "Customer Master",
    billingHref: "/customers",
    billingLabel: "Customer Billing",
    detailHref: (id) => `/customers/${id}`,
    templateFile: "customer_template.xlsx",
    templateColumns:
      "FIRST_NAME, LAST_NAME, COMPANY, TITLE, PHONE, EMAIL, GST_REGISTERED (Registered|Unregistered), GST_NO, PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency)",
    emailPlaceholder: "customer@email.com",
  },
  corporate: {
    kind: "corporate",
    resource: "corporates",
    singular: "Corporate",
    plural: "Corporates",
    masterHref: "/user-master/corporate-master",
    masterLabel: "Corporate Master",
    billingHref: "/corporates",
    billingLabel: "Corporate Billing",
    detailHref: (id) => `/corporates/${id}`,
    templateFile: "corporate_template.xlsx",
    templateColumns:
      "FIRST_NAME, LAST_NAME, COMPANY, TITLE, PHONE, EMAIL, GST_REGISTERED (Registered|Unregistered), GST_NO, PAN_NO, MARKUP_TYPE (percentage|fixed), MARKUP_VALUE, BILLING_TYPE (reseller|agency)",
    emailPlaceholder: "corporate@email.com",
  },
};

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

export function partyName(p: Party): string {
  return `${p.first_name} ${p.last_name ?? ""}`.trim();
}
