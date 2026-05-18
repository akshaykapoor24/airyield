"use client";

import { useEffect, useState } from "react";
import { DollarSign, Ticket, TrendingUp, FileText, RefreshCw } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";
import { formatCurrency } from "@/lib/utils";
import api from "@/lib/api";
import Link from "next/link";

type MonthlyIncome   = { month: string; income: number };
type AirlineIncome   = { airline: string; income: number };
type SummaryData = {
  total_income:      number;
  total_tickets:     number;
  active_deals:      number;
  pending_count:     number;
  monthly_income:    MonthlyIncome[];
  income_by_airline: AirlineIncome[];
};

type RecentDeal = {
  id: number;
  deal_no: string;
  airline_name: string | null;
  source_type: string;
  status: string;
  valid_to: string | null;
  created_at: string;
};

const STATUS_COLOR: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  pending_approval: "bg-yellow-100 text-yellow-700",
  extracted: "bg-blue-100 text-blue-700",
  rejected: "bg-red-100 text-red-700",
  confirmed: "bg-green-100 text-green-700",
};

function fmt(v: number) {
  return v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export default function DashboardPage() {
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [deals,   setDeals]   = useState<RecentDeal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<SummaryData>("/dashboard/summary"),
      api.get<RecentDeal[]>("/deals?limit=6"),
    ]).then(([sumRes, dealsRes]) => {
      setSummary(sumRes.data);
      setDeals(dealsRes.data);
    }).finally(() => setLoading(false));
  }, []);

  const now = new Date();
  const monthLabel = now.toLocaleString("default", { month: "long", year: "numeric" });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <RefreshCw className="w-5 h-5 animate-spin mr-2" /> Loading dashboard…
      </div>
    );
  }

  const s = summary;
  const kpis = [
    { label: "Total Income (All time)", value: s ? formatCurrency(s.total_income) : "—", icon: DollarSign, color: "text-green-600 bg-green-50" },
    { label: "Total Tickets", value: s ? s.total_tickets.toLocaleString() : "—", icon: Ticket, color: "text-purple-600 bg-purple-50" },
    { label: "Active Deals", value: s ? s.active_deals.toString() : "—", icon: FileText, color: "text-orange-600 bg-orange-50" },
    { label: "Pending Actions", value: s ? s.pending_count.toString() : "—", icon: TrendingUp, color: "text-blue-600 bg-blue-50" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">{monthLabel} — Live Overview</p>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className={`p-2.5 rounded-lg ${color} w-fit mb-3`}>
              <Icon className="w-4 h-4" />
            </div>
            <p className="text-2xl font-bold text-gray-900">{value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Monthly Income Trend</h2>
          {s && s.monthly_income.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={s.monthly_income}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                <Line type="monotone" dataKey="income" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-gray-400 text-sm">No income data yet</div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Airline</h2>
          {s && s.income_by_airline.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={s.income_by_airline} layout="vertical">
                <XAxis type="number" tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="airline" tick={{ fontSize: 10 }} width={70} />
                <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                <Bar dataKey="income" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[220px] flex items-center justify-center text-gray-400 text-sm">No data yet</div>
          )}
        </div>
      </div>

      {/* Recent Deals */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Recent Deals</h2>
          <Link href="/deals" className="text-xs text-blue-600 hover:underline">View all →</Link>
        </div>
        {deals.length === 0 ? (
          <div className="px-6 py-10 text-center text-xs text-gray-400">No deals yet. <Link href="/deals/upload" className="text-blue-500 hover:underline">Upload a deal</Link></div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-6 py-3 text-left">Reference</th>
                <th className="px-6 py-3 text-left">Airline</th>
                <th className="px-6 py-3 text-left">Type</th>
                <th className="px-6 py-3 text-left">Valid To</th>
                <th className="px-6 py-3 text-left">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {deals.map((d) => (
                <tr key={d.id} className="hover:bg-gray-50">
                  <td className="px-6 py-3 font-mono text-xs text-gray-600">{d.deal_no ?? `DEAL-${String(d.id).padStart(4,"0")}`}</td>
                  <td className="px-6 py-3 font-medium">{d.airline_name ?? "—"}</td>
                  <td className="px-6 py-3 text-gray-500 capitalize">{d.source_type}</td>
                  <td className="px-6 py-3 text-gray-500">{d.valid_to ?? "—"}</td>
                  <td className="px-6 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[d.status] ?? "bg-gray-100 text-gray-600"}`}>
                      {d.status.replace(/_/g, " ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
