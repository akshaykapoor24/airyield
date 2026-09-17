// Central registry for Vendors → Reconciliation.
//
// Shaped like lib/commissionSources.ts on purpose: plain data, icon-free, one entry per
// thing the screen can reconcile. Adding a source = add an entry here and register its
// backend adapter; no component changes.
//
// TWO DIFFERENT QUESTIONS SHARE THIS SCREEN, and that is what `comparison` records.
// BSP asks "did the airline settle what we expected", comparing one internal ticket
// against one settlement row. Every other source asks "what did this ticket cost and what
// did it sell for" — the vendor's statement is the BUY side, our own tickets the SELL
// side. They are different engines over different tables, so the tabs differ in wording
// and in which columns appear, never in layout.
//
// BSP KEEPS ITS OWN API. `/bsp-reconciliation/*` is a different router with different
// storage and is deliberately not aliased onto `/reconciliation/vendor/*` — the only
// reconciliation engine ever run against real settlement data does not depend on the newer
// code being right. The coupling is that their response shapes agree, which the backend
// guarantees by making schemas/sell_reconciliation.py a superset of the shared keys.

export type ReconSourceSlug = "bsp" | "ndc" | "lcc-detailed" | "tp-gds" | "tp-lcc";

export type ReconSource = {
  slug: ReconSourceSlug;
  label: string;
  apiBase: string;
  /** "expected-vs-actual" is BSP's settlement question; "buy-vs-sell" is everyone else's. */
  comparison: "expected-vs-actual" | "buy-vs-sell";
  /** Column headers for the two money sides, so one grid serves both questions. */
  buyLabel: string;
  sellLabel: string;
  /** The headline difference column. */
  diffLabel: string;
  /** What the empty state calls a statement of this kind. */
  statementNoun: string;
  /** Where the empty state sends someone with nothing to reconcile. */
  uploadHref: string;
  uploadLabel: string;
  /** One line under the page title — what this tab actually does. */
  blurb: string;
  /** Whether the grid offers a statement filter. The list is flat across every upload of
   *  a source, so without this there is no way to look at one week on its own. */
  showsBatchFilter: boolean;
  /** False when the source prints no ticket number, so the empty state can say WHY
   *  nothing matched instead of implying nothing was bought. LCC Detailed is keyed on
   *  PNRs and can only be linked through the billing projection. */
  joinsByTicket: boolean;
};

export const RECON_SOURCES: Record<ReconSourceSlug, ReconSource> = {
  bsp: {
    slug: "bsp",
    label: "BSP",
    apiBase: "/bsp-reconciliation",
    comparison: "expected-vs-actual",
    buyLabel: "Internal (expected)",
    sellLabel: "BSP (actual)",
    diffLabel: "Difference",
    statementNoun: "BSP statement",
    uploadHref: "/vendors/statements/bsp/bsp",
    uploadLabel: "Vendors data → Statements → BSP",
    blurb: "Expected (internal) vs actual (BSP) — for every ticket, did BSP settle what you expected?",
    showsBatchFilter: false,
    joinsByTicket: true,
  },
  ndc: {
    slug: "ndc",
    label: "NDC",
    apiBase: "/reconciliation/vendor/ndc",
    comparison: "buy-vs-sell",
    buyLabel: "Bought at",
    sellLabel: "Sold at",
    diffLabel: "Margin",
    statementNoun: "NDC statement",
    uploadHref: "/vendors/statements/bsp/ndc",
    uploadLabel: "Vendors data → Statements → BSP → NDC",
    blurb: "For every NDC ticket, what it cost you and what you sold it for.",
    showsBatchFilter: true,
    joinsByTicket: true,
  },
  "lcc-detailed": {
    slug: "lcc-detailed",
    label: "LCC",
    apiBase: "/reconciliation/vendor/lcc-detailed",
    comparison: "buy-vs-sell",
    buyLabel: "Bought at",
    sellLabel: "Sold at",
    diffLabel: "Margin",
    statementNoun: "LCC Detailed statement",
    uploadHref: "/vendors/statements/lcc/statement-detailed",
    uploadLabel: "Vendors data → Statements → LCC → Detailed Statement",
    blurb: "For every LCC booking, what it cost you and what you sold it for.",
    showsBatchFilter: true,
    // An LCC Detailed export is keyed on PNRs, not ticket numbers.
    joinsByTicket: false,
  },
  "tp-gds": {
    slug: "tp-gds",
    label: "GDS",
    apiBase: "/reconciliation/vendor/tp-gds",
    comparison: "buy-vs-sell",
    buyLabel: "Bought at",
    sellLabel: "Sold at",
    diffLabel: "Margin",
    statementNoun: "third-party GDS statement",
    uploadHref: "/vendors/statements/third-party/gds",
    uploadLabel: "Vendors data → Statements → Third Party → GDS",
    blurb: "For every ticket on your consolidator's GDS statement, what you bought it at and what you sold it at.",
    showsBatchFilter: true,
    joinsByTicket: true,
  },
  "tp-lcc": {
    slug: "tp-lcc",
    label: "LCC",
    apiBase: "/reconciliation/vendor/tp-lcc",
    comparison: "buy-vs-sell",
    buyLabel: "Bought at",
    sellLabel: "Sold at",
    diffLabel: "Margin",
    statementNoun: "third-party LCC statement",
    uploadHref: "/vendors/statements/third-party/lcc",
    uploadLabel: "Vendors data → Statements → Third Party → LCC",
    blurb: "For every ticket on your consolidator's LCC statement, what you bought it at and what you sold it at.",
    showsBatchFilter: true,
    joinsByTicket: true,
  },
};

export type ReconTab = {
  slug: string;
  label: string;
  sources: ReconSourceSlug[];
};

/** The three top-level tabs. A tab with one source renders no sub-tab row — the sub-tabs
 *  are a switch between documents of the same kind, and a switch with one option is noise. */
export const RECON_TABS: ReconTab[] = [
  { slug: "bsp", label: "BSP", sources: ["bsp", "ndc"] },
  { slug: "lcc", label: "LCC", sources: ["lcc-detailed"] },
  { slug: "third-party", label: "Third Party", sources: ["tp-gds", "tp-lcc"] },
];

export function getReconSource(slug: string | null | undefined): ReconSource | undefined {
  return RECON_SOURCES[(slug ?? "") as ReconSourceSlug];
}

export function tabForReconSource(slug: string): ReconTab {
  return RECON_TABS.find((t) => t.sources.includes(slug as ReconSourceSlug))
    ?? RECON_TABS[0];
}
