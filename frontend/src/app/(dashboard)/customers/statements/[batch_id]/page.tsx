"use client";

// Customer Statement detail — view/edit the imported ticket rows (no incentive
// calculation / deal-matching). Header shows the picked agency + entities/login-IDs
// and Preview/Download of the source file.

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import {
  ChevronLeft, RefreshCw, Building2, Calendar, KeyRound, AlertCircle,
  FileSpreadsheet, Eye, Download, Trash2,
} from "lucide-react";
import api from "@/lib/api";

type Snap = { id: number; name?: string; code?: string; login_id?: string; airline_name?: string; entity_name?: string };

type Stmt = {
  batch_id: string; statement_name: string | null; agency: string; agency_id: number | null;
  entities: Snap[] | null; login_ids: Snap[] | null;
  valid_from: string; valid_to: string; file_name: string; file_url: string | null;
  ticket_count: number; created_at: string;
};

type Row = Record<string, string | number | null> & { id: number };

type Col = { key: string; label: string; type: "text" | "date" | "number" };
type Group = { label: string; color: string; cols: Col[] };

const GROUPS: Group[] = [
  { label: "Passenger & Booking", color: "#1e3a5f", cols: [
    { key: "booking_ref", label: "Booking Ref", type: "text" },
    { key: "invoice_type", label: "Invoice Type", type: "text" },
    { key: "invoice_no", label: "Invoice No", type: "text" },
    { key: "ticket_date", label: "Ticket Date", type: "date" },
    { key: "last_name", label: "Last Name", type: "text" },
    { key: "first_name", label: "First Name", type: "text" },
  ]},
  { label: "Flight Info", color: "#4f46e5", cols: [
    { key: "sector", label: "Sector", type: "text" },
    { key: "booking_class", label: "Class", type: "text" },
    { key: "departure_datetime", label: "Departure", type: "date" },
    { key: "gds_pnr", label: "GDS PNR", type: "text" },
    { key: "airlines_code", label: "Airline", type: "text" },
    { key: "airline_name", label: "Airline Name", type: "text" },
    { key: "ticket_number", label: "Ticket #", type: "text" },
  ]},
  { label: "Financial", color: "#059669", cols: [
    { key: "sell_fare", label: "Sell Fare", type: "number" },
    { key: "sell_tax", label: "Sell Tax", type: "number" },
    { key: "sell_tax_yq", label: "Tax YQ", type: "number" },
    { key: "comm_sell", label: "Comm Sell", type: "number" },
    { key: "incentive_sell", label: "Incentive", type: "number" },
    { key: "total_amt", label: "Total Amt", type: "number" },
    { key: "net_amt", label: "Net AMT", type: "number" },
  ]},
  { label: "Account", color: "#9333ea", cols: [
    { key: "cc", label: "CC", type: "text" },
    { key: "acc_code", label: "Acc Code", type: "text" },
    { key: "sold_to", label: "Sold To", type: "text" },
    { key: "customer_name", label: "Customer Name", type: "text" },
  ]},
];
const ALL_COLS = GROUPS.flatMap(g => g.cols);

