// Central registry for Vendors data → Payment Module.
//
// Shaped like lib/reconciliationSources.ts: plain data, icon-free. Four tabs — the vendors'
// statements, the MO (your own booking record of the same tickets), Vendor Mapping between the
// two, and Vendor Payments, one account per vendor.
//
// NOTHING IS UPLOADED HERE. The vendor statements are the Third Party GDS and LCC uploads
// themselves (Vendors data → Statements → Third Party), and the MO is Internal Statement's
// uploads filed as a Booking / MO statement (Internal Statement → Upload Statement). Both tabs
// list them read-only; the mapping and the payments are computed from them
// (backend/app/services/vendor_mapping.py).

import { getType, type StatementType } from "@/lib/statements";

export type PaymentTabSlug = "vendor" | "mo" | "mapping" | "payments";

export type PaymentTab = {
  slug: PaymentTabSlug;
  label: string;
  /** One line under the page title — what this tab is for. */
  blurb: string;
};

export const PAYMENT_TABS: PaymentTab[] = [
  {
    slug: "vendor",
    label: "Vendor Statement",
    blurb: "The consolidators' Third Party GDS and LCC statements — uploaded under Statements → Third Party.",
  },
  {
    slug: "mo",
    label: "MO Statement",
    blurb: "Your own booking record — Internal Statement uploads filed as a Booking / MO statement.",
  },
  {
    slug: "mapping",
    label: "Vendor Mapping",
    blurb: "Every line a vendor billed, looked for in the MO — is the ticket there, and is its fare the same?",
  },
  {
    slug: "payments",
    label: "Vendor Payments",
    blurb: "One account per vendor: what it billed, what is held or claimed, what was paid and what is still owed.",
  },
];

const TP_GDS = getType("third-party", "gds");
const TP_LCC = getType("third-party", "lcc");

/** The Statements hub's own type, as the read-only list here shows it. */
function vendorType(t: StatementType | undefined, slug: string, label: string, apiBase: string): StatementType {
  return {
    slug: t?.slug ?? slug,
    label,
    kind: "spec-repo",
    status: "ready",
    apiBase: t?.apiBase ?? apiBase,
    requiresSupplier: t?.requiresSupplier ?? true,
    supportsMapping: t?.supportsMapping ?? true,
    capturesPeriod: t?.capturesPeriod,
    blurb: t?.blurb,
  };
}

export const VENDOR_GDS = vendorType(TP_GDS, "gds", "Third Party GDS", "/statements/tp-gds");
export const VENDOR_LCC = vendorType(TP_LCC, "lcc", "Third Party LCC", "/statements/tp-lcc");

/** Where each kind of statement IS uploaded — named on the read-only lists. */
export const VENDOR_GDS_HREF = "/vendors/statements/third-party/gds";
export const VENDOR_LCC_HREF = "/vendors/statements/third-party/lcc";
export const MO_UPLOAD_HREF = "/internal-statement/upload";

export const PAYMENT_MODULE_API = "/payment-module";
export const PAYMENT_CHECKS_API = `${PAYMENT_MODULE_API}/checks`;
export const VENDOR_MAPPING_API = `${PAYMENT_MODULE_API}/vendor-mapping`;
export const VENDOR_ACCOUNTS_API = `${PAYMENT_MODULE_API}/vendor-accounts`;

/** The completeness checks of a Third Party GDS upload (LCC records none). */
export const VENDOR_CHECKS = { api: PAYMENT_CHECKS_API, slug: "tp-gds" };

/** Where the screen sends someone to price a vendor's commission against the deals. */
export const COMMISSION_TP_GDS_HREF = "/vendors/commission-income?source=tp-gds";

export function getPaymentTab(slug: string | null | undefined): PaymentTab | undefined {
  // "reconciliation" is the tab's old name — links sent before it was renamed still open it.
  const s = slug === "reconciliation" ? "mapping" : slug;
  return PAYMENT_TABS.find((t) => t.slug === s);
}
