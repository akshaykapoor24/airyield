"use client";

import { useState } from "react";
import { Download, Search, Filter, Shield } from "lucide-react";

const LOGS = [
  { id: 1, timestamp: "05 Apr 2025, 14:32", user: "Manvendra C.", role: "Manager", action: "Deal Approved", entity: "Deal", entityRef: "EK-APR-NEG", details: "Deal approved and submitted for final review", module: "Deals", ip: "192.168.1.42" },
  { id: 2, timestamp: "05 Apr 2025, 14:15", user: "Manvendra C.", role: "Manager", action: "Calculation Run", entity: "Batch", entityRef: "BATCH-20250405-001", details: "Income calculation triggered for 271 tickets — April 2025", module: "Calculations", ip: "192.168.1.42" },
  { id: 3, timestamp: "05 Apr 2025, 13:58", user: "Pooja S.", role: "Agent", action: "Deal Submitted", entity: "Deal", entityRef: "AI-CORP-25", details: "New deal submitted for review by manager", module: "Deals", ip: "10.0.0.18" },
  { id: 4, timestamp: "05 Apr 2025, 12:44", user: "Manvendra C.", role: "Manager", action: "Ticket Batch Upload", entity: "Batch", entityRef: "BATCH-20250405-001", details: "284 tickets uploaded from April_tickets_batch1.xlsx", module: "Tickets", ip: "192.168.1.42" },
  { id: 5, timestamp: "04 Apr 2025, 17:20", user: "Rajesh K.", role: "Admin", action: "Override Approved", entity: "Income Override", entityRef: "OVRD-001", details: "Manual income override approved: $25.20 → $30.00 for ticket 176-4821903463", module: "Calculations", ip: "172.16.0.5" },
  { id: 6, timestamp: "04 Apr 2025, 16:10", user: "Pooja S.", role: "Agent", action: "Override Rejected", entity: "Income Override", entityRef: "OVRD-003", details: "Manual override rejected for IndiGo ticket 098-1234567901", module: "Calculations", ip: "10.0.0.18" },
  { id: 7, timestamp: "03 Apr 2025, 11:05", user: "Rajesh K.", role: "Admin", action: "Deal Rejected", entity: "Deal", entityRef: "SG-Q1-25", details: "Deal rejected — incorrect commission rate in deal terms", module: "Deals", ip: "172.16.0.5" },
  { id: 8, timestamp: "03 Apr 2025, 09:30", user: "Manvendra C.", role: "Manager", action: "User Created", entity: "User", entityRef: "pooja.sharma@co.in", details: "New user account created with Agent role", module: "Admin", ip: "192.168.1.42" },
  { id: 9, timestamp: "01 Apr 2025, 08:55", user: "Rajesh K.", role: "Admin", action: "Rule Updated", entity: "Calc Rule", entityRef: "Rule #2", details: "Emirates J-Class Override rule updated: formula changed", module: "Masters", ip: "172.16.0.5" },
  { id: 10, timestamp: "31 Mar 2025, 18:40", user: "Manvendra C.", role: "Manager", action: "Income Approved", entity: "Income Record", entityRef: "INC-MAR-0048", details: "Income record approved for processing", module: "Income", ip: "192.168.1.42" },
];

const ACTION_COLOR: Record<string, string> = {
  "Deal Approved": "bg-green-100 text-green-700",
  "Deal Rejected": "bg-red-100 text-red-700",
  "Deal Submitted": "bg-blue-100 text-blue-700",
  "Calculation Run": "bg-purple-100 text-purple-700",
  "Override Approved": "bg-green-100 text-green-700",
  "Override Rejected": "bg-red-100 text-red-700",
  "Ticket Batch Upload": "bg-orange-100 text-orange-700",
  "User Created": "bg-indigo-100 text-indigo-700",
  "Rule Updated": "bg-yellow-100 text-yellow-700",
  "Income Approved": "bg-green-100 text-green-700",
};

const MODULES = ["All Modules", "Deals", "Calculations", "Tickets", "Income", "Masters", "Admin"];

export default function AuditTrailPage() {
  const [search, setSearch] = useState("");
  const [module, setModule] = useState("All Modules");

  const filtered = LOGS.filter(l =>
    (module === "All Modules" || l.module === module) &&
    (l.user.toLowerCase().includes(search.toLowerCase()) || l.entityRef.toLowerCase().includes(search.toLowerCase()) || l.action.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Audit Trail Report</h1>
          <p className="text-sm text-gray-500 mt-0.5">Complete activity log for all user actions across the system</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 border border-gray-200 rounded-lg text-sm hover:bg-gray-50">
          <Download className="w-4 h-4" /> Export Log
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by user, action, or reference..."
            className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div className="flex gap-2">
          {MODULES.map(m => (
            <button key={m} onClick={() => setModule(m)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${module === m ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-2">
          <Shield className="w-4 h-4 text-blue-500" />
          <span className="text-sm font-semibold text-gray-900">{filtered.length} log entries</span>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr>
              <th className="px-5 py-3 text-left">Timestamp</th>
              <th className="px-5 py-3 text-left">User</th>
              <th className="px-5 py-3 text-left">Action</th>
              <th className="px-5 py-3 text-left">Reference</th>
              <th className="px-5 py-3 text-left">Module</th>
              <th className="px-5 py-3 text-left">Details</th>
              <th className="px-5 py-3 text-left">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map(log => (
              <tr key={log.id} className="hover:bg-gray-50">
                <td className="px-5 py-3 text-xs text-gray-500 whitespace-nowrap">{log.timestamp}</td>
                <td className="px-5 py-3">
                  <p className="font-medium text-gray-900 text-xs">{log.user}</p>
                  <p className="text-xs text-gray-400">{log.role}</p>
                </td>
                <td className="px-5 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${ACTION_COLOR[log.action] || "bg-gray-100 text-gray-600"}`}>
                    {log.action}
                  </span>
                </td>
                <td className="px-5 py-3 font-mono text-xs text-blue-600 font-bold whitespace-nowrap">{log.entityRef}</td>
                <td className="px-5 py-3">
                  <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded text-xs">{log.module}</span>
                </td>
                <td className="px-5 py-3 text-xs text-gray-600 max-w-xs">{log.details}</td>
                <td className="px-5 py-3 font-mono text-xs text-gray-400">{log.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
