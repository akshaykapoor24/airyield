"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  Plus, X, Edit2, Save, Trash2, RefreshCw, LayoutGrid,
  ChevronUp, ChevronDown,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, RadarChart, Radar, PolarGrid, PolarAngleAxis, Legend,
} from "recharts";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import {
  type BlockType, type CustomDashboard,
  loadDashboards, saveDashboards,
} from "@/lib/customDashboards";

// ── API response types ─────────────────────────────────────────────────────────

type SummaryResp = {
  total_income: number; total_tickets: number; active_deals: number; pending_count: number;
  monthly_income: { month: string; income: number }[];
  income_by_airline: { airline: string; income: number }[];
};
type PendingResp = {
  deal_approvals: { id: number; deal_ref: string; airline_name: string; submitted_by: string }[];
  unmatched_tickets: { id: number; ticket_number: string|null; airlines_code: string|null; airline_name: string|null; sector: string|null }[];
};
type IncomeSummaryResp = {
  by_airline: { airline: string; commission: number; total: number }[];
  monthly: { month: string; commission: number; incentive: number; adm: number }[];
};
type SupplierResp = {
  suppliers: { name: string; total_income: number; deal_count: number; ticket_count: number }[];
};
type DealRow = { id: number; deal_no: string|null; airline_name: string|null; status: string };

// ── Block Library ──────────────────────────────────────────────────────────────

const BLOCK_LIBRARY: Array<{ type: BlockType; label: string; description: string; category: string }> = [
  { type: "kpi_income",              label: "Total Income",         description: "All-time income KPI card",             category: "KPI" },
  { type: "kpi_tickets",             label: "Total Tickets",         description: "Total uploaded tickets",              category: "KPI" },
  { type: "kpi_deals",               label: "Active Deals",          description: "Currently approved deals",            category: "KPI" },
  { type: "kpi_pending",             label: "Pending Actions",       description: "Items requiring attention",           category: "KPI" },
  { type: "chart_monthly",           label: "Monthly Income Trend",  description: "Line chart of income over months",    category: "Charts" },
  { type: "chart_by_airline",        label: "Income by Airline",     description: "Bar chart per airline",               category: "Charts" },
  { type: "chart_supplier",          label: "Supplier Comparison",   description: "Radar chart comparing suppliers",     category: "Charts" },
  { type: "chart_income_breakdown",  label: "Income Breakdown",      description: "Stacked bar: commission/incentive/ADM", category: "Charts" },
  { type: "table_recent_deals",      label: "Recent Deals",          description: "Latest deals uploaded",               category: "Tables" },
  { type: "table_pending_approvals", label: "Pending Approvals",     description: "Deals awaiting approval",             category: "Tables" },
  { type: "table_unmatched",         label: "Unmatched Tickets",     description: "Tickets not matched to any deal",     category: "Tables" },
  { type: "table_top_airlines",      label: "Top Airlines",          description: "Airlines ranked by income",           category: "Tables" },
];

function fmt(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

// ── Data hooks (one per API endpoint) ─────────────────────────────────────────

function useSummary() {
  const [data, setData] = useState<SummaryResp | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get<SummaryResp>("/dashboard/summary").then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);
  return { data, loading };
}

function usePendingActions() {
  const [data, setData] = useState<PendingResp | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get<PendingResp>("/dashboard/pending-actions").then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);
  return { data, loading };
}

function useIncomeSummary() {
  const [data, setData] = useState<IncomeSummaryResp | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get<IncomeSummaryResp>("/dashboard/income-summary").then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);
  return { data, loading };
}

function useSupplierComparison() {
  const [data, setData] = useState<SupplierResp | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get<SupplierResp>("/dashboard/supplier-comparison").then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);
  return { data, loading };
}

function useRecentDeals() {
  const [data, setData] = useState<DealRow[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get<DealRow[]>("/deals?limit=10").then(r => setData(r.data)).finally(() => setLoading(false));
  }, []);
  return { data, loading };
}

function Spinner() {
  return (
    <div className="flex items-center justify-center h-24 text-gray-300">
      <RefreshCw className="w-4 h-4 animate-spin" />
    </div>
  );
}

