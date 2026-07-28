"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, RefreshCw, AlertTriangle, ChevronDown, ChevronRight, ExternalLink, Loader2 } from "lucide-react";
import api from "@/lib/api";
import toast from "react-hot-toast";

type BspStatement = {
  batch_id: string;
  statement_name: string | null;
  airline_code: string | null;
  airline_name: string | null;
  period_from: string | null;
  period_to: string | null;
  file_name: string | null;
  row_count: number;
  status: string;
  total_pages: number;
  processed_pages: number;
  total_rows: number;
  processed_rows: number;
  progress_pct: number;
  error: string | null;
  created_by_name: string | null;
  created_at: string;
};
type Tax = { component_type: string | null; component_code: string | null; amount: number | null };
type BspRowRead = {
  id: number;
  ticket_number: string | null;
  document_number: string | null;
  airline_code: string | null;
  airline_accounting_code: string | null;
  transaction_type: string | null;
  issue_date: string | null;
  stat: string | null;
  form_of_payment: string | null;
  transaction_amount: number | null;
  fare_amount: number | null;
  net_sales: number | null;
  standard_commission_amount: number | null;
  balance_payable: number | null;
  match_status: string;
  taxes: Tax[];
};
type RowsPage = { total: number; offset: number; limit: number; rows: BspRowRead[] };

const PAGE_SIZE = 50;
const num = (v: number | null) => (v == null ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));

function statusBadge(s: string): string {
  switch (s) {
    case "completed":  return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "processing": return "bg-blue-50 text-blue-700 border-blue-200";
    case "failed":     return "bg-red-50 text-red-700 border-red-200";
    default:           return "bg-gray-100 text-gray-500 border-gray-200"; // pending
  }
}

