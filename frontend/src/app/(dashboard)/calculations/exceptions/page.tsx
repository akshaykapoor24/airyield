"use client";

import { useState } from "react";
import { AlertTriangle, Search, X } from "lucide-react";

const EXCEPTIONS = [
  { ticket: "098-1234567921", pnr: "", airline: "Emirates (EK)", class: "B", route: "DXB-BOM", travelDate: "12 Apr 2025", baseFare: 510, reason: "No active deal for Emirates class B on this route" },
  { ticket: "176-4821903499", pnr: "QRST56", airline: "Air India (AI)", class: "J", route: "DEL-SIN", travelDate: "13 Apr 2025", baseFare: 2100, reason: "Deal AI-CORP-25 expired before travel date" },
  { ticket: "057-9876543230", pnr: "UVWX89", airline: "IndiGo (6E)", class: "Z", route: "BOM-DEL", travelDate: "09 Apr 2025", baseFare: 95, reason: "RBD 'Z' not configured in Class master" },
  { ticket: "057-9876543231", pnr: "ABCF01", airline: "SpiceJet (SG)", class: "G", route: "HYD-BOM", travelDate: "10 Apr 2025", baseFare: 75, reason: "No matching deal found for SpiceJet" },
  { ticket: "176-4821903501", pnr: "GHIJ23", airline: "Vistara (UK)", class: "Y", route: "DEL-CCU", travelDate: "11 Apr 2025", baseFare: 110, reason: "Airline 'UK' not found in Airline master" },
];

const DEAL_OPTIONS = ["EK-Q2-2025 (Emirates)", "AI-CORP-25 (Air India)", "6E-MAR-25 (IndiGo)", "SG-APR-25 (SpiceJet)"];

export default function ExceptionsPage() {
  const [search, setSearch] = useState("");
  const [resolved, setResolved] = useState<string[]>([]);
  const [assignDeal, setAssignDeal] = useState<Record<string, string>>({});

  const filtered = EXCEPTIONS.filter(e =>
    e.ticket.includes(search) || e.airline.toLowerCase().includes(search.toLowerCase())
  );

  const resolve = (ticket: string) => setResolved(p => [...p, ticket]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Exceptions / Unmatched Tickets</h1>
        <p className="text-sm text-gray-500 mt-0.5">Tickets that could not be matched to any deal in the last calculation run</p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Exceptions", value: EXCEPTIONS.length, color: "bg-yellow-50 text-yellow-700" },
          { label: "Resolved", value: resolved.length, color: "bg-green-50 text-green-700" },
          { label: "Pending Resolution", value: EXCEPTIONS.length - resolved.length, color: "bg-red-50 text-red-700" },
        ].map(({ label, value, color }) => (
          <div key={label} className={`rounded-xl p-4 text-center ${color}`}>
            <p className="text-3xl font-bold">{value}</p>
            <p className="text-xs font-medium mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-yellow-500" /> Exception List
          </h2>
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tickets..."
              className="w-full pl-9 pr-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div className="divide-y divide-gray-100">
          {filtered.map(exc => {
            const isResolved = resolved.includes(exc.ticket);
            return (
              <div key={exc.ticket} className={`px-5 py-4 ${isResolved ? "bg-green-50/40" : ""}`}>
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 flex-wrap">
                      <span className="font-mono text-xs font-bold text-gray-800">{exc.ticket}</span>
                      {exc.pnr && <span className="text-xs text-gray-500">PNR: {exc.pnr}</span>}
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{exc.airline}</span>
                      <span className="font-mono bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded text-xs font-bold">{exc.class}</span>
                      <span className="text-xs text-gray-500">{exc.route}</span>
                      <span className="text-xs text-gray-400">{exc.travelDate}</span>
                    </div>
                    <p className="text-sm text-red-600 mt-1.5 flex items-start gap-1.5">
                      <X className="w-3.5 h-3.5 shrink-0 mt-0.5" /> {exc.reason}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">Base Fare: ${exc.baseFare.toFixed(2)}</p>
                  </div>

                  {!isResolved ? (
                    <div className="flex items-center gap-2 shrink-0">
                      <select value={assignDeal[exc.ticket] || ""} onChange={e => setAssignDeal(p => ({ ...p, [exc.ticket]: e.target.value }))}
                        className="border border-gray-200 rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option value="">Assign Deal...</option>
                        {DEAL_OPTIONS.map(d => <option key={d}>{d}</option>)}
                      </select>
                      <button onClick={() => resolve(exc.ticket)}
                        className="px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-medium hover:bg-blue-700">
                        Resolve
                      </button>
                      <button className="px-3 py-1.5 border border-gray-200 text-gray-600 rounded-lg text-xs hover:bg-gray-50">
                        Exclude
                      </button>
                    </div>
                  ) : (
                    <span className="text-xs font-medium text-green-700 bg-green-100 px-3 py-1.5 rounded-lg shrink-0">Resolved</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {resolved.length > 0 && (
        <div className="flex justify-end">
          <button className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
            Recalculate {resolved.length} Resolved Tickets
          </button>
        </div>
      )}
    </div>
  );
}
