"use client";

import { useState } from "react";
import { Download, TrendingUp, TrendingDown } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, Legend } from "recharts";

const MONTHLY = [
  { month: "Oct 2024", income: 18200, tickets: 210, commission: 10800, override: 5200, incentive: 2200 },
  { month: "Nov 2024", income: 21500, tickets: 248, commission: 12800, override: 6100, incentive: 2600 },
  { month: "Dec 2024", income: 26800, tickets: 312, commission: 15900, override: 7500, incentive: 3400 },
  { month: "Jan 2025", income: 19400, tickets: 225, commission: 11600, override: 5400, incentive: 2400 },
  { month: "Feb 2025", income: 22100, tickets: 258, commission: 13200, override: 6200, incentive: 2700 },
  { month: "Mar 2025", income: 28400, tickets: 330, commission: 16900, override: 8100, incentive: 3400 },
  { month: "Apr 2025", income: 24800, tickets: 284, commission: 14700, override: 7000, incentive: 3100 },
];

const QUARTERLY = [
  { quarter: "Q1 2025", income: 69900, tickets: 813, prev: 62300, growth: 12.2 },
  { quarter: "Q2 2025 (partial)", income: 24800, tickets: 284, prev: null, growth: null },
  { quarter: "Q4 2024", income: 66500, tickets: 770, prev: 61800, growth: 7.6 },
];

export default function PeriodReportPage() {
  const [view, setView] = useState<"monthly" | "quarterly">("monthly");
  const latestMonth = MONTHLY[MONTHLY.length - 1];
  const prevMonth = MONTHLY[MONTHLY.length - 2];
  const growth = (((latestMonth.income - prevMonth.income) / prevMonth.income) * 100).toFixed(1);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Period-wise Report</h1>
          <p className="text-sm text-gray-500 mt-0.5">Income trend analysis by month and quarter</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg text-sm hover:bg-gray-50">
          <Download className="w-4 h-4" /> Export Report
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Apr 2025 Income", value: `$${latestMonth.income.toLocaleString()}`, sub: `${growth}% vs Mar 2025`, up: Number(growth) > 0 },
          { label: "Apr 2025 Tickets", value: latestMonth.tickets, sub: `${prevMonth.tickets} in Mar`, up: latestMonth.tickets > prevMonth.tickets },
          { label: "Q1 2025 Total", value: `$${QUARTERLY[0].income.toLocaleString()}`, sub: `+${QUARTERLY[0].growth}% vs Q1 2024`, up: true },
          { label: "Avg Monthly Income", value: `$${Math.round(MONTHLY.reduce((s, m) => s + m.income, 0) / MONTHLY.length).toLocaleString()}`, sub: "Last 7 months", up: null },
        ].map(({ label, value, sub, up }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
            <p className={`text-xs mt-0.5 flex items-center gap-1 ${up === true ? "text-green-600" : up === false ? "text-red-500" : "text-gray-400"}`}>
              {up === true && <TrendingUp className="w-3 h-3" />}
              {up === false && <TrendingDown className="w-3 h-3" />}
              {sub}
            </p>
          </div>
        ))}
      </div>

      {/* Chart toggle */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">Income Trend</h2>
          <div className="flex gap-2">
            {(["monthly", "quarterly"] as const).map(v => (
              <button key={v} onClick={() => setView(v)}
                className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-colors ${view === v ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
                {v}
              </button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={view === "monthly" ? MONTHLY : QUARTERLY} barSize={32}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey={view === "monthly" ? "month" : "quarter"} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: any) => [`$${Number(v).toLocaleString()}`, ""]} />
            <Legend />
            {view === "monthly" ? (
              <>
                <Bar dataKey="commission" name="Commission" fill="#3b82f6" stackId="a" />
                <Bar dataKey="override" name="Override" fill="#8b5cf6" stackId="a" />
                <Bar dataKey="incentive" name="Incentive" fill="#f59e0b" stackId="a" radius={[4, 4, 0, 0]} />
              </>
            ) : (
              <Bar dataKey="income" name="Total Income" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Monthly Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Monthly Breakdown</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Month</th>
              <th className="px-5 py-3 text-right">Tickets</th>
              <th className="px-5 py-3 text-right">Commission</th>
              <th className="px-5 py-3 text-right">Override</th>
              <th className="px-5 py-3 text-right">Incentive</th>
              <th className="px-5 py-3 text-right">Total Income</th>
              <th className="px-5 py-3 text-right">vs Prior</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {[...MONTHLY].reverse().map((m, i, arr) => {
              const prev = arr[i + 1];
              const change = prev ? (((m.income - prev.income) / prev.income) * 100).toFixed(1) : null;
              return (
                <tr key={m.month} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium">{m.month}</td>
                  <td className="px-5 py-3 text-right text-gray-600">{m.tickets}</td>
                  <td className="px-5 py-3 text-right text-blue-600">${m.commission.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-purple-600">${m.override.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-orange-500">${m.incentive.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right font-bold text-gray-900">${m.income.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right">
                    {change ? (
                      <span className={`text-xs font-medium ${Number(change) >= 0 ? "text-green-600" : "text-red-500"}`}>
                        {Number(change) >= 0 ? "+" : ""}{change}%
                      </span>
                    ) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
