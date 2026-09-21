"use client";

// Admin → Approval workflow. One workflow per module per workspace, defined by the Super
// Admin: either deals go live the moment they are created, or they walk a list of steps.
//
// THE PAGE IS THE DECISION, THEN ITS CONSEQUENCE. The mode cards come first because they
// decide whether steps exist at all; the steps read as a numbered route the deal takes,
// since their ORDER is the whole point — step 2 never sees a deal step 1 rejected.
//
// A NEW WORKSPACE IS ALREADY ON "AUTO-APPROVE" (backend
// services/auth_service._ensure_default_deal_workflow), so this screen starts where the
// account actually is rather than offering a mode it was never on.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus, Trash2, Save, RefreshCw, Zap, ListChecks, ArrowUp, ArrowDown,
  CheckCircle2, AlertTriangle, FolderOpen, Ticket, UserCheck,
} from "lucide-react";
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
type ModuleValue = "deals" | "tickets";

const ROLE_OPTIONS = [
  { value: "operations_user", label: "Operations User" },
  { value: "finance_user", label: "Finance User" },
  { value: "company_admin", label: "Company Admin" },
  { value: "approver", label: "Approver" },
];
const ROLE_LABEL: Record<string, string> =
  Object.fromEntries(ROLE_OPTIONS.map(r => [r.value, r.label]));

const MODULES: { value: ModuleValue; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { value: "deals", label: "Deals", icon: FolderOpen },
  { value: "tickets", label: "Tickets", icon: Ticket },
];

/** The two ways a workspace can handle deals. `enterprise` is the only mode the Tickets
 *  module has, which is why the cards show for Deals alone. */
const MODES = [
  {
    value: "proprietary" as const,
    label: "Auto-approve",
    icon: Zap,
    blurb: "Deals go live the moment they are created. No approvers, no waiting.",
    detail: "What a new workspace starts on.",
  },
  {
    value: "enterprise" as const,
    label: "Approval steps",
    icon: ListChecks,
    blurb: "Every deal waits for the steps below, in order.",
    detail: "Add at least one step, each with its approvers.",
  },
];

function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null) {
    const maybe = err as { response?: { data?: { detail?: string } } };
    return maybe.response?.data?.detail || fallback;
  }
  return fallback;
}

