/**
 * Types, fetchers and shared tokens for the PLB accrual dashboard.
 *
 * Mirrors the response models in backend/app/api/v1/dashboard.py. Kept in one
 * place so the Overview and the Accrual board cannot drift apart — they read the
 * same board from the same cache.
 */
import api from "@/lib/api";

// ── API shapes ───────────────────────────────────────────────────────────────

export type CellSource = "derived" | "manual" | "pooled" | "none";

export interface MonthCell {
  ym: string;
  flown: number;
  source: CellSource;
  in_period: boolean;
  confirmed: boolean;
  deflator_pct: number;
  commissionable: number;
  pool: number;
}

export interface AccrualRow {
  key: string;
  deal_id: number | null;
  deal_no: string | null;
  airline_name: string;
  channel: string;
  entity: string | null;
  lob: string | null;
  plb_period_from: string | null;
  plb_period_to: string | null;
  plb_period_label: string;
  flown_confirmed_through: string | null;
  basis_label: string;
  deflator_pct: number;
  deflator_source: string;
  plb_rate_pct: number;
  plb_rate_source: string;
  plb_rate_explain: string;
  months: Record<string, MonthCell>;
  flown_total: number;
  flown_in_period: number;
  commissionable_base: number;
  accrual: number;
  accrual_at_risk: number;
  status: StatusCode;
  status_flags: StatusCode[];
  reasons: string[];
}

export interface AccrualTotals {
  rows: number;
  flown_total: number;
  flown_in_period: number;
  commissionable_base: number;
  accrual: number;
  accrual_at_risk: number;
  by_month: Record<string, number>;
  accrual_by_month: Record<string, number>;
  flown_at_risk: number;
  status_counts: Record<string, number>;
  effective_deflator_pct: number;
  effective_yield_pct: number;
  flown_confirmed: number;
  flown_provisional: number;
}

export interface Frozen {
  period_key: string;
  frozen_at: string;
  total_accrual: number | null;
  row_count: number;
  note: string | null;
}

export interface PeriodInfo {
  key: string;
  label: string;
  from: string;
  to: string;
}

export interface DataQuality {
  travel_date_coverage_pct: number | null;
  unattributed_airlines: string[];
}

export interface AccrualBoard {
  period: PeriodInfo;
  months: string[];
  basis: string;
  rows: AccrualRow[];
  totals: AccrualTotals;
  data_quality: DataQuality;
  frozen: Frozen | null;
}

export interface AccrualFilterOptions {
  airlines: string[];
  entities: string[];
  channels: string[];
  lobs: string[];
  statuses: StatusCode[];
  periods: { key: string; label: string }[];
}

export interface OverviewResponse {
  period: PeriodInfo;
  totals: AccrualTotals;
  monthly: { ym: string; label: string; flown: number; accrual: number }[];
  by_airline: {
    airline: string;
    flown: number;
    accrual: number;
    share_pct: number;
    cumulative_pct: number;
  }[];
  by_entity: { entity: string; accrual: number; by_airline: Record<string, number> }[];
  entity_airlines: string[];
  exceptions: {
    code: StatusCode;
    label: string;
    count: number;
    amount: number;
    airlines: string[];
  }[];
  actions: {
    pending_deal_approvals: number;
    deals_awaiting_review: number;
    statements_awaiting_commission: number;
    unmatched_commission_rows: number;
  };
  data_quality: DataQuality;
  frozen: Frozen | null;
}

// ── Status vocabulary ────────────────────────────────────────────────────────

export type StatusCode =
  | "EXPIRED_WITH_FLOWN"
  | "NO_DEAL"
  | "NO_RATE"
  | "NEEDS_SPLIT"
  | "EXPIRING"
  | "UNCONFIRMED"
  | "OK";

/**
 * Status colours are reserved — they mean a state, never a data series, and every
 * use ships with a label so the colour is not the only channel. `bar` paints the
 * grid row's left edge, replacing the highlight someone applied by hand in Excel.
 */
export const STATUS: Record<
  StatusCode,
  { label: string; short: string; chip: string; bar: string; blurb: string }
