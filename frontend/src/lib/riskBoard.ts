// Client for the Risk analysis board. Mirrors backend/app/schemas/risk_board.py.
import api from "@/lib/api";
import { LIST_PARAMS, type BoardQuery } from "@/lib/salesFlown";

export type RiskLevel = "low" | "medium" | "high";

export interface RiskFactorDef {
  key: string;
  label: string;
  explain: string;
  /** % at which the factor turns medium, and high. Printed on the page. */
  medium: number;
  high: number;
}

export interface RiskTotals {
  sold: number | null;
  issued: number | null;
  rows: number;
  unflown: number | null;
  no_travel_date: number | null;
  refunds: number | null;
  unmatched_sale: number | null;
  needs_data_sale: number | null;
  unpriced_sale: number | null;
  incentive: number | null;
  slab_dependent_incentive: number | null;
  adm_exposure: number | null;
  adm_count: number;
  acm_credit: number | null;
  under_recovery: number | null;
  declared_mismatch_rows: number;
  top_airline: string | null;
  top_airline_share_pct: number;
  top3_share_pct: number;
  hhi: number;
}

export interface AgingBucket {
  key: string;
  label: string;
  amount: number;
  rows: number;
}

export interface RiskAirlineRow {
  airline_id: number | null;
  airline: string;
  sold: number | null;
  share_pct: number;
  rows: number;
  factors: Record<string, number>;
  levels: Record<string, RiskLevel>;
  level: RiskLevel;
  score: number;
  unflown: number | null;
  incentive: number | null;
  slab_dependent_incentive: number | null;
  adm_exposure: number | null;
}

export interface RiskSummary {
  scope: string;
  currency: string | null;
  as_of: string;
  date_from: string | null;
  date_to: string | null;
  factors: RiskFactorDef[];
  totals: RiskTotals;
  overall_levels: Record<string, RiskLevel>;
  overall_factors: Record<string, number>;
  concentration_level: RiskLevel;
  unflown_aging: AgingBucket[];
  by_airline: RiskAirlineRow[];
  level_counts: Record<RiskLevel, number>;
  other_currencies: Record<string, number>;
}

export async function fetchRiskSummary(q: BoardQuery): Promise<RiskSummary> {
  const { data } = await api.get<RiskSummary>("/dashboard/risk/summary", {
    params: q,
    ...LIST_PARAMS,
  });
  return data;
}

/** Status tokens: reserved for state, always shipped with a text label. */
export const LEVEL_META: Record<RiskLevel, { label: string; chip: string; cell: string }> = {
  high: {
    label: "High",
    chip: "bg-red-50 text-red-700 ring-1 ring-red-200",
    cell: "bg-red-50 text-red-800",
  },
  medium: {
    label: "Medium",
    chip: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    cell: "bg-amber-50 text-amber-900",
  },
  low: {
    label: "Low",
    chip: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    cell: "text-gray-700",
  },
};
