// Client for the Total Revenue board.
//
// Mirrors backend/app/schemas/revenue_board.py. Shaped like lib/incomeBoard.ts on
// purpose — same axios instance, same repeated-key serialisation, same rule about NULL.
//
// `number | null` IS NOT `number | 0`, and the distinction survives all the way to the
// screen. A null incentive means a deal matched but pays on something the statement does
// not print, so nothing is claimed; rendering it as ₹0 tells the reader "you are owed
// nothing" when the truth is "we could not confirm what you are owed". Every money field
// below that can be null is typed null, and every tile that shows one renders an em dash
// with the affected row count beside it.
import api from "@/lib/api";

export type RevenueScope = "auto" | "mine" | "agency";
export type RevenueBasis = "issue" | "travel";

/** The six statement types whose gross IS the agency's sale, in nav order.
 *  Byte-identical to models/income_board.SALE_SOURCES — they index `by_source`. */
export const SALE_SOURCES = [
  "bsp", "ndc", "lcc-detailed", "tp-gds", "tp-lcc", "tp-api",
] as const;
export type SaleSource = (typeof SALE_SOURCES)[number];

/** Short labels for a column header, where the registry's sheet titles are too long. */
export const SOURCE_SHORT: Record<string, string> = {
  bsp: "BSP",
  ndc: "NDC",
  "lcc-detailed": "LCC",
  "tp-gds": "TP GDS",
  "tp-lcc": "TP LCC",
  "tp-api": "TP API",
};

export interface RevenueTotals {
  sale: number | null;
  sale_rows: number;
  incentive: number | null;
  iata_commission: number | null;
  unpriced_rows: number;
  needs_data_rows: number;
  unmatched_rows: number;
  unattributed_airline_rows: number;
  /** Third Party API rows. No carrier BY NATURE, which is not the same claim as a
   *  carrier that could not be resolved — they never share a bucket. */
  not_carrier_attributed_rows: number;
  undated_rows: number;
  not_counted_rows: number;
  /** What the board left out of `sale` on purpose, so the gap has an answer on screen. */
  not_counted_sale: number | null;
}

export interface SourcePoint {
  source: string;
  category: string;
  label: string;
  sale: number | null;
  rows: number;
  incentive: number | null;
  priced_rows: number;
  unpriced_rows: number;
  not_counted_rows: number;
  share_pct: number;
}

export interface CategoryPoint {
  category: string;
  sale: number | null;
  rows: number;
  incentive: number | null;
  share_pct: number;
  sources: string[];
}

export interface MonthPoint {
  ym: string;
  label: string;
  sale: number | null;
  incentive: number | null;
  rows: number;
  by_source: Record<string, number>;
}

export interface AirlineRevenuePoint {
  airline_id: number | null;
  airline: string;
  sale: number | null;
  incentive: number | null;
  rows: number;
  share_pct: number;
  by_source: Record<string, number>;
  by_incentive_type: Record<string, number>;
}

export interface SupplierPoint {
  supplier_id: number | null;
  supplier: string;
  supplier_code: string | null;
  branch: string | null;
  sale: number | null;
  incentive: number | null;
  rows: number;
  share_pct: number;
}

export interface ProductPoint {
  product: string | null;
  sale: number | null;
  rows: number;
  share_pct: number;
}

export interface IncentiveTypePoint {
  incentive_type: string;
  amount: number | null;
  rows: number;
  share_pct: number;
}

export interface LinkedStatementPoint {
  source: string;
  label: string;
  category: string;
  rows: number;
  /** What the figure IS — "Flown revenue", "Debit memos". Never the word sale. */
  measure_label: string;
  measure: number | null;
  schema_unverified: boolean;
}

export interface NotCountedPoint {
  /** The Report Download's own NET_* wording, so the same row gives the same answer in
   *  the downloadable workbook. Never a phrasing invented for this screen. */
  reason: string;
  rows: number;
  amount: number | null;
  sources: string[];
}

export interface RevenueSummary {
  scope: string;
  basis: string;
  currency: string | null;
  date_from: string | null;
  date_to: string | null;
  totals: RevenueTotals;
  by_category: CategoryPoint[];
  by_source: SourcePoint[];
  by_month: MonthPoint[];
  by_airline: AirlineRevenuePoint[];
  by_supplier: SupplierPoint[];
  by_product: ProductPoint[];
  not_counted: NotCountedPoint[];
  other_currencies: Record<string, number>;
}

export interface AirlineDetail {
  airline_id: number | null;
  airline: string;
  totals: RevenueTotals;
  by_source: SourcePoint[];
  by_month: MonthPoint[];
  by_incentive_type: IncentiveTypePoint[];
  linked: LinkedStatementPoint[];
}

export interface RevenueFilterOptions {
  airlines: { id: number | null; name: string }[];
  suppliers: { id: number | null; name: string; code: string | null }[];
  sources: string[];
  categories: string[];
  months: string[];
  currencies: string[];
  incentive_types: string[];
  can_view_agency: boolean;
  default_scope: string;
}

export interface RevenueQuery {
  scope?: RevenueScope;
  basis?: RevenueBasis;
  date_from?: string;
  date_to?: string;
  airline?: number[];
  supplier?: number[];
  source?: string[];
  category?: string[];
  currency?: string;
  top?: number;
}

// Repeated keys, not comma-joined: FastAPI reads `airline=1&airline=2` as a list and
// would take "1,2" as a single malformed int.
const LIST_PARAMS = { paramsSerializer: { indexes: null as null } };

export async function fetchRevenueSummary(q: RevenueQuery): Promise<RevenueSummary> {
  const { data } = await api.get<RevenueSummary>("/dashboard/revenue/summary", {
    params: q,
    ...LIST_PARAMS,
  });
  return data;
}

export async function fetchIncentiveTypes(q: RevenueQuery): Promise<IncentiveTypePoint[]> {
  const { data } = await api.get<IncentiveTypePoint[]>(
    "/dashboard/revenue/by-incentive-type",
    { params: q, ...LIST_PARAMS },
  );
  return data;
}

export async function fetchAirlineDetail(
  airlineId: number,
  q: RevenueQuery,
): Promise<AirlineDetail> {
  const { data } = await api.get<AirlineDetail>(
    `/dashboard/revenue/airline/${airlineId}`,
    { params: q, ...LIST_PARAMS },
  );
  return data;
}

export async function fetchLinkedStatements(
  q: { scope?: RevenueScope; airline?: number },
): Promise<LinkedStatementPoint[]> {
  const { data } = await api.get<LinkedStatementPoint[]>("/dashboard/revenue/linked", {
    params: q,
  });
  return data;
}

export async function fetchRevenueFilters(
  scope: RevenueScope,
): Promise<RevenueFilterOptions> {
  const { data } = await api.get<RevenueFilterOptions>("/dashboard/revenue/filters", {
    params: { scope },
  });
  return data;
}

/** The last 12 months, as the board's default window — the same default the income
 *  board uses, so switching tabs does not silently change the period. */
export function defaultRange(): { date_from: string; date_to: string } {
  const now = new Date();
  const to = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  const from = new Date(now.getFullYear(), now.getMonth() - 11, 1);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { date_from: iso(from), date_to: iso(to) };
}