> = {
  EXPIRED_WITH_FLOWN: {
    label: "Flown outside the deal period",
    short: "Expired",
    chip: "bg-red-50 text-red-700 ring-1 ring-red-200",
    bar: "#dc2626",
    blurb: "Revenue flew in months this contract does not cover. Renew it, or reverse the at-risk amount.",
  },
  NO_DEAL: {
    label: "No PLB deal on file",
    short: "No deal",
    chip: "bg-red-50 text-red-700 ring-1 ring-red-200",
    bar: "#dc2626",
    blurb: "Flown revenue with no approved PLB deal behind it — nothing is being claimed.",
  },
  NO_RATE: {
    label: "Zero rate on live volume",
    short: "No rate",
    chip: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    bar: "#d97706",
    blurb: "The deal is live and carrying volume, but resolves to a 0% rate.",
  },
  NEEDS_SPLIT: {
    label: "Flown not attributed to an entity",
    short: "Split",
    chip: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    bar: "#d97706",
    blurb: "Several entities hold a deal for this airline and the agent code did not resolve. Key the split.",
  },
  EXPIRING: {
    label: "Deal expiring within 90 days",
    short: "Expiring",
    chip: "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
    bar: "#ea580c",
    blurb: "The PLB period ends soon — renegotiate before it lapses.",
  },
  UNCONFIRMED: {
    label: "Airline has not confirmed these months",
    short: "Provisional",
    chip: "bg-slate-100 text-slate-600 ring-1 ring-slate-200",
    bar: "#94a3b8",
    blurb: "Flown data is later than the airline's confirmed month, so this accrual is provisional.",
  },
  OK: {
    label: "No issues",
    short: "OK",
    chip: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
    bar: "transparent",
    blurb: "",
  },
};

/** Worst-first, matching STATUS_ORDER in services/plb_accrual.py. */
export const STATUS_ORDER: StatusCode[] = [
  "EXPIRED_WITH_FLOWN", "NO_DEAL", "NO_RATE", "NEEDS_SPLIT",
  "EXPIRING", "UNCONFIRMED", "OK",
];

// ── Chart tokens ─────────────────────────────────────────────────────────────

/**
 * Two categorical slots, validated with the palette checker (all checks pass on a
 * light surface): confirmed vs provisional flown. They are one hue two steps
 * apart because the pair is ordered, not two identities. The contrast warning on
 * the lighter step is answered by the legend, the direct-labelled totals and the
 * accrual grid, which is this dashboard's table view.
 */
export const SERIES = {
  confirmed: "#2563eb",
  provisional: "#60a5fa",
  accrual: "#2563eb",
} as const;

/** Sequential ramp for the entity × airline matrix — one hue, light to dark. */
export const HEAT_RAMP = ["#eff6ff", "#bfdbfe", "#93c5fd", "#60a5fa", "#2563eb"];

/** Solid hairline one step off the surface — never dashed. */
export const GRID_STROKE = "#eef2f7";
export const AXIS_TICK = { fontSize: 11, fill: "#64748b" };

// ── Fetchers ─────────────────────────────────────────────────────────────────

export interface BoardQuery {
  period?: string;
  basis?: string;
  airline?: string[];
  entity?: string[];
  channel?: string[];
  lob?: string[];
  status?: string[];
  search?: string;
}

/** axios serialises arrays as `a[]=x`; FastAPI wants repeated `a=x`. */
function toParams(q: BoardQuery): URLSearchParams {
  const p = new URLSearchParams();
  Object.entries(q).forEach(([k, v]) => {
    if (v == null || v === "") return;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.append(k, String(v));
  });
  return p;
}

export async function fetchBoard(q: BoardQuery): Promise<AccrualBoard> {
  const { data } = await api.get<AccrualBoard>(`/dashboard/accrual?${toParams(q)}`);
  return data;
}

export async function fetchOverview(q: BoardQuery): Promise<OverviewResponse> {
  const { data } = await api.get<OverviewResponse>(`/dashboard/overview?${toParams(q)}`);
  return data;
}

export async function fetchFilters(period?: string): Promise<AccrualFilterOptions> {
  const { data } = await api.get<AccrualFilterOptions>(
    `/dashboard/accrual/filters${period ? `?period=${encodeURIComponent(period)}` : ""}`,
  );
  return data;
}

export interface CellPatch {
  airline_name: string;
  entity?: string | null;
  channel?: string | null;
  lob?: string | null;
  ym: string;
  deflator_pct?: number | null;
  plb_rate_pct?: number | null;
  manual_flown?: number | null;
}

export async function patchCells(period: string, cells: CellPatch[]) {
  const { data } = await api.patch(`/dashboard/accrual/inputs`, { period, cells });
  return data;
}

export async function patchConfirmedThrough(items: {
  airline_name: string;
  entity?: string | null;
  channel?: string | null;
  flown_confirmed_through: string | null;
}[]) {
  const { data } = await api.patch(`/dashboard/accrual/settings`, items);
  return data;
}

export async function freezePeriod(period: string, note?: string) {
  const { data } = await api.post(`/dashboard/accrual/freeze`, { period, note });
  return data as Frozen;
}

export async function reopenPeriod(periodKey: string) {
  await api.delete(`/dashboard/accrual/freeze/${encodeURIComponent(periodKey)}`);
}

export async function downloadBoardXlsx(q: BoardQuery) {
  const res = await api.get(`/dashboard/accrual/xlsx?${toParams(q)}`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(new Blob([res.data]));
  const a = document.createElement("a");
  a.href = url;
  a.download = `plb-accrual-${q.period || "current"}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
