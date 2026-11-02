// Wire shapes for /payment-module/vendor-mapping and /payment-module/vendor-accounts —
// mirrors backend/app/services/vendor_mapping.py.

export type MappingStatus = "matched" | "fare_diff" | "not_in_mo" | "other_vendor";
export type MappingView = "all" | MappingStatus | "open" | "on_hold" | "claims" | "resolved";
/** What a line does to the payment — the backend's PAY_* states. */
export type PayState = "clear" | "hold" | "part_hold" | "review" | "credit" | "claim";
export type MappingDecision = "vendor_wrong" | "mo_wrong" | "accepted";

/** One side of a line — the vendor's statement line, or the MO's. */
export type MappingSide = {
  id: number;
  ticket_prefix: string | null;
  pax: string | null;
  pnr: string | null;
  sector: string;
  date: string | null;
  booked: string | null;
  /** Vendor: the statement's week. MO: the Doc No. */
  ref: string | null;
  /** The file the line came from. */
  source: string | null;
  statements: string[];
  lines: number;
  line_ids: number[];
  base: number;
  tax: number;
  ssr: number;
  /** Basic + whole tax + SSR. */
  fare: number;
  commission: number;
  tds: number;
  net: number;
  /** MO only: the commission it expects from the vendor (IATA + PLB). */
  comm_expected?: number;
  /** The ticket's airline cancellation charge on this side, counted once. */
  charge?: number;
};

/** One line a side has for the ticket — its figures as they move the ticket: a refund's are
 *  given back (negative), whatever sign its statement printed them with. */
export type MappingLine = {
  id: number;
  kind: "sale" | "refund";
  date: string | null;
  booked: string | null;
  /** Vendor: the statement's week. MO: the Doc No. */
  ref: string | null;
  source: string | null;
  statements: string[];
  pax: string | null;
  pnr: string | null;
  /** No Basic and no tax: a line of charges. */
  charges_only: boolean;
  base: number;
  tax: number;
  ssr: number;
  /** The airline's cancellation charge the line prints (MO: airline cancellation charge; vendor:
   *  Cancellation Charges / Agent Penalty). On a side's final: the ticket's, counted once. */
  charge: number;
  /** Taken off this line's fare — a refund, giving back less by it. */
  charge_applied: boolean;
  fare: number;
  net: number;
  commission: number;
  tds: number;
};

/** One ticket a vendor billed: every line it billed for it and every line the MO has, each side
 *  knocked off (sale less refund) into `vendor` / `mo`, which are what is compared. */
export type MappingRow = {
  key: string;
  ticket_number: string | null;
  /** The vendor's lines: "sale", "refund" or "sale+refund". */
  kind: string;
  /** The MO's lines, the same way; null when the MO has none. */
  mo_kind: string | null;
  vendor_lines: MappingLine[];
  mo_lines: MappingLine[];
  status: MappingStatus;
  vendor_id: string | null;
  vendor_name: string | null;
  /** The vendor the MO files the ticket under, when it is another. */
  mo_vendor_id: string | null;
  mo_vendor_name: string | null;
  statements: string[];
  booked: string | null;
  pending: string | null;
  vendor: MappingSide;
  mo: MappingSide | null;
  /** What the vendor's fare costs you more than the MO's (refunds: gives back less). */
  gap: number | null;
  parts: { base: number; tax: number; ssr: number } | null;
  /** The vendor's commission less what the MO expects — shown, never held. */
  commission_gap: number | null;
  hints: string[];
  open: boolean;
  decision: {
    decision: MappingDecision;
    note: string | null;
    status: string;
    decided_at: string | null;
    stale: boolean;
  } | null;
  pay: { state: PayState; hold: number; claim: number; payable: number };
};

export type MappingVendor = {
  id: string;
  name: string;
  branch: string | null;
  channels: string[];
  statements: number;
};

