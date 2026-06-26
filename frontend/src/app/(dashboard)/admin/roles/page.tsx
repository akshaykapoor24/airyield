"use client";

import { useState } from "react";
import { Shield, CheckCircle, XCircle, Edit2 } from "lucide-react";

const ROLES = ["Admin", "Manager", "Agent", "Viewer"];

const PERMISSIONS = [
  { module: "Dashboard", actions: ["View Dashboard", "View Income Statement", "View Supplier Comparison"] },
  { module: "Deals", actions: ["View Deals", "Upload Deal", "Manual Deal Entry", "Review Extraction", "Submit Deal", "Approve Deal", "Reject Deal"] },
  { module: "Tickets", actions: ["View Tickets", "Upload Tickets", "View Validation", "Match Deal Manually"] },
  { module: "Calculations", actions: ["Run Calculation", "View Output", "Resolve Exceptions", "Create Override", "Approve Override"] },
  { module: "Income", actions: ["View Income", "Approve Income", "Export Income"] },
  { module: "Reports", actions: ["View Period Report", "View Adjustment Report", "View Audit Trail", "Export Reports"] },
  { module: "Masters", actions: ["View Masters", "Add/Edit Masters", "Delete Masters", "Manage Calc Rules"] },
  { module: "Admin", actions: ["Manage Users", "Manage Roles", "Manage Approval Matrix", "System Configuration"] },
];

const DEFAULT_MATRIX: Record<string, Record<string, boolean>> = {
  Admin: Object.fromEntries(PERMISSIONS.flatMap(p => p.actions.map(a => [a, true]))),
  Manager: Object.fromEntries(PERMISSIONS.flatMap(p => p.actions.map(a => [a,
    !["Manage Users", "Manage Roles", "Manage Approval Matrix", "System Configuration", "Delete Masters"].includes(a)
  ]))),
  Agent: Object.fromEntries(PERMISSIONS.flatMap(p => p.actions.map(a => [a,
    ["View Dashboard", "View Income Statement", "View Supplier Comparison", "View Deals", "Upload Deal", "Manual Deal Entry", "Review Extraction", "Submit Deal",
     "View Tickets", "Upload Tickets", "View Validation", "View Income", "View Period Report", "View Masters"].includes(a)
  ]))),
  Viewer: Object.fromEntries(PERMISSIONS.flatMap(p => p.actions.map(a => [a,
    a.startsWith("View") || a === "Export Income" || a === "Export Reports"
  ]))),
};

const ROLE_COLOR: Record<string, string> = {
  Admin: "bg-red-100 text-red-700 border-red-200",
  Manager: "bg-purple-100 text-purple-700 border-purple-200",
  Agent: "bg-blue-100 text-blue-700 border-blue-200",
  Viewer: "bg-gray-100 text-gray-600 border-gray-200",
};

export default function RolesPage() {
  const [matrix, setMatrix] = useState(DEFAULT_MATRIX);
  const [selectedRole, setSelectedRole] = useState("Manager");

  const toggle = (action: string) =>
    setMatrix(prev => ({
      ...prev,
      [selectedRole]: { ...prev[selectedRole], [action]: !prev[selectedRole][action] }
    }));

  const granted = Object.values(matrix[selectedRole]).filter(Boolean).length;
  const total = Object.values(matrix[selectedRole]).length;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Role & Permission Management</h1>
        <p className="text-sm text-gray-500 mt-0.5">Configure what each role can access and perform</p>
      </div>

      {/* Role Cards */}
      <div className="grid grid-cols-4 gap-4">
        {ROLES.map(role => {
          const count = Object.values(matrix[role]).filter(Boolean).length;
          return (
            <button key={role} onClick={() => setSelectedRole(role)}
              className={`text-left p-4 rounded-xl border-2 transition-all ${selectedRole === role ? ROLE_COLOR[role] : "bg-white border-gray-200 hover:border-gray-300"}`}>
              <div className="flex items-center gap-2 mb-2">
                <Shield className="w-4 h-4" />
                <span className="font-semibold">{role}</span>
              </div>
              <p className="text-xs opacity-70">{count} of {total} permissions</p>
              <div className="mt-2 h-1.5 bg-black/10 rounded-full overflow-hidden">
                <div className="h-full bg-current rounded-full opacity-40" style={{ width: `${(count / total) * 100}%` }} />
              </div>
            </button>
          );
        })}
      </div>

      {/* Permission Matrix */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${ROLE_COLOR[selectedRole]}`}>{selectedRole}</span>
            <h2 className="text-sm font-semibold text-gray-900">Permission Matrix</h2>
          </div>
          <p className="text-xs text-gray-500">{granted} of {total} permissions granted</p>
        </div>

        <div className="divide-y divide-gray-100">
          {PERMISSIONS.map(({ module, actions }) => (
            <div key={module} className="px-5 py-4">
              <p className="text-xs font-semibold text-gray-500 uppercase mb-3">{module}</p>
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
                {actions.map(action => {
                  const has = matrix[selectedRole][action];
                  return (
                    <label key={action} className={`flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors ${has ? "bg-green-50 border-green-200" : "bg-gray-50 border-gray-200 hover:border-gray-300"}`}>
                      <input type="checkbox" checked={has} onChange={() => toggle(action)} className="sr-only" />
                      {has ? <CheckCircle className="w-4 h-4 text-green-600 shrink-0" /> : <XCircle className="w-4 h-4 text-gray-300 shrink-0" />}
                      <span className={`text-xs font-medium ${has ? "text-green-800" : "text-gray-500"}`}>{action}</span>
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="px-5 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">Reset to Default</button>
          <button className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">Save Permissions</button>
        </div>
      </div>
    </div>
  );
}
