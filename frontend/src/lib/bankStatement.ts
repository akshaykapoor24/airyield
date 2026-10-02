/**
 * Accounting → Bank Statement — types for /bank-statements (api/v1/bank_statements.py).
 *
 * The statement is the tenant's OWN bank account. A deposit linked to a corporate,
 * employee or agency is money received from them; that is what "Billed vs Received"
 * compares with Invoicing. A deposit linked to an agency is also posted into the
 * agency's ledger as a receipt, so it shows on the agency's account too.
 */

export type PartyType = "corporate" | "customer" | "agency";
export type Direction = "in" | "out";

export type PartyRef = {
  party_type: PartyType;
  party_id: number;
  name: string;
  code: string | null;
  detail: string | null;
  channels: string | null;
};

export type BankStatement = {
  id: number;
  bank_name: string | null;
  account_name: string | null;
  account_no: string | null;
  ifsc: string | null;
  branch: string | null;
  currency: string | null;
  period_from: string | null;
  period_to: string | null;
  file_name: string;
  row_count: number;
  duplicate_count: number;
  total_deposits: number;
  total_withdrawals: number;
  created_at: string;
  linked_count: number;
  linked_amount: number;
  unlinked_receipt_count: number;
  unlinked_receipt_amount: number;
};

export type BankRow = {
  id: number;
  statement_id: number;
  line_no: number | null;
  tran_id: string | null;
  value_date: string | null;
  txn_date: string | null;
  posted_at: string | null;
  cheque_ref: string | null;
  remarks: string;
  withdrawal: number;
  deposit: number;
  balance: number | null;
  direction: Direction;
  counterparty: string | null;
  payment_mode: string | null;
  reference: string | null;
  category: string;
  party: PartyRef | null;
  agency_ledger_id: number | null;
  note: string | null;
  suggestion: { party: PartyRef; score: number; source: "history" | "name" } | null;
};

export type StatementDetail = {
  statement: BankStatement;
  rows: BankRow[];
  categories: Record<string, string>;
};

export type UploadResult = {
  statement: BankStatement;
  inserted: number;
  skipped_duplicates: number;
  ignored_lines: number;
};

export type BilledReceivedRow = {
  party: PartyRef;
  billed: number;
  invoices: number;
  received: number;
  receipts: number;
  outstanding: number;
};

export type BilledReceivedSummary = {
  rows: BilledReceivedRow[];
  total_billed: number;
  total_received: number;
  total_outstanding: number;
  unlinked_receipt_count: number;
  unlinked_receipt_amount: number;
};

/** What a deposit / a withdrawal may be called — mirrors services/bank_statement.py. */
export const IN_CATEGORIES = ["receipt", "refund", "transfer", "other"] as const;
export const OUT_CATEGORIES = ["vendor_payment", "credit_card", "bank_charges", "transfer", "other"] as const;

/** "Employee", not "Customer": the customers table IS Employee Master. */
export const PARTY_TYPE_LABEL: Record<PartyType, string> = {
  corporate: "Corporate",
  customer: "Employee",
  agency: "Agency",
};

/** "2026-09-01" → "01 Sep 2026". */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function partyLabel(p: PartyRef): string {
  return `${PARTY_TYPE_LABEL[p.party_type]} · ${p.name}`;
}

/** The server's error message, or a fallback. */
export function errText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}
