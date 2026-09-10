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
  /** Upload demands a consolidator from the platform-admin SUPPLIER master — a
   *  third-party statement is issued by one and the file never names them, so the uploader
   *  is the only source of it, and the B2B deal is matched against it. Mirrors
   *  `requires_supplier` in services/statement_spec.py, which is what actually enforces it.
   *
   *  The Supplier master, not Agency Master: it is the same list a B2B deal picks its
   *  supplier from, so both sides of the match name the same thing. (Agency Master splits
   *  one vendor into a GDS row and an LCC row, which could never line up with a deal.) */
  requiresSupplier?: boolean;
  /** Upload goes through the map → review & edit → confirm wizard instead of the one-shot
   *  modal, because this type has no single fixed export: a consolidator writes whatever
   *  spreadsheet it likes, and every airline runs its own NDC portal with its own header
   *  names. Mirrors `supports_mapping` in services/statement_spec.py, which is what
   *  actually decides whether /extract and /confirm answer for the type. */
  supportsMapping?: boolean;
  /** This type has a Billing flow: its rows are resolved to a Customer/Corporate, rolled
   *  up per ticket, and projected into `uploaded_tickets` — the one table the billing
   *  screens read. Turns on the uploads list's **Billing** column and the worklist behind
   *  it. Mirrors `supports_billing` in services/statement_spec.py, which is what actually
   *  decides whether the /statements/ndc/**\/billing-* endpoints answer.
   *
   *  Opt-in per type, like the two flags above, because eight statement types share this
   *  one view — and only NDC has the columns (`_BillingMixin` is on `Ndc` alone) or the
   *  semantics for it. A commission ledger is not an invoice. */
  supportsBilling?: boolean;
  /** One line on the wizard's success screen telling the user where the rows went. */
  doneHint?: string;
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
      // supportsMapping, unlike TGQ HMPR above: an NDC export is the airline's own, and
      // every airline's portal names the same field differently, so the mapping is put in
      // front of the uploader rather than guessed at.
      {
        slug: "ndc", label: "NDC", kind: "spec-repo", status: "ready",
        apiBase: "/statements/ndc", supportsMapping: true, supportsBilling: true,
        blurb: "NDC statements — the airline's own sales export, one row per transaction.",
        doneHint: "Open Billing on the upload to bill them, or price them in Commission income.",
      },
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
      { slug: "gds", label: "GDS", kind: "spec-repo", status: "ready", apiBase: "/statements/tp-gds", requiresSupplier: true, supportsMapping: true, blurb: "Third-party GDS statement from your consolidator, normalized.", doneHint: "Price it under Vendors data → Commission income → Third Party." },
      { slug: "lcc", label: "LCC", kind: "spec-repo", status: "ready", apiBase: "/statements/tp-lcc", requiresSupplier: true, supportsMapping: true, blurb: "Third-party LCC statement from your consolidator, normalized.", doneHint: "Price it under Vendors data → Commission income → Third Party." },
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
