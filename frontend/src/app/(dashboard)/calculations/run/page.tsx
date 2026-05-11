"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play, Info, ChevronDown } from "lucide-react";

const BATCHES = [
  { id: "BATCH-20250405-001", label: "April_tickets_batch1.xlsx — 271 valid tickets (05 Apr 2025)" },
  { id: "BATCH-20250328-002", label: "March_tickets_final.xlsx — 318 valid tickets (28 Mar 2025)" },
];

const PERIODS = ["April 2025", "March 2025", "Q1 2025 (Jan–Mar)", "Custom Range"];
const DEAL_FILTERS = ["All Active Deals", "Emirates Only", "IndiGo Only", "Air India Only"];

export default function RunCalculationPage() {
  const router = useRouter();
  const [batch, setBatch] = useState(BATCHES[0].id);
  const [period, setPeriod] = useState("April 2025");
  const [dealFilter, setDealFilter] = useState("All Active Deals");
  const [includeUnmatched, setIncludeUnmatched] = useState(false);
  const [recalculate, setRecalculate] = useState(false);
  const [running, setRunning] = useState(false);

  const handleRun = () => {
    setRunning(true);
    setTimeout(() => {
      setRunning(false);
      router.push("/calculations/output");
    }, 2200);
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Run Income Calculation</h1>
        <p className="text-sm text-gray-500 mt-0.5">Configure parameters and run income calculation for a ticket batch</p>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex gap-3 text-sm text-blue-800">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        <div>
          Income is calculated using matched deals and the Calculation Rule Master. Unmatched tickets will be flagged as exceptions unless you choose to skip them.
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
        <h2 className="text-sm font-semibold text-gray-900 border-b border-gray-100 pb-3">Calculation Parameters</h2>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Ticket Batch *</label>
          <select value={batch} onChange={e => setBatch(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {BATCHES.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Calculation Period *</label>
          <select value={period} onChange={e => setPeriod(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {PERIODS.map(p => <option key={p}>{p}</option>)}
          </select>
        </div>

        {period === "Custom Range" && (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">From Date</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">To Date</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Deal Filter</label>
          <select value={dealFilter} onChange={e => setDealFilter(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {DEAL_FILTERS.map(d => <option key={d}>{d}</option>)}
          </select>
        </div>

        <div className="space-y-3 pt-1">
          <label className="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" checked={includeUnmatched} onChange={e => setIncludeUnmatched(e.target.checked)}
              className="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
            <div>
              <p className="text-sm font-medium text-gray-800">Include unmatched tickets as $0 income</p>
              <p className="text-xs text-gray-500">Unmatched tickets will appear in the output with zero income instead of being flagged as exceptions</p>
            </div>
          </label>
          <label className="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" checked={recalculate} onChange={e => setRecalculate(e.target.checked)}
              className="mt-0.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
            <div>
              <p className="text-sm font-medium text-gray-800">Recalculate already-processed tickets</p>
              <p className="text-xs text-gray-500">Overwrite any existing income records for tickets in this batch</p>
            </div>
          </label>
        </div>
      </div>

      {/* Summary Preview */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">Pre-run Summary</h2>
        <div className="grid grid-cols-3 gap-4 text-center">
          {[
            { label: "Tickets in Batch", value: "271", color: "text-gray-900" },
            { label: "Already Processed", value: "0", color: "text-gray-500" },
            { label: "Will be Calculated", value: "271", color: "text-blue-600" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-gray-50 rounded-xl p-3">
              <p className={`text-2xl font-bold ${color}`}>{value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={() => router.push("/tickets")} className="px-5 py-2.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
          Cancel
        </button>
        <button onClick={handleRun} disabled={running}
          className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-60">
          {running ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              Calculating...
            </>
          ) : (
            <><Play className="w-4 h-4" /> Run Calculation</>
          )}
        </button>
      </div>
    </div>
  );
}
