// Shared shapes for Vendors → Commission income (BSP settlement rows × airline deals).
// Mirrors backend/app/schemas/bsp_commission.py.

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
  enriched_rows: number;             // rows where TGQ actually recovered a field
  // TGQ HMPR data has arrived since this was last calculated. Enrichment only
  // runs inside a commission run, so it changes nothing until a re-run.
  tgq_stale: boolean;

  created_at: string;
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

  // From the TGQ HMPR counterpart — what the class/sector/travel-date match used.
  enriched_sector: string | null;              // whole journey, 'BOM/DEL/MNL/DEL/BOM'
  enriched_booking_class: string | null;       // distinct across legs, 'L/U'
  enriched_travel_date: string | null;         // first leg
  enriched_travel_date_source: string | null;  // explicit | inferred
  enriched_leg_count: number | null;
  enrichment_source: string | null;            // null = no TGQ counterpart
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
  errors: number;
  total_incentive: number;
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
  txn_types: string[];
  airlines: string[];
  statuses: string[];
  enrichment: string[];
};

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
