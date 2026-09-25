// Client for the Sales vs Flown board. Mirrors backend/app/schemas/sales_flown.py.
//
// Same axios instance and repeated-key serialisation as lib/revenueBoard.ts, and the
// same NULL rule: `deflator_pct: null` means no flown line printed a fare breakdown —
// "cannot say", never "0% commissionable".
import api from "@/lib/api";
import type { RevenueScope } from "@/lib/revenueBoard";

export interface FlownTotals {
  sold: number | null;
  rows: number;
  flown: number | null;
  unflown: number | null;
  no_travel_date: number | null;
  no_travel_date_rows: number;
  refunds: number | null;
  deflator_pct: number | null;
  deflator_coverage_pct: number | null;
}

export interface CohortCell {
  /** null = the line printed no travel date. */
  flown_ym: string | null;
  amount: number;
  rows: number;
}

export interface CohortRow {
  sale_ym: string;
  label: string;
  sold: number;
  flown: number;
  unflown: number;
  no_travel_date: number;
  rows: number;
  cells: CohortCell[];
}

export interface FlownMonthPoint {
  ym: string;
  label: string;
  flown: number;
  rows: number;
  /** A travel month after as_of — booked to fly, not flown. */
  future: boolean;
}

export interface FlownAirlinePoint {
  airline_id: number | null;
  airline: string;
  sold: number | null;
  flown: number | null;
  unflown: number | null;
  no_travel_date: number | null;
  flown_pct: number;
  deflator_pct: number | null;
  rows: number;
}

export interface SlabBand {
  threshold: number;
  rate_pct: number | null;
}

export interface PlbDealLine {
  deal_id: number;
  deal_no: string;
  entity: string | null;
  channel: string;
  segment: string;
  period_start: string | null;
  period_end: string | null;
  basis_label: string;
  target_based: string;
  bands: SlabBand[];
  flown: number;
  deflator_pct: number | null;
  achieved: number | null;
  rate_pct: number;
  rate_explain: string;
  payout: number | null;
  next_band: SlabBand | null;
  gap_to_next: number | null;
  achieved_pct_of_next: number | null;
}

export interface SalesFlownSummary {
  scope: string;
  currency: string | null;
  as_of: string;
  date_from: string | null;
  date_to: string | null;
  totals: FlownTotals;
  cohorts: CohortRow[];
  flown_months: string[];
  flown_by_month: FlownMonthPoint[];
  by_airline: FlownAirlinePoint[];
  plb_lines: PlbDealLine[];
  plb_airline: string | null;
  other_currencies: Record<string, number>;
}

/** The query both new boards take: a sale window plus the narrowing filters. */
export interface BoardQuery {
  scope?: RevenueScope;
  date_from?: string;
  date_to?: string;
  airline?: number[];
  segment?: "D" | "I";
  source?: string[];
  currency?: string;
  as_of?: string;
}

// Repeated keys, not comma-joined — see lib/revenueBoard.ts.
export const LIST_PARAMS = { paramsSerializer: { indexes: null as null } };

export async function fetchSalesFlown(q: BoardQuery): Promise<SalesFlownSummary> {
  const { data } = await api.get<SalesFlownSummary>("/dashboard/sales-flown/summary", {
    params: q,
    ...LIST_PARAMS,
  });
  return data;
}
