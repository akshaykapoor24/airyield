"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, XCircle, RefreshCw, AlertCircle, MinusCircle, User, Eye, X } from "lucide-react";
import api from "@/lib/api";

type InboxDeal = {
  id:              number;       // DealApproval.id — routing key for approve/reject/bulk-approve
  deal_id:         number;       // actual deal ID in its table — for history lookup
  deal_type:       string;       // 'upload' | 'airline' | 'b2b'
  source_agent:    string;
  airline_name:    string | null;
  airline_type:    string | null;
  status:          string;
  created_at:      string;
  valid_from:      string | null;
  valid_to:        string | null;
  business_type:   string | null;
  incentive_types: string[] | null;
  incentive_data:  Record<string, Record<string, string>> | null;
  incl_excl_types: string[] | null;
  incl_excl_data:  Record<string, Record<string, string>> | null;
  deal_maker_name: string | null;
  contract_year:   string | null;
  trigger_type:    string | null;
  payout_type:     string | null;
  entity_lcc:      string | null;
  remark:          string | null;
  deal_no:         string | null;
};

type DealHistoryStep = {
  step_order:         number;
  role:               string;
  assigned_user_name: string;
  status:             string;
  acted_by_name:      string | null;
  acted_at:           string | null;
  reason:             string | null;
};

type DealHistoryData = {
  deal_id:         number;
  created_by_name: string;
  created_at:      string;
  source_type:     string;
  status:          string;
  steps:           DealHistoryStep[];
};

type BulkApproveResult = {
  approved: number[];
  failed: Array<{ deal_id: number; reason: string }>;
};

function getErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === "object" && err !== null) {
    const maybe = err as { response?: { data?: { detail?: string } } };
    return maybe.response?.data?.detail || fallback;
  }
  return fallback;
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

const STEP_STATUS_CONFIG: Record<string, { icon: React.ReactNode; color: string; dot: string; label: string }> = {
  approved: { icon: <CheckCircle className="w-3 h-3" />, color: "text-green-600", dot: "bg-green-500", label: "Approved" },
  rejected: { icon: <XCircle    className="w-3 h-3" />, color: "text-red-600",   dot: "bg-red-500",   label: "Rejected" },
  pending:  { icon: <AlertCircle className="w-3 h-3" />, color: "text-blue-500", dot: "bg-blue-400",  label: "Pending"  },
  skipped:  { icon: <MinusCircle className="w-3 h-3" />, color: "text-gray-400", dot: "bg-gray-300",  label: "Skipped"  },
};

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <span className="text-gray-400">{label}: </span>
      <span className="font-medium text-gray-700">{value || "—"}</span>
    </div>
  );
}

