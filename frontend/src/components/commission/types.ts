// Shared shapes for Vendors → Commission income.
//
// ONE SHAPE FOR EVERY SOURCE TAB. Mirrors backend/app/schemas/commission.py, which is
// itself a deliberate superset of schemas/bsp_commission.py: every BSP field with the same
// name and meaning, plus optional extras (the consolidator, what the vendor said it paid,
// the variance) that simply come back absent for a source that has none. A discriminated
// union would mean narrowing on every field access for no benefit.

export type CommissionStatement = {
  batch_id: string;
  statement_name: string | null;
  airline_code: string | null;
  airline_name: string | null;
  period_from: string | null;
  period_to: string | null;
  row_count: number;
  parse_status: string;              // the PDF parse — rows only exist once "completed"

  status: string;                    // idle | queued | processing | completed | failed
  total_rows: number;
  processed_rows: number;
  progress_pct: number;
  error: string | null;
  heartbeat_at: string | null;
  is_stale: boolean;                 // queued/processing but its worker went quiet
  calculated_at: string | null;

  total_incentive: number | null;
  iata_total: number | null;
  matched_rows: number;
  unmatched_rows: number;
  excluded_rows: number;
  skipped_rows: number;
  // A deal matched, but it pays only on a criterion this statement does not
  // print (cabin class, travel window, route), so the amount is withheld.
  needs_data_rows: number;
  // Rows no run has touched. Without this a never-run statement looks identical
  // to a fully-run one that matched almost nothing.
  pending_rows: number;
  // ── BSP only ───────────────────────────────────────────────────────────────
  enriched_rows?: number;            // rows where TGQ actually recovered a field
  // TGQ HMPR data has arrived since this was last calculated. Enrichment only
  // runs inside a commission run, so it changes nothing until a re-run.
  tgq_stale?: boolean;

  // ── Third party only ───────────────────────────────────────────────────────
  // Which consolidator sent it, from the platform-admin Supplier master. Read off
  // the upload's snapshot, so a renamed vendor does not rewrite history. The screen
  // labels this "Agency" — that is the trade's word for it; the data is a supplier.
  supplier_id?: number | null;
  supplier_name?: string | null;
  supplier_branch?: string | null;
  supplier_code?: string | null;
  // A statement with no consolidator can be listed but not priced — there is no
  // B2B deal to match it against. Said up front rather than failing at run time.
  can_run?: boolean;
  blocked_reason?: string | null;

  declared_commission_total?: number | null;
  declared_incentive_total?: number | null;
  // Positive = under-recovery: the consolidator owes you.
  variance_total?: number | null;
  // Rows left out of the variance because the vendor's own figures did not add
  // up to its own Net Amount.
  variance_unverified_rows?: number;

  uploaded_at?: string | null;
  created_at?: string;
};

export type CommissionRow = {
  id: number;
  document_number: string | null;
  ticket_number: string | null;
  transaction_type: string | null;
  airline_code: string | null;
  airline_accounting_code: string | null;
  airline_name: string | null;
  issue_date: string | null;
  stat: string | null;
  form_of_payment: string | null;

  fare_amount: number | null;
  yq: number | null;
  yr: number | null;
  transaction_amount: number | null;
  standard_commission_amount: number | null;

  matched_deal_id: number | null;
  matched_deal_type: string | null;
  matched_deal_name: string | null;
  calculated_incentive: number | null;
  iata_commission: number | null;
  incentive_breakdown: Record<string, number> | null;
  commission_status: string;         // pending | calculated | excluded | reversed | skipped | unmatched
  commission_reason: string | null;
  skipped_criteria: string[] | null;   // what THIS row could not evaluate; [] = nothing

  // ── BSP only: from the TGQ HMPR counterpart ────────────────────────────────
  enriched_sector?: string | null;              // whole journey, 'BOM/DEL/MNL/DEL/BOM'
  enriched_booking_class?: string | null;       // distinct across legs, 'L/U'
  enriched_travel_date?: string | null;         // first leg
  enriched_travel_date_source?: string | null;  // explicit | inferred
  enriched_leg_count?: number | null;
  enrichment_source?: string | null;            // null = no TGQ counterpart

  // ── Every non-BSP source: the values came from the file itself ─────────────
  source_row_id?: number;
  pnr?: string | null;
  passenger_name?: string | null;
  segment_type?: string | null;
  booking_class?: string | null;
  sector?: string | null;
  travel_date?: string | null;
  ancillary_amount?: number | null;
  matched_deal_no?: string | null;
  // 'id' | 'name' | 'unrestricted'. A NAME match is real but UNVERIFIED — it
  // cannot tell two channels of one vendor apart — so the grid flags it.
  supplier_match_by?: string | null;
  // Per-row remarks worth reading: a missing YR column, an ancillary the deal pays
  // per sub-type, a carrier resolved against a disagreeing name.
  notes?: string[] | null;

  // ── Third party only: what the vendor says it already paid ─────────────────
  // Gross of TDS, because a deal's rates are gross too.
  declared_commission?: number | null;
  declared_incentive?: number | null;
  declared_tds?: number | null;
  declared_net?: number | null;
  // Did the vendor's own components add up to its own Net Amount? null = could
  // not be judged, which is NOT the same as false.
  declared_net_ok?: boolean | null;
  variance_commission?: number | null;
  variance_incentive?: number | null;
  variance_total?: number | null;
};