export type MappingStatement = {
  batch_id: string;
  slug: string;
  vendor_id: string | null;
  vendor_name: string | null;
  file_name: string | null;
  uploaded_at: string | null;
  period_from: string | null;
  period_to: string | null;
  lines: number;
  billed: number;
  opening: number | null;
  closing: number | null;
  open?: number;
  hold?: number;
};

export type MappingSummary = {
  lines: number;
  tickets: number;
  billed: number;
  payable: number;
  hold: number;
  claim: number;
  credit: number;
  /** Fare differences the vendor billed above the MO, and below it. */
  fare_excess: number;
  fare_short: number;
  open: number;
  open_amount: number;
  resolved: number;
  review: number;
  /** Per status: lines, their net, how many open, what its sales bill, how many refunds. */
  status: Record<MappingStatus, { lines: number; amount: number; open: number; sales: number; refunds: number }>;
};

export type MappingResponse = {
  scope: { vendor: string | null; statement: string | null; view: MappingView; q: string | null };
  options: { vendors: MappingVendor[]; statements: MappingStatement[]; unassigned: number };
  mo: { tickets: number; statements: number; from: string | null; to: string | null };
  statement: MappingStatement | null;
  summary: MappingSummary;
  counts: Record<MappingView, number>;
  total: number;
  offset: number;
  limit: number;
  rows: MappingRow[];
};

// ── Vendor Payments ──────────────────────────────────────────────────────────
export type AgingBucket = { bucket: string; amount: number };

export type AccountPayment = {
  id: number;
  payment_date: string | null;
  amount: number;
  mode: string | null;
  reference: string | null;
  remarks: string | null;
  /** The statement it was made against; none — on account. */
  statement: string | null;
  status: "completed" | "voided";
  void_reason: string | null;
  voided_at: string | null;
  created_at: string | null;
};

export type BalanceCheck = {
  as_at: string;
  statement: string;
  file_name: string | null;
  /** The balance the vendor printed. */
  vendor: number;
  /** This account at the same day, claims left out. */
  ours: number;
  difference: number;
};

export type AccountTotals = {
  opening: number | null;
  billed: number;
  claims: number;
  hold: number;
  paid: number;
  /** Owed to the vendor; below zero, an advance with it. */
  balance: number;
  advance: number;
  payable_now: number;
  hold_unpaid: number;
  unapplied: number;
  statements: number;
  open: number;
};

export type AccountVendor = {
  id: string;
  name: string;
  branch: string | null;
  channels: string[];
  agency_ids: number[];
};

export type VendorAccountRow = AccountVendor & AccountTotals & {
  aging: AgingBucket[];
  oldest_due: { batch_id: string; day: string | null; age: number | null } | null;
  last_payment: AccountPayment | null;
  check: BalanceCheck | null;
};

export type AccountsResponse = {
  as_of: string;
  vendors: VendorAccountRow[];
  totals: Pick<AccountTotals, "billed" | "claims" | "hold" | "paid" | "balance" | "payable_now" | "advance">;
  aging: AgingBucket[];
  unassigned_statements: number;
};

export type StatementState = "paid" | "part_paid" | "unpaid" | "credit";

export type AccountStatement = MappingStatement & {
  day: string | null;
  age_days: number | null;
  hold: number;
  claim: number;
  approved: number;
  due: number;
  paid: number;
  balance: number;
  payable_now: number;
  credit_used: number | null;
  state: StatementState;
  open: number;
  lines_mapped: number;
  counts: Record<MappingStatus, number>;
};

export type LedgerEntry = {
  day: string | null;
  type: "opening" | "statement" | "claim" | "payment";
  label: string;
  amount: number;
  balance: number;
  batch_id?: string;
  payment_id?: number;
  statement?: string | null;
  period_from?: string | null;
  period_to?: string | null;
};

export type VendorAccount = {
  vendor: AccountVendor;
  totals: AccountTotals;
  aging: AgingBucket[];
  oldest_due: VendorAccountRow["oldest_due"];
  last_payment: AccountPayment | null;
  statements: AccountStatement[];
  payments: AccountPayment[];
  ledger: LedgerEntry[];
  check: BalanceCheck | null;
};
