"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Trash2, Save, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import MultiSelectDropdown from "@/components/ui/MultiSelectDropdown";

type WorkflowUser = { id: number; full_name: string; email: string; role: string };
type WorkflowStep = {
  id?: number;
  step_order: number;
  role: string;
  approver_user_ids: number[];
};
type Workflow = {
  id: number;
  module: string;
  deal_category: string;
  steps: Array<{ id: number; step_order: number; role: string; approver_user_ids: number[] }>;
};
type ModuleOption = { value: "deals" | "tickets"; label: string };

const ROLE_OPTIONS = [
  { value: "operations_user", label: "Operations User" },
  { value: "finance_user", label: "Finance User" },
  { value: "company_admin", label: "Company Admin" },
  { value: "approver", label: "Approver" },
];
const MODULE_OPTIONS: ModuleOption[] = [
  { value: "deals", label: "Deals" },
  { value: "tickets", label: "Tickets" },
];

function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null) {
    const maybe = err as { response?: { data?: { detail?: string } } };
    return maybe.response?.data?.detail || fallback;
  }
  return fallback;
}

export default function ApprovalWorkflowPage() {
  const [selectedModule, setSelectedModule] = useState<ModuleOption["value"]>("deals");
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  const [dealCategory, setDealCategory] = useState<"enterprise" | "proprietary">("enterprise");
  const [steps, setSteps] = useState<WorkflowStep[]>([{ step_order: 1, role: "operations_user", approver_user_ids: [] }]);
  const [usersByRole, setUsersByRole] = useState<Record<string, WorkflowUser[]>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const usedRoles = useMemo(() => [...new Set(steps.map((s) => s.role).filter(Boolean))], [steps]);

  const fetchUsersByRole = useCallback(async (role: string) => {
    if (usersByRole[role]) return;
    const res = await api.get<WorkflowUser[]>(`/approval-workflows/roles/${role}/users`);
    setUsersByRole((prev) => ({ ...prev, [role]: res.data }));
  }, [usersByRole]);

  const loadWorkflow = useCallback(async (module: ModuleOption["value"] = selectedModule) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Workflow[]>("/approval-workflows", { params: { module } });
      const wf = res.data[0];
      if (!wf) {
        setWorkflowId(null);
        setDealCategory("enterprise");
        setSteps([{ step_order: 1, role: "operations_user", approver_user_ids: [] }]);
      } else {
        setWorkflowId(wf.id);
        setDealCategory((wf.deal_category ?? "enterprise") as "enterprise" | "proprietary");
        setSteps(
          wf.steps
            .sort((a, b) => a.step_order - b.step_order)
            .map((s) => ({ id: s.id, step_order: s.step_order, role: s.role, approver_user_ids: s.approver_user_ids || [] }))
        );
      }
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to load workflow"));
    } finally {
      setLoading(false);
    }
  }, [selectedModule]);

  useEffect(() => {
    loadWorkflow(selectedModule);
  }, [selectedModule, loadWorkflow]);

  useEffect(() => {
    usedRoles.forEach((role) => {
      fetchUsersByRole(role);
    });
  }, [usedRoles, fetchUsersByRole]);

  const setStep = (idx: number, patch: Partial<WorkflowStep>) => {
    setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const addStep = () => {
    setSteps((prev) => [
      ...prev,
      { step_order: prev.length + 1, role: "operations_user", approver_user_ids: [] },
    ]);
  };

  const removeStep = (idx: number) => {
    setSteps((prev) =>
      prev
        .filter((_, i) => i !== idx)
        .map((s, i) => ({ ...s, step_order: i + 1 }))
    );
  };

  const save = async () => {
    setError(null);
    setSuccess(null);
    const isProprietary = dealCategory === "proprietary" && selectedModule === "deals";
    if (!isProprietary) {
      if (!steps.length) {
        setError("At least one step is required");
        return;
      }
      if (steps.some((s) => !s.approver_user_ids.length)) {
        setError("Please choose one or more approvers for every step");
        return;
      }
    }

    const payload = {
      module: selectedModule,
      deal_category: selectedModule === "deals" ? dealCategory : "enterprise",
      steps: isProprietary ? [] : steps.map((s, idx) => ({
        step_order: idx + 1,
        role: s.role,
        approver_user_ids: s.approver_user_ids,
      })),
    };

    setSaving(true);
    try {
      if (workflowId) {
        await api.patch(`/approval-workflows/${workflowId}`, payload);
      } else {
        await api.post("/approval-workflows", payload);
      }
      setSuccess("Workflow saved successfully.");
      await loadWorkflow();
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to save workflow"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {selectedModule === "deals" ? "Deals" : "Tickets"} Approval Workflow
          </h1>
          <p className="text-sm text-gray-500 mt-1">Super Admin can define one tenant workflow per module.</p>
        </div>
        <button
          onClick={() => loadWorkflow()}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error && <div className="px-4 py-3 rounded-lg bg-red-50 text-sm text-red-700 border border-red-200">{error}</div>}
      {success && <div className="px-4 py-3 rounded-lg bg-green-50 text-sm text-green-700 border border-green-200">{success}</div>}

      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <div className="max-w-sm">
          <label className="block text-xs font-medium text-gray-600 mb-1">Module</label>
          <select
            value={selectedModule}
            onChange={(e) => setSelectedModule(e.target.value as ModuleOption["value"])}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          >
            {MODULE_OPTIONS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>

        {/* Deal Category — deals module only */}
        {selectedModule === "deals" && (
          <div className="space-y-2">
            <label className="block text-xs font-medium text-gray-600">Deal Category</label>
            <div className="flex gap-2 max-w-sm">
              {(["enterprise", "proprietary"] as const).map(cat => (
                <button
                  key={cat}
                  type="button"
                  onClick={() => setDealCategory(cat)}
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-semibold transition-all ${
                    dealCategory === cat
                      ? "border-[#1e3a5f] bg-[#1e3a5f] text-white"
                      : "border-gray-200 bg-white text-gray-600 hover:border-gray-300"
                  }`}
                >
                  <span className={`w-3 h-3 rounded-full border-2 flex items-center justify-center shrink-0 ${
                    dealCategory === cat ? "border-white" : "border-gray-400"
                  }`}>
                    {dealCategory === cat && <span className="w-1.5 h-1.5 rounded-full bg-white block" />}
                  </span>
                  {cat === "enterprise" ? "Enterprise" : "Proprietary"}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-500">
              {dealCategory === "proprietary"
                ? "All deals will be auto-approved — no approval steps required."
                : "Deals will follow the approval steps configured below."}
            </p>
          </div>
        )}

        {/* Approval steps — hidden when proprietary */}
        {(selectedModule !== "deals" || dealCategory === "enterprise") && steps.map((step, idx) => {
          const users = usersByRole[step.role] || [];
          return (
            <div key={idx} className="grid grid-cols-12 gap-3 items-end border border-gray-100 rounded-lg p-3">
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-600 mb-1">Step</label>
                <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50" value={step.step_order} readOnly />
              </div>
              <div className="col-span-4">
                <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
                <select
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
                  value={step.role}
                  onChange={(e) => setStep(idx, { role: e.target.value, approver_user_ids: [] })}
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
              <div className="col-span-5">
                <label className="block text-xs font-medium text-gray-600 mb-1">Approver Users (multi-select)</label>
                <MultiSelectDropdown
                  options={users.map((u) => ({ value: u.id, label: u.full_name, sublabel: u.email }))}
                  selected={step.approver_user_ids}
                  onChange={(ids) => setStep(idx, { approver_user_ids: ids })}
                  placeholder="Select approvers..."
                />
              </div>
              <div className="col-span-1 flex justify-end">
                <button
                  onClick={() => removeStep(idx)}
                  disabled={steps.length === 1}
                  className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-40"
                >
                  <Trash2 className="w-4 h-4 text-gray-600" />
                </button>
              </div>
            </div>
          );
        })}

        <div className="flex gap-3">
          {(selectedModule !== "deals" || dealCategory === "enterprise") && (
            <button
              onClick={addStep}
              className="inline-flex items-center gap-2 px-3 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
            >
              <Plus className="w-4 h-4" /> Add Step
            </button>
          )}
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-[#1e3a5f] text-white rounded-lg hover:bg-[#16304f] disabled:opacity-60"
          >
            <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save Workflow"}
          </button>
        </div>
      </div>
    </div>
  );
}

