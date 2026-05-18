"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import api from "@/lib/api";

type MonthlyBreakdown = { month: string; commission: number; incentive: number; adm: number };
type AirlineBreakdown = { airline: string; commission: number; incentive: number; adm: number; total: number };
type IncomeSummaryData = {
  total:      number;
  commission: number;
  incentive:  number;
  adm:        number;
  monthly:    MonthlyBreakdown[];
  by_airline: AirlineBreakdown[];
};

function fmt(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function pct(part: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

export default function IncomeSummaryPage() {
  const [data,    setData]    = useState<IncomeSummaryData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<IncomeSummaryData>("/dashboard/income-summary")
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

  const d = data ?? { total: 0, commission: 0, incentive: 0, adm: 0, monthly: [], by_airline: [] };
  const total = d.total || 1;

  const byHead = [
    { head: "Commission", amount: d.commission, pct: pct(d.commission, total) },
    { head: "Incentive",  amount: d.incentive,  pct: pct(d.incentive, total) },
    { head: "ADM",        amount: d.adm,        pct: pct(d.adm, total) },
  ].filter(r => r.amount !== 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Income Summary Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">All time · All income heads</p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Income",    value: fmt(d.total),      sub: "All heads combined",         color: "border-blue-500" },
          { label: "Commission",      value: fmt(d.commission), sub: pct(d.commission, total) + " of total", color: "border-green-500" },
          { label: "Incentive",       value: fmt(d.incentive),  sub: pct(d.incentive, total) + " of total",  color: "border-purple-500" },
          { label: "ADM",             value: fmt(d.adm),        sub: pct(d.adm, total) + " of total",        color: "border-orange-500" },
        ].map(({ label, value, sub, color }) => (
          <div key={label} className={`bg-white rounded-xl border-l-4 ${color} border border-gray-200 p-5`}>
            <p className="text-xs text-gray-500 uppercase font-medium">{label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
            <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
          </div>
        ))}
      </div>

      {/* Stacked Bar */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">Monthly Income Breakdown by Head</h2>
        {d.monthly.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={d.monthly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `₹${Number(v).toLocaleString("en-IN")}`} />
              <Legend />
              <Bar dataKey="commission" name="Commission" stackId="a" fill="#3b82f6" />
              <Bar dataKey="incentive"  name="Incentive"  stackId="a" fill="#8b5cf6" />
              <Bar dataKey="adm"        name="ADM"        stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[260px] flex items-center justify-center text-gray-400 text-sm">No monthly data yet</div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Income Head */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Income Head</h2>
          </div>
          {byHead.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-5 py-3 text-left">Income Head</th>
                  <th className="px-5 py-3 text-right">Amount</th>
                  <th className="px-5 py-3 text-right">% Share</th>
                  <th className="px-5 py-3 text-left">Bar</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {byHead.map((r) => (
                  <tr key={r.head} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.head}</td>
                    <td className="px-5 py-3 text-right">{fmt(r.amount)}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{r.pct}</td>
                    <td className="px-5 py-3 w-24">
                      <div className="h-2 bg-gray-100 rounded-full">
                        <div className="h-2 bg-blue-500 rounded-full" style={{ width: r.pct }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-5 py-8 text-center text-xs text-gray-400">No income data yet</div>
          )}
        </div>

        {/* By Airline */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Airline</h2>
          </div>
          {d.by_airline.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-5 py-3 text-left">Airline</th>
                  <th className="px-5 py-3 text-right">Commission</th>
                  <th className="px-5 py-3 text-right">Incentive</th>
                  <th className="px-5 py-3 text-right font-bold">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {d.by_airline.map((r) => (
                  <tr key={r.airline} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.airline}</td>
                    <td className="px-5 py-3 text-right text-gray-600">{fmt(r.commission)}</td>
                    <td className="px-5 py-3 text-right text-gray-600">{fmt(r.incentive)}</td>
                    <td className="px-5 py-3 text-right font-bold">{fmt(r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-5 py-8 text-center text-xs text-gray-400">No airline data yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
