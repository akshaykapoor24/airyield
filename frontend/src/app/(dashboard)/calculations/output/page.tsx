"use client";

import { useState } from "react";
import Link from "next/link";
import { Download, CheckCircle, AlertTriangle, Filter } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";

const CHART_DATA = [
  { airline: "Emirates", commission: 4820, override: 1680, incentive: 420 },
  { airline: "IndiGo", commission: 2310, override: 0, incentive: 890 },
  { airline: "Air India", commission: 3120, override: 940, incentive: 0 },
  { airline: "SpiceJet", commission: 870, override: 0, incentive: 0 },
];

const ROWS = [
  { ticket: "176-4821903463", pnr: "XKJP92", airline: "Emirates", class: "Y", baseFare: 420, commission: 18.90, override: 6.30, incentive: 0, total: 25.20, deal: "EK-Q2-2025", status: "calculated" },
  { ticket: "098-1234567901", pnr: "ABCD12", airline: "IndiGo", class: "M", baseFare: 180, commission: 5.40, override: 0, incentive: 5.00, total: 10.40, deal: "6E-MAR-25", status: "calculated" },
  { ticket: "057-9876543210", pnr: "EFGH78", airline: "Air India", class: "J", baseFare: 1850, commission: 92.50, override: 37.00, incentive: 0, total: 129.50, deal: "AI-CORP-25", status: "calculated" },
  { ticket: "057-9876543211", pnr: "WXYZ99", airline: "SpiceJet", class: "Y", baseFare: 95, commission: 2.38, override: 0, incentive: 0, total: 2.38, deal: "SG-APR-25", status: "calculated" },
  { ticket: "098-1234567921", pnr: "", airline: "Emirates", class: "B", baseFare: 510, commission: 0, override: 0, incentive: 0, total: 0, deal: "—", status: "unmatched" },
];

const STATUS_COLOR: Record<string, string> = {
  calculated: "bg-green-100 text-green-700",
  unmatched: "bg-yellow-100 text-yellow-700",
  excluded: "bg-red-100 text-red-700",
};

export default function CalcOutputPage() {
  const [filter, setFilter] = useState("all");

  const filtered = filter === "all" ? ROWS : ROWS.filter(r => r.status === filter);
  const totalIncome = ROWS.filter(r => r.status === "calculated").reduce((s, r) => s + r.total, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Calculation Output</h1>
          <p className="text-sm text-gray-500 mt-0.5">BATCH-20250405-001 · April 2025 · Run on 05 Apr 2025</p>
        </div>
        <div className="flex gap-2">
          <button className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg text-sm hover:bg-gray-50">
            <Download className="w-4 h-4" /> Export
          </button>
          <Link href="/income" className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
            View in Income Register →
          </Link>
        </div>
      </div>

      {/* Summary KPIs */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { label: "Tickets Processed", value: "271", color: "text-gray-900 bg-gray-50" },
          { label: "Calculated", value: "258", color: "text-green-700 bg-green-50" },
          { label: "Unmatched", value: "10", color: "text-yellow-700 bg-yellow-50" },
          { label: "Excluded", value: "3", color: "text-red-700 bg-red-50" },
          { label: "Total Income", value: `$${totalIncome.toFixed(2)}`, color: "text-blue-700 bg-blue-50" },
        ].map(({ label, value, color }) => (
          <div key={label} className={`rounded-xl p-4 text-center ${color}`}>
            <p className="text-2xl font-bold">{value}</p>
            <p className="text-xs font-medium mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Unmatched Warning */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-600 shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-yellow-800">10 tickets could not be matched to any deal</p>
          <p className="text-sm text-yellow-700 mt-0.5">These tickets will not have income calculated. Review and resolve in the exceptions screen.</p>
        </div>
        <Link href="/calculations/exceptions" className="text-xs bg-yellow-600 text-white px-3 py-1.5 rounded-lg hover:bg-yellow-700 shrink-0">
          View Exceptions
        </Link>
      </div>

      {/* Chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Airline</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={CHART_DATA} barSize={28}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="airline" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v: any) => [`$${v}`, ""]} />
            <Legend />
            <Bar dataKey="commission" name="Commission" fill="#3b82f6" stackId="a" />
            <Bar dataKey="override" name="Override" fill="#8b5cf6" stackId="a" />
            <Bar dataKey="incentive" name="Incentive" fill="#f59e0b" stackId="a" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Calculation Detail</h2>
          <div className="flex gap-2">
            {["all", "calculated", "unmatched", "excluded"].map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1 rounded-full text-xs font-medium capitalize transition-colors ${filter === f ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
                {f}
              </button>
            ))}
          </div>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Ticket #</th>
              <th className="px-5 py-3 text-left">Airline</th>
              <th className="px-5 py-3 text-left">Class</th>
              <th className="px-5 py-3 text-right">Base Fare</th>
              <th className="px-5 py-3 text-right">Commission</th>
              <th className="px-5 py-3 text-right">Override</th>
              <th className="px-5 py-3 text-right">Incentive</th>
              <th className="px-5 py-3 text-right">Total</th>
              <th className="px-5 py-3 text-left">Deal</th>
              <th className="px-5 py-3 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((r, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs">{r.ticket}</td>
                <td className="px-5 py-3 text-gray-700">{r.airline}</td>
                <td className="px-5 py-3"><span className="font-mono bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-xs font-bold">{r.class}</span></td>
                <td className="px-5 py-3 text-right">${r.baseFare.toFixed(2)}</td>
                <td className="px-5 py-3 text-right text-blue-700">${r.commission.toFixed(2)}</td>
                <td className="px-5 py-3 text-right text-purple-700">${r.override.toFixed(2)}</td>
                <td className="px-5 py-3 text-right text-orange-600">${r.incentive.toFixed(2)}</td>
                <td className="px-5 py-3 text-right font-bold text-green-700">${r.total.toFixed(2)}</td>
                <td className="px-5 py-3 font-mono text-xs text-gray-500">{r.deal}</td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_COLOR[r.status]}`}>{r.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
