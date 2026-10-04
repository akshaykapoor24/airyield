// Wire shapes for /payment-module — mirrors backend/app/schemas/payment_reconciliation.py.
// `vendor_*` is the consolidator's bill, `mo_*` our mid-office record; every variance is
// vendor − MO.

/** One upload, as `GET /statements/{slug}/batches` returns it. */
export type StatementBatch = {
  batch_id: string;
  source_file: string | null;
  uploaded_at: string;
  row_count: number;
  created_by_name: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  supplier_branch?: string | null;
  supplier_code?: string | null;
};

export type PaymentStatus =
  | "matched" | "minor_diff" | "mismatch" | "possible_match" | "vendor_only" | "mo_only";

export type CommissionStatus =
  | "priced" | "partial" | "unpriced" | "skipped" | "not_run" | "none";

/** Operations' decision on one billed ticket (step 10). Paid is not a status — a paid
 *  ticket keeps the decision it was paid under and carries `payment_id`. */
export type DecisionStatus = "approved" | "pending" | "held" | "excluded";

/** How the MO side of a ticket relates to the vendor whose statement billed it (step 6C). */
export type MoVendorStatus = "ok" | "other_vendor" | "corrected" | "none";

export type PaymentTotals = {
  total: number;
  matched: number;
  minor_diff: number;
  mismatch: number;
  possible_match: number;
  vendor_only: number;
  mo_only: number;
  vendor_net_total: number;
  mo_net_total: number;
  net_variance_total: number;
  vendor_only_total: number;
  mo_only_total: number;
  calc_commission_total: number;
  vendor_commission_total: number;
  shortfall_total: number;
  payable_total: number;
};

export type PaymentRunResult = PaymentTotals & {
  run_id: number;
  reconciled_at: string;
  vendor_closing_balance: number | null;
  mo_closing_balance: number | null;
};

export type BalanceLine = { kind: string; label: string; row_id: number; amount: number | null };

export type PaymentRunInfo = {
  run_id: number;
  completed_at: string | null;
  vendor_source_file: string | null;
  mo_source_file: string | null;
  vendor_closing_balance: number | null;
  mo_closing_balance: number | null;
  vendor_opening_balance: number | null;
  vendor_opening_derived: boolean;
  mo_opening_balance: number | null;
  mo_opening_derived: boolean;
  vendor_balance_lines: BalanceLine[];
  mo_balance_lines: BalanceLine[];
  commission_run_id: number | null;
  commission_completed_at: string | null;
  commission_priced_rows: number;
  commission_unpriced_rows: number;
};

export type PaymentCommissionState = {
  run_id: number | null;
  status: string;            // none | queued | processing | completed | failed
  completed_at: string | null;
  total_rows: number;
  priced_rows: number;
  pending_rows: number;
  stale: boolean;
};

export type PaymentRow = {
  id: number;
  vendor_batch_id: string;
  mo_batch_id: string;
  ticket_number: string | null;
  ticket_prefix: string | null;
  airline_name: string | null;
  airline_code: string | null;
  issue_date: string | null;
  pax_name: string | null;
  sector: string | null;
  pnr: string | null;
  match_status: PaymentStatus;
  severity: string;
  match_method: string;
  vendor_rows: number;
  mo_rows: number;
  vendor_gross: number | null;
  mo_gross: number | null;
  vendor_net: number | null;
  mo_net: number | null;
  net_variance: number | null;
  vendor_commission: number | null;
  mo_commission: number | null;
  calc_commission: number | null;
  commission_shortfall: number | null;
  payable_after_commission: number | null;
  commission_status: CommissionStatus;
  issue_count: number;
  // ── process checks (steps 6A–6E) ──
  ticket_key: string | null;
  booking_id: string | null;
  not_billed: boolean;
  is_duplicate: boolean;
  mo_vendor_status: MoVendorStatus;
  mo_vendor_name: string | null;
  /** Fields the vendor left blank and the MO statement filled: booking_class, sector, travel_date. */
  enriched_fields: string[];
  // ── the ticket's payment item (null for an MO-only line — nothing was billed) ──
  item_id: number | null;
  decision_status: DecisionStatus | null;
  decision_source: "auto" | "user" | null;
  decision_action: string | null;
  approved_amount: number | null;
  decision_reason: string | null;
  paid: boolean;
};

export type PaymentFieldDiff = {
  key: string;
  label: string;
  vendor: number | null;
  mo: number | null;
  variance: number | null;
  match: boolean | null;
  severity: string | null;
};

export type PaymentIssue = {
  field: string | null;
  label: string | null;
  severity: string;
  message: string;
};

/** One vendor row's commission, as the engine read it from Commission income. */
export type CommissionDetailEntry = {
  source_row_id: number;
  ticket_status: string | null;
  status: string;
  reason?: string | null;
  deal_no?: string | null;
  deal_name?: string | null;
  iata?: number | null;
  incentive?: number | null;
  calc_commission?: number | null;
  shortfall?: number | null;
  declared_commission: number | null;
  declared_incentive: number | null;
  declared_tds: number | null;
  net_ok?: boolean | null;
  note?: string;
};

