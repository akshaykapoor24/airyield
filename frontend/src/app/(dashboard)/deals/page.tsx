"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Upload, Search, RefreshCw, X, CheckCircle, XCircle, AlertCircle, MinusCircle, User, Save, Trash2, FileText, FileSpreadsheet, ChevronRight, Building2, Calendar, Hash, History, Pencil, Plane, List } from "lucide-react";
import api from "@/lib/api";
import { IncentiveTabContent, InclExclTabContent, IEFieldValue, CONTINENTS, COUNTRY_GROUPS, IncentiveRulesModal } from "@/components/deals/IncentiveInclExclShared";

// ── types ── batch ─────────────────────────────────────────────────────────
type DealBatch = {
  batch_id:         string;
  deal_type:        string;
  deal_tag:         string;
  supplier_name:    string | null;
  file_name:        string | null;
  file_type:        string | null;
  incentive_types:  string[];
  valid_from:       string | null;
  valid_to:         string | null;
  deal_count:       number;
  lifecycle_counts: Record<string, number>;
  created_by_name:  string | null;
  created_at:       string;
};

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
type DealType = "upload" | "airline" | "b2b" | "unified";

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
  incl_excl_data:  Record<string, unknown> | null;
  deal_tag:              string | null;
  status:                string;
  deal_lifecycle_status: string | null;
  created_at:            string;
  file_type:             string | null;
  batch_id:              string | null;
  supplier_name:         string | null;
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

const ALL_RULE_TYPES = ["Inclusion For Trigger", "Exclusion For Trigger", "Inclusion For Payout", "Exclusion For Payout"] as const;
type RuleType = typeof ALL_RULE_TYPES[number];

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
  airline: { label: "Airline",     cls: "bg-sky-50 text-sky-700 border-sky-200"         },
  b2b:     { label: "B2B",         cls: "bg-violet-50 text-violet-700 border-violet-200" },
  upload:  { label: "Upload",      cls: "bg-teal-50 text-teal-700 border-teal-200"       },
  unified: { label: "Airline/B2B", cls: "bg-indigo-50 text-indigo-700 border-indigo-200" },
};

function getDealTypeBadge(d: DealRepositoryItem) {
  if (d.deal_type === "unified") {
    // The deal KIND (B2B vs Airline) is encoded in the deal_no prefix the backend
    // builds from Deal.deal_type — the same signal the statement view shows. Don't
    // use business_type (B2B/B2C/B2E/MICE), which is optional and may be empty on a
    // B2B-kind deal, otherwise the badge disagrees with the statement.
    const isB2b = d.deal_no?.startsWith("B2B") ?? !!d.business_type;
    return isB2b ? DEAL_TYPE_STYLE.b2b : DEAL_TYPE_STYLE.airline;
  }
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

// ── normalizeIncentiveEntry ────────────────────────────────────────────────
// Converts raw incentive_data entry (which may contain legacy `slabs[]` arrays
// from uploaded/airline deals) into the flat Record<string,string> that
// IncentiveTabContent expects (amountSlabs/segmentSlabs as JSON strings).
function normalizeIncentiveEntry(raw: Record<string, unknown>): Record<string, string> {
  const form: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (k === "slabs") continue;
    if (v !== null && v !== undefined && !Array.isArray(v) && typeof v !== "object") {
      form[k] = String(v);
    }
  }
  // Deals carry slabs as a single SlabRow[] under the "slabs" key. Convert to the
  // amountSlabs / segmentSlabs / siSlabs JSON strings the SlabGrid renders, routing
  // by slabType so Segment Incentive rows are not misrouted and dropped on save.
  const slabs = raw["slabs"] as Array<Record<string, unknown>> | undefined;
  if (slabs && slabs.length > 0) {
    const groups: Record<string, Record<string, string>[]> = { amount: [], segment: [], si: [] };
    slabs.forEach((s, i) => {
      const row: Record<string, string> = { id: `r${i}` };
      if (s.quarterlyFreq)        row.quarterlyFreq    = String(s.quarterlyFreq);
      if (s.halfYearlyFreq)       row.halfYearlyFreq   = String(s.halfYearlyFreq);
      if (s.baseTargetAmtNumPct)  row.baseTargetNumPct = String(s.baseTargetAmtNumPct);
      if (s.baseTargetAmount)     row.baseTargetAmount = String(s.baseTargetAmount);
      if (s.targetFrom)           row.targetFrom       = String(s.targetFrom);
      if (s.targetTo)             row.targetTo         = String(s.targetTo);
      if (s.segment)              row.segment          = String(s.segment);
      if (s.class)                row.class            = String(s.class);
      for (const [vk, vv] of Object.entries((s.values as Record<string, unknown>) ?? {})) {
        row[vk] = vv != null ? String(vv) : "";
      }
      const st = String(s.slabType ?? "amount").toLowerCase();
      (groups[st] ?? groups.amount).push(row);
    });
    if (groups.amount.length && !form.amountSlabs)   form.amountSlabs = JSON.stringify(groups.amount);
    if (groups.segment.length && !form.segmentSlabs) form.segmentSlabs = JSON.stringify(groups.segment);
    if (groups.si.length && !form.siSlabs)           form.siSlabs = JSON.stringify(groups.si);
  }
  return form;
}

