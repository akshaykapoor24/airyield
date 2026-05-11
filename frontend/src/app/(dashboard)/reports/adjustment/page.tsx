"use client";

import { useState } from "react";
import { Download, Plus, AlertCircle } from "lucide-react";

const ADJUSTMENTS = [
  { id: 1, ref: "ADJ-2025-001", type: "Credit Note", airline: "Emirates", amount: 1200.00, reason: "Duplicate commission charged for March batch", period: "Mar 2025", status: "approved", createdBy: "Rajesh K.", createdOn: "02 Apr 2025", approvedBy: "Arjun M.", approvedOn: "03 Apr 2025" },
  { id: 2, ref: "ADJ-2025-002", type: "Reversal", airline: "IndiGo", amount: -340.50, reason: "Ticket cancelled — income reversed", period: "Apr 2025", status: "approved", createdBy: "Manvendra C.", createdOn: "04 Apr 2025", approvedBy: "Rajesh K.", approvedOn: "04 Apr 2025" },
  { id: 3, ref: "ADJ-2025-003", type: "Debit Note", airline: "Air India", amount: -580.00, reason: "Clawback on PLB — volume target not met", period: "Q1 2025", status: "pending", createdBy: "Pooja S.", createdOn: "05 Apr 2025", approvedBy: null, approvedOn: null },
  { id: 4, ref: "ADJ-2025-004", type: "Correction", airline: "SpiceJet", amount: 95.20, reason: "Commission rate correction — wrong rate applied for March", period: "Mar 2025", status: "pending", createdBy: "Manvendra C.", createdOn: "05 Apr 2025", approvedBy: null, approvedOn: null },
];

const TYPE_COLOR: Record<string, string> = {
  "Credit Note": "bg-green-100 text-green-700",
  "Reversal": "bg-red-100 text-red-700",
  "Debit Note": "bg-orange-100 text-orange-700",
  "Correction": "bg-blue-100 text-blue-700",
};

const STATUS_COLOR: Record<string, string> = {
  approved: "bg-green-100 text-green-700",
  pending: "bg-yellow-100 text-yellow-700",
  rejected: "bg-red-100 text-red-700",
};

export default function AdjustmentReportPage() {
  const [showModal, setShowModal] = useState(false);
  const [filter, setFilter] = useState("all");

  const filtered = filter === "all" ? ADJUSTMENTS : ADJUSTMENTS.filter(a => a.status === filter);
  const totalNet = ADJUSTMENTS.filter(a => a.status === "approved").reduce((s, a) => s + a.amount, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Adjustment & Reversal Report</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track income adjustments, credit/debit notes, and reversals</p>
        </div>
        <div className="flex gap-2">
          <button className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg text-sm hover:bg-gray-50">
            <Download className="w-4 h-4" /> Export
          </button>
          <button onClick={() => setShowModal(true)} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
            <Plus className="w-4 h-4" /> New Adjustment
          </button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Total Adjustments", value: ADJUSTMENTS.length, color: "text-gray-900 bg-gray-50" },
          { label: "Pending Approval", value: ADJUSTMENTS.filter(a => a.status === "pending").length, color: "text-yellow-700 bg-yellow-50" },
          { label: "Approved Net Impact", value: `${totalNet >= 0 ? "+" : ""}$${totalNet.toFixed(2)}`, color: `${totalNet >= 0 ? "text-green-700 bg-green-50" : "text-red-700 bg-red-50"}` },
          { label: "This Period", value: ADJUSTMENTS.filter(a => a.period.includes("Apr")).length, color: "text-blue-700 bg-blue-50" },
        ].map(({ label, value, color }) => (
          <div key={label} className={`rounded-xl p-4 text-center ${color}`}>
            <p className="text-2xl font-bold">{value}</p>
            <p className="text-xs font-medium mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-900">Adjustment Records</h2>
          <div className="flex gap-2">
            {["all", "pending", "approved"].map(f => (
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
              <th className="px-5 py-3 text-left">Ref</th>
              <th className="px-5 py-3 text-left">Type</th>
              <th className="px-5 py-3 text-left">Airline</th>
              <th className="px-5 py-3 text-left">Period</th>
              <th className="px-5 py-3 text-right">Amount</th>
              <th className="px-5 py-3 text-left">Reason</th>
              <th className="px-5 py-3 text-left">Status</th>
              <th className="px-5 py-3 text-left">Approved By</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map(a => (
              <tr key={a.id} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs font-bold text-gray-700">{a.ref}</td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_COLOR[a.type]}`}>{a.type}</span>
                </td>
                <td className="px-5 py-3 text-gray-700">{a.airline}</td>
                <td className="px-5 py-3 text-gray-500 text-xs">{a.period}</td>
                <td className={`px-5 py-3 text-right font-bold ${a.amount >= 0 ? "text-green-700" : "text-red-600"}`}>
                  {a.amount >= 0 ? "+" : ""}${Math.abs(a.amount).toFixed(2)}
                </td>
                <td className="px-5 py-3 text-gray-600 text-xs max-w-xs truncate">{a.reason}</td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${STATUS_COLOR[a.status]}`}>{a.status}</span>
                </td>
                <td className="px-5 py-3 text-gray-500 text-xs">{a.approvedBy || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-bold text-gray-900 mb-4">New Adjustment</h2>
            <div className="space-y-3">
              {[["Type", "select"], ["Airline", "select"], ["Period", "text"], ["Amount ($)", "number"], ["Reason", "textarea"]].map(([label, type]) => (
                <div key={label}>
                  <label className="block text-xs font-medium text-gray-700 mb-1">{label} *</label>
                  {type === "textarea" ? (
                    <textarea rows={3} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  ) : type === "select" ? (
                    <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                      {label === "Type" ? ["Credit Note", "Debit Note", "Reversal", "Correction"].map(o => <option key={o}>{o}</option>)
                        : ["Emirates", "IndiGo", "Air India", "SpiceJet"].map(o => <option key={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type={type} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  )}
                </div>
              ))}
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
