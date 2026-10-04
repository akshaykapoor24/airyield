// Central registry for Vendors data → Payment Module.
//
// Shaped like lib/reconciliationSources.ts: plain data, icon-free. Four tabs — the
// vendor's bill, our own mid-office (MO) record of it, the reconciliation between the two,
// and the payments that settle it — and the statement configs the first two hand to
// AdjustmentStatementsView, which is the same uploads screen Vendors data → Statements uses
// (plus a Checks column and control totals, which only these two tabs switch on).
//
// THE VENDOR STATEMENT IS NOT A COPY. It is the Third Party GDS type itself (`tp-gds`):
// uploading here is uploading under Statements → Third Party → GDS, so Commission income
// prices exactly these rows and the reconciliation can read that commission row-to-row.
// The MO statement is its own type (`mo-gds`) on the same backend router, parsed with the
// Third Party GDS columns for now, so one file loads identically on both sides.

import { getType, type StatementType } from "@/lib/statements";

export type PaymentTabSlug = "vendor" | "mo" | "reconciliation" | "payments";

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
    blurb: "The consolidator's Third Party GDS statement — the same uploads as Statements → Third Party → GDS.",
  },
  {
    slug: "mo",
    label: "MO Statement",
    blurb: "Your mid-office (internal) record of the same bookings, uploaded in the Third Party GDS format.",
  },
  {
    slug: "reconciliation",
    label: "Reconciliation",
    blurb: "Vendor statement against MO statement, ticket by ticket — with the commission your deals say you earned.",
  },
  {
    slug: "payments",
    label: "Payments",
    blurb: "What each statement leaves payable after Operations' decisions, the payments made against it, and what is still outstanding.",
  },
];

const TP_GDS = getType("third-party", "gds");

export const VENDOR_STATEMENT: StatementType = {
  slug: TP_GDS?.slug ?? "gds",
  label: "Vendor Statement",
  kind: "spec-repo",
  status: "ready",
  apiBase: TP_GDS?.apiBase ?? "/statements/tp-gds",
  requiresSupplier: TP_GDS?.requiresSupplier ?? true,
  supportsMapping: TP_GDS?.supportsMapping ?? true,
  blurb: TP_GDS?.blurb,
  doneHint: "Price it under Vendors data → Commission income → Third Party → GDS, then check it against your MO statement under Payment Module → Reconciliation.",
};

export const MO_STATEMENT: StatementType = {
  slug: "mo-gds",
  label: "MO Statement",
  kind: "spec-repo",
  status: "ready",
  apiBase: "/statements/mo-gds",
  // The consolidator whose bookings this record holds — it is what pairs an MO upload
  // with that vendor's statement on the Reconciliation tab.
  requiresSupplier: true,
  supportsMapping: true,
  blurb: "Mid-office (internal) statement, read with the Third Party GDS columns.",
  doneHint: "Check it against the vendor statement under Payment Module → Reconciliation.",
};

export const PAYMENT_MODULE_API = "/payment-module";
export const PAYMENT_RECON_API = `${PAYMENT_MODULE_API}/reconciliation`;
export const PAYMENT_CHECKS_API = `${PAYMENT_MODULE_API}/checks`;

/** The backend statement types behind the two upload tabs — what the checks API keys on.
 *  Not `VENDOR_STATEMENT.slug`, which is the Statements hub's own short slug ("gds"). */
export const VENDOR_CHECKS = { api: PAYMENT_CHECKS_API, slug: "tp-gds" };
export const MO_CHECKS = { api: PAYMENT_CHECKS_API, slug: "mo-gds" };

/** Where the screen sends someone whose vendor statement has no commission yet. */
export const COMMISSION_TP_GDS_HREF = "/vendors/commission-income?source=tp-gds";

export function getPaymentTab(slug: string | null | undefined): PaymentTab | undefined {
  return PAYMENT_TABS.find((t) => t.slug === slug);
}