export type StatementRecord = Record<string, string | number | null> & { _id: number };

export type DuplicateInfo =
  | { kind: "earlier"; batch_id?: string | null; source_file?: string | null;
      uploaded_at?: string | null; paid?: boolean | null }
  | { kind: "within"; sale_rows: number };

export type MoVendorInfo = {
  batch_id?: string | null;
  supplier_id?: number | null;
  supplier_name?: string | null;
  source_file?: string | null;
  corrected_from?: string | null;
};

export type PaymentDetail = PaymentRow & {
  reconciled_at: string | null;
  fields: PaymentFieldDiff[];
  issues: PaymentIssue[];
  notes: string[];
  commission_detail: CommissionDetailEntry[];
  duplicate_info: DuplicateInfo | null;
  mo_vendor_info: MoVendorInfo | null;
  enrichment: Record<string, { value: string; source: string }> | null;
  remarks: string | null;
  ops_reference: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  paid_amount: number | null;
  paid_at: string | null;
  payment_id: number | null;
  suggested_payable: number | null;
  vendor_records: StatementRecord[];
  mo_records: StatementRecord[];
  records_missing: boolean;
};

export type PaymentFlagCounts = {
  duplicates: number; not_billed: number; other_vendor: number; enriched: number;
};

export type PaymentDecisionCounts = {
  approved: number; pending: number; held: number; excluded: number; paid: number;
  /** Σ approved_amount of approved, unpaid tickets in the filtered set. */
  approved_amount: number;
};

export type PaymentPage = {
  summary: PaymentTotals;
  run: PaymentRunInfo | null;
  commission: PaymentCommissionState;
  flags: Partial<PaymentFlagCounts>;
  decisions: Partial<PaymentDecisionCounts>;
  total: number;
  offset: number;
  limit: number;
  rows: PaymentRow[];
};

/** `POST /payment-module/reconciliation/calculate-income`. */
export type CalculateIncomeResult = {
  mode: "inline" | "queued";
  commission_run_id: number;
  status: string;
  calculated?: number;
  reversed?: number;
  needs_data?: number;
  unmatched?: number;
  skipped?: number;
  reconciliation?: PaymentRunResult;
};

// ── decisions, payable, payments, outstanding (steps 10–13) ──────────────────

/** One billed vendor ticket in the payment ledger. */
export type PaymentItem = {
  id: number;
  vendor_batch_id: string;
  vendor_source_file: string | null;
  statement_uploaded_at: string | null;
  supplier_id: number | null;
  supplier_name: string | null;
  ticket_key: string;
  ticket_number: string | null;
  ticket_prefix: string | null;
  pax_name: string | null;
  airline_name: string | null;
  issue_date: string | null;
  sector: string | null;
  booking_id: string | null;
  match_status: string | null;
  is_duplicate: boolean;
  not_billed: boolean;
  mo_vendor_status: string | null;
  vendor_net: number | null;
  mo_net: number | null;
  net_variance: number | null;
  commission_shortfall: number | null;
  suggested_payable: number | null;
  decision_status: DecisionStatus;
  decision_source: "auto" | "user";
  decision_action: string | null;
  approved_amount: number | null;
  decision_reason: string | null;
  remarks: string | null;
  ops_reference: string | null;
  payment_id: number | null;
  paid_amount: number | null;
  paid_at: string | null;
  stale: boolean;
  age_days: number | null;
};

export type PayableSummary = {
  vendor_batch_id: string;
  supplier_id: number | null;
  supplier_name: string | null;
  source_file: string | null;
  tickets: number;
  billed: number;
  commission_shortfall: number;
  suggested: number;
  counts: Partial<Record<DecisionStatus | "paid" | "brought_forward", number>>;
  excluded: number;
  pending: number;
  held: number;
  approved: number;
  brought_forward: number;
  paid: number;
  final_payable: number;
  /** Approved and unpaid: this statement's, then those brought forward from earlier ones. */
  items: PaymentItem[];
};

export type VendorPayment = {
  id: number;
  supplier_id: number | null;
  supplier_name: string | null;
  vendor_batch_id: string | null;
  vendor_source_file: string | null;
  payment_date: string;
  amount: number;
  mode: string | null;
  reference: string | null;
  remarks: string | null;
  items_count: number;
  status: "completed" | "voided";
  void_reason: string | null;
  voided_at: string | null;
  created_at: string | null;
};

export type VendorPaymentDetail = VendorPayment & { items: PaymentItem[] };

export type OutstandingPage = {
  supplier_id: number | null;
  totals: Partial<Record<DecisionStatus, { count: number; amount: number }>>;
  items: PaymentItem[];
};

export type PaymentFacets = { airlines: string[]; statuses: string[] };