/** One line of the Variance tab — grouped by airline and deal, biggest gap first. */
export type VarianceGroup = {
  airline: string;
  deal_no: string | null;
  deal_name: string | null;
  rows: number;
  declared_commission: number;
  computed_commission: number;
  declared_incentive: number;
  computed_incentive: number;
  variance_total: number;
};

export type VarianceReport = {
  groups: VarianceGroup[];
  under_recovery: number;   // sum of positive variance — they owe you
  over_paid: number;        // sum of negative variance
  net_variance: number;
  unverified_rows: number;
};

export type RunResponse = {
  batch_id: string;
  status: string;
  mode: "queued" | "inline";
  processed: number;
  calculated: number;
  reversed: number;
  excluded: number;
  skipped: number;
  unmatched: number;
  errors?: number;
  needs_data?: number;
  run_id?: number | null;
  source?: string;
  total_incentive: number;
  variance_total?: number;
};

export type CommissionRowsPage = {
  total: number;
  offset: number;
  limit: number;
  rows: CommissionRow[];
};

export type CommissionSummary = {
  airlines: {
    airline: string;
    rows: number;
    incentives: Record<string, number>;
    total_incentive: number;
    iata_commission: number;
  }[];
  totals: {
    incentives: Record<string, number>;
    total_incentive: number;
    iata_commission: number;
  };
};

export type CommissionGap = {
  status: string;
  reason: string;
  count: number;
  sample_documents: string[];
};

export type Facets = {
  txn_types?: string[];
  airlines?: string[];
  statuses?: string[];
  enrichment?: string[];
  // The generic runner returns the same three keyed by their query parameter, so one
  // reader serves both: see `facetValues` below.
  air?: string[];
  comm_status?: string[];
  txn_type?: string[];
};

/** Facet values for a filter, whichever key the source's API used.
 *  BSP answers with `airlines` / `statuses` / `txn_types`; the generic runner answers with
 *  the query-parameter names. Reading both keeps one grid component. */
export function facetValues(f: Facets | null, kind: "air" | "status" | "txn"): string[] {
  if (!f) return [];
  if (kind === "air") return f.airlines ?? f.air ?? [];
  if (kind === "status") return f.statuses ?? f.comm_status ?? [];
  return f.txn_types ?? f.txn_type ?? [];
}

/** Indian-format money, em dash for absent values. */
export function inr(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const STAT_LABEL: Record<string, string> = { I: "International", D: "Domestic" };

/** Human labels for the criteria a BSP statement simply does not print. */
export const SKIPPED_LABEL: Record<string, string> = {
  class: "cabin class",
  sector: "sector",
  travel_date: "travel date",
};

export const STATUS_STYLE: Record<string, { cls: string; label: string }> = {
  calculated: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Calculated" },
  reversed:   { cls: "bg-amber-50 text-amber-700 border-amber-200",       label: "Reversed" },
  excluded:   { cls: "bg-red-50 text-red-600 border-red-200",             label: "Excluded" },
  unmatched:  { cls: "bg-orange-50 text-orange-600 border-orange-200",    label: "Unmatched" },
  skipped:    { cls: "bg-slate-100 text-slate-500 border-slate-200",      label: "Skipped" },
  // Reads as Unmatched, because that is what it is: a deal was found but could
  // not be confirmed against the terms it pays on, so nothing is earned and every
  // money column on the row is empty. The status VALUE stays distinct so the
  // count, the filter and the gaps bucket can still separate the rows that only
  // need a TGQ HMPR upload from the ones with no deal at all.
  needs_data: { cls: "bg-orange-50 text-orange-600 border-orange-200",    label: "Unmatched" },
  pending:    { cls: "bg-slate-50 text-slate-400 border-slate-200",       label: "Not run" },
};

/** Statuses that mean "a run has looked at this row". */
export const RUN_STATUSES = [
  "calculated", "needs_data", "reversed", "excluded", "unmatched", "skipped",
] as const;
