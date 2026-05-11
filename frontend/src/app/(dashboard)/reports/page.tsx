"use client";

import { useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";

const BY_AIRLINE = [
  { name: "Emirates", income: 34200, tickets: 412 },
  { name: "IndiGo", income: 28500, tickets: 618 },
  { name: "Air India", income: 22100, tickets: 287 },
  { name: "SpiceJet", income: 14800, tickets: 310 },
  { name: "Vistara", income: 11200, tickets: 175 },
  { name: "Air Asia", income: 6800, tickets: 140 },
];

const BY_SUPPLIER = [
  { name: "Gulf Travel Co.", income: 38400 },
  { name: "Sky Agents Ltd.", income: 24100 },
  { name: "PremiumAir", income: 18900 },
  { name: "Budget Wings", income: 14800 },
  { name: "Direct", income: 22100 },
];

const BY_ROUTE = [
  { route: "BOM-DXB", income: 21500, tickets: 198 },
  { route: "DEL-DXB", income: 18200, tickets: 165 },
  { route: "BOM-DEL", income: 14800, tickets: 312 },
  { route: "DEL-LHR", income: 12400, tickets: 88 },
  { route: "DEL-BOM", income: 11900, tickets: 278 },
  { route: "BOM-CCU", income: 7400, tickets: 145 },
];

const BY_CLASS = [
  { name: "Economy (Y)", value: 48200, tickets: 980 },
  { name: "Business (J)", value: 28900, tickets: 187 },
  { name: "Prem. Eco (W)", value: 15400, tickets: 89 },
  { name: "First (F)", value: 8300, tickets: 28 },
];

const COLORS = ["#3b82f6", "#6366f1", "#8b5cf6", "#ec4899"];
type ViewType = "airline" | "supplier" | "route" | "class";

const fmt = (v: number) => `$${(v / 1000).toFixed(1)}k`;

export default function ReportsPage() {
  const [view, setView] = useState<ViewType>("airline");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500 mt-0.5">Income analytics — April 2025</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 flex-wrap">
        {(["airline", "supplier", "route", "class"] as ViewType[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-4 py-2 rounded-lg text-sm font-medium capitalize transition-colors ${
              view === v ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}
          >
            By {v}
          </button>
        ))}
      </div>

      {/* Chart + Table */}
      {view === "airline" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Airline</h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={BY_AIRLINE}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, "Income"]} />
                <Bar dataKey="income" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-5 py-3 text-left">Airline</th>
                  <th className="px-5 py-3 text-right">Total Income</th>
                  <th className="px-5 py-3 text-right">Tickets</th>
                  <th className="px-5 py-3 text-right">Avg/Ticket</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {BY_AIRLINE.map((r) => (
                  <tr key={r.name} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.name}</td>
                    <td className="px-5 py-3 text-right font-semibold">${r.income.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{r.tickets}</td>
                    <td className="px-5 py-3 text-right text-gray-500">${(r.income / r.tickets).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {view === "supplier" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Supplier</h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={BY_SUPPLIER} layout="vertical">
                <XAxis type="number" tickFormatter={fmt} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={110} />
                <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, "Income"]} />
                <Bar dataKey="income" fill="#6366f1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-5 py-3 text-left">Supplier</th>
                  <th className="px-5 py-3 text-right">Total Income</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {BY_SUPPLIER.sort((a, b) => b.income - a.income).map((r) => (
                  <tr key={r.name} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.name}</td>
                    <td className="px-5 py-3 text-right font-semibold">${r.income.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {view === "route" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Route</h2>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={BY_ROUTE}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="route" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={fmt} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => [`$${v.toLocaleString()}`, "Income"]} />
                <Bar dataKey="income" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-5 py-3 text-left">Route</th>
                  <th className="px-5 py-3 text-right">Income</th>
                  <th className="px-5 py-3 text-right">Tickets</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {BY_ROUTE.map((r) => (
                  <tr key={r.route} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-mono font-medium">{r.route}</td>
                    <td className="px-5 py-3 text-right font-semibold">${r.income.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{r.tickets}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {view === "class" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Income by Booking Class</h2>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={BY_CLASS} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name, percent }) => `${name.split(" ")[0]} ${(percent * 100).toFixed(0)}%`}>
                  {BY_CLASS.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-5 py-3 text-left">Class</th>
                  <th className="px-5 py-3 text-right">Income</th>
                  <th className="px-5 py-3 text-right">Tickets</th>
                  <th className="px-5 py-3 text-right">Avg/Ticket</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {BY_CLASS.map((r, i) => (
                  <tr key={r.name} className="hover:bg-gray-50">
                    <td className="px-5 py-3 flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: COLORS[i] }} />
                      <span className="font-medium">{r.name}</span>
                    </td>
                    <td className="px-5 py-3 text-right font-semibold">${r.value.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{r.tickets}</td>
                    <td className="px-5 py-3 text-right text-gray-500">${(r.value / r.tickets).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