function formatDate(d: string) {
  if (!d) return "—";
  return new Date(d).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export default function CustomerStatementDetailPage() {
  const params = useParams();
  const router = useRouter();
  const batchId = String(params.batch_id);

  const [stmt, setStmt] = useState<Stmt | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  // The cell's displayed value at focus time — lets blur skip no-op saves (e.g. a
  // non-ISO date renders as "" in <input type="date">, so an untouched focus→blur
  // must NOT PATCH null) and revert the optimistic edit if the save fails.
  const focusVal = useRef<string>("");

  const fetchAll = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, r] = await Promise.all([
        api.get<Stmt>(`/customer-statements/statements/${batchId}`),
        api.get<Row[]>(`/customer-statements/uploads`, { params: { batch_id: batchId, limit: 2000 } }),
      ]);
      setStmt(s.data);
      setRows(r.data);
    } catch {
      setError("Failed to load statement.");
    } finally {
      setLoading(false);
    }
  }, [batchId]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const onCellChange = (id: number, key: string, type: Col["type"], val: string) => {
    setRows(prev => prev.map(r => r.id === id
      ? { ...r, [key]: type === "number" ? (val === "" ? null : parseFloat(val)) : (val || null) }
      : r));
  };

  const saveCell = async (id: number, key: string, type: Col["type"], val: string) => {
    // Skip if the value did not actually change from what was displayed at focus.
    // (Also guards the date-wipe case: an untouched cell blurs with val unchanged.)
    if (val === focusVal.current) return;
    const value = type === "number" ? (val === "" ? null : parseFloat(val)) : (val || null);
    setSavingId(id);
    try {
      await api.patch(`/customer-statements/uploads/${id}`, { [key]: value });
      setError(null);
    } catch {
      // Roll the optimistic edit back to the pre-edit displayed value.
      onCellChange(id, key, type, focusVal.current);
      setError("Failed to save change.");
    } finally {
      setSavingId(null);
    }
  };

  const deleteRow = async (id: number) => {
    try {
      await api.delete(`/customer-statements/uploads/${id}`);
      setRows(prev => prev.filter(r => r.id !== id));
      setStmt(prev => prev ? { ...prev, ticket_count: Math.max(0, prev.ticket_count - 1) } : prev);
    } catch {
      setError("Failed to delete row.");
    }
  };

  const openFile = async (preview: boolean) => {
    try {
      const { data } = await api.get<{ url: string }>(`/customer-statements/statements/${batchId}/file-url`);
      const target = preview
        ? `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(data.url)}`
        : data.url;
      window.open(target, "_blank");
    } catch {
      setError("No file attached to this statement.");
    }
  };

  const deleteStatement = async () => {
    if (!confirm("Delete this statement and all its rows? This cannot be undone.")) return;
    try {
      await api.delete(`/customer-statements/statements/${batchId}`);
      router.push("/customers/statements");
    } catch {
      setError("Failed to delete statement.");
    }
  };

  const inp = "w-full bg-transparent text-[11px] text-gray-800 focus:outline-none focus:bg-blue-50 rounded px-1 py-0.5 min-w-[72px]";

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link href="/customers/statements" className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-900">{stmt?.statement_name ?? "Customer Statement"}</h1>
            <p className="text-xs text-gray-500 mt-0.5">{stmt ? `${stmt.ticket_count} tickets · ${stmt.file_name}` : "Loading…"}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={fetchAll} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
          {stmt?.file_url && (
            <>
              <button onClick={() => openFile(true)}
                className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
                <Eye className="w-3.5 h-3.5" /> Preview
              </button>
              <button onClick={() => openFile(false)}
                className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
                <Download className="w-3.5 h-3.5" /> Download
              </button>
            </>
          )}
          <button onClick={deleteStatement}
            className="flex items-center gap-1.5 px-3 py-2 border border-red-200 text-red-500 rounded-lg text-xs hover:bg-red-50">
            <Trash2 className="w-3.5 h-3.5" /> Delete
          </button>
        </div>
      </div>

      {/* meta bar */}
      {stmt && (
        <div className="bg-[#1e3a5f]/5 border border-[#1e3a5f]/20 rounded-xl px-5 py-3 flex items-center gap-3 flex-wrap">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 border border-indigo-100 text-xs font-medium text-indigo-700">
            <Building2 className="w-3 h-3" /> {stmt.agency}
          </span>
          <span className="inline-flex items-center gap-1 text-xs text-gray-600">
            <Calendar className="w-3.5 h-3.5 text-gray-400" /> {formatDate(stmt.valid_from)} → {formatDate(stmt.valid_to)}
          </span>
          {(stmt.entities?.length ?? 0) > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-600">
              <Building2 className="w-3.5 h-3.5 text-gray-400" />
              {stmt.entities!.map(e => e.name || e.code).filter(Boolean).join(", ")}
            </span>
          )}
          {(stmt.login_ids?.length ?? 0) > 0 && (
            <span className="inline-flex items-center gap-1 text-xs text-gray-600">
              <KeyRound className="w-3.5 h-3.5 text-gray-400" />
              {stmt.login_ids!.map(l => l.login_id).filter(Boolean).join(", ")}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-24">
          <div className="text-center space-y-3">
            <RefreshCw className="w-7 h-7 text-blue-400 animate-spin mx-auto" />
            <p className="text-sm text-gray-500">Loading rows…</p>
          </div>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <FileSpreadsheet className="w-8 h-8 text-gray-300 mb-3" />
          <p className="text-sm font-medium text-gray-600">No rows in this statement</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200">
          <div className="px-4 py-2.5 border-b border-gray-100 flex items-center gap-2">
            <h2 className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Tickets</h2>
            <span className="ml-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">{rows.length} rows</span>
            {savingId != null && <span className="text-[10px] text-gray-400 ml-auto"><RefreshCw className="w-3 h-3 inline animate-spin mr-1" />Saving…</span>}
            <span className="text-[10px] text-gray-400 ml-auto">Click any cell to edit · saved on blur</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-max border-collapse">
              <thead>
                <tr>
                  <th className="px-2 py-2 text-[10px] text-white font-bold sticky left-0 z-10" style={{ background: "#1e3a5f" }}>#</th>
                  {GROUPS.map(g => (
                    <th key={g.label} colSpan={g.cols.length} className="px-2 py-2 text-[10px] text-white font-bold uppercase tracking-wider text-center border-l border-white/20 whitespace-nowrap" style={{ background: g.color }}>
                      {g.label}
                    </th>
                  ))}
                  <th className="px-2 py-2" style={{ background: "#1e3a5f" }} />
                </tr>
                <tr style={{ background: "#2d4f7c" }}>
                  <th className="px-2 py-1.5 sticky left-0 z-10" style={{ background: "#2d4f7c" }} />
                  {ALL_COLS.map(c => (
                    <th key={c.key} className="px-2 py-1.5 text-left text-[10px] font-semibold text-white/80 whitespace-nowrap border-l border-white/10">{c.label}</th>
                  ))}
                  <th className="px-2 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={row.id} className="border-b border-gray-100 group hover:bg-blue-50/20">
                    <td className="px-2 py-1.5 text-[10px] text-gray-400 sticky left-0 bg-white group-hover:bg-blue-50/20">{i + 1}</td>
                    {ALL_COLS.map(col => {
                      const raw = row[col.key];
                      const val = raw == null ? "" : String(raw);
                      return (
                        <td key={col.key} className="px-1 py-1 border-l border-gray-100">
                          <input
                            type={col.type === "date" ? "date" : col.type === "number" ? "number" : "text"}
                            className={inp}
                            value={val}
                            placeholder="—"
                            onFocus={e => { focusVal.current = e.target.value; }}
                            onChange={e => onCellChange(row.id, col.key, col.type, e.target.value)}
                            onBlur={e => saveCell(row.id, col.key, col.type, e.target.value)}
                            onClick={col.type === "date" ? e => { try { (e.target as HTMLInputElement).showPicker(); } catch {} } : undefined}
                          />
                        </td>
                      );
                    })}
                    <td className="px-2 py-1.5">
                      <button onClick={() => deleteRow(row.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded text-red-400">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