export default function BspStatementDetailPage() {
  const params = useParams<{ batch_id: string }>();
  const router = useRouter();
  const batchId = (params?.batch_id as string) || "";

  const [stmt, setStmt] = useState<BspStatement | null>(null);
  const [rowsPage, setRowsPage] = useState<RowsPage | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [errorCount, setErrorCount] = useState(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatement = useCallback(async () => {
    const { data } = await api.get<BspStatement>(`/bsp/statements/${batchId}`);
    setStmt(data);
    return data;
  }, [batchId]);

  const fetchRows = useCallback(async (p: number) => {
    const offset = (p - 1) * PAGE_SIZE;
    const { data } = await api.get<RowsPage>(`/bsp/statements/${batchId}/rows`, { params: { offset, limit: PAGE_SIZE } });
    setRowsPage(data);
  }, [batchId]);

  const fetchErrors = useCallback(async () => {
    try {
      const { data } = await api.get<{ total: number }>(`/bsp/statements/${batchId}/errors`, { params: { offset: 0, limit: 1 } });
      setErrorCount(data.total);
    } catch { /* ignore */ }
  }, [batchId]);

  // Initial load
  useEffect(() => {
    if (!batchId) return;
    (async () => {
      setLoading(true);
      try {
        const s = await fetchStatement();
        if (s.status === "completed" || s.status === "failed") {
          await Promise.all([fetchRows(1), fetchErrors()]);
        }
      } catch {
        toast.error("Failed to load BSP statement.");
      } finally {
        setLoading(false);
      }
    })();
  }, [batchId, fetchStatement, fetchRows, fetchErrors]);

  // Poll while pending/processing
  useEffect(() => {
    const active = stmt?.status === "pending" || stmt?.status === "processing";
    if (!active) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const s = await fetchStatement();
        if (s.status === "completed" || s.status === "failed") {
          await Promise.all([fetchRows(1), fetchErrors()]);
          setPage(1);
        }
      } catch { /* keep polling */ }
    }, 3000);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [stmt?.status, fetchStatement, fetchRows, fetchErrors]);

  const goPage = async (p: number) => { setPage(p); await fetchRows(p); };

  const toggleRow = (id: number) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const viewPdf = async () => {
    try {
      const { data } = await api.get<{ url: string }>(`/bsp/statements/${batchId}/file-url`);
      window.open(data.url, "_blank");
    } catch {
      toast.error("Could not open the source PDF.");
    }
  };

  const isProcessing = stmt?.status === "pending" || stmt?.status === "processing";

  return (
    <div className="w-full pb-16">
      <div className="flex items-center gap-2 mb-4">
        <button onClick={() => router.push("/tickets/bsp")} className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600">
          <ArrowLeft className="w-3.5 h-3.5" /> Back
        </button>
        <span className="text-gray-300 text-xs">|</span>
        <h1 className="text-sm font-semibold text-gray-700 truncate">{stmt?.statement_name || "BSP Statement"}</h1>
        {stmt?.file_name && (
          <button onClick={viewPdf} className="ml-2 flex items-center gap-1 text-[11px] text-blue-600 hover:underline">
            <ExternalLink className="w-3 h-3" /> View PDF
          </button>
        )}
        <button onClick={() => fetchStatement()} className="ml-auto flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* Header card */}
      {stmt && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 mb-3 flex flex-wrap items-center gap-x-8 gap-y-2 text-xs">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-gray-400">Status</p>
            <span className={`inline-block mt-0.5 px-2 py-0.5 rounded-full text-[10px] font-medium border capitalize ${statusBadge(stmt.status)}`}>{stmt.status}</span>
          </div>
          <Meta label="Airline" value={stmt.airline_name || stmt.airline_code || "—"} />
          <Meta label="Period" value={`${stmt.period_from || "—"} → ${stmt.period_to || "—"}`} />
          <Meta label="Rows" value={String(stmt.total_rows || stmt.row_count)} />
          <Meta label="Pages" value={stmt.total_pages ? String(stmt.total_pages) : "—"} />
          <Meta label="Uploaded by" value={stmt.created_by_name || "—"} />
        </div>
      )}

      {/* Progress banner */}
      {isProcessing && stmt && (
        <div className="bg-blue-50/60 border border-blue-100 rounded-lg px-4 py-3 mb-3">
          <div className="flex items-center gap-2 text-[12px] text-blue-700 mb-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Parsing your BSP statement… {stmt.processed_pages}/{stmt.total_pages || "?"} pages · {stmt.processed_rows} rows so far. You can keep working — this page updates automatically.</span>
          </div>
          <div className="h-2 w-full bg-blue-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 transition-all duration-500" style={{ width: `${stmt.progress_pct}%` }} />
          </div>
        </div>
      )}

      {/* Failure banner */}
      {stmt?.status === "failed" && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mb-3 text-[12px] text-red-700">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>Parsing failed: {stmt.error || "unknown error"}. Fix the source file and re-upload.</span>
        </div>
      )}

      {/* Parse errors note */}
      {errorCount > 0 && (
        <div className="flex items-start gap-2 bg-amber-50/70 border border-amber-100 rounded-lg px-3 py-2 mb-3 text-[11px] text-amber-700">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span>{errorCount} page{errorCount === 1 ? "" : "s"} could not be fully parsed and were skipped. The rest of the statement was imported.</span>
        </div>
      )}

      {/* Rows table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-[11px] uppercase tracking-wide text-gray-400">
                <th className="px-2 py-2 font-semibold w-6"></th>
                <th className="px-3 py-2 font-semibold">Document #</th>
                <th className="px-3 py-2 font-semibold">Txn</th>
                <th className="px-3 py-2 font-semibold">Airline</th>
                <th className="px-3 py-2 font-semibold">Issue Date</th>
                <th className="px-3 py-2 font-semibold">Stat</th>
                <th className="px-3 py-2 font-semibold">FOP</th>
                <th className="px-3 py-2 font-semibold text-right">Fare</th>
                <th className="px-3 py-2 font-semibold text-right">Txn Amt</th>
                <th className="px-3 py-2 font-semibold text-right">Net Sales</th>
                <th className="px-3 py-2 font-semibold text-right">Comm.</th>
                <th className="px-3 py-2 font-semibold text-right">Balance</th>
                <th className="px-3 py-2 font-semibold">Match</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={13} className="px-3 py-10 text-center text-sm text-gray-400">Loading…</td></tr>
              ) : isProcessing ? (
                <tr><td colSpan={13} className="px-3 py-10 text-center text-sm text-gray-400">Rows will appear here as parsing completes.</td></tr>
              ) : !rowsPage || rowsPage.rows.length === 0 ? (
                <tr><td colSpan={13} className="px-3 py-10 text-center text-sm text-gray-400">No rows parsed.</td></tr>
              ) : rowsPage.rows.map(r => (
                <Fragment key={r.id}>
                  <tr className="border-b border-gray-100 hover:bg-gray-50/60">
                    <td className="px-2 py-2">
                      <button onClick={() => toggleRow(r.id)} className="text-gray-400 hover:text-gray-700" title="Show taxes">
                        {expanded.has(r.id) ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-800">{r.document_number || r.ticket_number || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 uppercase">{r.transaction_type || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">{r.airline_code || r.airline_accounting_code || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">{r.issue_date || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">{r.stat || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-600">{r.form_of_payment || "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{num(r.fare_amount)}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{num(r.transaction_amount)}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{num(r.net_sales)}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{num(r.standard_commission_amount)}</td>
                    <td className="px-3 py-2 text-xs text-gray-800 text-right">{num(r.balance_payable)}</td>
                    <td className="px-3 py-2">
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium border capitalize bg-gray-100 text-gray-500 border-gray-200">{r.match_status}</span>
                    </td>
                  </tr>
                  {expanded.has(r.id) && (
                    <tr className="bg-gray-50/60 border-b border-gray-100">
                      <td></td>
                      <td colSpan={12} className="px-3 py-2">
                        {r.taxes.length === 0 ? (
                          <span className="text-[11px] text-gray-400">No tax components parsed for this row.</span>
                        ) : (
                          <div className="flex flex-wrap gap-1.5">
                            {r.taxes.map((t, i) => (
                              <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-white border border-gray-200 text-[11px]">
                                <span className="text-gray-400">{t.component_type}</span>
                                <span className="font-medium text-gray-700">{t.component_code}</span>
                                <span className="text-gray-800">{num(t.amount)}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {rowsPage && rowsPage.total > PAGE_SIZE && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 bg-white text-xs">
            <span className="text-[11px] text-gray-400">
              Showing {rowsPage.total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, rowsPage.total)} of {rowsPage.total} rows
            </span>
            <div className="flex items-center gap-1.5">
              <button onClick={() => goPage(page - 1)} disabled={page <= 1}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-30">Prev</button>
              <span className="text-gray-500">Page {page} / {Math.max(1, Math.ceil(rowsPage.total / PAGE_SIZE))}</span>
              <button onClick={() => goPage(page + 1)} disabled={page >= Math.ceil(rowsPage.total / PAGE_SIZE)}
                className="px-2 py-1 rounded border border-gray-200 hover:bg-gray-50 disabled:opacity-30">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="text-gray-800 font-medium mt-0.5">{value}</p>
    </div>
  );
}
