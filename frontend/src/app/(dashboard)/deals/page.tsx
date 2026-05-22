"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, Upload, Search, RefreshCw, Clock, X, CheckCircle, XCircle, AlertCircle, MinusCircle, User, Pencil, Save, Trash2 } from "lucide-react";
import api from "@/lib/api";

// ── section tabs ───────────────────────────────────────────────────────────
const SECTION_TABS = [
  "Deal Repository",
  "Deal Approver Details",
  "B2E Details",
  "B2B Details",
  "B2C Details",
  "LOB Approval Details",
  "Final Approver Details",
  "Audit Details",
];

// ── types ──────────────────────────────────────────────────────────────────
type DealType = "upload" | "airline" | "b2b";

type DealRepositoryItem = {
  id:              number;
  deal_no:         string;
  deal_type:       DealType;
  source_agent:    string;
  airline_type:    string | null;
  airline_name:    string | null;
  contract_year:   string | null;
  valid_from:      string | null;
  valid_to:        string | null;
  trigger_type:    string | null;
  payout_type:     string | null;
  business_type:   string | null;
  entity_lcc:      string | null;
  remark:          string | null;
  deal_maker_name: string | null;
  incentive_types: string[] | null;
  incentive_data:  Record<string, Record<string, string>> | null;
  incl_excl_types: string[] | null;
  incl_excl_data:  Record<string, Record<string, string>> | null;
  status:                string;
  deal_lifecycle_status: string | null;
  created_at:            string;
  file_type:             string | null;
};

type DealHistoryStep = {
  step_order:          number;
  role:                string;
  assigned_user_name:  string;
  status:              string;
  acted_by_name:       string | null;
  acted_at:            string | null;
  reason:              string | null;
};

type DealHistoryData = {
  deal_id:          number;
  created_by_name:  string;
  created_at:       string;
  source_type:      string;
  status:           string;
  steps:            DealHistoryStep[];
};

// ── helpers ────────────────────────────────────────────────────────────────
const STATUS_STYLE: Record<string, string> = {
  approved:         "bg-green-50 text-green-600 border-green-200",
  confirmed:        "bg-blue-50 text-blue-600 border-blue-200",
  pending_approval: "bg-blue-50 text-blue-600 border-blue-200",
  extracted:        "bg-yellow-50 text-yellow-600 border-yellow-200",
  rejected:         "bg-red-50 text-red-600 border-red-200",
};
const STATUS_DOT: Record<string, string> = {
  approved:         "bg-green-500",
  confirmed:        "bg-blue-500",
  pending_approval: "bg-blue-500",
  extracted:        "bg-yellow-500",
  rejected:         "bg-red-500",
};
const STATUS_LABEL: Record<string, string> = {
  confirmed:        "Pending Approval",
  pending_approval: "Pending Approval",
  approved:         "Approved",
  rejected:         "Rejected",
  extracted:        "Extracted",
};

const LIFECYCLE_STYLE: Record<string, string> = {
  draft:  "bg-gray-50 text-gray-500 border-gray-200",
  active: "bg-emerald-50 text-emerald-600 border-emerald-200",
  closed: "bg-slate-100 text-slate-500 border-slate-300",
};
const LIFECYCLE_DOT: Record<string, string> = {
  draft:  "bg-gray-400",
  active: "bg-emerald-500",
  closed: "bg-slate-400",
};
const LIFECYCLE_LABEL: Record<string, string> = {
  draft:  "Draft",
  active: "Active",
  closed: "Closed",
};

const DEAL_TYPE_STYLE: Record<string, { label: string; cls: string }> = {
  airline: { label: "Airline", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  b2b:     { label: "B2B",     cls: "bg-violet-50 text-violet-700 border-violet-200" },
  upload:  { label: "Upload",  cls: "bg-teal-50 text-teal-700 border-teal-200" },
};

function getDealTypeBadge(d: DealRepositoryItem) {
  if (d.deal_type !== "upload") return DEAL_TYPE_STYLE[d.deal_type];
  if (d.business_type) return DEAL_TYPE_STYLE.b2b;
  return DEAL_TYPE_STYLE.airline;
}

const STEP_STATUS_CONFIG: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  approved: { icon: <CheckCircle className="w-3.5 h-3.5" />, color: "text-green-600", label: "Approved" },
  rejected: { icon: <XCircle    className="w-3.5 h-3.5" />, color: "text-red-600",   label: "Rejected" },
  pending:  { icon: <AlertCircle className="w-3.5 h-3.5" />, color: "text-blue-500", label: "Pending"  },
  skipped:  { icon: <MinusCircle className="w-3.5 h-3.5" />, color: "text-gray-400", label: "Skipped"  },
};

