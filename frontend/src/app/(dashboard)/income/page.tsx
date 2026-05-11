"use client";

import { useState } from "react";
import { CheckCircle, Clock, Edit2, TrendingUp } from "lucide-react";

const MOCK_INCOME = [
  { id: 1, ticket: "176-4821903456", passenger: "Rahul Sharma", airline: "Emirates", deal: "EK-Q2-2025", base_fare: 420, commission: 18.90, override: 6.30, incentive: 12.00, total: 37.20, currency: "USD", approved: true, override_flag: false },
  { id: 2, ticket: "176-4821903457", passenger: "Priya Mehta", airline: "Emirates", deal: "EK-Q2-2025", base_fare: 1850, commission: 83.25, override: 27.75, incentive: 12.00, total: 123.00, currency: "USD", approved: true, override_flag: false },
  { id: 3, ticket: "098-1234567890", passenger: "Amit Verma", airline: "IndiGo", deal: "6E-MAR-25", base_fare: 85, commission: 2.55, override: 0, incentive: 0, total: 2.55, currency: "USD", approved: false, override_flag: false },
  { id: 5, ticket: "057-9876543210", passenger: "Vikram Nair", airline: "Air India", deal: "AI-CORP-25", base_fare: 520, commission: 26.00, override: 10.40, incentive: 20.00, total: 56.40, currency: "USD", approved: false, override_flag: true },
  { id: 6, ticket: "176-4821903460", passenger: "Meena Joshi", airline: "Emirates", deal: "EK-Q2-2025", base_fare: 980, commission: 44.10, override: 14.70, incentive: 0, total: 58.80, currency: "USD", approved: true, override_flag: false },
  { id: 8, ticket: "218-9988776655", passenger: "Kavya Reddy", airline: "Vistara", deal: "UK-MAR-OT", base_fare: 310, commission: 18.60, override: 7.75, incentive: 30.00, total: 56.35, currency: "USD", approved: false, override_flag: false },
];

export default function IncomePage() {
  const [records, setRecords] = useState(MOCK_INCOME);

  const total = records.reduce((s, r) => s + r.total, 0);
  const approved = records.filter((r) => r.approved).reduce((s, r) => s + r.total, 0);
  const pending = total - approved;

  const approve = (id: number) =>
    setRecords((prev) => prev.map((r) => r.id === id ? { ...r, approved: true } : r));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Income</h1>
        <p className="text-sm text-gray-500 mt-0.5">Deal-matched income across all tickets</p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border p-5">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-4 h-4 text-blue-500" />
            <p className="text-xs text-gray-500 uppercase font-medium">Total Calculated</p>
          </div>
          <p className="text-3xl font-bold text-gray-900">${total.toFixed(2)}</p>
        </div>
        <div className="bg-white rounded-xl border p-5">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <p className="text-xs text-gray-500 uppercase font-medium">Approved</p>
          </div>
          <p className="text-3xl font-bold text-green-600">${approved.toFixed(2)}</p>
        </div>
        <div className="bg-white rounded-xl border p-5">
          <div className="flex items-center gap-2 mb-1">
            <Clock className="w-4 h-4 text-yellow-500" />
            <p className="text-xs text-gray-500 uppercase font-medium">Pending Approval</p>
          </div>
          <p className="text-3xl font-bold text-yellow-600">${pending.toFixed(2)}</p>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
            <tr>
              <th className="px-4 py-3 text-left">Ticket</th>
              <th className="px-4 py-3 text-left">Passenger</th>
              <th className="px-4 py-3 text-left">Airline</th>
              <th className="px-4 py-3 text-left">Deal</th>
              <th className="px-4 py-3 text-right">Base Fare</th>
              <th className="px-4 py-3 text-right">Commission</th>
              <th className="px-4 py-3 text-right">Override</th>
              <th className="px-4 py-3 text-right">Incentive</th>
              <th className="px-4 py-3 text-right font-bold">Total Income</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {records.map((r) => (
              <tr key={r.id} className={`hover:bg-gray-50 ${r.override_flag ? "bg-orange-50/40" : ""}`}>
                <td className="px-4 py-3 font-mono text-xs text-gray-500">{r.ticket.slice(-6)}</td>
                <td className="px-4 py-3 font-medium">{r.passenger}</td>
                <td className="px-4 py-3 text-gray-600">{r.airline}</td>
                <td className="px-4 py-3 text-xs font-mono text-blue-600">{r.deal}</td>
                <td className="px-4 py-3 text-right">${r.base_fare.toFixed(2)}</td>
                <td className="px-4 py-3 text-right text-gray-600">${r.commission.toFixed(2)}</td>
                <td className="px-4 py-3 text-right text-gray-600">${r.override.toFixed(2)}</td>
                <td className="px-4 py-3 text-right text-gray-600">${r.incentive.toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-bold text-gray-900">
                  ${r.total.toFixed(2)}
                  {r.override_flag && <span className="ml-1 text-xs text-orange-500">(override)</span>}
                </td>
                <td className="px-4 py-3 text-center">
                  {r.approved ? (
                    <span className="text-xs text-green-600 font-medium flex items-center justify-center gap-1">
                      <CheckCircle className="w-3.5 h-3.5" /> Approved
                    </span>
                  ) : (
                    <span className="text-xs text-yellow-600 font-medium">Pending</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  {!r.approved && (
                    <button
                      onClick={() => approve(r.id)}
                      className="text-xs bg-green-600 text-white px-2.5 py-1 rounded-lg hover:bg-green-700"
                    >
                      Approve
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="bg-gray-50 border-t border-gray-200">
            <tr>
              <td colSpan={8} className="px-4 py-3 text-right text-sm font-semibold text-gray-700">Total</td>
              <td className="px-4 py-3 text-right text-sm font-bold text-gray-900">${total.toFixed(2)}</td>
              <td colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
