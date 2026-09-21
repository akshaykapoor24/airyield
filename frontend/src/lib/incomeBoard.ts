/**
 * The income board's client surface.
 *
 * Mirrors the response models in backend/app/schemas/income_board.py. When one
 * changes, change the other in the same commit — nothing enforces this at build time.
 *
 * WHY EVERY MONEY FIELD IS `number | null`. `incentive` is NULL when a deal matched but
 * pays on something the statement does not print, so nothing is claimed. That is not
 * zero: zero means the deal applied and earned nothing. The backend keeps the two
 * apart all the way down to the column, and these types carry the distinction to the
 * screen so that `?? 0` has to be a deliberate act rather than an accident of typing.
 * Render a null as an em dash with the affected row count beside it — never as ₹0.
 *
 * The type is `IncomeCounterpartyKind`, not `CounterpartyKind`: lib/counterparty.ts
 * already exports that name for the Customer Directory with entirely different values
 * ("direct" | "agency" | "corporate"), and two of them in one app is a bug waiting to
 * be written.
 */
import api from "@/lib/api";

export type IncomeCounterpartyKind = "airline" | "supplier" | "customer";
export type IncomeScope = "mine" | "agency";
export type IncomeBasis = "issue" | "travel";

export type IncomeTotals = {
  vendor_income: number | null;
  iata_commission: number | null;
  gross_revenue: number | null;
  commission_paid: number | null;
  markup_income: number | null;
  spread: number | null;
  rows: number;
  needs_data_rows: number;
  unmatched_rows: number;
  unattributed_airline_rows: number;
  unattributed_supplier_rows: number;
  debit_memo_amount: number | null;
  credit_memo_amount: number | null;
  slab_dependent_rows: number;
};

export type AirlinePoint = {
  airline_id: number | null;
  airline: string;
  incentive: number | null;
  iata_commission: number | null;
  gross: number | null;
  rows: number;
  needs_data_rows: number;
  share_pct: number;
  cumulative_pct: number;
};

export type SupplierPoint = {
  supplier_id: number | null;
  supplier: string;
  supplier_code: string | null;
  branch: string | null;
  incentive: number | null;
  iata_commission: number | null;
  gross: number | null;
  rows: number;
  needs_data_rows: number;
  share_pct: number;
  cumulative_pct: number;
  match_quality: string | null;
};

export type MonthPoint = {
  ym: string;
  label: string;
  incentive: number | null;
  gross: number | null;
  rows: number;
  has_slab_dependent: boolean;
};

export type SourcePoint = {
  source: string;
  label: string;
  incentive: number | null;
  rows: number;
  needs_data_rows: number;
};

export type IncomeSummary = {
  scope: IncomeScope;
  basis: IncomeBasis;
  date_from: string | null;
  date_to: string | null;
  totals: IncomeTotals;
  by_month: MonthPoint[];
  by_airline: AirlinePoint[];
  by_supplier: SupplierPoint[];
  by_source: SourcePoint[];
};

export type FilterOptions = {
  airlines: { id: number | null; name: string }[];
  suppliers: { id: number | null; name: string; code: string | null }[];
  sources: string[];
  months: string[];
  can_view_agency: boolean;
};

export type SourceFreshness = {
  source: string;
  batches: number;
  projected: number;
  stale: number;
  never: number;
  last_projected_at: string | null;
};

export type Freshness = {
  by_source: SourceFreshness[];
  stale_total: number;
  never_total: number;
  ok: boolean;
};

export type IncomeQuery = {
  scope?: IncomeScope;
  basis?: IncomeBasis;
  date_from?: string;
  date_to?: string;
  airline?: number[];
  supplier?: number[];
  source?: string[];
  top?: number;
};

export async function fetchIncomeSummary(q: IncomeQuery): Promise<IncomeSummary> {
  const { data } = await api.get<IncomeSummary>("/dashboard/income/summary", {
    params: q,
    // Repeated keys, not comma-joined: FastAPI reads `airline=1&airline=2` as a list
    // and would take "1,2" as a single malformed int.
    paramsSerializer: { indexes: null },
  });
  return data;
}

export async function fetchIncomeFilters(scope: IncomeScope): Promise<FilterOptions> {
  const { data } = await api.get<FilterOptions>("/dashboard/income/filters", {
    params: { scope },
  });
  return data;
}

export async function fetchIncomeFreshness(): Promise<Freshness> {
  const { data } = await api.get<Freshness>("/dashboard/income/freshness");
  return data;
}

export async function rebuildIncomeBoard(): Promise<{
  batches: number;
  rows_by_source: Record<string, number>;
  failed: string[];
}> {
  const { data } = await api.post("/dashboard/income/rebuild");
  return data;
}

/** The last 12 months, as the board's default window. */
export function defaultRange(): { date_from: string; date_to: string } {
  const now = new Date();
  const to = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const from = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { date_from: iso(from), date_to: iso(to) };
}
