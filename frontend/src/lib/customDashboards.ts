export type BlockType =
  | "kpi_income" | "kpi_tickets" | "kpi_deals" | "kpi_pending"
  | "chart_monthly" | "chart_by_airline" | "chart_supplier" | "chart_income_breakdown"
  | "table_recent_deals" | "table_pending_approvals" | "table_unmatched" | "table_top_airlines";

export type Block = { id: string; type: BlockType };
export type CustomDashboard = { id: string; name: string; blocks: Block[]; createdAt: string };

export const STORAGE_KEY = "airyield_custom_dashboards";

export function loadDashboards(): CustomDashboard[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]"); } catch { return []; }
}

export function saveDashboards(dashboards: CustomDashboard[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(dashboards));
}
