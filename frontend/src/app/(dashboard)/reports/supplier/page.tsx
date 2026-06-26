"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Building2, Filter, TrendingUp, Ticket, Wallet, FileSpreadsheet, AlertCircle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import api from "@/lib/api";

// Must stay byte-identical to the backend INCENTIVE_TYPE_KEYS.
const INCENTIVE_TYPE_COLS = [
  { key: "PLB",                    label: "PLB"                 },
  { key: "Super PLB",              label: "Super PLB"           },
  { key: "Transaction Fee",        label: "Transaction Fee"     },
  { key: "Deposit Incentive (DI)", label: "Deposit Incentive"   },
  { key: "Marketing Fund",         label: "Marketing Fund"      },
  { key: "Ancillary",              label: "Ancillary"           },
  { key: "Frontend",               label: "Frontend"            },
  { key: "Backend",                label: "Backend"             },
  { key: "Cashback",               label: "Cashback"            },
  { key: "Segment Incentive",      label: "Segment Incentive"   },
  { key: "Push Action",            label: "Push Action"         },
] as const;

const BAR_COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#06b6d4", "#ec4899", "#6366f1", "#84cc16", "#f97316", "#14b8a6"];

type SupplierStatement = {
  batch_id:       string;
  statement_name: string | null;
  statement_type: string;
  valid_from:     string;
  valid_to:       string;
  ticket_count:   number;
  total_income:   number;
};

type SupplierReport = {
  supplier:         string;
  date_from:        string | null;
  date_to:          string | null;
  ticket_count:     number;
  statement_count:  number;
  total_sell_fare:  number;
  total_commission: number;
  total_income:     number;
  incentive_totals: Record<string, number>;
  statements:       SupplierStatement[];
};