// ── KPI Blocks ─────────────────────────────────────────────────────────────────

function KpiIncomeBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  return (
    <>
      <p className="text-xs text-gray-500 uppercase font-medium mb-1">Total Income</p>
      <p className="text-3xl font-bold text-gray-900">{data ? formatCurrency(data.total_income) : "—"}</p>
      <p className="text-xs text-gray-400 mt-1">All time · all heads</p>
    </>
  );
}

function KpiTicketsBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  return (
    <>
      <p className="text-xs text-gray-500 uppercase font-medium mb-1">Total Tickets</p>
      <p className="text-3xl font-bold text-gray-900">{data ? data.total_tickets.toLocaleString() : "—"}</p>
      <p className="text-xs text-gray-400 mt-1">All uploaded</p>
    </>
  );
}

function KpiDealsBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  return (
    <>
      <p className="text-xs text-gray-500 uppercase font-medium mb-1">Active Deals</p>
      <p className="text-3xl font-bold text-gray-900">{data ? data.active_deals : "—"}</p>
      <p className="text-xs text-gray-400 mt-1">Currently approved</p>
    </>
  );
}

function KpiPendingBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  return (
    <>
      <p className="text-xs text-gray-500 uppercase font-medium mb-1">Pending Actions</p>
      <p className="text-3xl font-bold text-orange-500">{data ? data.pending_count : "—"}</p>
      <p className="text-xs text-gray-400 mt-1">Require attention</p>
    </>
  );
}

// ── Chart Blocks ───────────────────────────────────────────────────────────────

function ChartMonthlyBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  const monthly = data?.monthly_income ?? [];
  if (!monthly.length) return <div className="flex items-center justify-center h-40 text-sm text-gray-400">No income data yet</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-3">Monthly Income Trend</p>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={monthly}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="month" tick={{ fontSize: 10 }} />
          <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
          <Line type="monotone" dataKey="income" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2 }} />
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}

function ChartByAirlineBlock() {
  const { data, loading } = useSummary();
  if (loading) return <Spinner />;
  const airlines = data?.income_by_airline ?? [];
  if (!airlines.length) return <div className="flex items-center justify-center h-40 text-sm text-gray-400">No data yet</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-3">Income by Airline</p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={airlines} layout="vertical">
          <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 9 }} />
          <YAxis type="category" dataKey="airline" tick={{ fontSize: 9 }} width={65} />
          <Tooltip formatter={(v) => formatCurrency(Number(v))} />
          <Bar dataKey="income" fill="#6366f1" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </>
  );
}

const RADAR_COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444"];

function ChartSupplierBlock() {
  const { data, loading } = useSupplierComparison();
  if (loading) return <Spinner />;
  const suppliers = (data?.suppliers ?? []).slice(0, 5);
  if (!suppliers.length) return <div className="flex items-center justify-center h-40 text-sm text-gray-400">No supplier data</div>;
  const maxIncome  = Math.max(...suppliers.map(s => s.total_income), 1);
  const maxDeals   = Math.max(...suppliers.map(s => s.deal_count), 1);
  const maxTickets = Math.max(...suppliers.map(s => s.ticket_count), 1);
  const radarData = [
    { subject: "Income",  ...Object.fromEntries(suppliers.map(s => [s.name, Math.round((s.total_income / maxIncome) * 100)])) },
    { subject: "Deals",   ...Object.fromEntries(suppliers.map(s => [s.name, Math.round((s.deal_count / maxDeals) * 100)])) },
    { subject: "Tickets", ...Object.fromEntries(suppliers.map(s => [s.name, Math.round((s.ticket_count / maxTickets) * 100)])) },
  ];
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-3">Supplier Comparison</p>
      <ResponsiveContainer width="100%" height={180}>
        <RadarChart data={radarData}>
          <PolarGrid />
          <PolarAngleAxis dataKey="subject" tick={{ fontSize: 10 }} />
          {suppliers.map((s, i) => (
            <Radar key={s.name} name={s.name} dataKey={s.name} stroke={RADAR_COLORS[i]} fill={RADAR_COLORS[i]} fillOpacity={0.1} />
          ))}
          <Legend wrapperStyle={{ fontSize: 9 }} />
        </RadarChart>
      </ResponsiveContainer>
    </>
  );
}