function DealApprovalModal({ deal, history, remark, onRemarkChange, onApprove, onReject, onClose, acting, rejectError }: {
  deal: InboxDeal;
  history: DealHistoryData | null;
  remark: string;
  onRemarkChange: (v: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onClose: () => void;
  acting: boolean;
  rejectError: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h2 className="text-sm font-bold text-gray-900">{deal.airline_name || deal.source_agent}</h2>
            <div className="flex items-center gap-2 mt-1">
              {deal.deal_no && (
                <span className="font-mono text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 border border-gray-200">
                  {deal.deal_no}
                </span>
              )}
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 uppercase">
                {deal.deal_type}
              </span>
              {deal.airline_type && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                  {deal.airline_type}
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">

          {/* Contract Details */}
          <div>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-2">Contract Details</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs bg-gray-50/60 rounded-lg px-3 py-2.5 border border-gray-100">
              <InfoRow label="Source Agent" value={deal.source_agent} />
              <InfoRow label="Deal Maker" value={deal.deal_maker_name} />
              <InfoRow label="Airline Name" value={deal.airline_name} />
              <InfoRow label="Airline Type" value={deal.airline_type} />
              <InfoRow label="Valid From" value={deal.valid_from} />
              <InfoRow label="Valid To" value={deal.valid_to} />
              <InfoRow label="Business Type" value={deal.business_type} />
              <InfoRow label="Contract Year" value={deal.contract_year} />
              {deal.trigger_type && <InfoRow label="Trigger Type" value={deal.trigger_type} />}
              {deal.payout_type  && <InfoRow label="Payout Type"  value={deal.payout_type}  />}
              {deal.entity_lcc   && <InfoRow label="Entity (LCC)" value={deal.entity_lcc}   />}
            </div>
          </div>

          {/* Incentive Types */}
          {(deal.incentive_types ?? []).length > 0 && (
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-2">Incentive Types</p>
              <div className="space-y-2">
                {(deal.incentive_types ?? []).map(type => {
                  const data = deal.incentive_data?.[type] ?? {};
                  const entries = Object.entries(data);
                  return (
                    <div key={type} className="rounded-lg border border-purple-100 overflow-hidden">
                      <div className="bg-purple-50 px-3 py-1.5">
                        <span className="text-[10px] font-bold text-purple-700 uppercase tracking-wide">{type}</span>
                      </div>
                      {entries.length > 0 ? (
                        <div className="grid grid-cols-2 gap-x-6 gap-y-1 px-3 py-2 text-xs">
                          {entries.map(([k, v]) => (
                            <InfoRow key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                          ))}
                        </div>
                      ) : (
                        <p className="px-3 py-2 text-xs text-gray-400 italic">No detail fields recorded.</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Inclusions / Exclusions */}
          {(deal.incl_excl_types ?? []).length > 0 && (
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-2">Inclusions / Exclusions</p>
              <div className="space-y-2">
                {(deal.incl_excl_types ?? []).map(type => {
                  const isExcl = type.toLowerCase().includes("exclusion");
                  const data = deal.incl_excl_data?.[type] ?? {};
                  const entries = Object.entries(data);
                  return (
                    <div key={type} className={`rounded-lg border overflow-hidden ${isExcl ? "border-red-100" : "border-green-100"}`}>
                      <div className={`px-3 py-1.5 ${isExcl ? "bg-red-50" : "bg-green-50"}`}>
                        <span className={`text-[10px] font-bold uppercase tracking-wide ${isExcl ? "text-red-700" : "text-green-700"}`}>{type}</span>
                      </div>
                      {entries.length > 0 ? (
                        <div className="grid grid-cols-2 gap-x-6 gap-y-1 px-3 py-2 text-xs">
                          {entries.map(([k, v]) => (
                            <InfoRow key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                          ))}
                        </div>
                      ) : (
                        <p className="px-3 py-2 text-xs text-gray-400 italic">No detail fields recorded.</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Deal Remark */}
          {deal.remark && (
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-1">Deal Remark</p>
              <p className="text-xs text-gray-600 italic bg-gray-50 rounded-lg px-3 py-2 border border-gray-100">
                &ldquo;{deal.remark}&rdquo;
              </p>
            </div>
          )}

          {/* Approval History */}
          <div>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wide mb-2">Approval History</p>
            {history ? (
              history.steps.length === 0 ? (
                <p className="text-xs text-gray-400 italic">No history yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {history.steps.map((s, i) => {
                    const statusDot = s.status === "approved" ? "bg-green-500" : s.status === "rejected" ? "bg-red-500" : s.status === "skipped" ? "bg-gray-300" : "bg-yellow-400";
                    const statusBadge = s.status === "approved" ? "bg-green-100 text-green-700" : s.status === "rejected" ? "bg-red-100 text-red-600" : s.status === "skipped" ? "bg-gray-100 text-gray-400" : "bg-yellow-100 text-yellow-700";
                    return (
                      <div key={i} className="flex items-start gap-2.5 text-xs">
                        <span className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${statusDot}`} />
                        <div className="flex-1 min-w-0">
                          <span className="font-medium text-gray-700">{s.role} — {s.assigned_user_name}</span>
                          {s.acted_by_name && <span className="text-gray-400 ml-1">by {s.acted_by_name}</span>}
                          {s.reason && <p className="text-gray-400 text-[11px] mt-0.5 italic">&ldquo;{s.reason}&rdquo;</p>}
                        </div>
                        <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded flex-shrink-0 ${statusBadge}`}>{s.status}</span>
                      </div>
                    );
                  })}
                </div>
              )
            ) : (
              <p className="text-xs text-gray-400">Loading history…</p>
            )}
          </div>

          {/* Approver Remark */}
          <div>
            <label className="block text-[11px] font-medium text-gray-500 uppercase tracking-wide mb-1">
              Remark <span className="text-gray-400 font-normal normal-case">(required for rejection)</span>
            </label>
            <textarea
              value={remark}
              onChange={e => onRemarkChange(e.target.value)}
              placeholder="Enter reason or note…"
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            {rejectError && <p className="text-[11px] text-red-500 mt-1">{rejectError}</p>}
          </div>
        </div>

        <div className="flex items-center gap-3 px-5 py-3.5 border-t border-gray-100">
          <button onClick={onClose} className="flex-1 border border-gray-200 text-gray-600 rounded-lg py-2 text-sm font-medium hover:bg-gray-50">
            Close
          </button>
          <button onClick={onReject} disabled={acting} className="flex-1 border border-red-300 text-red-700 rounded-lg py-2 text-sm font-semibold hover:bg-red-50 disabled:opacity-50">
            {acting ? "…" : "Reject"}
          </button>
          <button onClick={onApprove} disabled={acting} className="flex-1 bg-green-600 text-white rounded-lg py-2 text-sm font-semibold hover:bg-green-700 disabled:opacity-50">
            {acting ? "…" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ApprovalsPage() {
  const [inbox,         setInbox]         = useState<InboxDeal[]>([]);
  // keyed by DealApproval.id (d.id)
  const [historyByDeal, setHistoryByDeal] = useState<Record<number, DealHistoryData>>({});
  const [remarksByDeal, setRemarksByDeal] = useState<Record<number, string>>({});
  const [selectedDeals, setSelectedDeals] = useState<number[]>([]);
  const [loading,       setLoading]       = useState(false);
  const [acting,        setActing]        = useState(false);
  const [error,         setError]         = useState<string | null>(null);
  const [success,       setSuccess]       = useState<string | null>(null);
  const [modalDeal,     setModalDeal]     = useState<InboxDeal | null>(null);
  const [rejectError,   setRejectError]   = useState("");

  const loadInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<InboxDeal[]>("/deals/approvals/inbox");
      setInbox(res.data);
      setSelectedDeals((prev) => prev.filter((id) => res.data.some((d) => d.id === id)));
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to load approvals inbox"));
    } finally {
      setLoading(false);
    }
  }, []);

  // Load history using the actual deal_id + deal_type, cache by DealApproval.id
  const loadHistory = useCallback(async (approvalId: number, dealId: number, dealType: string) => {
    try {
      const res = await api.get<DealHistoryData>(
        `/deals/repository/${dealId}/history?deal_type=${dealType}`
      );
      setHistoryByDeal((prev) => ({ ...prev, [approvalId]: res.data }));
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Failed to load deal history"));
    }
  }, []);

  useEffect(() => { loadInbox(); }, [loadInbox]);

  useEffect(() => {
    inbox.forEach((d) => {
      if (!historyByDeal[d.id]) loadHistory(d.id, d.deal_id, d.deal_type);
    });
  }, [inbox, historyByDeal, loadHistory]);

  // approval_id = d.id (DealApproval.id)
  const takeAction = async (d: InboxDeal, kind: "approve" | "reject") => {
    const remark = (remarksByDeal[d.id] || "").trim();
    if (kind === "reject" && !remark) {
      setError("Rejection reason is required.");
      return;
    }
    setActing(true);
    setError(null);
    setSuccess(null);
    try {
      await api.post(`/deals/approvals/${d.id}/${kind}`, { reason: remark || null });
      setRemarksByDeal((prev) => ({ ...prev, [d.id]: "" }));
      await loadInbox();
      await loadHistory(d.id, d.deal_id, d.deal_type);
      setSuccess(`Deal #${d.deal_id} ${kind === "approve" ? "approved" : "rejected"} successfully.`);
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Action failed"));
    } finally {
      setActing(false);
    }
  };

  const toggleDeal = (approvalId: number) => {
    setSelectedDeals((prev) =>
      prev.includes(approvalId) ? prev.filter((id) => id !== approvalId) : [...prev, approvalId]
    );
  };

  const toggleSelectAll = () => {
    if (selectedDeals.length === inbox.length) { setSelectedDeals([]); return; }
    setSelectedDeals(inbox.map((d) => d.id));
  };

  const bulkApprove = async () => {
    if (!selectedDeals.length) { setError("Please select one or more deals for bulk approve."); return; }
    setActing(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.post<BulkApproveResult>("/deals/approvals/bulk-approve", {
        deal_ids: selectedDeals,   // these are DealApproval.id values
      });
      const affectedDeals = inbox.filter((d) => selectedDeals.includes(d.id));
      await loadInbox();
      await Promise.all(affectedDeals.map((d) => loadHistory(d.id, d.deal_id, d.deal_type)));
      const failCount = res.data.failed.length;
      setSuccess(`Bulk approve complete: ${res.data.approved.length} approved, ${failCount} failed.`);
      if (failCount) setError(res.data.failed.map((f) => `#${f.deal_id}: ${f.reason}`).join(" | "));
      setSelectedDeals([]);
    } catch (e: unknown) {
      setError(getErrorMessage(e, "Bulk approve failed"));
    } finally {
      setActing(false);
    }
  };

  const handleModalApprove = async () => {
    if (!modalDeal) return;
    await takeAction(modalDeal, "approve");
    setModalDeal(null);
  };

  const handleModalReject = async () => {
    if (!modalDeal) return;
    const remark = (remarksByDeal[modalDeal.id] || "").trim();
    if (!remark) { setRejectError("Please enter a reason for rejection."); return; }
    setRejectError("");
    await takeAction(modalDeal, "reject");
    setModalDeal(null);
  };

  return (
    <div className="space-y-5">
      {modalDeal && (
        <DealApprovalModal
          deal={modalDeal}
          history={historyByDeal[modalDeal.id] ?? null}
          remark={remarksByDeal[modalDeal.id] ?? ""}
          onRemarkChange={v => setRemarksByDeal(p => ({ ...p, [modalDeal.id]: v }))}
          onApprove={handleModalApprove}
          onReject={handleModalReject}
          onClose={() => { setModalDeal(null); setRejectError(""); }}
          acting={acting}
          rejectError={rejectError}
        />
      )}

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Deal Approvals</h1>
          <p className="text-sm text-gray-500 mt-1">{inbox.length} deals pending your action</p>
        </div>
        <button
          onClick={loadInbox}
          className="inline-flex items-center gap-2 px-3 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {error   && <div className="px-4 py-3 rounded-lg bg-red-50 text-sm text-red-700 border border-red-200">{error}</div>}
      {success && <div className="px-4 py-3 rounded-lg bg-green-50 text-sm text-green-700 border border-green-200">{success}</div>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <div className="text-sm font-semibold text-gray-900">Approvals Table</div>
          <button
            disabled={acting || !selectedDeals.length}
            onClick={bulkApprove}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-green-600 text-white rounded-lg disabled:opacity-50 hover:bg-green-700"
          >
            <CheckCircle className="w-4 h-4" /> Approve All Selected
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-275">
            <thead className="bg-gray-50 text-xs uppercase text-gray-500">
              <tr>
                <th className="px-3 py-2 text-left">
                  <input type="checkbox" checked={!!inbox.length && selectedDeals.length === inbox.length} onChange={toggleSelectAll} />
                </th>
                <th className="px-3 py-2 text-left">Deal</th>
                <th className="px-3 py-2 text-left">Details</th>
                <th className="px-3 py-2 text-left">Approval History</th>
                <th className="px-3 py-2 text-left">Remark</th>
                <th className="px-3 py-2 text-left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {!inbox.length ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                    {loading ? "Loading…" : "No approvals assigned."}
                  </td>
                </tr>
              ) : (
                inbox.map((d) => {
                  const history = historyByDeal[d.id];
                  const completedSteps = (history?.steps ?? []).filter((s) => s.status !== "pending");
                  return (
                    <tr key={d.id} className="border-t border-gray-100 align-top">
                      <td className="px-3 py-3">
                        <input type="checkbox" checked={selectedDeals.includes(d.id)} onChange={() => toggleDeal(d.id)} />
                      </td>

                      {/* deal info */}
                      <td className="px-3 py-3">
                        <div className="text-sm font-semibold text-gray-900">
                          {d.airline_name || d.source_agent || `Deal #${d.deal_id}`}
                        </div>
                        <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${
                            d.deal_type === "b2b"
                              ? "bg-violet-50 text-violet-700 border-violet-200"
                              : "bg-sky-50 text-sky-700 border-sky-200"
                          }`}>
                            {d.deal_type === "b2b" ? "B2B" : "Airline"}
                          </span>
                          {d.airline_type && (
                            <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border bg-gray-50 text-gray-600 border-gray-200">
                              {d.airline_type}
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-gray-400 mt-1">#{d.deal_id}</div>
                      </td>

                      {/* details + creator */}
                      <td className="px-3 py-3 text-xs text-gray-600 min-w-45">
                        <div>Source: <span className="font-medium text-gray-800">{d.source_agent}</span></div>
                        <div>Status: <span className="font-medium text-gray-800">{d.status}</span></div>
                        {history ? (
                          <div className="mt-1.5 pt-1.5 border-t border-gray-100 flex items-start gap-1.5">
                            <div className="w-5 h-5 rounded-full bg-[#1e3a5f] flex items-center justify-center shrink-0 mt-0.5">
                              <User className="w-2.5 h-2.5 text-white" />
                            </div>
                            <div>
                              <div className="font-medium text-gray-800">{history.created_by_name}</div>
                              <div className="text-[10px] text-gray-400">{formatDateTime(history.created_at)}</div>
                            </div>
                          </div>
                        ) : (
                          <div className="mt-1.5 text-[10px] text-gray-400">Loading creator…</div>
                        )}
                      </td>

                      {/* approval history */}
                      <td className="px-3 py-3 text-xs text-gray-600 max-w-85">
                        {!history ? (
                          <span className="text-gray-400 text-[11px]">Loading…</span>
                        ) : completedSteps.length === 0 ? (
                          <span className="text-gray-400 text-[11px] italic">No history yet</span>
                        ) : (
                          <div className="space-y-2">
                            {completedSteps.map((s, i) => {
                              const cfg = STEP_STATUS_CONFIG[s.status] ?? STEP_STATUS_CONFIG.pending;
                              return (
                                <div key={i} className="flex gap-2 items-start">
                                  <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot} mt-1.5 shrink-0`} />
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      <span className="font-medium text-gray-700">Step {s.step_order}</span>
                                      <span className="text-gray-400">·</span>
                                      <span className="text-gray-600">{s.role}</span>
                                      <span className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${cfg.color}`}>
                                        {cfg.icon} {cfg.label}
                                      </span>
                                    </div>
                                    {s.acted_by_name && (
                                      <div className="text-[10px] text-gray-500 mt-0.5">
                                        By: <span className="font-medium text-gray-700">{s.acted_by_name}</span>
                                        {s.acted_at && <> · {formatDateTime(s.acted_at)}</>}
                                      </div>
                                    )}
                                    {s.reason && (
                                      <div className="text-[10px] text-gray-500 italic mt-0.5 truncate max-w-65">
                                        &ldquo;{s.reason}&rdquo;
                                      </div>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </td>

                      {/* remark */}
                      <td className="px-3 py-3">
                        <textarea
                          value={remarksByDeal[d.id] || ""}
                          onChange={(e) => setRemarksByDeal((prev) => ({ ...prev, [d.id]: e.target.value }))}
                          placeholder="Reason required for reject"
                          className="w-full border border-gray-200 rounded-lg px-2 py-2 text-xs min-h-17.5"
                        />
                      </td>

                      {/* actions */}
                      <td className="px-3 py-3">
                        <div className="flex gap-2">
                          <button
                            disabled={acting}
                            onClick={() => takeAction(d, "reject")}
                            className="inline-flex items-center gap-1 px-3 py-1.5 border border-red-300 text-red-700 rounded-lg text-xs hover:bg-red-50 disabled:opacity-50"
                          >
                            <XCircle className="w-3.5 h-3.5" /> Reject
                          </button>
                          <button
                            disabled={acting}
                            onClick={() => { setRejectError(""); setModalDeal(d); if (!historyByDeal[d.id]) loadHistory(d.id, d.deal_id, d.deal_type); }}
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs hover:bg-green-700 disabled:opacity-50"
                          >
                            <Eye className="w-3.5 h-3.5" /> View &amp; Approve
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
