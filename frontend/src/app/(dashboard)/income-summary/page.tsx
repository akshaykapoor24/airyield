"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, Filter } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import api from "@/lib/api";

type MonthlyBreakdown = { month: string; commission: number; incentive: number; delta_comm: number };
type AirlineBreakdown = { airline: string; commission: number; incentive: number; delta_comm: number; total: number };
type IncomeSummaryData = {
  total:      number;
  commission: number;
  incentive:  number;
  delta_comm: number;
  monthly:    MonthlyBreakdown[];
  by_airline: AirlineBreakdown[];
};
type IncomeFilters = {
  airlines:    string[];
  segments:    string[];
  class_types: string[];
};

function fmt(v: number) {
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function pct(part: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((part / total) * 100)}%`;
}

const EMPTY: IncomeSummaryData = { total: 0, commission: 0, incentive: 0, delta_comm: 0, monthly: [], by_airline: [] };

export default function IncomeSummaryPage() {
  const [data,       setData]       = useState<IncomeSummaryData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [filterOpts, setFilterOpts] = useState<IncomeFilters>({ airlines: [], segments: ["Domestic", "International"], class_types: [] });

  const [airline,    setAirline]    = useState("");
  const [segment,    setSegment]    = useState("");
  const [classType,  setClassType]  = useState("");

  // fetch airlines + initial class types on mount
  useEffect(() => {
    api.get<IncomeFilters>("/dashboard/income-filters")
      .then(r => setFilterOpts(r.data))
      .catch(() => {});
  }, []);

  // re-fetch class types when airline changes (class master is per-airline)
  useEffect(() => {
    const params: Record<string, string> = {};
    if (airline) params.airline = airline;
    api.get<IncomeFilters>("/dashboard/income-filters", { params })
      .then(r => setFilterOpts(prev => ({ ...prev, class_types: r.data.class_types })))
      .catch(() => {});
    // reset class selection when airline changes
    setClassType("");
  }, [airline]);

  const fetchData = useCallback(() => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (airline)   params.airline    = airline;
    if (segment)   params.segment    = segment;
    if (classType) params.class_type = classType;
    api.get<IncomeSummaryData>("/dashboard/income-summary", { params })
      .then(r => setData(r.data))
      .finally(() => setLoading(false));
  }, [airline, segment, classType]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const d     = data ?? EMPTY;
  const total = d.total || 1;

  const byHead = [
    { head: "Commission Statement",  amount: d.commission,  pct: pct(d.commission,  total) },
    { head: "Commission Calculated", amount: d.incentive,   pct: pct(d.incentive,   total) },
    { head: "Delta Commission",      amount: d.delta_comm,  pct: pct(d.delta_comm,  total) },
  ].filter(r => r.amount !== 0);

  const activeFilterCount = [airline, segment, classType].filter(Boolean).length;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Income Statement Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">All time · All income heads</p>
        </div>
        <button onClick={fetchData} disabled={loading}
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* ── Filters ── */}
      <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 flex items-center gap-3 flex-wrap shadow-sm">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 shrink-0">
          <Filter className="w-3.5 h-3.5" />
          Filters
          {activeFilterCount > 0 && (
            <span className="bg-sky-500 text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full">{activeFilterCount}</span>
          )}
        </div>

        {/* Airline — from master */}
        <select value={airline} onChange={e => setAirline(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50 min-w-40">
          <option value="">All Airlines</option>
          {filterOpts.airlines.map(a => <option key={a} value={a}>{a}</option>)}
        </select>

        {/* Segment — always Domestic / International */}
        <select value={segment} onChange={e => setSegment(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50 min-w-35">
          <option value="">All Segments</option>
          {filterOpts.segments.map(s => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Class — from AirlineClassMaster, narrows when airline is selected */}
        <select value={classType} onChange={e => setClassType(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-400 bg-gray-50 min-w-35">
          <option value="">All Classes</option>
          {filterOpts.class_types.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        {activeFilterCount > 0 && (
          <button onClick={() => { setAirline(""); setSegment(""); setClassType(""); }}
            className="text-xs text-red-500 hover:text-red-700 font-medium ml-1">
            Clear all
          </button>
        )}

        {loading && <RefreshCw className="w-3.5 h-3.5 animate-spin text-gray-400 ml-auto" />}
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Income",             value: fmt(d.total),       sub: "Sell fare · all tickets",               color: "border-blue-500"   },
          { label: "Commission Statement",     value: fmt(d.commission),  sub: pct(d.commission,  total) + " of total", color: "border-green-500"  },
          { label: "Commission Calculated",    value: fmt(d.incentive),   sub: pct(d.incentive,   total) + " of total", color: "border-purple-500" },
          { label: "Delta Commission",         value: fmt(d.delta_comm),  sub: pct(d.delta_comm,  total) + " of total", color: "border-orange-500" },
        ].map(({ label, value, sub, color }) => (
          <div key={label} className={`bg-white rounded-xl border-l-4 ${color} border border-gray-200 p-5`}>
            <p className="text-xs text-gray-500 uppercase font-medium">{label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
            <p className="text-xs text-gray-400 mt-0.5">{sub}</p>
          </div>
        ))}
      </div>

      {/* Stacked Bar */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-4">Monthly Income Breakdown by Head</h2>
        {d.monthly.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={d.monthly}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v) => `₹${Number(v).toLocaleString("en-IN")}`} />
              <Legend />
              <Bar dataKey="commission" name="Commission Statement"  stackId="a" fill="#3b82f6" />
              <Bar dataKey="incentive"  name="Commission Calculated" stackId="a" fill="#8b5cf6" />
              <Bar dataKey="delta_comm" name="Delta Commission"      stackId="a" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[260px] flex items-center justify-center text-gray-400 text-sm">No monthly data yet</div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By Income Head */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Income Head</h2>
          </div>
          {byHead.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-5 py-3 text-left">Income Head</th>
                  <th className="px-5 py-3 text-right">Amount</th>
                  <th className="px-5 py-3 text-right">% Share</th>
                  <th className="px-5 py-3 text-left">Bar</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {byHead.map((r) => (
                  <tr key={r.head} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.head}</td>
                    <td className="px-5 py-3 text-right">{fmt(r.amount)}</td>
                    <td className="px-5 py-3 text-right text-gray-500">{r.pct}</td>
                    <td className="px-5 py-3 w-24">
                      <div className="h-2 bg-gray-100 rounded-full">
                        <div className="h-2 bg-blue-500 rounded-full" style={{ width: r.pct }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-5 py-8 text-center text-xs text-gray-400">No income data yet</div>
          )}
        </div>

        {/* By Airline */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-900">By Airline</h2>
          </div>
          {d.by_airline.length > 0 ? (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase text-gray-500">
                <tr>
                  <th className="px-5 py-3 text-left">Airline</th>
                  <th className="px-5 py-3 text-right">Comm Stmt</th>
                  <th className="px-5 py-3 text-right">Comm Calc</th>
                  <th className="px-5 py-3 text-right">Delta</th>
                  <th className="px-5 py-3 text-right font-bold">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {d.by_airline.map((r) => (
                  <tr key={r.airline} className="hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium">{r.airline}</td>
                    <td className="px-5 py-3 text-right text-gray-600">{fmt(r.commission)}</td>
                    <td className="px-5 py-3 text-right text-gray-600">{fmt(r.incentive)}</td>
                    <td className="px-5 py-3 text-right text-gray-600">{fmt(r.delta_comm)}</td>
                    <td className="px-5 py-3 text-right font-bold">{fmt(r.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-5 py-8 text-center text-xs text-gray-400">No airline data yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
