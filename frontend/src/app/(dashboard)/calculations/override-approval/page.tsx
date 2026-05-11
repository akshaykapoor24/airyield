"use client";

import { useState } from "react";
import { CheckCircle, XCircle, Clock, ArrowRight } from "lucide-react";

const PENDING = [
  { id: 2, ticket: "057-9876543210", airline: "Air India", class: "J", route: "DEL-LHR", baseFare: 1850, calculated: 129.50, manual: 145.00, reason: "Corporate deal terms updated mid-period", requestedBy: "Manvendra C.", requestedOn: "05 Apr 2025" },
  { id: 4, ticket: "057-9876543219", airline: "Emirates", class: "F", route: "DXB-JFK", baseFare: 4200, calculated: 210.00, manual: 252.00, reason: "Airline confirmed additional override for premium class booking in writing", requestedBy: "Pooja S.", requestedOn: "06 Apr 2025" },
];

const HISTORY = [
  { id: 1, ticket: "176-4821903463", airline: "Emirates", calculated: 25.20, manual: 30.00, action: "approved", actionBy: "Rajesh K.", actionOn: "05 Apr 2025" },
  { id: 3, ticket: "098-1234567901", airline: "IndiGo", calculated: 10.40, manual: 8.00, action: "rejected", actionBy: "Rajesh K.", actionOn: "04 Apr 2025" },
];

export default function OverrideApprovalPage() {
  const [remarks, setRemarks] = useState<Record<number, string>>({});
  const [action, setAction] = useState<Record<number, "approved" | "rejected">>({});

  const act = (id: number, type: "approved" | "rejected") =>
    setAction(prev => ({ ...prev, [id]: type }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Override Approval</h1>
        <p className="text-sm text-gray-500 mt-0.5">{PENDING.length} manual income overrides pending your approval</p>
      </div>

      {/* Pending */}
      <div className="space-y-4">
        {PENDING.map(item => {
          const done = action[item.id];
          const diff = item.manual - item.calculated;
          return (
            <div key={item.id} className={`bg-white rounded-xl border-2 transition-colors ${done === "approved" ? "border-green-400" : done === "rejected" ? "border-red-300" : "border-gray-200"}`}>
              <div className="p-5">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs font-bold text-gray-800">{item.ticket}</span>
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{item.airline}</span>
                      <span className="font-mono bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-xs font-bold">{item.class}</span>
                      <span className="text-xs text-gray-500">{item.route}</span>
                    </div>
                    <p className="text-sm text-gray-500 mt-1">
                      Requested by {item.requestedBy} · {item.requestedOn}
                    </p>
                  </div>
                  <div className={`text-right px-3 py-1.5 rounded-lg ${diff > 0 ? "bg-green-50" : "bg-red-50"}`}>
                    <p className={`text-lg font-bold ${diff > 0 ? "text-green-700" : "text-red-600"}`}>
                      {diff > 0 ? "+" : ""}${diff.toFixed(2)}
                    </p>
                    <p className="text-xs text-gray-500">income change</p>
                  </div>
                </div>

                <div className="mt-4 flex items-center gap-8 text-sm">
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Base Fare</p>
                    <p className="font-bold text-gray-900">${item.baseFare.toFixed(2)}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 text-gray-300" />
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Calculated Income</p>
                    <p className="font-medium text-gray-500 line-through">${item.calculated.toFixed(2)}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 text-gray-300" />
                  <div className="text-center">
                    <p className="text-xs text-gray-500">Override Amount</p>
                    <p className="font-bold text-blue-700 text-lg">${item.manual.toFixed(2)}</p>
                  </div>
                </div>

                <div className="mt-3 bg-gray-50 rounded-lg px-3 py-2 text-sm text-gray-700 italic">
                  "{item.reason}"
                </div>

                {!done && (
                  <div className="mt-4">
                    <label className="block text-xs font-medium text-gray-600 mb-1">Remarks (optional)</label>
                    <input value={remarks[item.id] || ""}
                      onChange={e => setRemarks(p => ({ ...p, [item.id]: e.target.value }))}
                      placeholder="Add approval or rejection note..."
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </div>
                )}

                {!done ? (
                  <div className="mt-4 flex gap-3">
                    <button onClick={() => act(item.id, "rejected")} className="flex items-center gap-2 px-4 py-2 border border-red-300 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50">
                      <XCircle className="w-4 h-4" /> Reject Override
                    </button>
                    <button onClick={() => act(item.id, "approved")} className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700">
                      <CheckCircle className="w-4 h-4" /> Approve Override
                    </button>
                  </div>
                ) : (
                  <div className={`mt-4 flex items-center gap-2 text-sm font-medium ${done === "approved" ? "text-green-700" : "text-red-600"}`}>
                    {done === "approved" ? <CheckCircle className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    Override {done === "approved" ? "approved" : "rejected"}
                    {remarks[item.id] && <span className="text-gray-400 font-normal ml-1">· "{remarks[item.id]}"</span>}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* History */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Recently Actioned</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Ticket</th>
              <th className="px-5 py-3 text-left">Airline</th>
              <th className="px-5 py-3 text-right">Calculated</th>
              <th className="px-5 py-3 text-right">Override</th>
              <th className="px-5 py-3 text-left">Action</th>
              <th className="px-5 py-3 text-left">By</th>
              <th className="px-5 py-3 text-left">On</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {HISTORY.map(h => (
              <tr key={h.id} className="hover:bg-gray-50">
                <td className="px-5 py-3 font-mono text-xs">{h.ticket}</td>
                <td className="px-5 py-3 text-gray-600">{h.airline}</td>
                <td className="px-5 py-3 text-right text-gray-500 line-through">${h.calculated.toFixed(2)}</td>
                <td className="px-5 py-3 text-right font-medium text-blue-700">${h.manual.toFixed(2)}</td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${h.action === "approved" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                    {h.action}
                  </span>
                </td>
                <td className="px-5 py-3 text-gray-500">{h.actionBy}</td>
                <td className="px-5 py-3 text-gray-500">{h.actionOn}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
