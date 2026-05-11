"use client";

import { useState } from "react";
import { Plus, Edit2, Trash2, DollarSign } from "lucide-react";

const DATA = [
  { id: 1, code: "COMM", name: "Commission", type: "Percentage", basis: "Base Fare", formula: "Base Fare × Commission %", seq: 1, taxable: true, active: true },
  { id: 2, code: "OVR", name: "Override", type: "Percentage", basis: "Base Fare", formula: "Base Fare × Override %", seq: 2, taxable: true, active: true },
  { id: 3, code: "INC", name: "Incentive", type: "Per Pax", basis: "Per Passenger", formula: "Fixed Amount × PAX Count", seq: 3, taxable: false, active: true },
  { id: 4, code: "PLB", name: "PLB (Performance Linked Bonus)", type: "Volume Slab", basis: "Quarterly Revenue", formula: "Revenue × PLB % (slab based)", seq: 4, taxable: true, active: true },
  { id: 5, code: "ADJ", name: "Adjustment", type: "Manual", basis: "Manual Entry", formula: "Manual override amount", seq: 5, taxable: false, active: true },
];

const TYPE_STYLE: Record<string, string> = {
  Percentage:    "bg-blue-50 text-blue-700",
  "Per Pax":     "bg-emerald-50 text-emerald-700",
  "Volume Slab": "bg-violet-50 text-violet-700",
  Manual:        "bg-gray-100 text-gray-600",
};

export default function IncomeHeadsPage() {
  const [showModal, setShowModal] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Income Head Master</h1>
          <p className="text-[11px] text-gray-400 mt-0.5">Define income types and calculation basis</p>
        </div>
        <button onClick={() => setShowModal(true)} className="flex items-center gap-1.5 text-white text-xs font-semibold px-3.5 py-2 rounded-lg shadow-sm hover:opacity-90" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>
          <Plus className="w-3.5 h-3.5" /> Add Income Head
        </button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Commission", color: "text-blue-600 bg-blue-50" },
          { label: "Override", color: "text-violet-600 bg-violet-50" },
          { label: "Incentive / PLB", color: "text-emerald-600 bg-emerald-50" },
          { label: "Taxable Heads", color: "text-orange-600 bg-orange-50" },
        ].map(({ label, color }, i) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-3 py-2 flex items-center gap-3 shadow-sm">
            <div className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${color}`}><DollarSign className="w-4 h-4" /></div>
            <div>
              <p className="text-base font-bold text-gray-900 leading-none">
                {i === 3 ? DATA.filter(d => d.taxable).length : i === 2 ? 2 : 1}
              </p>
              <p className="text-[11px] text-gray-400 mt-0.5">{label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="px-3 py-2 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">All Income Heads</p>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              {["Seq", "Code", "Name", "Type", "Basis", "Formula", "Taxable", "Actions"].map((h, i) => (
                <th key={h} className={`px-3 py-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wide ${i === 0 || i === 6 || i === 7 ? "text-center" : "text-left"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DATA.map(h => (
              <tr key={h.id} className="border-b border-gray-50 hover:bg-blue-50/30 transition-colors group">
                <td className="px-3 py-0.5 text-center">
                  <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-500 text-[11px] font-bold inline-flex items-center justify-center">{h.seq}</span>
                </td>
                <td className="px-3 py-0.5">
                  <span className="font-mono text-[11px] font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">{h.code}</span>
                </td>
                <td className="px-3 py-0.5 text-[11px] font-semibold text-gray-800">{h.name}</td>
                <td className="px-3 py-0.5">
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${TYPE_STYLE[h.type]}`}>{h.type}</span>
                </td>
                <td className="px-3 py-0.5 text-[11px] text-gray-400">{h.basis}</td>
                <td className="px-3 py-0.5">
                  <code className="text-[11px] bg-gray-50 text-gray-600 px-2 py-0.5 rounded border border-gray-100">{h.formula}</code>
                </td>
                <td className="px-3 py-0.5 text-center">
                  <span className={`text-[11px] font-semibold ${h.taxable ? "text-orange-600" : "text-gray-300"}`}>{h.taxable ? "Yes" : "No"}</span>
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
        <div className="px-3 py-1 border-t border-gray-50"><p className="text-[11px] text-gray-400">{DATA.length} income heads configured</p></div>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-5 w-full max-w-lg shadow-2xl">
            <h2 className="text-base font-bold text-gray-900 mb-4">Add Income Head</h2>
            <div className="grid grid-cols-2 gap-3">
              {[["Code",""],["Sequence",""],["Name","col-span-2"],["Type",""],["Basis",""],["Formula","col-span-2"]].map(([label, span]) => (
                <div key={label} className={span}>
                  <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</label>
                  <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-gray-50" />
                </div>
              ))}
              <div className="col-span-2 flex items-center gap-2">
                <input type="checkbox" id="taxable" className="w-4 h-4 rounded border-gray-300 text-blue-600" />
                <label htmlFor="taxable" className="text-[11px] font-semibold text-gray-600">Taxable income head</label>
              </div>
            </div>
            <div className="flex gap-2.5 mt-5">
              <button onClick={() => setShowModal(false)} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-500 hover:bg-gray-50">Cancel</button>
              <button onClick={() => setShowModal(false)} className="flex-1 text-white rounded-lg py-2 text-sm font-semibold" style={{ background: "linear-gradient(135deg, #1e4d8c, #1a3f7a)" }}>Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
