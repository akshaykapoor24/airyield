"use client";

import { useState } from "react";
import { Plus, Edit2, Trash2, Info, Calculator } from "lucide-react";

const DATA = [
  { id: 1, name: "Standard Commission Rule", airline: "All Airlines", incomeHead: "Commission", condition: "All Classes", formula: "Base Fare × Commission %", priority: 1, active: true },
  { id: 2, name: "Emirates J-Class Override", airline: "Emirates (EK)", incomeHead: "Override", condition: "Class = J or F", formula: "Base Fare × Override %", priority: 2, active: true },
  { id: 3, name: "IndiGo Economy Incentive", airline: "IndiGo (6E)", incomeHead: "Incentive", condition: "Class = Y, B, M", formula: "Incentive Per Pax × Count", priority: 3, active: true },
  { id: 4, name: "Air India PLB Slab", airline: "Air India (AI)", incomeHead: "PLB", condition: "Quarterly Rev > $50,000", formula: "Revenue × PLB % (tiered)", priority: 4, active: true },
  { id: 5, name: "Negotiated Deal Override", airline: "All Airlines", incomeHead: "Override", condition: "Deal Type = Negotiated", formula: "Base Fare × Negotiated Override %", priority: 2, active: true },
];

const PLB_SLABS = [
  { min: 0, max: 50000, rate: "0.5%" },
  { min: 50001, max: 100000, rate: "1.0%" },
  { min: 100001, max: 200000, rate: "1.5%" },
  { min: 200001, max: null, rate: "2.0%" },
];

const HEAD_STYLE: Record<string, string> = {
  Commission: "bg-blue-50 text-blue-700",
  Override:   "bg-violet-50 text-violet-700",
  Incentive:  "bg-emerald-50 text-emerald-700",
  PLB:        "bg-orange-50 text-orange-700",
};

const PRIORITY_COLORS = ["bg-red-500","bg-orange-500","bg-amber-500","bg-blue-500","bg-gray-400"];

export default function CalculationRulesPage() {
  const [showModal, setShowModal] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Calculation Rule Master</h1>
          <p className="text-[11px] text-gray-400 mt-0.5">Define income calculation logic and priority order</p>
        </div>
        <button onClick={() => setShowModal(true)} className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          <Plus className="w-3.5 h-3.5" /> Add Rule
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Total Rules", value: DATA.length, color: "text-blue-600 bg-blue-50" },
          { label: "Active", value: DATA.filter(r => r.active).length, color: "text-emerald-600 bg-emerald-50" },
          { label: "Income Heads", value: [...new Set(DATA.map(r => r.incomeHead))].length, color: "text-violet-600 bg-violet-50" },
          { label: "Airlines Covered", value: [...new Set(DATA.map(r => r.airline))].length, color: "text-orange-600 bg-orange-50" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}><Calculator className="w-4 h-4" /></div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">{value}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-blue-50 border border-blue-100 rounded-xl px-3 py-1.5 flex gap-2.5">
        <Info className="w-3.5 h-3.5 text-blue-500 shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700"><strong>Rule Priority:</strong> Rules are evaluated lowest number first (1 = highest). First matching rule per income head wins.</p>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-3 py-2 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Calculation Rules</p>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["P","Rule Name","Airline","Income Head","Condition","Formula","Status","Actions"].map((h, i) => (
                <th key={h} className={`px-3 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wide ${i === 0 || i === 7 ? "text-center" : "text-left"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DATA.map(r => (
              <tr key={r.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors group">
                <td className="px-3 py-0.5 text-center">
                  <span className={`w-5 h-5 rounded-full ${PRIORITY_COLORS[r.priority - 1] ?? "bg-gray-400"} text-white text-[10px] font-black inline-flex items-center justify-center`}>{r.priority}</span>
                </td>
                <td className="px-3 py-0.5 text-[11px] font-semibold text-gray-800 max-w-45 truncate">{r.name}</td>
                <td className="px-3 py-0.5 text-[11px] text-gray-500">{r.airline}</td>
                <td className="px-3 py-0.5">
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${HEAD_STYLE[r.incomeHead] ?? "bg-gray-100 text-gray-600"}`}>{r.incomeHead}</span>
                </td>
                <td className="px-3 py-0.5 text-[11px] text-gray-400">{r.condition}</td>
                <td className="px-3 py-0.5">
                  <code className="text-[11px] bg-gray-50 text-gray-600 px-2 py-0.5 rounded border border-gray-100">{r.formula}</code>
                </td>
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
        <div className="px-3 py-1 border-t border-gray-50"><p className="text-[11px] text-gray-400">{DATA.length} rules configured</p></div>
      </div>

      {/* PLB Slabs */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">PLB Volume Slab Configuration</p>
          <button className="text-[11px] bg-gray-100 text-gray-600 px-3 py-1 rounded-lg hover:bg-gray-200 font-medium">Edit Slabs</button>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["Revenue From", "Revenue To", "PLB Rate"].map(h => (
                <th key={h} className="px-3 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wide text-left">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PLB_SLABS.map((s, i) => (
              <tr key={i} className="border-b border-gray-50 hover:bg-gray-50/60">
                <td className="px-3 py-0.5 text-[11px] font-medium text-gray-700">${s.min.toLocaleString()}</td>
                <td className="px-3 py-0.5 text-[11px] font-medium text-gray-700">{s.max ? `$${s.max.toLocaleString()}` : <span className="text-gray-400">No limit</span>}</td>
                <td className="px-3 py-0.5"><span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded">{s.rate}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-5 w-full max-w-lg shadow-2xl">
            <h2 className="text-base font-bold text-gray-900 mb-4">Add Calculation Rule</h2>
            <div className="grid grid-cols-2 gap-3">
              {[["Rule Name","col-span-2"],["Airline",""],["Income Head",""],["Priority",""],["Condition","col-span-2"],["Formula","col-span-2"]].map(([label, span]) => (
                <div key={label} className={span}>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</label>
                  <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50" />
                </div>
              ))}
            </div>
            <div className="flex gap-2.5 mt-5">
              <button onClick={() => setShowModal(false)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-500 hover:bg-gray-50">Cancel</button>
              <button onClick={() => setShowModal(false)} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>Save Rule</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
