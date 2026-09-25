// Central registry for Vendors → Commission income.
//
// Shaped like lib/statements.ts on purpose: plain data, icon-free, one entry per thing the
// screen can price. Adding a source = add an entry here and register its backend adapter;
// no component changes.
//
// BSP KEEPS ITS OWN API. `/bsp-commission/*` is a different router with different storage
// and is deliberately not aliased onto `/commission/vendor/*` — the flagship screen does
// not depend on the newer code being right. The only coupling between them is that their
// response shapes agree, which the backend guarantees by making schemas/commission.py a
// superset of schemas/bsp_commission.py.

export type CommissionSourceSlug =
  | "bsp" | "ndc" | "lcc-detailed" | "tp-gds" | "tp-lcc" | "tp-api";

export type CommissionSource = {
  slug: CommissionSourceSlug;
  label: string;
  apiBase: string;
  /** What the empty state calls a statement of this kind. */
  statementNoun: string;
  /** Where the empty state sends someone with nothing to price. */
  uploadHref: string;
  uploadLabel: string;
  /** One line under the page title — what this tab actually does. */
  blurb: string;
  /** BSP only: TGQ enrichment stats, the tgq_stale banner, the enrichment filter.
   *  No other source has a second document to join against. */
  showsEnrichment: boolean;
  /** Third party only: which consolidator sent the statement. Labelled "Agency" on
   *  screen — the trade's word for it — but the value is a Supplier master row. */
  showsAgency: boolean;
  /** Third party only: the vendor prints what it paid, so it can be compared. */
  showsVariance: boolean;
  /** Whether class / sector / travel date come from the FILE rather than from an
   *  enrichment join. Changes the column tooltips, not the columns. */
  sectorFromSource: boolean;
  /** The chip prefix on a matched deal. BSP and LCC price airline deals; a consolidator
   *  statement prices a B2B one. Hardcoded "AIR" previously mislabelled every B2B match. */
  dealKindLabel: string;
};

export const COMMISSION_SOURCES: Record<CommissionSourceSlug, CommissionSource> = {
  bsp: {
    slug: "bsp",
    label: "BSP",
    apiBase: "/bsp-commission",
    statementNoun: "BSP statement",
    uploadHref: "/vendors/statements/bsp/bsp",
    uploadLabel: "Vendors data → Statements → BSP",
    blurb: "Match every BSP settlement row to an airline deal and estimate the commission you have earned.",
    showsEnrichment: true,
    showsAgency: false,
    showsVariance: false,
    sectorFromSource: false,
    dealKindLabel: "AIR",
  },
  ndc: {
    slug: "ndc",
    label: "NDC",
    apiBase: "/commission/vendor/ndc",
    statementNoun: "NDC statement",
    uploadHref: "/vendors/statements/bsp/ndc",
    uploadLabel: "Vendors data → Statements → BSP → NDC",
    blurb: "Match every row of the airline's own NDC export to an airline deal and estimate the commission you have earned.",
    // No second document to join against — an NDC export already prints the class, the
    // sector and the fare components that BSP needs the TGQ for.
    showsEnrichment: false,
    showsAgency: false,
    showsVariance: false,
    sectorFromSource: true,
    dealKindLabel: "AIR",
  },
  "lcc-detailed": {
    slug: "lcc-detailed",
    label: "LCC",
    apiBase: "/commission/vendor/lcc-detailed",
    statementNoun: "LCC Detailed statement",
    uploadHref: "/vendors/statements/lcc/statement-detailed",
    uploadLabel: "Vendors data → Statements → LCC → Detailed Statement",
    blurb: "Match every LCC Detailed row to an airline deal and estimate the commission you have earned.",
    showsEnrichment: false,
    showsAgency: false,
    showsVariance: false,
    sectorFromSource: true,
    dealKindLabel: "AIR",
  },
  "tp-gds": {
    slug: "tp-gds",
    label: "GDS",
    apiBase: "/commission/vendor/tp-gds",
    statementNoun: "third-party GDS statement",
    uploadHref: "/vendors/statements/third-party/gds",
    uploadLabel: "Vendors data → Statements → Third Party → GDS",
    blurb: "Match every row of your consolidator's GDS statement to a B2B deal, and compare what they paid against what your deal says.",
    showsEnrichment: false,
    showsAgency: true,
    showsVariance: true,
    sectorFromSource: true,
    dealKindLabel: "B2B",
  },
  "tp-lcc": {
    slug: "tp-lcc",
    label: "LCC",
    apiBase: "/commission/vendor/tp-lcc",
    statementNoun: "third-party LCC statement",
    uploadHref: "/vendors/statements/third-party/lcc",
    uploadLabel: "Vendors data → Statements → Third Party → LCC",
    blurb: "Match every row of your consolidator's LCC statement to a B2B deal, and compare what they paid against what your deal says.",
    showsEnrichment: false,
    showsAgency: true,
    showsVariance: true,
    sectorFromSource: true,
    dealKindLabel: "B2B",
  },
  "tp-api": {
    slug: "tp-api",
    label: "API",
    apiBase: "/commission/vendor/tp-api",
    statementNoun: "third-party API statement",
    uploadHref: "/vendors/statements/third-party/api",
    uploadLabel: "Vendors data → Statements → Third Party → API",
    blurb: "Match the flight rows of your aggregator's booking export to a B2B deal. Hotel, train, bus and car rows are listed as skipped — they have no airline deal to price against.",
    showsEnrichment: false,
    showsAgency: true,
    // The aggregator prints what a booking cost and what was paid for it, never a
    // commission it paid us, so there is nothing to compare against and the backend's
    // /variance 404s for this source.
    showsVariance: false,
    sectorFromSource: true,
    dealKindLabel: "B2B",
  },
};

export type CommissionTab = {
  slug: string;
  label: string;
  sources: CommissionSourceSlug[];
};

/** The three top-level tabs, each holding the documents of one family — the same two
 *  questions in the same order as the Statements page: which family, then which document.
 *
 *  The inner switch is not decoration. Every source in a family is a DIFFERENT DOCUMENT
 *  with a different column shape and a different set of things it can prove: a BSP
 *  settlement row knows neither class nor sector while the NDC export beside it prints
 *  both, and an aggregator's API file carries four products that no airline deal covers.
 *  Merging any two of them into one grid would merge two column shapes and quietly change
 *  what a figure means.
 *
 *  LCC has ONE source and therefore no inner switch — the shell renders the second row
 *  only when a family holds more than one. The four other LCC statement types (DI, Divided
 *  PNR, Flown Report, CTA/BTA) are ledgers and reports rather than sales documents: there
 *  is no fare to price on them, so they are uploadable but deliberately not listed here. */
export const COMMISSION_TABS: CommissionTab[] = [
  { slug: "bsp", label: "BSP", sources: ["bsp", "ndc"] },
  { slug: "lcc", label: "LCC", sources: ["lcc-detailed"] },
  { slug: "third-party", label: "Third Party", sources: ["tp-gds", "tp-lcc", "tp-api"] },
];

export function getSource(slug: string | null | undefined): CommissionSource | undefined {
  return COMMISSION_SOURCES[(slug ?? "") as CommissionSourceSlug];
}

export function tabForSource(slug: string): CommissionTab {
  return COMMISSION_TABS.find((t) => t.sources.includes(slug as CommissionSourceSlug))
    ?? COMMISSION_TABS[0];
}
