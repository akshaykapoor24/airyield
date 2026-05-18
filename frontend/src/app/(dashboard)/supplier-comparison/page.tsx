"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";
import api from "@/lib/api";

type SupplierStat = { name: string; total_income: number; deal_count: number; ticket_count: number; avg_commission: number };
type SupplierComparisonData = { suppliers: SupplierStat[] };

const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#06b6d4"];

function fmt(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export default function SupplierComparisonPage() {
  const [data,    setData]    = useState<SupplierComparisonData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<SupplierComparisonData>("/dashboard/supplier-comparison")
      .then(r => setData(r.data))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading…
      </div>
    );
  }

  const suppliers = data?.suppliers ?? [];

  if (suppliers.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Supplier Comparison Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">No supplier data yet</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center text-sm text-gray-400">
          Upload deals with supplier names to see comparisons here.
        </div>
      </div>
    );
  }

  // Build bar chart data — income per supplier (top 6)
  const top6 = suppliers.slice(0, 6);
  const barData = [{ metric: "Income", ...Object.fromEntries(top6.map(s => [s.name, s.total_income])) }];

  // Radar chart — normalise each supplier's metrics to 0-100
  const maxIncome  = Math.max(...top6.map(s => s.total_income), 1);
  const maxDeals   = Math.max(...top6.map(s => s.deal_count), 1);
  const maxTickets = Math.max(...top6.map(s => s.ticket_count), 1);
  const maxComm    = Math.max(...top6.map(s => s.avg_commission), 1);
  const radarData = [
    { subject: "Income",     ...Object.fromEntries(top6.map(s => [s.name, Math.round((s.total_income / maxIncome) * 100)])) },
    { subject: "Deals",      ...Object.fromEntries(top6.map(s => [s.name, Math.round((s.deal_count / maxDeals) * 100)])) },
    { subject: "Tickets",    ...Object.fromEntries(top6.map(s => [s.name, Math.round((s.ticket_count / maxTickets) * 100)])) },
    { subject: "Commission", ...Object.fromEntries(top6.map(s => [s.name, Math.round((s.avg_commission / maxComm) * 100)])) },
  ];

  const METRICS: Array<{ label: string; fmt: (s: SupplierStat) => string }> = [
    { label: "Total Income",    fmt: s => fmt(s.total_income) },
    { label: "Deal Count",      fmt: s => s.deal_count.toString() },
    { label: "Ticket Count",    fmt: s => s.ticket_count.toString() },
    { label: "Avg Commission",  fmt: s => `₹${s.avg_commission.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Supplier Comparison Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">{suppliers.length} active supplier{suppliers.length !== 1 ? "s" : ""}</p>
      </div>

      {/* Supplier Cards */}
      <div className={`grid gap-4 ${top6.length <= 2 ? "grid-cols-2" : top6.length === 3 ? "grid-cols-3" : "grid-cols-2 lg:grid-cols-4"}`}>
        {top6.slice(0, 4).map((s, i) => (
          <div key={s.name} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-start justify-between mb-3">
              <span className="text-xs font-bold text-white px-2 py-0.5 rounded-full" style={{ background: COLORS[i] }}>#{i + 1}</span>
            </div>
            <p className="font-semibold text-gray-900 text-sm truncate">{s.name}</p>
            <p className="text-2xl font-bold text-gray-900 mt-2">{fmt(s.total_income)}</p>
            <div className="mt-2 flex gap-3 text-xs text-gray-500">
              <span>{s.deal_count} deal{s.deal_count !== 1 ? "s" : ""}</span>
              <span>·</span>
              <span>{s.ticket_count} tickets</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bar Chart — income by supplier */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Supplier</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={top6} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
              <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={100} />
              <Tooltip formatter={(v) => fmt(Number(v))} />
              <Bar dataKey="total_income" name="Income" radius={[0, 4, 4, 0]}>
                {top6.map((_, i) => (
                  <rect key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Radar */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Performance Radar (normalised 0–100)</h2>
          <ResponsiveContainer width="100%" height={240}>
            <RadarChart data={radarData}>
              <PolarGrid />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11 }} />
              {top6.map((s, i) => (
                <Radar key={s.name} name={s.name} dataKey={s.name} stroke={COLORS[i]} fill={COLORS[i]} fillOpacity={0.08} />
              ))}
              <Legend wrapperStyle={{ fontSize: 10 }} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Metrics Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100"><h2 className="text-sm font-semibold text-gray-900">Detailed Comparison</h2></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Metric</th>
                {suppliers.map((s) => <th key={s.name} className="px-4 py-3 text-right whitespace-nowrap">{s.name}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {METRICS.map(({ label, fmt: fmtFn }) => {
                const raw = suppliers.map(s => {
                  if (label === "Total Income")   return s.total_income;
                  if (label === "Deal Count")     return s.deal_count;
                  if (label === "Ticket Count")   return s.ticket_count;
                  return s.avg_commission;
                });
                const maxVal = Math.max(...raw);
                return (
                  <tr key={label} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium text-gray-700">{label}</td>
                    {suppliers.map((s, i) => {
                      const isBest = raw[i] === maxVal && maxVal > 0;
                      return (
                        <td key={s.name} className={`px-4 py-3 text-right font-medium ${isBest ? "text-green-700" : "text-gray-600"}`}>
                          {fmtFn(s)}
                          {isBest && <span className="ml-1 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">Best</span>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
