// Central registry for Reconciliation → Vendor Reconciliation: its tabs (RECON_TABS, at the
// end) and the grid sources some of them show.
//
// Shaped like lib/commissionSources.ts on purpose: plain data, icon-free, one entry per
// thing the screen can reconcile. Adding a source = add an entry here and register its
// backend adapter; no component changes.
//
// TWO DIFFERENT QUESTIONS SHARE THE GRID, and that is what `comparison` records.
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

// No "tp-gds": the Third Party GDS tab reconciles against Internal Statement instead (see the
// tabs below). Its buy-vs-sell adapter stays on the backend, at /reconciliation/vendor/tp-gds.
export type ReconSourceSlug = "bsp" | "ndc" | "lcc-detailed" | "tp-lcc";

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

// ── The tabs ──────────────────────────────────────────────────────────────────
// One tab per kind of vendor statement, in one row: Vendor Reconciliation matches a vendor's
// statement against the tickets you sold, so the statement type IS the choice — there is no
// family-then-document second row. A tab shows either a registry source's grid above, or the
// vendor ↔ Internal Statement reconciliation (components/reconciliation/VendorInternalRecon.tsx:
// sale with sale and refund with refund, against what Internal Statement → Upload Statement and
// Create Ticket hold). Third Party GDS is the first on Internal Statement; the rest still show
// their own grid until they move over.

export type ReconTabSlug = "bsp" | "ndc" | "lcc-detailed" | "tp-gds" | "tp-lcc";

export type ReconTab = {
  /** Also the `?source=` value that opens it. */
  slug: ReconTabSlug;
  label: string;
  view: { kind: "source"; source: ReconSourceSlug } | { kind: "vendor-internal" };
  /** One line under the page title; a source tab uses its source's. */
  blurb?: string;
};

export const RECON_TABS: ReconTab[] = [
  { slug: "bsp", label: "BSP", view: { kind: "source", source: "bsp" } },
  { slug: "ndc", label: "BSP-NDC", view: { kind: "source", source: "ndc" } },
  { slug: "lcc-detailed", label: "LCC", view: { kind: "source", source: "lcc-detailed" } },
  {
    slug: "tp-gds",
    label: "Third Party GDS",
    view: { kind: "vendor-internal" },
    blurb: "Each vendor's Third Party GDS statements against your Internal Statement — the balance payable as per the vendor and as per your books, and every difference between them, ticket by ticket.",
  },
  { slug: "tp-lcc", label: "Third Party LCC", view: { kind: "source", source: "tp-lcc" } },
];

// `?source=` values from before the tabs were flattened: Third Party → GDS ↔ Internal is now
// the Third Party GDS tab itself.
const LEGACY_TAB: Record<string, ReconTabSlug> = { "tp-gds-internal": "tp-gds" };

export function getReconTab(slug: string | null | undefined): ReconTab | undefined {
  const s = LEGACY_TAB[slug ?? ""] ?? slug;
  return RECON_TABS.find((t) => t.slug === s);
}