// ── IncentiveEditModal ─────────────────────────────────────────────────────
function IncentiveEditModal({ name, data, onSave, onClose }: {
  name: string;
  data: Record<string, string>;
  onSave: (updated: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const [formData, setFormData] = useState<Record<string, string>>({ ...data });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try { await onSave(formData); onClose(); }
    finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{name}</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">Edit incentive details · changes are saved to the deal</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>
        <div className="overflow-y-auto flex-1">
          <IncentiveTabContent
            name={name}
            data={formData}
            onChange={(k, v) => setFormData(prev => ({ ...prev, [k]: v }))}
          />
        </div>
        <div className="px-5 pb-4 pt-3 border-t border-gray-100 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save Changes"}
          </button>
          <button onClick={onClose} className="flex-1 border border-gray-200 rounded-lg py-2 text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ── InclExclEditModal ──────────────────────────────────────────────────────
function InclExclEditModal({ rawData, dealType, incentiveTypes, initialRuleType, onSave, onClose }: {
  rawData: Record<string, unknown>;
  dealType: DealType;
  incentiveTypes: string[];
  initialRuleType?: RuleType;
  onSave: (updated: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const isPerIncentive = dealType === "unified" && incentiveTypes.length > 0;

  const [forms, setForms] = useState<Record<string, Record<string, Record<string, IEFieldValue>>>>(() => {
    if (isPerIncentive) {
      const init: Record<string, Record<string, Record<string, IEFieldValue>>> = {};
      for (const incType of incentiveTypes) {
        const incData = (rawData[incType] ?? {}) as Record<string, Record<string, IEFieldValue>>;
        init[incType] = {};
        for (const rt of ALL_RULE_TYPES) {
          init[incType][rt] = { ...(incData[rt] ?? {}) };
        }
      }
      return init;
    } else {
      const flatData = rawData as Record<string, Record<string, IEFieldValue>>;
      const init: Record<string, Record<string, Record<string, IEFieldValue>>> = { "": {} };
      for (const rt of ALL_RULE_TYPES) {
        init[""][rt] = { ...(flatData[rt] ?? {}) };
      }
      return init;
    }
  });

  const [activeIncType, setActiveIncType] = useState<string>(isPerIncentive ? (incentiveTypes[0] ?? "") : "");
  const [activeRuleType, setActiveRuleType] = useState<RuleType>(initialRuleType ?? "Inclusion For Payout");
  const [continentOptions, setContinentOptions] = useState<string[]>(CONTINENTS);
  const [countryGroupOptions, setCountryGroupOptions] = useState<string[]>(COUNTRY_GROUPS);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<{ continents: string[]; country_groups: string[] }>("/airports/options")
      .then(r => {
        if (r.data.continents?.length) setContinentOptions(r.data.continents);
        if (r.data.country_groups?.length) setCountryGroupOptions(r.data.country_groups);
      }).catch(() => {});
  }, []);

  const formKey = isPerIncentive ? activeIncType : "";
  const currentForm = forms[formKey]?.[activeRuleType] ?? {};

  const handleFormChange = (k: string, v: IEFieldValue) => {
    setForms(prev => ({
      ...prev,
      [formKey]: {
        ...(prev[formKey] ?? {}),
        [activeRuleType]: { ...(prev[formKey]?.[activeRuleType] ?? {}), [k]: v },
      },
    }));
  };

  const handleClear = () => {
    setForms(prev => ({
      ...prev,
      [formKey]: { ...(prev[formKey] ?? {}), [activeRuleType]: {} },
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      let updated: Record<string, unknown>;
      if (isPerIncentive) {
        updated = {};
        for (const incType of incentiveTypes) {
          updated[incType] = forms[incType] ?? {};
        }
      } else {
        updated = { ...(forms[""] ?? {}) };
      }
      await onSave(updated);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const isExcl = activeRuleType.toLowerCase().includes("exclusion");
  const suffix = isExcl ? "for Exclusion" : "for Inclusion";
  const viceVersa = currentForm["viceVersa"] === "true";
  const handleViceVersa = () => handleFormChange("viceVersa", viceVersa ? "" : "true");

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Inclusions &amp; Exclusions</h2>
            <p className="text-[10px] text-gray-400 mt-0.5">
              {isPerIncentive ? "Per incentive type — select incentive then rule type" : "All fields support multiple values."}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg"><X className="w-4 h-4 text-gray-500" /></button>
        </div>

        {isPerIncentive && incentiveTypes.length > 1 && (
          <div className="flex gap-1 px-5 pt-3 pb-0">
            {incentiveTypes.map(t => (
              <button key={t} type="button" onClick={() => setActiveIncType(t)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${activeIncType === t ? "bg-[#1e3a5f] text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200"}`}>
                {t}
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between border-b border-gray-100 px-5 mt-1">
          <div className="flex">
            {ALL_RULE_TYPES.map(rt => (
              <button key={rt} type="button" onClick={() => setActiveRuleType(rt)}
                className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-colors whitespace-nowrap ${activeRuleType === rt ? "border-[#1e3a5f] text-[#1e3a5f]" : "border-transparent text-gray-400 hover:text-gray-600"}`}>
                {rt}
              </button>
            ))}
          </div>
          <button type="button" onClick={handleClear}
            className="flex items-center gap-1 text-[11px] font-medium text-red-500 hover:text-red-700 hover:bg-red-50 px-2.5 py-1 rounded-md transition-colors">
            <X className="w-3 h-3" />Clear
          </button>
        </div>

        <div className="overflow-y-auto flex-1">
          <InclExclTabContent
            key={`${formKey}:${activeRuleType}`}
            suffix={suffix}
            isExclusion={isExcl}
            data={currentForm}
            onChange={handleFormChange}
            viceVersa={viceVersa}
            onViceVersa={handleViceVersa}
            continentOptions={continentOptions}
            countryGroupOptions={countryGroupOptions}
          />
        </div>

        <div className="px-5 pb-4 pt-3 border-t border-gray-100 flex gap-2">
          <button onClick={handleSave} disabled={saving}
            className="flex-1 flex items-center justify-center gap-1.5 bg-[#1e3a5f] text-white rounded-lg py-2 text-sm font-medium hover:bg-[#16304f] disabled:opacity-50">
            <Save className="w-3.5 h-3.5" />{saving ? "Saving..." : "Save Changes"}
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

// ── DealFlatTable ──────────────────────────────────────────────────────────
// Shared row rendering for the "All Deal" and "Airline Wise" repository views.
function DealFlatTable({ deals, showAirlineCol = true, onOpenHistory, onEdit, onDelete, onOpenIncentiveRules }: {
  deals: DealRepositoryItem[];
  showAirlineCol?: boolean;
  onOpenHistory: (d: DealRepositoryItem) => void;
  onEdit: (d: DealRepositoryItem) => void;
  onDelete: (d: DealRepositoryItem) => void;
  onOpenIncentiveRules: (d: DealRepositoryItem, name: string) => void;
}) {
  if (deals.length === 0) {
    return <p className="px-4 py-10 text-center text-xs text-gray-400">No deals match the filters.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr style={{ background: "#1e3a5f" }}>
            <th className="px-4 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Deal No</th>
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Deal Type</th>
            {showAirlineCol && (
              <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Airline / Maker</th>
            )}
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Valid Period</th>
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Incentive &amp; Rules</th>
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Approval Status</th>
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Deal Status</th>
            <th className="px-3 py-2.5 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {deals.map(d => {
            const dtStyle = getDealTypeBadge(d);
            const canEdit = d.status === "approved" || d.status === "rejected";
            return (
              <tr key={`${d.deal_type}-${d.id}`} className="hover:bg-blue-50/30 transition-colors">
                <td className="px-4 py-2.5 text-xs font-semibold text-gray-800 whitespace-nowrap">{d.deal_no}</td>
                <td className="px-3 py-2.5">
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border whitespace-nowrap ${dtStyle.cls}`}>
                    {dtStyle.label}
                  </span>
                </td>
                {showAirlineCol && (
                  <td className="px-3 py-2.5 text-xs text-gray-700 max-w-[160px] truncate" title={d.airline_name ?? d.deal_maker_name ?? undefined}>
                    {d.airline_name || d.deal_maker_name || d.supplier_name || "—"}
                  </td>
                )}
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <span className="text-xs text-gray-700">{formatDate(d.valid_from)}</span>
                  <span className="text-gray-400 mx-1">→</span>
                  <span className="text-xs text-gray-700">{formatDate(d.valid_to)}</span>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap gap-0.5 max-w-[220px]">
                    {(d.incentive_types ?? []).length > 0
                      ? d.incentive_types!.map(t => (
                          <button key={t} onClick={() => onOpenIncentiveRules(d, t)} title="Edit incentive details & inclusion/exclusion rules"
                            className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 whitespace-nowrap">
                            {t}
                          </button>
                        ))
                      : <span className="text-xs text-gray-400">—</span>}
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${STATUS_STYLE[d.status] ?? "bg-gray-50 text-gray-500 border-gray-200"}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[d.status] ?? "bg-gray-400"}`} />
                    {STATUS_LABEL[d.status] ?? d.status}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${LIFECYCLE_STYLE[d.deal_lifecycle_status ?? "draft"] ?? LIFECYCLE_STYLE.draft}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${LIFECYCLE_DOT[d.deal_lifecycle_status ?? "draft"] ?? LIFECYCLE_DOT.draft}`} />
                    {LIFECYCLE_LABEL[d.deal_lifecycle_status ?? "draft"] ?? "Draft"}
                  </span>
                </td>
                <td className="px-2 py-2.5 whitespace-nowrap">
                  <div className="flex items-center gap-1">
                    <button onClick={() => onOpenHistory(d)}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-gray-200 text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors">
                      <History className="w-3 h-3" /> History
                    </button>
                    <button
                      onClick={() => canEdit && onEdit(d)}
                      disabled={!canEdit || d.deal_lifecycle_status === "closed"}
                      title={d.status === "rejected" ? "Edit and resubmit for approval" : !canEdit ? "Only approved or rejected deals can be edited" : undefined}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent">
                      {d.status === "rejected"
                        ? <><RefreshCw className="w-3 h-3" /> Edit &amp; Resubmit</>
                        : <><Pencil className="w-3 h-3" /> Edit</>}
                    </button>
                    <button
                      onClick={() => d.status === "approved" && onDelete(d)}
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
  );
}

// ── main page ──────────────────────────────────────────────────────────────
export default function DealsPage() {
  const router = useRouter();
  const [sectionTab, setSectionTab] = useState("Deal Repository");
  const [deals,      setDeals]      = useState<DealRepositoryItem[]>([]);
  const [batches,    setBatches]    = useState<DealBatch[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [apiError,   setApiError]   = useState("");
  const [search,     setSearch]     = useState("");
  const [dealTypeFilter, setDealTypeFilter] = useState<"all" | DealType>("all");
  const [page,       setPage]       = useState(1);
  const [repoView,   setRepoView]   = useState<"statement" | "airline" | "all">("statement"); // default to first tab

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

  // combined incentive + incl/excl edit popup
  const [incentiveRulesPopup, setIncentiveRulesPopup] = useState<{
    deal: DealRepositoryItem; initialIncType?: string;
  } | null>(null);

  const fetchDeals = useCallback(async () => {
    setLoading(true);
    setApiError("");
    try {
      const [batchRes, dealRes] = await Promise.all([
        api.get<DealBatch[]>("/deals/batches"),
        api.get<DealRepositoryItem[]>("/deals/repository"),
      ]);
      setBatches(batchRes.data);
      setDeals(dealRes.data);
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

  const handleIncentiveRulesSave = useCallback(async (
    incData: Record<string, Record<string, string>>,
    ieData: Record<string, Record<string, Record<string, IEFieldValue>>>,
  ) => {
    if (!incentiveRulesPopup) return;
    const { deal } = incentiveRulesPopup;
    // One PATCH writes both incentive payout data and per-incentive incl/excl rules.
    await patchDeal(deal.id, deal.deal_type, { incentive_data: incData, incl_excl_data: ieData });
  }, [incentiveRulesPopup, patchDeal]);

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

  const openIncentiveRules = useCallback((d: DealRepositoryItem, name: string) => {
    setIncentiveRulesPopup({ deal: d, initialIncType: name });
  }, []);

  // ── stat counts ───────────────────────────────────────────────────────
  const totalDeals     = batches.reduce((s, b) => s + b.deal_count, 0);
  const countAirline   = batches.filter(b => b.deal_type === "airline").reduce((s, b) => s + b.deal_count, 0);
  const countB2B       = batches.filter(b => b.deal_type === "b2b").reduce((s, b) => s + b.deal_count, 0);
  const countPending   = deals.filter(d => d.status === "pending_approval" || d.status === "confirmed").length;
  const countActive    = deals.filter(d => d.deal_lifecycle_status === "active").length;
  // ── filtered batches ──────────────────────────────────────────────────
  const filteredBatches = batches.filter(b => {
    if (dealTypeFilter !== "all" && b.deal_type !== dealTypeFilter) return false;
    const q = search.toLowerCase();
    return !q ||
      (b.supplier_name ?? "").toLowerCase().includes(q) ||
      (b.file_name     ?? "").toLowerCase().includes(q) ||
      (b.created_by_name ?? "").toLowerCase().includes(q);
  });

  // ── filtered deals (All Deal + Airline Wise views) ─────────────────────
  const filteredDeals = useMemo(() => deals.filter(d => {
    if (dealTypeFilter !== "all") {
      const dType = d.deal_type === "unified" ? (d.business_type ? "b2b" : "airline") : d.deal_type;
      if (dType !== dealTypeFilter) return false;
    }
    const q = search.toLowerCase();
    return !q ||
      (d.airline_name     ?? "").toLowerCase().includes(q) ||
      (d.deal_maker_name   ?? "").toLowerCase().includes(q) ||
      (d.supplier_name     ?? "").toLowerCase().includes(q) ||
      d.deal_no.toLowerCase().includes(q);
  }), [deals, dealTypeFilter, search]);

  const dealsByAirline = useMemo(() => {
    const map = new Map<string, DealRepositoryItem[]>();
    for (const d of filteredDeals) {
      const key = d.airline_name || "Unspecified Airline";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(d);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredDeals]);

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

          {/* ── Repository view switcher ──────────────────────────────────── */}
          <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-xl p-1 w-fit">
            {([
              { key: "statement", label: "Statement/Agency Wise", icon: Building2 },
              { key: "airline",   label: "Airline Wise",          icon: Plane },
              { key: "all",       label: "All Deals",             icon: List },
            ] as const).map(v => (
              <button key={v.key} onClick={() => setRepoView(v.key)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                  repoView === v.key ? "bg-[#1e3a5f] text-white" : "text-gray-500 hover:bg-gray-50"
                }`}>
                <v.icon className="w-3.5 h-3.5" /> {v.label}
              </button>
            ))}
          </div>

          {/* ── Stats bar ───────────────────────────────────────────────── */}
          <div className="grid grid-cols-6 gap-2">
            {[
              { label: "Total Batches",    value: batches.length,                         color: "bg-blue-50 text-blue-700 border-blue-200"       },
              { label: "Total Deals",      value: totalDeals,                             color: "bg-indigo-50 text-indigo-700 border-indigo-200"  },
              { label: "Airline Deals",    value: countAirline,                           color: "bg-sky-50 text-sky-700 border-sky-200"           },
              { label: "B2B Deals",        value: countB2B,                               color: "bg-violet-50 text-violet-700 border-violet-200"  },
              { label: "Active",           value: countActive,                            color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
              { label: "Pending Approval", value: countPending,                           color: "bg-amber-50 text-amber-700 border-amber-200"     },
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
                placeholder={repoView === "statement" ? "Search by supplier, file name, uploaded by..." : "Search by deal no, airline, deal maker..."}
                className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
            </div>
            <select value={dealTypeFilter} onChange={e => { setDealTypeFilter(e.target.value as "all" | DealType); setPage(1); }}
              className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs text-gray-700 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400">
              <option value="all">All Deal Types</option>
              <option value="airline">Airline</option>
              <option value="b2b">B2B</option>
            </select>
            <span className="text-[11px] text-gray-400 ml-auto whitespace-nowrap">
              {repoView === "statement"
                ? `${filteredBatches.length} batch${filteredBatches.length !== 1 ? "es" : ""}`
                : `${filteredDeals.length} deal${filteredDeals.length !== 1 ? "s" : ""}`}
            </span>
          </div>

          {/* ── Statement/Agency Wise: batch list table ────────────────────── */}
          {repoView === "statement" && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden overflow-x-auto">
            {/* summary bar */}
            <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                {filteredBatches.length === batches.length
                  ? `${batches.length} Batch${batches.length !== 1 ? "es" : ""}`
                  : `${filteredBatches.length} of ${batches.length} Batches`}
              </p>
              <p className="text-xs text-gray-400">Click a row to view deals</p>
            </div>

            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Supplier / Source</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Deal Type</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Deal Tag</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Incentive Types</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center gap-1"><Calendar className="w-3.5 h-3.5" /> Valid Period</span>
                  </th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">File</th>
                  <th className="px-3 py-3 text-center text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center justify-center gap-1"><Hash className="w-3 h-3" /> Deals</span>
                  </th>
                  <th className="px-3 py-3 text-center text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Draft</th>
                  <th className="px-3 py-3 text-center text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Active</th>
                  <th className="px-3 py-3 text-center text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Closed</th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">
                    <span className="flex items-center gap-1"><User className="w-3.5 h-3.5" /> Uploaded By</span>
                  </th>
                  <th className="px-3 py-3 text-left text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap">Date</th>
                  <th className="px-2 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td colSpan={13} className="px-4 py-12 text-center text-xs text-gray-400">
                      <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" />
                      Loading batches...
                    </td>
                  </tr>
                ) : apiError ? (
                  <tr>
                    <td colSpan={13} className="px-4 py-10 text-center text-xs text-red-400">{apiError}</td>
                  </tr>
                ) : filteredBatches.length === 0 ? (
                  <tr>
                    <td colSpan={13} className="px-4 py-12 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <Upload className="w-8 h-8 text-gray-300" />
                        <p className="text-xs text-gray-400 font-medium">
                          {batches.length === 0 ? "No deal batches yet" : "No batches match the filters"}
                        </p>
                        {batches.length === 0 && (
                          <Link href="/deals/upload"
                            className="flex items-center gap-1.5 bg-[#1e3a5f] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#16304f]">
                            <Upload className="w-3 h-3" /> Upload First Deal
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                ) : filteredBatches.map(b => {
                  const dtStyle = DEAL_TYPE_STYLE[b.deal_type] ?? DEAL_TYPE_STYLE.airline;
                  const FileIcon = b.file_type === "pdf" ? FileText : FileSpreadsheet;
                  return (
                    <tr
                      key={b.batch_id}
                      onClick={() => router.push(`/deals/${b.batch_id}`)}
                      className="hover:bg-blue-50/40 cursor-pointer transition-colors group"
                    >
                      {/* Supplier */}
                      <td className="px-4 py-3 max-w-[160px]">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-blue-50 flex items-center justify-center shrink-0">
                            <Building2 className="w-3.5 h-3.5 text-blue-500" />
                          </div>
                          <p className="text-xs font-semibold text-gray-800 group-hover:text-[#1e3a5f] leading-tight truncate" title={b.supplier_name ?? undefined}>
                            {b.supplier_name || "—"}
                          </p>
                        </div>
                      </td>

                      {/* Deal type */}
                      <td className="px-3 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase border whitespace-nowrap ${dtStyle.cls}`}>
                          {dtStyle.label}
                        </span>
                      </td>

                      {/* Deal tag */}
                      <td className="px-3 py-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${(b.deal_tag||"standard")==="adhoc"?"bg-amber-50 text-amber-700 border-amber-200":"bg-slate-50 text-slate-600 border-slate-200"}`}>
                          {(b.deal_tag||"standard")==="adhoc"?"Adhoc":"Standard"}
                        </span>
                      </td>

                      {/* Incentive types */}
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-0.5">
                          {(b.incentive_types ?? []).length > 0
                            ? b.incentive_types.map(t => (
                                <span key={t} className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-blue-50 text-blue-700 border border-blue-200 whitespace-nowrap">{t}</span>
                              ))
                            : <span className="text-xs text-gray-400">—</span>
                          }
                        </div>
                      </td>

                      {/* Valid period */}
                      <td className="px-3 py-3 whitespace-nowrap">
                        <span className="text-xs font-medium text-gray-700">{formatDate(b.valid_from)}</span>
                        <span className="text-gray-400 mx-1">→</span>
                        <span className="text-xs font-medium text-gray-700">{formatDate(b.valid_to)}</span>
                      </td>

                      {/* File */}
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1.5">
                          <FileIcon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                          <span className="text-xs text-gray-500 truncate max-w-36 block" title={b.file_name ?? undefined}>
                            {b.file_name || "—"}
                          </span>
                        </div>
                      </td>

                      {/* Total deal count */}
                      <td className="px-3 py-3 text-center">
                        <span className="inline-flex items-center justify-center w-9 h-7 rounded-full bg-[#1e3a5f]/10 text-[#1e3a5f] text-xs font-semibold">
                          {b.deal_count}
                        </span>
                      </td>

                      {/* Draft */}
                      <td className="px-3 py-3 text-center text-xs font-semibold text-gray-400">
                        {b.lifecycle_counts?.["draft"] ?? 0}
                      </td>

                      {/* Active */}
                      <td className="px-3 py-3 text-center text-xs font-semibold text-emerald-600">
                        {b.lifecycle_counts?.["active"] ?? 0}
                      </td>

                      {/* Closed */}
                      <td className="px-3 py-3 text-center text-xs font-semibold text-slate-400">
                        {b.lifecycle_counts?.["closed"] ?? 0}
                      </td>

                      {/* Uploaded by */}
                      <td className="px-3 py-3 text-xs text-gray-600 font-medium max-w-[120px]">
                        <span className="truncate block" title={b.created_by_name ?? undefined}>
                          {b.created_by_name || "—"}
                        </span>
                      </td>

                      {/* Date */}
                      <td className="px-3 py-3 text-xs text-gray-500 whitespace-nowrap">
                        {formatDate(b.created_at)}
                      </td>

                      {/* Arrow */}
                      <td className="px-2 py-3 text-right">
                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-[#1e3a5f] transition-colors inline" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}

          {/* ── All Deal: flat per-deal table ───────────────────────────────── */}
          {repoView === "all" && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/40">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  {loading ? "Loading deals..." : `${filteredDeals.length} Deal${filteredDeals.length !== 1 ? "s" : ""}`}
                </p>
              </div>
              {loading ? (
                <div className="px-4 py-12 text-center text-xs text-gray-400">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading deals...
                </div>
              ) : apiError ? (
                <p className="px-4 py-10 text-center text-xs text-red-400">{apiError}</p>
              ) : (
                <DealFlatTable
                  deals={filteredDeals}
                  onOpenHistory={openHistory}
                  onEdit={setEditDeal}
                  onDelete={setDeleteTarget}
                  onOpenIncentiveRules={openIncentiveRules}
                />
              )}
            </div>
          )}

          {/* ── Airline Wise: deals grouped by airline ──────────────────────── */}
          {repoView === "airline" && (
            <div className="space-y-3">
              {loading ? (
                <div className="bg-white rounded-xl border border-gray-200 px-4 py-12 text-center text-xs text-gray-400">
                  <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading deals...
                </div>
              ) : apiError ? (
                <div className="bg-white rounded-xl border border-gray-200 px-4 py-10 text-center text-xs text-red-400">{apiError}</div>
              ) : dealsByAirline.length === 0 ? (
                <div className="bg-white rounded-xl border border-gray-200 px-4 py-10 text-center text-xs text-gray-400">No deals match the filters.</div>
              ) : (
                dealsByAirline.map(([airline, airlineDeals]) => (
                  <details key={airline} open className="bg-white rounded-xl border border-gray-200 overflow-hidden group">
                    <summary className="px-5 py-3 border-b border-gray-100 bg-gray-50/40 flex items-center gap-2 cursor-pointer list-none">
                      <Plane className="w-3.5 h-3.5 text-blue-500" />
                      <p className="text-xs font-semibold text-gray-700">{airline}</p>
                      <span className="ml-auto inline-flex items-center justify-center px-2 py-0.5 rounded-full bg-[#1e3a5f]/10 text-[#1e3a5f] text-[11px] font-semibold">
                        {airlineDeals.length} deal{airlineDeals.length !== 1 ? "s" : ""}
                      </span>
                    </summary>
                    <DealFlatTable
                      deals={airlineDeals}
                      showAirlineCol={false}
                      onOpenHistory={openHistory}
                      onEdit={setEditDeal}
                      onDelete={setDeleteTarget}
                      onOpenIncentiveRules={openIncentiveRules}
                    />
                  </details>
                ))
              )}
            </div>
          )}
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

      {/* ── Combined Incentive + Incl/Excl edit popup ────────────────────── */}
      {incentiveRulesPopup && (
        <IncentiveRulesModal
          incentiveTypes={incentiveRulesPopup.deal.incentive_types ?? []}
          incentiveData={(incentiveRulesPopup.deal.incentive_data ?? {}) as Record<string, Record<string, unknown>>}
          inclExclData={(incentiveRulesPopup.deal.incl_excl_data ?? {}) as Record<string, Record<string, Record<string, IEFieldValue>>>}
          initialIncType={incentiveRulesPopup.initialIncType}
          onSave={handleIncentiveRulesSave}
          onClose={() => setIncentiveRulesPopup(null)}
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
