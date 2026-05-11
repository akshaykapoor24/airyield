"use client";

import { useState } from "react";
import { Edit2, Plus, Search, Clock } from "lucide-react";

const OVERRIDES = [
  { id: 1, ticket: "176-4821903463", airline: "Emirates", class: "Y", baseFare: 420, calculated: 25.20, manual: 30.00, reason: "Special arrangement with airline for this client", overriddenBy: "Rajesh K.", overriddenOn: "05 Apr 2025", status: "approved" },
  { id: 2, ticket: "057-9876543210", airline: "Air India", class: "J", baseFare: 1850, calculated: 129.50, manual: 145.00, reason: "Corporate deal terms updated mid-period", overriddenBy: "Manvendra C.", overriddenOn: "05 Apr 2025", status: "pending" },
  { id: 3, ticket: "098-1234567901", airline: "IndiGo", class: "M", baseFare: 180, calculated: 10.40, manual: 8.00, reason: "Customer complaint — goodwill adjustment", overriddenBy: "Pooja S.", overriddenOn: "04 Apr 2025", status: "rejected" },
];

const STATUS_COLOR: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  pending: "bg-yellow-100 text-yellow-700",
  rejected: "bg-red-100 text-red-700",
};

export default function ManualOverridePage() {
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);

  const filtered = OVERRIDES.filter(o =>
    o.ticket.includes(search) || o.airline.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Manual Income Overrides</h1>
          <p className="text-sm text-gray-500 mt-0.5">View and manage manual income adjustments for individual tickets</p>
        </div>
        <button onClick={() => setShowModal(true)} className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> New Override
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Overrides", value: OVERRIDES.length, sub: "This period", color: "text-gray-900 bg-gray-50" },
          { label: "Approved", value: OVERRIDES.filter(o => o.status === "approved").length, sub: "Active", color: "text-green-700 bg-green-50" },
          { label: "Pending Approval", value: OVERRIDES.filter(o => o.status === "pending").length, sub: "Awaiting review", color: "text-yellow-700 bg-yellow-50" },
        ].map(({ label, value, sub, color }) => (
          <div key={label} className={`rounded-xl p-4 ${color}`}>
            <p className="text-3xl font-bold">{value}</p>
            <p className="text-sm font-medium">{label}</p>
            <p className="text-xs opacity-70 mt-0.5">{sub}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3">
          <h2 className="text-sm font-semibold text-gray-900 flex-1">Override History</h2>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..."
              className="pl-9 pr-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48" />
          </div>
        </div>

        <div className="divide-y divide-gray-100">
          {filtered.map(o => (
            <div key={o.id} className="px-5 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className="font-mono text-xs font-bold text-gray-800">{o.ticket}</span>
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{o.airline}</span>
                    <span className="font-mono bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-xs font-bold">{o.class}</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_COLOR[o.status]}`}>{o.status}</span>
                  </div>
                  <div className="flex items-center gap-6 mt-2 text-sm">
                    <div>
                      <span className="text-gray-500 text-xs">Calculated</span>
                      <p className="font-medium text-gray-700 line-through">${o.calculated.toFixed(2)}</p>
                    </div>
                    <div className="text-xl text-gray-300">→</div>
                    <div>
                      <span className="text-gray-500 text-xs">Override</span>
                      <p className="font-bold text-blue-700">${o.manual.toFixed(2)}</p>
                    </div>
                    <div>
                      <span className="text-gray-500 text-xs">Difference</span>
                      <p className={`font-medium ${o.manual > o.calculated ? "text-green-600" : "text-red-600"}`}>
                        {o.manual > o.calculated ? "+" : ""}${(o.manual - o.calculated).toFixed(2)}
                      </p>
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 mt-1.5 italic">"{o.reason}"</p>
                  <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> {o.overriddenBy} · {o.overriddenOn}
                  </p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button className="p-1.5 hover:bg-blue-50 rounded-lg"><Edit2 className="w-4 h-4 text-blue-500" /></button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-bold text-gray-900 mb-4">New Manual Override</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Ticket Number *</label>
                <input placeholder="e.g. 176-4821903463" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Calculated Income</label>
                  <input placeholder="$0.00" disabled className="w-full border border-gray-100 bg-gray-50 rounded-lg px-3 py-2 text-sm text-gray-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Override Amount *</label>
                  <input placeholder="e.g. 30.00" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Reason *</label>
                <textarea rows={3} placeholder="Reason for manual override..." className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={() => setShowModal(false)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm">Cancel</button>
              <button onClick={() => setShowModal(false)} className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm font-medium">Submit for Approval</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
