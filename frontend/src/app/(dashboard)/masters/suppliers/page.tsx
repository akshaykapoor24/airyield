"use client";

import { useState } from "react";
import { Plus, Search, Edit2, Trash2, Building2, MapPin, Phone, Mail, TrendingUp } from "lucide-react";

const DATA = [
  { id: 1, name: "Gulf Travel Co.", code: "GTC", email: "deals@gulftravelco.com", phone: "+971-4-234-5678", city: "Dubai", country: "UAE", deals: 12, income: 38400, active: true },
  { id: 2, name: "Sky Agents Ltd.", code: "SAL", email: "ops@skyagents.in", phone: "+91-22-4567-8901", city: "Mumbai", country: "India", deals: 9, income: 24100, active: true },
  { id: 3, name: "PremiumAir", code: "PAR", email: "b2b@premiumair.com", phone: "+91-11-9876-5432", city: "Delhi", country: "India", deals: 7, income: 18900, active: true },
  { id: 4, name: "Budget Wings", code: "BWG", email: "deals@budgetwings.in", phone: "+91-80-1234-5678", city: "Bangalore", country: "India", deals: 6, income: 14800, active: false },
  { id: 5, name: "FlyDeal Partners", code: "FDP", email: "info@flydeal.ae", phone: "+971-2-111-2222", city: "Abu Dhabi", country: "UAE", deals: 4, income: 9200, active: true },
];

const AVATAR_COLORS = [
  "from-violet-500 to-purple-600",
  "from-sky-500 to-blue-600",
  "from-emerald-500 to-teal-600",
  "from-orange-500 to-amber-600",
  "from-rose-500 to-pink-600",
];

export default function SuppliersPage() {
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);

  const filtered = DATA.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    s.code.toLowerCase().includes(search.toLowerCase())
  );

  const totalIncome = DATA.reduce((s, d) => s + d.income, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Supplier Master</h1>
          <p className="text-[11px] text-gray-400 mt-0.5">{DATA.length} suppliers · {DATA.filter(s => s.active).length} active</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-1 rounded-lg shadow-sm hover:opacity-90 transition-opacity"
          style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}
        >
          <Plus className="w-3.5 h-3.5" /> Add Supplier
        </button>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Suppliers", value: DATA.length, icon: Building2, color: "text-blue-600 bg-blue-50" },
          { label: "Active", value: DATA.filter(s => s.active).length, icon: TrendingUp, color: "text-emerald-600 bg-emerald-50" },
          { label: "Total Deals", value: DATA.reduce((s, d) => s + d.deals, 0), icon: Building2, color: "text-violet-600 bg-violet-50" },
          { label: "Total Income", value: `$${(totalIncome / 1000).toFixed(1)}k`, icon: TrendingUp, color: "text-orange-600 bg-orange-50" },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Table card */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        {/* Table toolbar */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">All Suppliers</p>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name or code..."
              className="pl-8 pr-3 py-1 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 w-52 bg-gray-50"
            />
          </div>
        </div>

        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["Name", "Code", "Contact", "Location", "Active Deals", "Total Income", "Status", "Actions"].map((h, i) => (
                <th key={h} className={`px-3 py-0.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide ${i >= 4 && i <= 5 ? "text-right" : i === 7 ? "text-center" : "text-left"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((s, idx) => (
              <tr key={s.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors group">
                {/* Name */}
                <td className="px-3 py-0.5">
                  <div className="flex items-center gap-2.5">
                    <div className={`w-5 h-5 rounded bg-gradient-to-br ${AVATAR_COLORS[idx % AVATAR_COLORS.length]} flex items-center justify-center shrink-0`}>
                      <span className="text-white text-[9px] font-bold">{s.name[0]}</span>
                    </div>
                    <span className="text-[11px] font-semibold text-gray-800">{s.name}</span>
                  </div>
                </td>
                {/* Code */}
                <td className="px-3 py-0.5">
                  <span className="font-mono text-xs font-bold text-violet-600 bg-violet-50 px-2 py-0.5 rounded">{s.code}</span>
                </td>
                {/* Contact */}
                <td className="px-3 py-0.5">
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1 text-[11px] text-gray-500">
                      <Mail className="w-2.5 h-2.5 text-gray-300 shrink-0" />{s.email}
                    </div>
                    <span className="text-gray-200">·</span>
                    <div className="flex items-center gap-1 text-[11px] text-gray-400">
                      <Phone className="w-2.5 h-2.5 text-gray-300 shrink-0" />{s.phone}
                    </div>
                  </div>
                </td>
                {/* Location */}
                <td className="px-3 py-0.5">
                  <div className="flex items-center gap-1 text-[11px] text-gray-500">
                    <MapPin className="w-3 h-3 text-gray-300 shrink-0" />
                    {s.city}, {s.country}
                  </div>
                </td>
                {/* Active Deals */}
                <td className="px-3 py-0.5 text-right">
                  <span className="text-[11px] font-semibold text-gray-700">{s.deals}</span>
                </td>
                {/* Income */}
                <td className="px-3 py-0.5 text-right">
                  <span className="text-[11px] font-semibold text-emerald-600">${s.income.toLocaleString()}</span>
                </td>
                {/* Status */}
                <td className="px-3 py-0.5">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${s.active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-400"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${s.active ? "bg-emerald-500" : "bg-gray-400"}`} />
                    {s.active ? "Active" : "Inactive"}
                  </span>
                </td>
                {/* Actions */}
                <td className="px-3 py-0.5">
                  <div className="flex justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button className="p-1.5 hover:bg-blue-50 rounded-lg transition-colors">
                      <Edit2 className="w-3.5 h-3.5 text-blue-500" />
                    </button>
                    <button className="p-1.5 hover:bg-red-50 rounded-lg transition-colors">
                      <Trash2 className="w-3.5 h-3.5 text-red-400" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="py-12 text-center text-sm text-gray-400">No suppliers match your search.</div>
        )}

        <div className="px-3 py-1.5 border-t border-gray-50 flex items-center justify-between">
          <p className="text-[11px] text-gray-400">Showing {filtered.length} of {DATA.length} suppliers</p>
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-5 w-full max-w-md shadow-2xl">
            <h2 className="text-base font-bold text-gray-900 mb-4">Add Supplier</h2>
            <div className="grid grid-cols-2 gap-3">
              {[["Supplier Name", "text", "col-span-2"], ["Code", "text", ""], ["Contact Email", "email", "col-span-2"], ["Phone", "text", ""], ["City", "text", ""], ["Country", "text", ""]].map(([label, type, span]) => (
                <div key={label} className={span}>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</label>
                  <input type={type}
                    className="w-full border border-gray-200 rounded-lg px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50" />
                </div>
              ))}
            </div>
            <div className="flex gap-2.5 mt-5">
              <button onClick={() => setShowModal(false)}
                className="flex-1 border border-gray-200 rounded-lg py-1 text-sm text-gray-500 hover:bg-gray-50">
                Cancel
              </button>
              <button onClick={() => setShowModal(false)}
                className="flex-1 text-white rounded-lg py-1 text-sm font-semibold hover:opacity-90"
                style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
                Save Supplier
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
