"use client";

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, Legend } from "recharts";

const monthly = [
  { month: "Oct", commission: 28000, override: 8400, incentive: 5600 },
  { month: "Nov", commission: 35000, override: 10500, incentive: 7000 },
  { month: "Dec", commission: 31000, override: 9300, incentive: 6200 },
  { month: "Jan", commission: 42000, override: 12600, incentive: 8400 },
  { month: "Feb", commission: 46000, override: 13800, incentive: 9200 },
  { month: "Mar", commission: 55000, override: 16500, incentive: 11000 },
];

const byHead = [
  { head: "Commission", amount: 55000, pct: "61%" },
  { head: "Override", amount: 16500, pct: "18%" },
  { head: "Incentive", amount: 11000, pct: "12%" },
  { head: "PLB", amount: 5400, pct: "6%" },
  { head: "Other", amount: 1500, pct: "2%" },
];

const byAirline = [
  { airline: "Emirates", commission: 24200, override: 7260, incentive: 4840, total: 36300 },
  { airline: "IndiGo", commission: 14250, override: 4275, incentive: 2850, total: 21375 },
  { airline: "Air India", commission: 11050, override: 3315, incentive: 2210, total: 16575 },
  { airline: "SpiceJet", commission: 7400, override: 2220, incentive: 1480, total: 11100 },
  { airline: "Vistara", commission: 5600, override: 1680, incentive: 1120, total: 8400 },
];

export default function IncomeSummaryPage() {
  const totalIncome = 89400;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Income Summary Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">March 2025 — Approved & Pending</p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Income", value: "$89,400", sub: "All heads combined", color: "border-blue-500" },
          { label: "Commission", value: "$55,000", sub: "61% of total", color: "border-green-500" },
          { label: "Override", value: "$16,500", sub: "18% of total", color: "border-purple-500" },
          { label: "Incentive + PLB", value: "$17,900", sub: "20% of total", color: "border-orange-500" },
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
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={monthly}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} />
            <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(v) => `$${Number(v).toLocaleString()}`} />
            <Legend />
            <Bar dataKey="commission" name="Commission" stackId="a" fill="#3b82f6" />
            <Bar dataKey="override" name="Override" stackId="a" fill="#8b5cf6" />
            <Bar dataKey="incentive" name="Incentive" stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Income Head */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Income Head (Mar 2025)</h2>
          </div>
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
                  <td className="px-5 py-3 text-right">${r.amount.toLocaleString()}</td>
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
        </div>

        {/* By Airline */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Airline (Mar 2025)</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-5 py-3 text-left">Airline</th>
                <th className="px-5 py-3 text-right">Commission</th>
                <th className="px-5 py-3 text-right">Override</th>
                <th className="px-5 py-3 text-right font-bold">Total</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {byAirline.map((r) => (
                <tr key={r.airline} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium">{r.airline}</td>
                  <td className="px-5 py-3 text-right text-gray-600">${r.commission.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right text-gray-600">${r.override.toLocaleString()}</td>
                  <td className="px-5 py-3 text-right font-bold">${r.total.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