function ChartIncomeBreakdownBlock() {
  const { data, loading } = useIncomeSummary();
  if (loading) return <Spinner />;
  const monthly = data?.monthly ?? [];
  if (!monthly.length) return <div className="flex items-center justify-center h-40 text-sm text-gray-400">No data yet</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-3">Income Breakdown</p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={monthly}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="month" tick={{ fontSize: 9 }} />
          <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 9 }} />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 9 }} />
          <Bar dataKey="commission" name="Commission" stackId="a" fill="#3b82f6" />
          <Bar dataKey="incentive"  name="Incentive"  stackId="a" fill="#8b5cf6" />
          <Bar dataKey="adm"        name="ADM"        stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </>
  );
}

// ── Table Blocks ───────────────────────────────────────────────────────────────

function TableRecentDealsBlock() {
  const { data, loading } = useRecentDeals();
  if (loading) return <Spinner />;
  if (!data.length) return <div className="flex items-center justify-center h-24 text-sm text-gray-400">No deals yet</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-2">Recent Deals</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 uppercase text-[10px]">
            <th className="pb-1.5 text-left">Reference</th>
            <th className="pb-1.5 text-left">Airline</th>
            <th className="pb-1.5 text-left">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {data.slice(0, 6).map((d) => (
            <tr key={d.id}>
              <td className="py-1.5 font-mono text-blue-600">{d.deal_no ?? `DEAL-${String(d.id).padStart(4, "0")}`}</td>
              <td className="py-1.5 font-medium">{d.airline_name ?? "—"}</td>
              <td className="py-1.5">
                <span className="bg-gray-100 px-1.5 py-0.5 rounded text-[10px]">{d.status.replace(/_/g, " ")}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TablePendingApprovalsBlock() {
  const { data, loading } = usePendingActions();
  if (loading) return <Spinner />;
  const items = data?.deal_approvals ?? [];
  if (!items.length) return <div className="flex items-center justify-center h-24 text-sm text-gray-400">No pending approvals</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-2">Pending Approvals</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 uppercase text-[10px]">
            <th className="pb-1.5 text-left">Reference</th>
            <th className="pb-1.5 text-left">Airline</th>
            <th className="pb-1.5 text-left">Submitted By</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.slice(0, 6).map((a) => (
            <tr key={a.id}>
              <td className="py-1.5 font-mono text-blue-600">{a.deal_ref}</td>
              <td className="py-1.5 font-medium">{a.airline_name}</td>
              <td className="py-1.5 text-gray-500">{a.submitted_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TableUnmatchedBlock() {
  const { data, loading } = usePendingActions();
  if (loading) return <Spinner />;
  const items = data?.unmatched_tickets ?? [];
  if (!items.length) return <div className="flex items-center justify-center h-24 text-sm text-gray-400">All tickets matched</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-2">Unmatched Tickets</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 uppercase text-[10px]">
            <th className="pb-1.5 text-left">Ticket #</th>
            <th className="pb-1.5 text-left">Airline</th>
            <th className="pb-1.5 text-left">Sector</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {items.slice(0, 6).map((t) => (
            <tr key={t.id}>
              <td className="py-1.5 font-mono">{t.ticket_number ?? `#${t.id}`}</td>
              <td className="py-1.5 font-medium">{t.airline_name || t.airlines_code || "—"}</td>
              <td className="py-1.5 text-gray-500">{t.sector ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function TableTopAirlinesBlock() {
  const { data, loading } = useIncomeSummary();
  if (loading) return <Spinner />;
  const airlines = data?.by_airline ?? [];
  if (!airlines.length) return <div className="flex items-center justify-center h-24 text-sm text-gray-400">No data yet</div>;
  return (
    <>
      <p className="text-xs font-semibold text-gray-700 mb-2">Top Airlines by Income</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-400 uppercase text-[10px]">
            <th className="pb-1.5 text-left">Airline</th>
            <th className="pb-1.5 text-right">Commission</th>
            <th className="pb-1.5 text-right">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {airlines.slice(0, 6).map((r) => (
            <tr key={r.airline}>
              <td className="py-1.5 font-medium">{r.airline}</td>
              <td className="py-1.5 text-right text-gray-500">{fmt(r.commission)}</td>
              <td className="py-1.5 text-right font-semibold">{fmt(r.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ── Block Renderer ─────────────────────────────────────────────────────────────

function BlockRenderer({ type }: { type: BlockType }) {
  switch (type) {
    case "kpi_income":              return <KpiIncomeBlock />;
    case "kpi_tickets":             return <KpiTicketsBlock />;
    case "kpi_deals":               return <KpiDealsBlock />;
    case "kpi_pending":             return <KpiPendingBlock />;
    case "chart_monthly":           return <ChartMonthlyBlock />;
    case "chart_by_airline":        return <ChartByAirlineBlock />;
    case "chart_supplier":          return <ChartSupplierBlock />;
    case "chart_income_breakdown":  return <ChartIncomeBreakdownBlock />;
    case "table_recent_deals":      return <TableRecentDealsBlock />;
    case "table_pending_approvals": return <TablePendingApprovalsBlock />;
    case "table_unmatched":         return <TableUnmatchedBlock />;
    case "table_top_airlines":      return <TableTopAirlinesBlock />;
    default:                        return null;
  }
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function CustomDashboardPage() {
  const params       = useParams();
  const router       = useRouter();
  const searchParams = useSearchParams();

  const id     = params.id as string;
  const isNew  = id === "new";
  const editMode = isNew || searchParams.get("edit") === "true";

  // Lazy init: on client, load from localStorage; on server return a safe placeholder
  const [dashboard, setDashboard] = useState<CustomDashboard>(() => {
    if (isNew) {
      return { id: crypto.randomUUID(), name: "My Dashboard", blocks: [], createdAt: new Date().toISOString() };
    }
    if (typeof window !== "undefined") {
      const saved = loadDashboards().find(d => d.id === id);
      if (saved) return saved;
    }
    return { id, name: "My Dashboard", blocks: [], createdAt: "" };
  });

  const notFound = !isNew && typeof window !== "undefined" && !loadDashboards().find(d => d.id === id) && dashboard.createdAt === "";

  const [editingName, setEditingName] = useState(false);

  if (notFound) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-gray-500 text-sm">Dashboard not found.</p>
        <button onClick={() => router.replace("/dashboard")} className="text-blue-600 text-sm hover:underline">Go home</button>
      </div>
    );
  }

  const addBlock = (type: BlockType) => {
    setDashboard(d => ({ ...d, blocks: [...d.blocks, { id: crypto.randomUUID(), type }] }));
  };

  const removeBlock = (blockId: string) => {
    setDashboard(d => ({ ...d, blocks: d.blocks.filter(b => b.id !== blockId) }));
  };

  const moveBlock = (blockId: string, dir: -1 | 1) => {
    setDashboard(d => {
      const idx = d.blocks.findIndex(b => b.id === blockId);
      if (idx < 0) return d;
      const blocks = [...d.blocks];
      const target = idx + dir;
      if (target < 0 || target >= blocks.length) return d;
      [blocks[idx], blocks[target]] = [blocks[target], blocks[idx]];
      return { ...d, blocks };
    });
  };

  const save = () => {
    const all = loadDashboards();
    const idx = all.findIndex(d => d.id === dashboard.id);
    if (idx >= 0) all[idx] = dashboard;
    else all.push(dashboard);
    saveDashboards(all);
    router.replace(`/dashboard/${dashboard.id}`);
  };

  const deleteDashboard = () => {
    saveDashboards(loadDashboards().filter(d => d.id !== dashboard.id));
    router.replace("/dashboard");
  };

  const categories = ["KPI", "Charts", "Tables"];

  return (
    <div className="flex gap-6">
      {/* ── Main area ── */}
      <div className="flex-1 min-w-0 space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <LayoutGrid className="w-5 h-5 text-blue-500 shrink-0" />
            {editMode && editingName ? (
              <input
                autoFocus
                className="text-2xl font-bold text-gray-900 border-b-2 border-blue-400 focus:outline-none bg-transparent flex-1 min-w-0"
                value={dashboard.name}
                onChange={e => setDashboard(d => ({ ...d, name: e.target.value }))}
                onBlur={() => setEditingName(false)}
                onKeyDown={e => { if (e.key === "Enter") setEditingName(false); }}
              />
            ) : (
              <h1
                className={`text-2xl font-bold text-gray-900 truncate ${editMode ? "cursor-pointer hover:text-blue-600" : ""}`}
                onClick={() => { if (editMode) setEditingName(true); }}
              >
                {dashboard.name}
                {editMode && <Edit2 className="inline ml-2 w-4 h-4 text-gray-400 align-middle" />}
              </h1>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {!editMode && (
              <button
                onClick={() => router.push(`/dashboard/${id}?edit=true`)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors"
              >
                <Edit2 className="w-3.5 h-3.5" /> Edit
              </button>
            )}
            {editMode && (
              <>
                <button
                  onClick={save}
                  className="flex items-center gap-1.5 px-4 py-1.5 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
                >
                  <Save className="w-3.5 h-3.5" /> Save Dashboard
                </button>
                {!isNew && (
                  <button
                    onClick={deleteDashboard}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-red-600 border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                )}
              </>
            )}
          </div>
        </div>

        {/* Block Grid */}
        {dashboard.blocks.length === 0 ? (
          <div className="bg-white rounded-xl border-2 border-dashed border-gray-200 flex flex-col items-center justify-center py-20 gap-3">
            <LayoutGrid className="w-8 h-8 text-gray-300" />
            <p className="text-gray-400 text-sm">
              {editMode ? "Click blocks in the panel on the right to add them here." : "No blocks added yet."}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {dashboard.blocks.map((block, idx) => (
              <div key={block.id} className="bg-white rounded-xl border border-gray-200 p-5 relative">
                {editMode && (
                  <div className="absolute top-2 right-2 flex items-center gap-0.5 z-10">
                    <button
                      title="Move up"
                      disabled={idx === 0}
                      onClick={() => moveBlock(block.id, -1)}
                      className="p-1 rounded text-gray-300 hover:text-gray-600 disabled:opacity-20 transition-colors"
                    >
                      <ChevronUp className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="Move down"
                      disabled={idx === dashboard.blocks.length - 1}
                      onClick={() => moveBlock(block.id, 1)}
                      className="p-1 rounded text-gray-300 hover:text-gray-600 disabled:opacity-20 transition-colors"
                    >
                      <ChevronDown className="w-3.5 h-3.5" />
                    </button>
                    <button
                      title="Remove block"
                      onClick={() => removeBlock(block.id)}
                      className="p-1 rounded text-gray-300 hover:text-red-500 transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
                <BlockRenderer type={block.type} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Block Library Panel (edit mode only) ── */}
      {editMode && (
        <div className="w-68 shrink-0" style={{ width: 272 }}>
          <div className="sticky top-6 bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-900">Block Library</h2>
              <p className="text-xs text-gray-400 mt-0.5">Click any block to add it</p>
            </div>
            <div className="p-3 space-y-4 overflow-y-auto" style={{ maxHeight: "calc(100vh - 11rem)" }}>
              {categories.map(cat => (
                <div key={cat}>
                  <p className="text-[10px] uppercase font-bold text-gray-400 tracking-wide mb-1.5">{cat}</p>
                  <div className="space-y-1">
                    {BLOCK_LIBRARY.filter(b => b.category === cat).map(b => (
                      <button
                        key={b.type}
                        onClick={() => addBlock(b.type)}
                        className="w-full text-left px-3 py-2 rounded-lg border border-gray-100 hover:border-blue-300 hover:bg-blue-50 transition-colors group"
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-xs font-medium text-gray-700 group-hover:text-blue-700 truncate">{b.label}</span>
                          <Plus className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-500 shrink-0" />
                        </div>
                        <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">{b.description}</p>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
