"use client";

import { DollarSign, Ticket, TrendingUp, FileText, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";
import { formatCurrency } from "@/lib/utils";

const monthlyIncome = [
  { month: "Oct", income: 42000 },
  { month: "Nov", income: 58000 },
  { month: "Dec", income: 51000 },
  { month: "Jan", income: 67000 },
  { month: "Feb", income: 73000 },
  { month: "Mar", income: 89000 },
];

const airlineBreakdown = [
  { airline: "Emirates", income: 34200 },
  { airline: "IndiGo", income: 28500 },
  { airline: "Air India", income: 22100 },
  { airline: "SpiceJet", income: 14800 },
  { airline: "Vistara", income: 11200 },
];

const recentDeals = [
  { id: 1, ref: "EK-Q2-2025", airline: "Emirates", type: "Negotiated", commission: "4.5%", status: "approved", validTo: "30 Jun 2025" },
  { id: 2, ref: "6E-MAR-25", airline: "IndiGo", type: "Standard", commission: "3.0%", status: "approved", validTo: "31 Mar 2025" },
  { id: 3, ref: "AI-CORP-25", airline: "Air India", type: "Airline Direct", commission: "5.0%", status: "pending_review", validTo: "15 Apr 2025" },
  { id: 4, ref: "SG-Q1-25", airline: "SpiceJet", type: "Standard", commission: "2.5%", status: "approved", validTo: "31 Mar 2025" },
];

const STATUS_COLOR: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  pending_review: "bg-yellow-100 text-yellow-700",
};

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">April 2025 — Live Overview</p>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Income (MTD)", value: formatCurrency(89400), change: "+18%", up: true, icon: DollarSign, color: "text-green-600 bg-green-50" },
          { label: "Approved Income", value: formatCurrency(76200), change: "+12%", up: true, icon: TrendingUp, color: "text-blue-600 bg-blue-50" },
          { label: "Total Tickets", value: "1,284", change: "+9%", up: true, icon: Ticket, color: "text-purple-600 bg-purple-50" },
          { label: "Active Deals", value: "34", change: "-2", up: false, icon: FileText, color: "text-orange-600 bg-orange-50" },
        ].map(({ label, value, change, up, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-start justify-between">
              <div className={`p-2.5 rounded-lg ${color}`}>
                <Icon className="w-4 h-4" />
              </div>
              <span className={`flex items-center gap-0.5 text-xs font-medium ${up ? "text-green-600" : "text-red-500"}`}>
                {up ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
                {change}
              </span>
            </div>
            <p className="text-2xl font-bold text-gray-900 mt-3">{value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Monthly Income Trend</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={monthlyIncome}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v) => formatCurrency(Number(v))} />
              <Line type="monotone" dataKey="income" stroke="#3b82f6" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Airline</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={airlineBreakdown} layout="vertical">
              <XAxis type="number" tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="airline" tick={{ fontSize: 11 }} width={60} />
              <Tooltip formatter={(v) => formatCurrency(Number(v))} />
              <Bar dataKey="income" fill="#6366f1" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Deals */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">Recent Deals</h2>
          <a href="/deals" className="text-xs text-blue-600 hover:underline">View all →</a>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
            <tr>
              <th className="px-6 py-3 text-left">Reference</th>
              <th className="px-6 py-3 text-left">Airline</th>
              <th className="px-6 py-3 text-left">Type</th>
              <th className="px-6 py-3 text-left">Commission</th>
              <th className="px-6 py-3 text-left">Valid To</th>
              <th className="px-6 py-3 text-left">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {recentDeals.map((d) => (
              <tr key={d.id} className="hover:bg-gray-50">
                <td className="px-6 py-3 font-mono text-xs text-gray-600">{d.ref}</td>
                <td className="px-6 py-3 font-medium">{d.airline}</td>
                <td className="px-6 py-3 text-gray-500">{d.type}</td>
                <td className="px-6 py-3 font-semibold text-gray-900">{d.commission}</td>
                <td className="px-6 py-3 text-gray-500">{d.validTo}</td>
                <td className="px-6 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[d.status]}`}>
                    {d.status.replace("_", " ")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
