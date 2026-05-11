"use client";

import { useState } from "react";
import { Plus, Search, Edit2, Trash2, ArrowRight, Route } from "lucide-react";

const DATA = [
  { id: 1, origin: "BOM", destination: "DXB", airline: "Emirates", type: "International", distance: "1939 km", active: true },
  { id: 2, origin: "DEL", destination: "DXB", airline: "Emirates", type: "International", distance: "2199 km", active: true },
  { id: 3, origin: "BOM", destination: "DEL", airline: "IndiGo", type: "Domestic", distance: "1148 km", active: true },
  { id: 4, origin: "DEL", destination: "LHR", airline: "Air India", type: "International", distance: "6728 km", active: true },
  { id: 5, origin: "DEL", destination: "BOM", airline: "IndiGo", type: "Domestic", distance: "1148 km", active: true },
  { id: 6, origin: "BOM", destination: "CCU", airline: "Air India", type: "Domestic", distance: "1650 km", active: true },
  { id: 7, origin: "DEL", destination: "SIN", airline: "Air India", type: "International", distance: "4150 km", active: false },
];

export default function RoutesPage() {
  const [search, setSearch] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [typeFilter, setTypeFilter] = useState("All");

  const filtered = DATA.filter(r =>
    (typeFilter === "All" || r.type === typeFilter) &&
    (`${r.origin}${r.destination}`.toLowerCase().includes(search.toLowerCase()) ||
      r.airline.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Route Mapping</h1>
          <p className="text-[11px] text-gray-400 mt-0.5">{DATA.length} routes · {DATA.filter(r => r.active).length} active</p>
        </div>
        <button onClick={() => setShowModal(true)} className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          <Plus className="w-3.5 h-3.5" /> Add Route
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Routes", value: DATA.length, color: "text-blue-600 bg-blue-50" },
          { label: "International", value: DATA.filter(r => r.type === "International").length, color: "text-sky-600 bg-sky-50" },
          { label: "Domestic", value: DATA.filter(r => r.type === "Domestic").length, color: "text-emerald-600 bg-emerald-50" },
          { label: "Active", value: DATA.filter(r => r.active).length, color: "text-violet-600 bg-violet-50" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}><Route className="w-4 h-4" /></div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 gap-3">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide shrink-0">All Routes</p>
          <div className="flex items-center gap-2 ml-auto">
            {["All", "International", "Domestic"].map(t => (
              <button key={t} onClick={() => setTypeFilter(t)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-colors ${typeFilter === t ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200"}`}>{t}</button>
            ))}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search route..."
                className="pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-blue-500 w-40 bg-gray-50" />
            </div>
          </div>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["Route", "Airline", "Type", "Distance", "Status", "Actions"].map((h, i) => (
                <th key={h} className={`px-3 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wide ${i === 5 ? "text-center" : "text-left"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(r => (
              <tr key={r.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors group">
                <td className="px-3 py-0.5">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-[11px] font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">{r.origin}</span>
                    <ArrowRight className="w-3 h-3 text-gray-300 shrink-0" />
                    <span className="font-mono text-[11px] font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded">{r.destination}</span>
                  </div>
                </td>
                <td className="px-3 py-0.5 text-[11px] font-medium text-gray-700">{r.airline}</td>
                <td className="px-3 py-0.5">
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${r.type === "International" ? "bg-sky-50 text-sky-700" : "bg-emerald-50 text-emerald-700"}`}>
                    {r.type}
                  </span>
                </td>
                <td className="px-3 py-0.5 text-[11px] text-gray-400">{r.distance}</td>
                <td className="px-3 py-0.5">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${r.active ? "bg-emerald-50 text-emerald-700" : "bg-gray-100 text-gray-400"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${r.active ? "bg-emerald-500" : "bg-gray-400"}`} />
                    {r.active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-3 py-0.5">
                  <div className="flex justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button className="p-1.5 hover:bg-blue-50 rounded-lg"><Edit2 className="w-3.5 h-3.5 text-blue-500" /></button>
                    <button className="p-1.5 hover:bg-red-50 rounded-lg"><Trash2 className="w-3.5 h-3.5 text-red-400" /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="px-3 py-1 border-t border-gray-50"><p className="text-[11px] text-gray-400">Showing {filtered.length} of {DATA.length} routes</p></div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-5 w-full max-w-md shadow-2xl">
            <h2 className="text-base font-bold text-gray-900 mb-4">Add Route</h2>
            <div className="grid grid-cols-2 gap-3">
              {[["Origin (IATA)",""],["Destination (IATA)",""],["Airline","col-span-2"],["Type",""],["Distance",""]].map(([label, span]) => (
                <div key={label} className={span}>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</label>
                  <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50" />
                </div>
              ))}
            </div>
            <div className="flex gap-2.5 mt-5">
              <button onClick={() => setShowModal(false)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-500 hover:bg-gray-50">Cancel</button>
              <button onClick={() => setShowModal(false)} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>Save Route</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