const CONTRACT_YEAR_OPTIONS = ["Calendar year", "Financial year"];
const TRIGGER_TYPE_OPTIONS  = ["Flown", "Sales"];
const PAYOUT_TYPE_OPTIONS   = ["Flown", "Sales"];
const BUSINESS_TYPE_OPTIONS = ["B2B", "B2C", "B2E", "MICE"];
const AIRLINE_TYPE_OPTIONS  = ["GDS", "LCC"];

function formatDate(d: string | null) {
  if (!d) return "—";
  try { return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return d; }
}

function formatDateTime(d: string | null) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return d; }
}

const PAGE_SIZE = 20;

// ── IncentiveEditModal ─────────────────────────────────────────────────────
function IncentiveEditModal({ name, data, onSave, onClose }: {
  name: string;
  data: Record<string, string>;
  onSave: (updated: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>({ ...data });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(fields); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Incentive Type — Edit Details</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
          {Object.keys(fields).length === 0 ? (
            <p className="text-xs text-gray-400 py-2">No fields recorded for this incentive.</p>
          ) : (
            <div className="space-y-3">
              {Object.entries(fields).map(([k, v]) => (
                <div key={k}>
                  <label className="block text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                    {k.replace(/([A-Z])/g, " $1").trim()}
                  </label>
                  <input
                    type="text"
                    value={v}
                    onChange={e => setFields(prev => ({ ...prev, [k]: e.target.value }))}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="px-5 pb-4 flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ── InclExclEditModal ──────────────────────────────────────────────────────
function InclExclEditModal({ name, data, onSave, onClose }: {
  name: string;
  data: Record<string, string>;
  onSave: (updated: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<Record<string, string>>({ ...data });
  const [saving, setSaving] = useState(false);
  const isExcl = name.toLowerCase().includes("exclusion");

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(fields); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className={`text-sm font-bold ${isExcl ? "text-red-700" : "text-green-700"}`}>{name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">{isExcl ? "Exclusion" : "Inclusion"} Rule — Edit Details</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="px-5 py-4 max-h-[60vh] overflow-y-auto">
          {Object.keys(fields).length === 0 ? (
            <p className="text-xs text-gray-400 py-2">No fields recorded for this rule.</p>
          ) : (
            <div className="space-y-3">
              {Object.entries(fields).map(([k, v]) => (
                <div key={k}>
                  <label className="block text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1">
                    {k.replace(/([A-Z])/g, " $1").trim()}
                  </label>
                  <input
                    type="text"
                    value={v}
                    onChange={e => setFields(prev => ({ ...prev, [k]: e.target.value }))}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
                  />
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="px-5 pb-4 flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ── DealHistoryPanel ───────────────────────────────────────────────────────
function DealHistoryPanel({ dealId, dealType, displayLabel, data, loading, onClose }: {
  dealId: number; dealType: DealType; displayLabel: string;
  data: DealHistoryData | null; loading: boolean; onClose: () => void;
}) {
  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-100 bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Deal #{dealId} — History</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">
              {displayLabel} deal · Creation &amp; approval trail
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-5 h-5 animate-spin text-gray-300" />
            </div>
          ) : !data ? (
            <p className="text-xs text-gray-400 text-center py-12">Failed to load history.</p>
          ) : (
            <>
              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Created</p>
                <div className="flex items-start gap-3 bg-gray-50 rounded-xl p-3">
                  <div className="w-8 h-8 rounded-full bg-[#1e3a5f] flex items-center justify-center shrink-0">
                    <User className="w-4 h-4 text-white" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold text-gray-800">{data.created_by_name}</p>
                    <p className="text-[11px] text-gray-500 mt-0.5">{formatDateTime(data.created_at)}</p>
                    <span className={`inline-block mt-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                      data.source_type === "manual"
                        ? "bg-indigo-50 text-indigo-600 border border-indigo-200"
                        : "bg-teal-50 text-teal-600 border border-teal-200"
                    }`}>
                      {data.source_type}
                    </span>
                  </div>
                </div>
              </div>

              <div>
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Approval Timeline</p>
                {data.steps.length === 0 ? (
                  <p className="text-[12px] text-gray-400 italic py-4 text-center">No approval steps yet.</p>
                ) : (
                  <div className="relative">
                    <div className="absolute left-4 top-2 bottom-2 w-px bg-gray-200" />
                    <div className="space-y-4">
                      {data.steps.map((step, idx) => {
                        const cfg = STEP_STATUS_CONFIG[step.status] ?? STEP_STATUS_CONFIG.pending;
                        return (
                          <div key={idx} className="flex gap-3 relative">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 ${
                              step.status === "approved" ? "bg-green-50 border-2 border-green-400"
                              : step.status === "rejected" ? "bg-red-50 border-2 border-red-400"
                              : step.status === "skipped" ? "bg-gray-50 border-2 border-gray-300"
                              : "bg-blue-50 border-2 border-blue-400"
                            }`}>
                              <span className={`text-[10px] font-bold ${cfg.color}`}>{step.step_order}</span>
                            </div>
                            <div className="flex-1 min-w-0 pb-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-[11px] font-semibold text-gray-700">{step.role}</span>
                                <span className={`inline-flex items-center gap-1 text-[10px] font-medium ${cfg.color}`}>
                                  {cfg.icon} {cfg.label}
                                </span>
                              </div>
                              <p className="text-[11px] text-gray-500 mt-0.5">
                                Assigned to: <span className="font-medium text-gray-700">{step.assigned_user_name}</span>
                              </p>
                              {step.acted_by_name && step.acted_at && (
                                <p className="text-[11px] text-gray-500 mt-0.5">
                                  By: <span className="font-medium text-gray-700">{step.acted_by_name}</span>
                                  {" · "}{formatDateTime(step.acted_at)}
                                </p>
                              )}
                              {step.reason && (
                                <p className="text-[11px] text-gray-500 italic mt-1 bg-gray-50 rounded px-2 py-1">
                                  &ldquo;{step.reason}&rdquo;
                                </p>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ── DealEditPanel ──────────────────────────────────────────────────────────
type EditFields = {
  airline_type:    string;
  airline_name:    string;
  contract_year:   string;
  valid_from:      string;
  valid_to:        string;
  trigger_type:    string;
  payout_type:     string;
  business_type:   string;
  entity_lcc:      string;
  remark:          string;
  deal_maker_name: string;
};

function DealEditPanel({ deal, onSave, onClose }: {
  deal: DealRepositoryItem;
  onSave: (updated: Partial<EditFields>) => Promise<void>;
  onClose: () => void;
}) {
  const [fields, setFields] = useState<EditFields>({
    airline_type:    deal.airline_type    ?? "",
    airline_name:    deal.airline_name    ?? "",
    contract_year:   deal.contract_year   ?? "",
    valid_from:      deal.valid_from      ?? "",
    valid_to:        deal.valid_to        ?? "",
    trigger_type:    deal.trigger_type    ?? "",
    payout_type:     deal.payout_type     ?? "",
    business_type:   deal.business_type   ?? "",
    entity_lcc:      deal.entity_lcc      ?? "",
    remark:          deal.remark          ?? "",
    deal_maker_name: deal.deal_maker_name ?? "",
  });
  const [saving, setSaving] = useState(false);

  const set = (k: keyof EditFields) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setFields(prev => ({ ...prev, [k]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Partial<EditFields> = {};
      for (const [k, v] of Object.entries(fields) as [keyof EditFields, string][]) {
        const orig = (deal[k as keyof DealRepositoryItem] ?? "") as string;
        if (v !== orig) payload[k] = v || undefined;
      }
      await onSave(payload);
    } finally {
      setSaving(false);
    }
  };

  const inp = "w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400";
  const lbl = "block text-[9px] font-semibold text-gray-400 uppercase tracking-wide mb-1";
  const sel = `${inp} bg-white`;

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-[480px] bg-white shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Edit Deal #{deal.id}</h2>
            <p className="text-[11px] text-gray-400 mt-0.5">{getDealTypeBadge(deal).label} deal · {deal.airline_name || deal.source_agent}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Contract Details</p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Airline Type</label>
              <select value={fields.airline_type} onChange={set("airline_type")} className={sel}>
                <option value="">— Select —</option>
                {AIRLINE_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Airline Name</label>
              <input type="text" value={fields.airline_name} onChange={set("airline_name")} className={inp} placeholder="e.g. Air India" />
            </div>
            <div>
              <label className={lbl}>Contract Year</label>
              <select value={fields.contract_year} onChange={set("contract_year")} className={sel}>
                <option value="">— Select —</option>
                {CONTRACT_YEAR_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Deal Maker</label>
              <input type="text" value={fields.deal_maker_name} onChange={set("deal_maker_name")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Valid From</label>
              <input type="date" value={fields.valid_from?.slice(0, 10) ?? ""} onChange={set("valid_from")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Valid To</label>
              <input type="date" value={fields.valid_to?.slice(0, 10) ?? ""} onChange={set("valid_to")} className={inp} />
            </div>
            <div>
              <label className={lbl}>Trigger Type</label>
              <select value={fields.trigger_type} onChange={set("trigger_type")} className={sel}>
                <option value="">— Select —</option>
                {TRIGGER_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Payout Type</label>
              <select value={fields.payout_type} onChange={set("payout_type")} className={sel}>
                <option value="">— Select —</option>
                {PAYOUT_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Business Type</label>
              <select value={fields.business_type} onChange={set("business_type")} className={sel}>
                <option value="">— Select —</option>
                {BUSINESS_TYPE_OPTIONS.map(o => <option key={o}>{o}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Entity (LCC)</label>
              <input type="text" value={fields.entity_lcc} onChange={set("entity_lcc")} className={inp} />
            </div>
          </div>

          <div>
            <label className={lbl}>Remark</label>
            <textarea value={fields.remark} onChange={set("remark")} rows={3}
              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none" />
          </div>

          {(deal.incentive_types ?? []).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Incentive Types</p>
              <div className="flex flex-wrap gap-1">
                {(deal.incentive_types ?? []).map(t => (
                  <span key={t} className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                    {t}
                  </span>
                ))}
              </div>
              <p className="text-[10px] text-gray-400 mt-1">Click incentive pills in the table to edit their details.</p>
            </div>
          )}

          {(deal.incl_excl_types ?? []).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Inclusions / Exclusions</p>
              <div className="flex flex-wrap gap-1">
                {(deal.incl_excl_types ?? []).map(t => {
                  const isExcl = t.toLowerCase().includes("exclusion");
                  return (
                    <span key={t} className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${
                      isExcl ? "bg-red-50 text-red-600 border-red-200" : "bg-green-50 text-green-700 border-green-200"
                    }`}>{t}</span>
                  );
                })}
              </div>
              <p className="text-[10px] text-gray-400 mt-1">Click incl/excl pills in the table to edit their details.</p>
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-100 flex gap-2">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save Changes"}
          </button>
          <button onClick={onClose}
            className="px-4 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">
            Cancel
          </button>
        </div>
      </div>
    </>
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function DealsPage() {
  const [sectionTab, setSectionTab] = useState("Deal Repository");
  const [deals,      setDeals]      = useState<DealRepositoryItem[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [apiError,   setApiError]   = useState("");
  const [search,     setSearch]     = useState("");
  const [dealTypeFilter, setDealTypeFilter] = useState<"all" | DealType>("all");
  const [page,       setPage]       = useState(1);

  // history panel
  const [historyDealId,   setHistoryDealId]   = useState<number | null>(null);
  const [historyDealType, setHistoryDealType] = useState<DealType>("upload");
  const [historyLabel,    setHistoryLabel]    = useState("Upload");
  const [historyData,     setHistoryData]     = useState<DealHistoryData | null>(null);
  const [historyLoading,  setHistoryLoading]  = useState(false);

  // edit panel
  const [editDeal,        setEditDeal]        = useState<DealRepositoryItem | null>(null);

  // delete
  const [deleteTarget,    setDeleteTarget]    = useState<DealRepositoryItem | null>(null);
  const [deleteLoading,   setDeleteLoading]   = useState(false);

  // detail / edit popups (keyed by deal + incentive/incl name)
  const [incentivePopup, setIncentivePopup] = useState<{
    name: string; data: Record<string, string>; dealId: number; dealType: DealType;
  } | null>(null);
  const [inclExclPopup, setInclExclPopup] = useState<{
    name: string; data: Record<string, string>; dealId: number; dealType: DealType;
  } | null>(null);

  const fetchDeals = useCallback(async () => {
    setLoading(true);
    setApiError("");
    try {
      const { data } = await api.get<DealRepositoryItem[]>("/deals/repository");
      setDeals(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setApiError(msg ?? "Failed to load deals.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDeals(); }, [fetchDeals]);

  const openHistory = useCallback(async (d: DealRepositoryItem) => {
    setHistoryDealId(d.id);
    setHistoryDealType(d.deal_type);
    setHistoryLabel(getDealTypeBadge(d).label);
    setHistoryData(null);
    setHistoryLoading(true);
    try {
      const { data } = await api.get<DealHistoryData>(
        `/deals/repository/${d.id}/history?deal_type=${d.deal_type}`
      );
      setHistoryData(data);
    } catch {
      setHistoryData(null);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const closeHistory = useCallback(() => {
    setHistoryDealId(null);
    setHistoryData(null);
  }, []);

  const patchDeal = useCallback(async (dealId: number, dealType: DealType, payload: object) => {
    const { data } = await api.patch<DealRepositoryItem>(
      `/deals/repository/${dealId}?deal_type=${dealType}`,
      payload
    );
    setDeals(prev => prev.map(d => d.id === data.id && d.deal_type === data.deal_type ? data : d));
    return data;
  }, []);

  const handleEditSave = useCallback(async (payload: Partial<EditFields>) => {
    if (!editDeal) return;
    const wasRejected = editDeal.status === "rejected";
    await patchDeal(editDeal.id, editDeal.deal_type, payload);
    if (wasRejected) {
      await api.post(`/deals/repository/${editDeal.id}/resubmit?deal_type=${editDeal.deal_type}`);
      await fetchDeals();
    }
    setEditDeal(null);
  }, [editDeal, patchDeal, fetchDeals]);

  const handleIncentiveSave = useCallback(async (updatedData: Record<string, string>) => {
    if (!incentivePopup) return;
    const deal = deals.find(d => d.id === incentivePopup.dealId && d.deal_type === incentivePopup.dealType);
    if (!deal) return;
    const newIncentiveData = { ...(deal.incentive_data ?? {}), [incentivePopup.name]: updatedData };
    await patchDeal(incentivePopup.dealId, incentivePopup.dealType, { incentive_data: newIncentiveData });
  }, [incentivePopup, deals, patchDeal]);

  const handleInclExclSave = useCallback(async (updatedData: Record<string, string>) => {
    if (!inclExclPopup) return;
    const deal = deals.find(d => d.id === inclExclPopup.dealId && d.deal_type === inclExclPopup.dealType);
    if (!deal) return;
    const newInclExclData = { ...(deal.incl_excl_data ?? {}), [inclExclPopup.name]: updatedData };
    await patchDeal(inclExclPopup.dealId, inclExclPopup.dealType, { incl_excl_data: newInclExclData });
  }, [inclExclPopup, deals, patchDeal]);

  const handleDeleteDeal = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      await api.delete(`/deals/repository/${deleteTarget.id}?deal_type=${deleteTarget.deal_type}`);
      setDeals(prev => prev.filter(d => !(d.id === deleteTarget.id && d.deal_type === deleteTarget.deal_type)));
      setDeleteTarget(null);
    } catch {
      // keep state; user can retry
    } finally {
      setDeleteLoading(false);
    }
  }, [deleteTarget]);

  // ── filtered ──────────────────────────────────────────────────────────
  const filtered = deals.filter(d => {
    if (dealTypeFilter !== "all" && d.deal_type !== dealTypeFilter) return false;
    const q = search.toLowerCase();
    return !q ||
      d.source_agent.toLowerCase().includes(q) ||
      (d.airline_name ?? "").toLowerCase().includes(q) ||
      (d.deal_maker_name ?? "").toLowerCase().includes(q);
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated  = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // ── stat counts ───────────────────────────────────────────────────────
  const countPending   = deals.filter(d => d.status === "pending_approval" || d.status === "confirmed").length;
  const countAirline   = deals.filter(d => d.deal_type === "airline").length;
  const countB2B       = deals.filter(d => d.deal_type === "b2b").length;
  const countActive    = deals.filter(d => d.deal_lifecycle_status === "active").length;
  const countDraft     = deals.filter(d => !d.deal_lifecycle_status || d.deal_lifecycle_status === "draft").length;
  const countClosed    = deals.filter(d => d.deal_lifecycle_status === "closed").length;

  const TABLE_HEADERS = [
    "Deal No", "Deal Type", "Airline Name", "Airline Type", "Contract Year",
    "Valid From", "Valid To",
    "Trigger Type", "Payout Type",
    "Business Type", "Entity (LCC)",
    "Incentive Types", "Incl / Excl",
    "Deal Maker", "Approval Status", "Deal Status", "Actions",
  ];

  return (
    <div className="space-y-3">

      {/* ── Section tab bar ─────────────────────────────────────────────── */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <div className="flex min-w-max">
            {SECTION_TABS.map(tab => (
              <button key={tab} onClick={() => setSectionTab(tab)}
                className={`px-4 py-2.5 text-[11px] font-semibold whitespace-nowrap border-b-2 transition-colors ${
                  sectionTab === tab
                    ? "border-[#1e3a5f] text-[#1e3a5f] bg-blue-50/40"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                }`}>
                {tab}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Placeholder for other tabs ──────────────────────────────────── */}
      {sectionTab !== "Deal Repository" && (
        <div className="bg-white rounded-xl border border-gray-200 flex items-center justify-center py-20">
          <p className="text-sm text-gray-400 font-medium">{sectionTab} — Coming soon</p>
        </div>
      )}

      {sectionTab === "Deal Repository" && (
        <>
          {/* ── Header ──────────────────────────────────────────────────── */}
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-bold text-gray-900 uppercase tracking-wide">Deal Repository</h1>
              <p className="text-xs text-gray-500 mt-0.5">All deals — uploads, airline contracts and B2B agreements</p>
            </div>
            <div className="flex gap-2">
              <button onClick={fetchDeals} disabled={loading}
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50">
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              </button>
              <Link href="/deals/upload"
                className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-700 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50">
                <Upload className="w-3.5 h-3.5" /> Upload
              </Link>
              <Link href="/deals/new"
                className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#16304f]">
                <Plus className="w-3.5 h-3.5" /> Create Deal
              </Link>
            </div>
          </div>

          {/* ── Stats bar ───────────────────────────────────────────────── */}
          <div className="grid grid-cols-6 gap-2">
            {[
              { label: "Total",            value: deals.length,                           color: "bg-blue-50 text-blue-700 border-blue-200"       },
              { label: "Active",           value: countActive,                            color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
              { label: "Draft",            value: countDraft,                             color: "bg-gray-50 text-gray-600 border-gray-200"        },
              { label: "Closed",           value: countClosed,                            color: "bg-slate-100 text-slate-600 border-slate-300"    },
              { label: "Pending Approval", value: countPending,                           color: "bg-amber-50 text-amber-700 border-amber-200"     },
              { label: "Airline / B2B",    value: `${countAirline} / ${countB2B}`,        color: "bg-violet-50 text-violet-700 border-violet-200"  },
            ].map(s => (
              <div key={s.label} className={`rounded-xl border px-4 py-3 ${s.color}`}>
                <p className="text-xl font-bold">{s.value}</p>
                <p className="text-[11px] font-medium mt-0.5">{s.label}</p>
              </div>
            ))}
          </div>

          {/* ── Filters ─────────────────────────────────────────────────── */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
                placeholder="Search by airline, deal maker, agent..."
                className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
            </div>
            <select value={dealTypeFilter} onChange={e => { setDealTypeFilter(e.target.value as "all" | DealType); setPage(1); }}
              className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
              <option value="all">All Deal Types</option>
              <option value="airline">Airline</option>
              <option value="b2b">B2B</option>
            </select>
            <span className="text-[11px] text-gray-400 ml-auto whitespace-nowrap">
              {filtered.length} deal{filtered.length !== 1 ? "s" : ""}
            </span>
          </div>

          {/* ── Table ───────────────────────────────────────────────────── */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr style={{ background: "#1e3a5f" }}>
                    {TABLE_HEADERS.map(h => (
                      <th key={h} className="px-2 py-2 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <tr>
                      <td colSpan={TABLE_HEADERS.length} className="px-4 py-12 text-center text-xs text-gray-400">
                        <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
                        Loading deals...
                      </td>
                    </tr>
                  ) : apiError ? (
                    <tr>
                      <td colSpan={TABLE_HEADERS.length} className="px-4 py-12 text-center text-xs text-red-400">{apiError}</td>
                    </tr>
                  ) : paginated.length === 0 ? (
                    <tr>
                      <td colSpan={TABLE_HEADERS.length} className="px-4 py-12 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <Upload className="w-8 h-8 text-gray-300" />
                          <p className="text-xs text-gray-400 font-medium">No deals found</p>
                          <Link href="/deals/new"
                            className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#16304f]">
                            <Plus className="w-3 h-3" /> Create First Deal
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ) : paginated.map((d, idx) => {
                    const dtStyle = getDealTypeBadge(d);
                    return (
                      <tr key={`${d.deal_type}-${d.id}`}
                        className={`border-b border-gray-100 hover:bg-gray-50/60 transition-colors ${idx % 2 === 0 ? "bg-white" : "bg-gray-50/30"}`}>

                        {/* deal no */}
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          <span className="font-mono text-[10px] font-semibold text-gray-600 bg-gray-100 px-1.5 py-0.5 rounded border border-gray-200">
                            {d.deal_no}
                          </span>
                        </td>

                        {/* deal type */}
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          <span className={`px-2 py-0.5 rounded-full text-[9px] font-bold uppercase border ${dtStyle.cls}`}>
                            {dtStyle.label}
                          </span>
                        </td>

                        {/* airline name */}
                        <td className="px-2 py-1.5 min-w-32">
                          <p className="text-[11px] font-semibold text-gray-800 whitespace-nowrap">
                            {d.airline_name || <span className="text-gray-300">—</span>}
                          </p>
                        </td>

                        {/* airline type */}
                        <td className="px-2 py-1.5 min-w-20">
                          {d.airline_type ? (
                            <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${
                              d.airline_type === "LCC"
                                ? "bg-purple-50 text-purple-700 border-purple-200"
                                : "bg-sky-50 text-sky-700 border-sky-200"
                            }`}>{d.airline_type}</span>
                          ) : <span className="text-[11px] text-gray-300">—</span>}
                        </td>

                        {/* contract year */}
                        <td className="px-2 py-1.5 min-w-24">
                          <p className="text-[11px] text-gray-700 font-medium whitespace-nowrap">
                            {d.contract_year || <span className="text-gray-300">—</span>}
                          </p>
                        </td>

                        {/* valid from */}
                        <td className="px-2 py-1.5 min-w-24">
                          <p className="text-[11px] text-green-600 font-medium whitespace-nowrap">{formatDate(d.valid_from)}</p>
                        </td>

                        {/* valid to */}
                        <td className="px-2 py-1.5 min-w-24">
                          <p className="text-[11px] text-red-500 font-medium whitespace-nowrap">{formatDate(d.valid_to)}</p>
                        </td>

                        {/* trigger type */}
                        <td className="px-2 py-1.5 min-w-20">
                          <p className="text-[11px] text-gray-700 whitespace-nowrap">
                            {d.trigger_type || <span className="text-gray-300">—</span>}
                          </p>
                        </td>

                        {/* payout type */}
                        <td className="px-2 py-1.5 min-w-20">
                          <p className="text-[11px] text-gray-700 whitespace-nowrap">
                            {d.payout_type || <span className="text-gray-300">—</span>}
                          </p>
                        </td>

                        {/* business type */}
                        <td className="px-2 py-1.5 min-w-20">
                          {d.business_type ? (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-gray-100 text-gray-600 border border-gray-200">{d.business_type}</span>
                          ) : <span className="text-[11px] text-gray-300">—</span>}
                        </td>

                        {/* entity lcc */}
                        <td className="px-2 py-1.5 min-w-20">
                          <p className="text-[11px] text-gray-700 whitespace-nowrap">
                            {d.entity_lcc || <span className="text-gray-300">—</span>}
                          </p>
                        </td>

                        {/* incentive type pills */}
                        <td className="px-2 py-1.5 min-w-28">
                          {(d.incentive_types ?? []).length > 0 ? (
                            <div className="flex flex-wrap gap-0.5">
                              {(d.incentive_types ?? []).map(t => (
                                <button key={t}
                                  onClick={() => setIncentivePopup({ name: t, data: d.incentive_data?.[t] ?? {}, dealId: d.id, dealType: d.deal_type })}
                                  className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-50 text-blue-700 border border-blue-200 whitespace-nowrap hover:bg-blue-100 cursor-pointer transition-colors">
                                  {t}
                                </button>
                              ))}
                            </div>
                          ) : <span className="text-[11px] text-gray-300">—</span>}
                        </td>

                        {/* incl / excl pills */}
                        <td className="px-2 py-1.5 min-w-28">
                          {(d.incl_excl_types ?? []).length > 0 ? (
                            <div className="flex flex-wrap gap-0.5">
                              {(d.incl_excl_types ?? []).map(t => {
                                const isExcl = t.toLowerCase().includes("exclusion");
                                return (
                                  <button key={t}
                                    onClick={() => setInclExclPopup({ name: t, data: d.incl_excl_data?.[t] ?? {}, dealId: d.id, dealType: d.deal_type })}
                                    className={`px-1.5 py-0.5 rounded text-[9px] font-semibold border whitespace-nowrap cursor-pointer transition-colors ${
                                      isExcl
                                        ? "bg-red-50 text-red-600 border-red-200 hover:bg-red-100"
                                        : "bg-green-50 text-green-700 border-green-200 hover:bg-green-100"
                                    }`}>
                                    {t}
                                  </button>
                                );
                              })}
                            </div>
                          ) : <span className="text-[11px] text-gray-300">—</span>}
                        </td>

                        {/* deal maker */}
                        <td className="px-2 py-1.5 min-w-28">
                          <p className="text-[11px] font-medium text-gray-700 whitespace-nowrap">
                            {d.deal_maker_name || d.source_agent}
                          </p>
                        </td>

                        {/* approval status */}
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${STATUS_STYLE[d.status] ?? "bg-gray-50 text-gray-500 border-gray-200"}`}>
                            <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[d.status] ?? "bg-gray-400"}`} />
                            {STATUS_LABEL[d.status] ?? d.status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                          </span>
                        </td>

                        {/* deal lifecycle status */}
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          {(() => {
                            const ls = d.deal_lifecycle_status ?? "draft";
                            return (
                              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${LIFECYCLE_STYLE[ls] ?? LIFECYCLE_STYLE.draft}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${LIFECYCLE_DOT[ls] ?? LIFECYCLE_DOT.draft}`} />
                                {LIFECYCLE_LABEL[ls] ?? ls}
                              </span>
                            );
                          })()}
                        </td>

                        {/* actions */}
                        <td className="px-2 py-1.5 whitespace-nowrap">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => openHistory(d)}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors">
                              <Clock className="w-3 h-3" /> History
                            </button>
                            <button
                              onClick={() => (d.status === "approved" || d.status === "rejected") && setEditDeal(d)}
                              disabled={d.status !== "approved" && d.status !== "rejected"}
                              title={
                                d.status === "rejected" ? "Edit and resubmit for approval" :
                                d.status !== "approved" ? "Only approved or rejected deals can be edited" :
                                undefined
                              }
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                              {d.status === "rejected"
                                ? <><RefreshCw className="w-3 h-3" /> Edit &amp; Resubmit</>
                                : <><Pencil className="w-3 h-3" /> Edit</>
                              }
                            </button>
                            <button
                              onClick={() => d.status === "approved" && setDeleteTarget(d)}
                              disabled={d.status !== "approved"}
                              title={d.status !== "approved" ? "Only approved deals can be deleted" : undefined}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-red-200 text-red-500 hover:bg-red-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                              <Trash2 className="w-3 h-3" /> Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* pagination */}
            {totalPages > 1 && (
              <div className="px-4 py-2.5 border-t border-gray-100 flex items-center justify-between">
                <p className="text-[10px] text-gray-400">
                  {Math.min((page-1)*PAGE_SIZE+1, filtered.length)}–{Math.min(page*PAGE_SIZE, filtered.length)} of{" "}
                  <span className="font-semibold text-gray-600">{filtered.length}</span>
                </p>
                <div className="flex items-center gap-1">
                  <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}
                    className="px-2.5 py-1 rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40">
                    Previous
                  </button>
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => (
                    <button key={p} onClick={() => setPage(p)}
                      className={`w-6 h-6 rounded-full text-[11px] font-medium border ${
                        p === page ? "bg-[#1e3a5f] text-white border-[#1e3a5f]" : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
                      }`}>{p}</button>
                  ))}
                  <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page === totalPages}
                    className="px-2.5 py-1 rounded border border-gray-200 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40">
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Deal History Slide-over ──────────────────────────────────────── */}
      {historyDealId !== null && (
        <DealHistoryPanel
          dealId={historyDealId}
          dealType={historyDealType}
          displayLabel={historyLabel}
          data={historyData}
          loading={historyLoading}
          onClose={closeHistory}
        />
      )}

      {/* ── Deal Edit Slide-over ─────────────────────────────────────────── */}
      {editDeal && (
        <DealEditPanel
          deal={editDeal}
          onSave={handleEditSave}
          onClose={() => setEditDeal(null)}
        />
      )}

      {/* ── Incentive edit popup ─────────────────────────────────────────── */}
      {incentivePopup && (
        <IncentiveEditModal
          name={incentivePopup.name}
          data={incentivePopup.data}
          onSave={handleIncentiveSave}
          onClose={() => setIncentivePopup(null)}
        />
      )}

      {/* ── Incl / Excl edit popup ───────────────────────────────────────── */}
      {inclExclPopup && (
        <InclExclEditModal
          name={inclExclPopup.name}
          data={inclExclPopup.data}
          onSave={handleInclExclSave}
          onClose={() => setInclExclPopup(null)}
        />
      )}

      {/* ── Delete Confirm Modal ─────────────────────────────────────────── */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-red-500" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-gray-800">Delete Deal</h3>
                <p className="text-xs text-gray-500 mt-0.5">This action cannot be undone.</p>
              </div>
            </div>
            <p className="text-xs text-gray-600 mb-6">
              Are you sure you want to delete deal{" "}
              <span className="font-semibold text-gray-800">
                {deleteTarget.airline_name || deleteTarget.deal_no || `#${deleteTarget.id}`}
              </span>?
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleteLoading}
                className="px-4 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50">
                Cancel
              </button>
              <button
                onClick={handleDeleteDeal}
                disabled={deleteLoading}
                className="px-4 py-1.5 rounded-lg bg-red-500 text-white text-xs font-medium hover:bg-red-600 transition-colors disabled:opacity-50 flex items-center gap-1.5">
                {deleteLoading ? (
                  <><RefreshCw className="w-3 h-3 animate-spin" /> Deleting…</>
                ) : (
                  <><Trash2 className="w-3 h-3" /> Delete</>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
