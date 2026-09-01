// Central registry for the Vendors → Statements hub.
// Drives both the in-page tab shell and the content dispatch. Adding a new
// spec-driven statement type = flip its `kind` to "spec-repo" and give it an
// `apiBase` (the backend column-spec endpoint); no UI code changes needed.

export type StatementKind = "spec-repo" | "bsp" | "lcc-detailed" | "coming-soon";

export type StatementVariant = {
  slug: string;
  label: string;
  apiBase: string;
};

export type StatementType = {
  slug: string;
  label: string;
  kind: StatementKind;
  status: "ready" | "coming-soon";
  blurb?: string;
  apiBase?: string;               // spec-repo: full API base, e.g. "/statements/tgq-hmpr"
  variants?: StatementVariant[];  // spec-repo with an inner switch, e.g. ADM/ACM/RA
  /** Upload demands an Airline Master ID — the LCC exports name no carrier, so the
   *  uploader is the only source of it. Mirrors `requires_airline_id` in the backend
   *  spec (services/statement_spec.py), which is what actually enforces it; opt-in per
   *  type because every spec-repo type shares one view and one upload endpoint. */
  requiresAirlineId?: boolean;
};

export type StatementCategory = {
  slug: string;                   // "bsp" | "lcc" | "third-party"
  label: string;
  types: StatementType[];
};

export const STATEMENT_NAV: StatementCategory[] = [
  {
    slug: "bsp",
    label: "BSP",
    types: [
      {
        slug: "bsp",
        label: "BSP",
        kind: "bsp",
        status: "ready",
        blurb: "BSP settlement statements — summary & detailed.",
      },
      {
        slug: "adm-acm-ra",
        label: "ADM / ACM / RA",
        kind: "spec-repo",
        status: "ready",
        blurb: "Agency Debit / Credit Memos and Refund Applications from BSPlink.",
        variants: [
          { slug: "adm", label: "ADM", apiBase: "/airline-adjustments/adm" },
          { slug: "acm", label: "ACM", apiBase: "/airline-adjustments/acm" },
          { slug: "ra",  label: "RA",  apiBase: "/airline-adjustments/ra" },
        ],
      },
      { slug: "tgq-hmpr", label: "TGQ HMPR", kind: "spec-repo", status: "ready", apiBase: "/statements/tgq-hmpr", blurb: "TGQ / HMPR statements — one row per ticket, unlimited taxes." },
      { slug: "ndc",      label: "NDC",      kind: "spec-repo", status: "ready", apiBase: "/statements/ndc", blurb: "NDC statements — one row per ticket, unlimited taxes." },
    ],
  },
  {
    slug: "lcc",
    label: "LCC",
    types: [
      { slug: "statement-detailed", label: "Detailed Statement", kind: "lcc-detailed", status: "ready", apiBase: "/lcc-detailed", blurb: "LCC detailed statement — map any airline export to the standard 129-column template, then ingest." },
      // requiresAirlineId on all four: like Detailed, an LCC export names no carrier.
      { slug: "di",                 label: "DI Statement",       kind: "spec-repo", status: "ready", apiBase: "/statements/lcc-di", requiresAirlineId: true, blurb: "Deposit (DI) statement — deposit or agency ledger, normalized." },
      { slug: "divided-pnr",        label: "Divided PNR",        kind: "spec-repo", status: "ready", apiBase: "/statements/lcc-divided-pnr", requiresAirlineId: true, blurb: "Divided PNR statement — parent→child PNR splits, normalized." },
      { slug: "flown-report",       label: "Flown Report",       kind: "spec-repo", status: "ready", apiBase: "/statements/lcc-flown-report", requiresAirlineId: true, blurb: "Flown (uplifted) segment report — normalized." },
      { slug: "cta-bta",            label: "CTA/BTA Report",     kind: "spec-repo", status: "ready", apiBase: "/statements/lcc-cta-bta", requiresAirlineId: true, blurb: "CTA/BTA (Central/Business Travel Account) lodged-account settlement report — normalized." },
    ],
  },
  {
    slug: "third-party",
    label: "Third Party",
    types: [
      { slug: "gds", label: "GDS", kind: "spec-repo", status: "ready", apiBase: "/statements/tp-gds", blurb: "Third-party GDS statement from your consolidator, normalized." },
      { slug: "lcc", label: "LCC", kind: "spec-repo", status: "ready", apiBase: "/statements/tp-lcc", blurb: "Third-party LCC statement from your consolidator, normalized." },
    ],
  },
];

export function getCategory(slug: string): StatementCategory | undefined {
  return STATEMENT_NAV.find((c) => c.slug === slug);
}

export function getType(categorySlug: string, typeSlug: string): StatementType | undefined {
  return getCategory(categorySlug)?.types.find((t) => t.slug === typeSlug);
}

/** First type path within a category (used by the category tabs). */
export function categoryFirstPath(categorySlug: string): string {
  const cat = getCategory(categorySlug);
  const first = cat?.types[0];
  return cat && first ? `/vendors/statements/${cat.slug}/${first.slug}` : "/vendors/statements";
}

/** Landing redirect target — the very first type in the tree. */
export const FIRST_STATEMENT_PATH = categoryFirstPath(STATEMENT_NAV[0].slug);
