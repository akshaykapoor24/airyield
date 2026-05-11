"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle, XCircle, RefreshCw, AlertCircle, MinusCircle, User } from "lucide-react";
import api from "@/lib/api";

type InboxDeal = {
  id:           number;       // DealApproval.id — routing key for approve/reject/bulk-approve
  deal_id:      number;       // actual deal ID in its table — for history lookup
  deal_type:    string;       // 'upload' | 'airline' | 'b2b'
  source_agent: string;
  airline_name: string | null;
  airline_type: string | null;
  status:       string;
  created_at:   string;
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

  return (
    <div className="space-y-5">
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
                            onClick={() => takeAction(d, "approve")}
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs hover:bg-green-700 disabled:opacity-50"
                          >
                            <CheckCircle className="w-3.5 h-3.5" /> Approve
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