function fmt0(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
function fmt2(v: number | null | undefined) {
  if (v == null) return "—";
  return `₹${v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}
function pct(part: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

export default function SupplierWiseReportPage() {
  const [suppliers, setSuppliers] = useState<string[]>([]);
  const [supplier,  setSupplier]  = useState("");
  const [dateFrom,  setDateFrom]  = useState("");
  const [dateTo,    setDateTo]    = useState("");

  const [data,      setData]      = useState<SupplierReport | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Supplier master → dropdown
  useEffect(() => {
    api.get<{ id: number; name: string }[]>("/suppliers/?limit=5000")
      .then(r => setSuppliers(r.data.map(s => s.name).filter(Boolean).sort()))
      .catch(() => {});
  }, []);

  // Load the report whenever the supplier, date range, or reload key changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!supplier) { setData(null); return; }
      setLoading(true);
      setError(null);
      try {
        const params: Record<string, string> = { supplier };
        if (dateFrom) params.date_from = dateFrom;
        if (dateTo)   params.date_to   = dateTo;
        const { data } = await api.get<SupplierReport>("/reports/supplier-wise", { params });
        if (!cancelled) setData(data);
      } catch {
        if (!cancelled) setError("Failed to load the supplier report. Please try again.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [supplier, dateFrom, dateTo, reloadKey]);

  const hasData = data && data.statement_count > 0;
  const chartData = data
    ? INCENTIVE_TYPE_COLS.map(c => ({ name: c.label, value: data.incentive_totals?.[c.key] ?? 0 }))
    : [];
  const incomeForPct = data?.total_income || 1;

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Supplier-wise Report</h1>
          <p className="text-xs text-gray-500 mt-0.5">Incentive breakdown &amp; tickets sold for a supplier over a period</p>
        </div>
        <button onClick={() => setReloadKey(k => k + 1)} disabled={loading || !supplier}
          className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {/* filter bar */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-3 flex-wrap shadow-sm">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 shrink-0">
          <Filter className="w-3.5 h-3.5" /> Filters
        </div>

        <select value={supplier} onChange={e => setSupplier(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50 min-w-52">
          <option value="">Select a supplier…</option>
          {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-400">From</span>
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
          <span className="text-[11px] text-gray-400">To</span>
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50" />
        </div>

        {(dateFrom || dateTo) && (
          <button onClick={() => { setDateFrom(""); setDateTo(""); }}
            className="text-xs text-red-500 hover:text-red-700 font-medium">
            Clear dates
          </button>
        )}

        {loading && <RefreshCw className="w-3.5 h-3.5 animate-spin text-gray-400 ml-auto" />}
      </div>

      {/* error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* prompt: no supplier */}
      {!supplier && !error && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <Building2 className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">Select a supplier to view the report</p>
          <p className="text-xs text-gray-400 mt-1">Pick a supplier and (optionally) a date range above.</p>
        </div>
      )}

      {/* empty: supplier selected but no data */}
      {supplier && !loading && !error && data && data.statement_count === 0 && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
            <FileSpreadsheet className="w-8 h-8 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">No statements found for {supplier}</p>
          <p className="text-xs text-gray-400 mt-1">Try a different supplier or widen the date range.</p>
        </div>
      )}

      {/* dashboard */}
      {hasData && (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: "Total Income",   value: fmt0(data!.total_income),   sub: "Calculated incentive",                 color: "border-emerald-500", Icon: TrendingUp },
              { label: "Tickets Sold",   value: data!.ticket_count.toLocaleString("en-IN"), sub: `${data!.statement_count} statement${data!.statement_count !== 1 ? "s" : ""}`, color: "border-blue-500", Icon: Ticket },
              { label: "Total Sell Fare",value: fmt0(data!.total_sell_fare),sub: "Sum of sell fares",                    color: "border-indigo-500", Icon: Wallet },
              { label: "Commission",     value: fmt0(data!.total_commission),sub: "Statement commission",                color: "border-orange-500", Icon: Wallet },
            ].map(({ label, value, sub, color, Icon }) => (
              <div key={label} className={`bg-white rounded-xl border-l-4 ${color} border border-gray-200 p-5`}>
                <div className="flex items-center justify-between">
                  <p className="text-xs text-gray-500 uppercase font-medium">{label}</p>
                  <Icon className="w-4 h-4 text-gray-300" />
                </div>
                <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
                <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>

          {/* Incentive breakdown chart */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Incentive Breakdown by Type</h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={130} />
                <Tooltip formatter={(v) => fmt2(Number(v))} />
                <Bar dataKey="value" name="Incentive" radius={[0, 4, 4, 0]}>
                  {chartData.map((_, i) => <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* By incentive type table */}
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-900">Income by Incentive Type</h2>
              </div>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-5 py-3 text-left">Incentive Type</th>
                    <th className="px-5 py-3 text-right">Amount</th>
                    <th className="px-5 py-3 text-right">% of Income</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {INCENTIVE_TYPE_COLS.map(c => {
                    const v = data!.incentive_totals?.[c.key] ?? 0;
                    return (
                      <tr key={c.key} className="hover:bg-gray-50">
                        <td className="px-5 py-2.5 font-medium text-gray-700">{c.label}</td>
                        <td className="px-5 py-2.5 text-right font-mono">{v ? fmt2(v) : <span className="text-gray-300">—</span>}</td>
                        <td className="px-5 py-2.5 text-right text-gray-500">{pct(v, incomeForPct)}</td>
                      </tr>
                    );
                  })}
                  <tr className="border-t-2 border-gray-300 bg-gray-50 font-bold">
                    <td className="px-5 py-3 text-gray-900">Total Income</td>
                    <td className="px-5 py-3 text-right font-mono text-emerald-700">{fmt2(data!.total_income)}</td>
                    <td className="px-5 py-3 text-right text-gray-500">100%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Statements table */}
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-900">Statements in Period</h2>
              </div>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                  <tr>
                    <th className="px-5 py-3 text-left">Statement</th>
                    <th className="px-5 py-3 text-left">Valid Period</th>
                    <th className="px-5 py-3 text-right">Tickets</th>
                    <th className="px-5 py-3 text-right">Income</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data!.statements.map(s => (
                    <tr key={s.batch_id} className="hover:bg-gray-50">
                      <td className="px-5 py-2.5 font-medium text-gray-700">{s.statement_name ?? `${s.statement_type} · ${data!.supplier}`}</td>
                      <td className="px-5 py-2.5 text-xs text-gray-600 whitespace-nowrap">{formatDate(s.valid_from)} → {formatDate(s.valid_to)}</td>
                      <td className="px-5 py-2.5 text-right">{s.ticket_count.toLocaleString("en-IN")}</td>
                      <td className="px-5 py-2.5 text-right font-mono text-emerald-700">{fmt2(s.total_income)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
