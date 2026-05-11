"use client";

import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from "recharts";

const SUPPLIERS = ["Gulf Travel Co.", "Sky Agents Ltd.", "PremiumAir", "Budget Wings"];

const METRICS = [
  { metric: "Total Income", "Gulf Travel Co.": 38400, "Sky Agents Ltd.": 24100, "PremiumAir": 18900, "Budget Wings": 14800 },
  { metric: "Deal Count", "Gulf Travel Co.": 12, "Sky Agents Ltd.": 9, "PremiumAir": 7, "Budget Wings": 6 },
  { metric: "Avg Commission %", "Gulf Travel Co.": 4.5, "Sky Agents Ltd.": 3.2, "PremiumAir": 5.8, "Budget Wings": 2.8 },
  { metric: "Tickets", "Gulf Travel Co.": 412, "Sky Agents Ltd.": 298, "PremiumAir": 187, "Budget Wings": 210 },
];

const MONTHLY = [
  { month: "Jan", "Gulf Travel Co.": 28000, "Sky Agents Ltd.": 18000, "PremiumAir": 14000, "Budget Wings": 10000 },
  { month: "Feb", "Gulf Travel Co.": 32000, "Sky Agents Ltd.": 20000, "PremiumAir": 15500, "Budget Wings": 11500 },
  { month: "Mar", "Gulf Travel Co.": 38400, "Sky Agents Ltd.": 24100, "PremiumAir": 18900, "Budget Wings": 14800 },
];

const RADAR = [
  { subject: "Income", A: 100, B: 63, C: 49, D: 39 },
  { subject: "Deals", A: 100, B: 75, C: 58, D: 50 },
  { subject: "Commission", A: 78, B: 55, C: 100, D: 48 },
  { subject: "Volume", A: 100, B: 72, C: 45, D: 51 },
  { subject: "Diversity", A: 85, B: 70, C: 60, D: 55 },
];

const COLORS = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981"];

export default function SupplierComparisonPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Supplier Comparison Dashboard</h1>
        <p className="text-sm text-gray-500 mt-0.5">Jan – Mar 2025 · All active suppliers</p>
      </div>

      {/* Supplier Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { name: "Gulf Travel Co.", income: "$38,400", deals: 12, commission: "4.5%", rank: 1 },
          { name: "Sky Agents Ltd.", income: "$24,100", deals: 9, commission: "3.2%", rank: 2 },
          { name: "PremiumAir", income: "$18,900", deals: 7, commission: "5.8%", rank: 3 },
          { name: "Budget Wings", income: "$14,800", deals: 6, commission: "2.8%", rank: 4 },
        ].map(({ name, income, deals, commission, rank }) => (
          <div key={name} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-start justify-between mb-3">
              <span className="text-xs font-bold text-white bg-blue-600 px-2 py-0.5 rounded-full">#{rank}</span>
            </div>
            <p className="font-semibold text-gray-900 text-sm">{name}</p>
            <p className="text-2xl font-bold text-gray-900 mt-2">{income}</p>
            <div className="mt-2 flex gap-3 text-xs text-gray-500">
              <span>{deals} deals</span>
              <span>·</span>
              <span>{commission} avg comm.</span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Monthly Trend */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Monthly Income by Supplier</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={MONTHLY}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="month" tick={{ fontSize: 12 }} />
              <YAxis tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v) => `$${Number(v).toLocaleString()}`} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {SUPPLIERS.map((s, i) => (
                <Bar key={s} dataKey={s} fill={COLORS[i]} radius={[2, 2, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Radar */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-4">Performance Radar</h2>
          <ResponsiveContainer width="100%" height={240}>
            <RadarChart data={RADAR}>
              <PolarGrid />
              <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11 }} />
              {["A", "B", "C", "D"].map((k, i) => (
                <Radar key={k} name={SUPPLIERS[i]} dataKey={k} stroke={COLORS[i]} fill={COLORS[i]} fillOpacity={0.1} />
              ))}
              <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v, e: any) => SUPPLIERS[["A","B","C","D"].indexOf(e.dataKey)]} />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Metrics Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100"><h2 className="text-sm font-semibold text-gray-900">Detailed Comparison</h2></div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Metric</th>
              {SUPPLIERS.map((s) => <th key={s} className="px-5 py-3 text-right">{s}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {METRICS.map((row) => {
              const vals = SUPPLIERS.map((s) => Number(row[s as keyof typeof row]));
              const max = Math.max(...vals);
              return (
                <tr key={row.metric} className="hover:bg-gray-50">
                  <td className="px-5 py-3 font-medium text-gray-700">{row.metric}</td>
                  {SUPPLIERS.map((s) => {
                    const val = Number(row[s as keyof typeof row]);
                    const isBest = val === max;
                    return (
                      <td key={s} className={`px-5 py-3 text-right font-medium ${isBest ? "text-green-700" : "text-gray-600"}`}>
                        {row.metric === "Total Income" ? `$${val.toLocaleString()}` : row.metric === "Avg Commission %" ? `${val}%` : val}
                        {isBest && <span className="ml-1 text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">Best</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