export default function ApprovalWorkflowPage() {
  const [selectedModule, setSelectedModule] = useState<ModuleValue>("deals");
  const [workflowId, setWorkflowId] = useState<number | null>(null);
  // Proprietary, to match what a workspace is created with (backend
  // services/auth_service._ensure_default_deal_workflow) — the screen should not offer a
  // different starting point from the one the account actually has.
  const [dealCategory, setDealCategory] = useState<"enterprise" | "proprietary">("proprietary");
  const [steps, setSteps] = useState<WorkflowStep[]>([{ step_order: 1, role: "operations_user", approver_user_ids: [] }]);
  const [usersByRole, setUsersByRole] = useState<Record<string, WorkflowUser[]>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  /** What is STORED — so the strip at the top describes the workflow in force, not the
   *  edits on screen. */
  const [saved, setSaved] = useState<{ category: string; steps: number } | null>(null);

  const usedRoles = useMemo(() => [...new Set(steps.map((s) => s.role).filter(Boolean))], [steps]);
  // Tickets have no category — they always run steps.
  const stepsApply = selectedModule !== "deals" || dealCategory === "enterprise";

  const fetchUsersByRole = useCallback(async (role: string) => {
    if (usersByRole[role]) return;
    const res = await api.get<WorkflowUser[]>(`/approval-workflows/roles/${role}/users`);
    setUsersByRole((prev) => ({ ...prev, [role]: res.data }));
  }, [usersByRole]);

  const loadWorkflow = useCallback(async (module: ModuleValue = selectedModule) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<Workflow[]>("/approval-workflows", { params: { module } });
      const wf = res.data[0];
      if (!wf) {
        setWorkflowId(null);
        setDealCategory("proprietary");
        setSteps([{ step_order: 1, role: "operations_user", approver_user_ids: [] }]);
        setSaved(null);
      } else {
        setWorkflowId(wf.id);
        setDealCategory((wf.deal_category ?? "enterprise") as "enterprise" | "proprietary");
        const ordered = wf.steps
          .sort((a, b) => a.step_order - b.step_order)
          .map((s) => ({ id: s.id, step_order: s.step_order, role: s.role, approver_user_ids: s.approver_user_ids || [] }));
        // Never leave the editor with nothing to edit: a stored workflow with no steps is
        // the auto-approve one, and switching to Approval steps needs a row to start from.
        setSteps(ordered.length ? ordered : [{ step_order: 1, role: "operations_user", approver_user_ids: [] }]);
        setSaved({ category: wf.deal_category ?? "enterprise", steps: ordered.length });
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
    setSuccess(null);
  };

  const addStep = () => {
    setSteps((prev) => [
      ...prev,
      { step_order: prev.length + 1, role: "operations_user", approver_user_ids: [] },
    ]);
    setSuccess(null);
  };

  const removeStep = (idx: number) => {
    setSteps((prev) =>
      prev
        .filter((_, i) => i !== idx)
        .map((s, i) => ({ ...s, step_order: i + 1 }))
    );
    setSuccess(null);
  };

  /** Move a step earlier or later. The order IS the position in this list — the save
   *  renumbers from it — so swapping two rows is the whole operation. */
  const moveStep = (idx: number, delta: -1 | 1) => {
    setSteps((prev) => {
      const to = idx + delta;
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[to]] = [next[to], next[idx]];
      return next.map((s, i) => ({ ...s, step_order: i + 1 }));
    });
    setSuccess(null);
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
      setSuccess("Workflow saved.");
      await loadWorkflow();
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to save workflow"));
    } finally {
      setSaving(false);
    }
  };

  const moduleLabel = selectedModule === "deals" ? "Deals" : "Tickets";
  /** One sentence for the strip: what this workspace does with a new deal right now. */
  const inForce = !saved
    ? `No workflow saved for ${moduleLabel.toLowerCase()} yet.`
    : saved.category === "proprietary" && selectedModule === "deals"
      ? `${moduleLabel} are auto-approved — no approval steps.`
      : `${moduleLabel} go through ${saved.steps} approval step${saved.steps === 1 ? "" : "s"}.`;

  return (
    <div className="space-y-5 max-w-5xl">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Admin</p>
          <h1 className="text-xl font-bold text-gray-900">Approval Workflow</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Decide what happens to a new {moduleLabel.toLowerCase().replace(/s$/, "")} — one workflow per module, for the whole workspace.
          </p>
        </div>
        <button onClick={() => loadWorkflow()} disabled={loading} title="Refresh"
          className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {/* ── Module tabs + what is in force ───────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="px-4 pt-3 flex items-center gap-1 border-b border-gray-100">
          {MODULES.map(m => {
            const active = selectedModule === m.value;
            return (
              <button key={m.value} onClick={() => setSelectedModule(m.value)}
                className={`flex items-center gap-1.5 px-3.5 py-2.5 text-xs font-semibold border-b-2 -mb-px transition-colors ${
                  active ? "border-[#1e4d8c] text-[#1e4d8c]" : "border-transparent text-gray-400 hover:text-gray-700"
                }`}>
                <m.icon className="w-3.5 h-3.5" /> {m.label}
              </button>
            );
          })}
        </div>

        <div className="px-5 py-3 bg-gray-50/70 border-b border-gray-100 flex items-center gap-2">
          {loading ? (
            <RefreshCw className="w-3.5 h-3.5 text-gray-300 animate-spin" />
          ) : saved ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
          ) : (
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
          )}
          <p className="text-[11px] text-gray-600">
            <span className="font-semibold text-gray-800">In force now:</span> {loading ? "Loading…" : inForce}
          </p>
        </div>

        <div className="p-5 space-y-5">
          {/* ── Mode — deals only ──────────────────────────────────────── */}
          {selectedModule === "deals" && (
            <div>
              <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-2">
                What happens to a new deal
              </p>
              <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Deal approval mode">
                {MODES.map(m => {
                  const active = dealCategory === m.value;
                  return (
                    <button key={m.value} type="button" role="radio" aria-checked={active}
                      onClick={() => { setDealCategory(m.value); setSuccess(null); }}
                      className={`text-left rounded-xl border p-3.5 transition-all ${
                        active
                          ? "border-[#1e4d8c] bg-[#1e4d8c]/[0.04] ring-1 ring-[#1e4d8c]"
                          : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50/60"
                      }`}>
                      <div className="flex items-start justify-between gap-2">
                        <span className="flex items-center gap-2">
                          <span className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${
                            active ? "bg-[#1e4d8c] text-white" : "bg-gray-100 text-gray-500"
                          }`}>
                            <m.icon className="w-3.5 h-3.5" />
                          </span>
                          <span className="text-[13px] font-bold text-gray-900">{m.label}</span>
                        </span>
                        <span className={`w-4 h-4 mt-1 rounded-full border flex items-center justify-center shrink-0 ${
                          active ? "border-[#1e4d8c]" : "border-gray-300"
                        }`}>
                          {active && <span className="w-2 h-2 rounded-full bg-[#1e4d8c]" />}
                        </span>
                      </div>
                      <p className="text-[11px] text-gray-600 mt-2 leading-relaxed">{m.blurb}</p>
                      <p className="text-[10px] text-gray-400 mt-1">{m.detail}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Steps ──────────────────────────────────────────────────── */}
          {stepsApply ? (
            <div>
              <div className="flex items-end justify-between gap-2 mb-2">
                <div>
                  <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Approval route</p>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    Each step must be approved before the next one is asked. Any one of a step&apos;s approvers can act for it.
                  </p>
                </div>
                <span className="text-[10px] text-gray-400 whitespace-nowrap">
                  {steps.length} step{steps.length === 1 ? "" : "s"}
                </span>
              </div>

              <div className="space-y-2">
                {steps.map((step, idx) => {
                  const users = usersByRole[step.role] || [];
                  const missing = !step.approver_user_ids.length;
                  return (
                    <div key={idx} className="relative flex gap-3">
                      {/* the route line — a step is a position, not just a row */}
                      <div className="flex flex-col items-center pt-3">
                        <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold shrink-0 ${
                          missing ? "bg-amber-100 text-amber-700 border border-amber-300" : "bg-[#1e4d8c] text-white"
                        }`}>
                          {idx + 1}
                        </span>
                        {idx < steps.length - 1 && <span className="w-px flex-1 bg-gray-200 my-1" />}
                      </div>

                      <div className={`flex-1 rounded-xl border p-3 ${missing ? "border-amber-200 bg-amber-50/40" : "border-gray-200 bg-white"}`}>
                        <div className="grid gap-3 sm:grid-cols-2">
                          <div>
                            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">Role</label>
                            <select
                              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sky-400"
                              value={step.role}
                              onChange={(e) => setStep(idx, { role: e.target.value, approver_user_ids: [] })}
                            >
                              {ROLE_OPTIONS.map((r) => (
                                <option key={r.value} value={r.value}>{r.label}</option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
                              Approvers
                            </label>
                            <MultiSelectDropdown
                              options={users.map((u) => ({ value: u.id, label: u.full_name, sublabel: u.email }))}
                              selected={step.approver_user_ids}
                              onChange={(ids) => setStep(idx, { approver_user_ids: ids })}
                              placeholder={users.length ? "Select approvers…" : `No ${ROLE_LABEL[step.role] ?? "user"}s in this workspace`}
                            />
                          </div>
                        </div>

                        <div className="flex items-center justify-between gap-2 mt-2">
                          <p className={`text-[10px] flex items-center gap-1 ${missing ? "text-amber-700" : "text-gray-400"}`}>
                            {missing ? <AlertTriangle className="w-3 h-3" /> : <UserCheck className="w-3 h-3" />}
                            {missing
                              ? "Pick at least one approver — a step with nobody to act on it cannot be saved."
                              : `${step.approver_user_ids.length} approver${step.approver_user_ids.length === 1 ? "" : "s"} · any one of them can approve`}
                          </p>
                          <div className="flex items-center gap-1 shrink-0">
                            <button onClick={() => moveStep(idx, -1)} disabled={idx === 0} title="Move earlier"
                              className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30">
                              <ArrowUp className="w-3.5 h-3.5" />
                            </button>
                            <button onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} title="Move later"
                              className="p-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-30">
                              <ArrowDown className="w-3.5 h-3.5" />
                            </button>
                            <button onClick={() => removeStep(idx)} disabled={steps.length === 1} title="Remove step"
                              className="p-1.5 rounded-lg border border-gray-200 text-red-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30">
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <button onClick={addStep}
                className="mt-2 ml-9 flex items-center justify-center gap-1.5 border border-dashed border-sky-300 text-sky-600 rounded-lg py-2 px-4 text-xs font-semibold hover:bg-sky-50">
                <Plus className="w-3.5 h-3.5" /> Add step
              </button>
            </div>
          ) : (
            /* Auto-approve: say plainly that there is nothing else to set up. */
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3 flex items-start gap-2.5">
              <Zap className="w-4 h-4 text-emerald-600 mt-0.5 shrink-0" />
              <div>
                <p className="text-[12px] font-semibold text-emerald-900">No approvals needed</p>
                <p className="text-[11px] text-emerald-800/80 mt-0.5 leading-relaxed">
                  Every deal is approved as soon as it is created, and goes straight to Active. Nothing to configure —
                  switch to <span className="font-semibold">Approval steps</span> above when you want sign-offs.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* ── Save bar ────────────────────────────────────────────────── */}
        <div className="px-5 py-3 border-t border-gray-200 bg-white flex items-center justify-between gap-3">
          <div className="text-[11px] min-w-0">
            {error ? (
              <p className="flex items-center gap-1.5 text-red-600"><AlertTriangle className="w-3.5 h-3.5 shrink-0" />{error}</p>
            ) : success ? (
              <p className="flex items-center gap-1.5 text-green-600"><CheckCircle2 className="w-3.5 h-3.5 shrink-0" />{success}</p>
            ) : (
              <p className="text-gray-400">
                {workflowId ? "Saving replaces the workflow in force for this module." : "Nothing saved for this module yet."}
              </p>
            )}
          </div>
          <button onClick={save} disabled={saving || loading}
            className="flex items-center gap-1.5 text-white rounded-lg px-5 py-2 text-xs font-semibold disabled:opacity-50 shrink-0"
            style={{ background: "linear-gradient(135deg, #1e4d8c, #16304f)" }}>
            <Save className="w-3.5 h-3.5" /> {saving ? "Saving…" : "Save workflow"}
          </button>
        </div>
      </div>
    </div>
  );
}
