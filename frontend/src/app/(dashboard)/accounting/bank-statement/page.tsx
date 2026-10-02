"use client";

// Accounting → Bank Statement. Upload the bank's own Excel export of the tenant's
// account, then open a statement to link each deposit to the party that paid it
// (/accounting/bank-statement/{id}). The second tab adds it up: per corporate,
// employee and agency, what Invoicing billed and what the bank says they paid.

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Banknote, CheckCircle2, RefreshCw, Trash2, Upload } from "lucide-react";
import api from "@/lib/api";
import { inr, rupees } from "@/lib/money";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  PARTY_TYPE_LABEL, errText, fmtDate,
  type BankStatement, type BilledReceivedSummary, type UploadResult,
} from "@/lib/bankStatement";

type Tab = "statements" | "summary";

const TH = "px-3 py-2.5 text-left text-[10px] font-semibold text-white uppercase tracking-wider whitespace-nowrap";
const TH_R = TH.replace("text-left", "text-right");
const CELL = "px-3 py-2.5 text-[11px] text-gray-700 align-top";
const CELL_R = `${CELL} text-right tabular-nums`;
const INPUT = "px-2 py-1.5 border border-gray-200 rounded-lg text-xs bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1e3a5f]/40";

export default function BankStatementPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("statements");
  const [statements, setStatements] = useState<BankStatement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploaded, setUploaded] = useState<UploadResult | null>(null);
  const [deleting, setDeleting] = useState<BankStatement | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get<BankStatement[]>("/bank-statements/");
      setStatements(data);
    } catch (e) {
      setError(errText(e, "Failed to load bank statements."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError("");
    setUploaded(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await api.post<UploadResult>("/bank-statements/upload", form);
      setUploaded(data);
      setTab("statements");
      await load();
    } catch (e) {
      setError(errText(e, "Upload failed."));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Accounting</p>
          <h1 className="text-xl font-bold text-gray-900">Bank Statement</h1>
          <p className="text-xs text-gray-500 mt-0.5">
            Upload your bank&apos;s Excel statement, link each deposit to the corporate, employee or
            agency that paid, and compare what you billed with what you received.
          </p>
        </div>
        <div className="flex gap-2 shrink-0">
          <input
            ref={fileRef}
            type="file"
            accept=".xls,.xlsx,.csv"
            className="hidden"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 bg-[#1e3a5f] hover:bg-[#16304f] text-white px-3.5 py-2 rounded-lg text-xs font-semibold disabled:opacity-50"
          >
            {uploading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {uploading ? "Reading…" : "Upload Statement"}
          </button>
          <button
            onClick={load}
            disabled={loading}
            title="Refresh"
            className="flex items-center gap-1.5 bg-white border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {uploaded && (
        <div className="flex items-center justify-between gap-3 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <div className="flex items-start gap-2 text-xs text-green-800">
            <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
            <p>
              Added <strong>{uploaded.inserted}</strong> transactions from{" "}
              <strong>{uploaded.statement.file_name}</strong>
              {uploaded.skipped_duplicates > 0 && (
                <> — {uploaded.skipped_duplicates} were already loaded from an earlier statement and were skipped</>
              )}
              . {uploaded.statement.unlinked_receipt_count} deposits are waiting to be linked.
            </p>
          </div>
          <Link
            href={`/accounting/bank-statement/${uploaded.statement.id}`}
            className="flex items-center gap-1 text-xs font-semibold text-green-800 hover:underline shrink-0"
          >
            Link deposits <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      )}
      {error && <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{error}</div>}

      <div className="flex gap-1 border-b border-gray-200">
        {([["statements", "Statements"], ["summary", "Billed vs Received"]] as const).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-3.5 py-2 text-xs font-semibold -mb-px border-b-2 ${
              tab === key ? "border-[#1e3a5f] text-[#1e3a5f]" : "border-transparent text-gray-500 hover:text-gray-800"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "statements" ? (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: "#1e3a5f" }}>
                  <th className={TH}>Account</th>
                  <th className={TH}>Period</th>
                  <th className={TH_R}>Transactions</th>
                  <th className={TH_R}>Deposits</th>
                  <th className={TH_R}>Withdrawals</th>
                  <th className={TH_R}>Linked</th>
                  <th className={TH_R}>Waiting to link</th>
                  <th className={TH}>Uploaded</th>
                  <th className={TH} />
                </tr>
              </thead>
              <tbody>
                {loading && statements.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-12 text-center text-xs text-gray-400">
                      <RefreshCw className="w-4 h-4 animate-spin mx-auto mb-2 text-gray-300" /> Loading statements…
                    </td>
                  </tr>
                ) : statements.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-16 text-center">
                      <div className="flex flex-col items-center">
                        <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mb-3">
                          <Banknote className="w-7 h-7 text-gray-300" />
                        </div>
                        <p className="text-sm font-medium text-gray-600">No bank statements yet</p>
                        <p className="text-xs text-gray-400 mt-1 max-w-sm">
                          Download the statement from your bank&apos;s net banking as Excel (ICICI&apos;s
                          &ldquo;Detailed Statement&rdquo; works as it comes) and upload it here.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  statements.map((s, idx) => {
                    const deposits = s.linked_count + s.unlinked_receipt_count;
                    return (
                      <tr
                        key={s.id}
                        onClick={() => router.push(`/accounting/bank-statement/${s.id}`)}
                        className={`border-b border-gray-50 hover:bg-blue-50/40 cursor-pointer ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}
                      >
                        <td className={CELL}>
                          <p className="font-semibold text-gray-800">{s.account_name || s.file_name}</p>
                          <p className="text-[10px] text-gray-400 font-mono">
                            {[s.bank_name, s.account_no].filter(Boolean).join(" · ") || s.file_name}
                          </p>
                        </td>
                        <td className={`${CELL} whitespace-nowrap`}>{fmtDate(s.period_from)} – {fmtDate(s.period_to)}</td>
                        <td className={CELL_R}>{s.row_count}</td>
                        <td className={`${CELL_R} text-green-700`}>{inr(s.total_deposits, 2)}</td>
                        <td className={`${CELL_R} text-red-600`}>{inr(s.total_withdrawals, 2)}</td>
                        <td className={CELL_R}>
                          {s.linked_count}{deposits ? ` / ${deposits}` : ""}
                          <p className="text-[10px] text-gray-400">{rupees(s.linked_amount)}</p>
                        </td>
                        <td className={CELL_R}>
                          {s.unlinked_receipt_count > 0 ? (
                            <span className="font-semibold text-amber-600">
                              {s.unlinked_receipt_count} · {rupees(s.unlinked_receipt_amount)}
                            </span>
                          ) : (
                            <span className="text-green-600">All linked</span>
                          )}
                        </td>
                        <td className={`${CELL} whitespace-nowrap text-gray-500`}>{fmtDate(s.created_at)}</td>
                        <td className={CELL} onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={() => setDeleting(s)}
                            title="Delete this statement"
                            className="p-1 rounded hover:bg-red-50 text-gray-400 hover:text-red-500"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <BilledReceived />
      )}

      {deleting && (
        <ConfirmDialog
          title="Delete bank statement?"
          onClose={() => setDeleting(null)}
          onConfirm={async () => {
            await api.delete(`/bank-statements/${deleting.id}`);
            setDeleting(null);
            setUploaded(null);
            await load();
          }}
        >
          All {deleting.row_count} transactions of <strong>{deleting.file_name}</strong> and their links go.
          Receipts it posted to agency ledgers are reversed there, not erased.
        </ConfirmDialog>
      )}
    </div>
  );
}

function BilledReceived() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  // State is only written when a request settles; "loading" is simply "the last answer
  // is for a different date range". The previous table stays up (dimmed) meanwhile.
  const key = `${from}|${to}`;
  const [result, setResult] = useState<{ key: string; data?: BilledReceivedSummary; error?: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params: Record<string, string> = {};
    if (from) params.date_from = from;
    if (to) params.date_to = to;
    api.get<BilledReceivedSummary>("/bank-statements/summary", { params })
      .then(({ data }) => { if (!cancelled) setResult({ key, data }); })
      .catch((e) => { if (!cancelled) setResult({ key, error: errText(e, "Failed to load the summary.") }); });
    return () => { cancelled = true; };
  }, [key, from, to]);

  const loading = result?.key !== key;
  const data = result?.data ?? null;
  const error = !loading ? result?.error ?? "" : "";

  const tiles = data ? [
    { label: "Billed", value: rupees(data.total_billed), tone: "text-gray-900" },
    { label: "Received", value: rupees(data.total_received), tone: "text-green-700" },
    { label: "Outstanding", value: rupees(data.total_outstanding), tone: data.total_outstanding > 0 ? "text-red-600" : "text-green-700" },
    {
      label: "Deposits not linked yet",
      value: `${rupees(data.unlinked_receipt_amount)}`,
      sub: `${data.unlinked_receipt_count} deposits — received, but not credited to anyone`,
      tone: data.unlinked_receipt_count ? "text-amber-600" : "text-gray-400",
    },
  ] : [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500">
        <span>Invoices ending, and money received,</span>
        <label className="flex items-center gap-1">from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={INPUT} /></label>
        <label className="flex items-center gap-1">to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={INPUT} /></label>
        {(from || to) && (
          <button onClick={() => { setFrom(""); setTo(""); }} className="text-[11px] text-gray-400 hover:text-gray-700">All time</button>
        )}
      </div>

      {error && <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-xl px-4 py-3">{error}</div>}

      {data && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {tiles.map((t) => (
            <div key={t.label} className="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3">
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{t.label}</p>
              <p className={`text-lg font-bold tabular-nums mt-0.5 ${t.tone}`}>{t.value}</p>
              {t.sub && <p className="text-[10px] text-gray-400 mt-0.5">{t.sub}</p>}
            </div>
          ))}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: "#1e3a5f" }}>
                <th className={TH}>Party</th>
                <th className={TH_R}>Invoices</th>
                <th className={TH_R}>Billed</th>
                <th className={TH_R}>Receipts</th>
                <th className={TH_R}>Received</th>
                <th className={TH_R}>Outstanding</th>
              </tr>
            </thead>
            <tbody className={loading && data ? "opacity-50" : ""}>
              {!data && loading ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-xs text-gray-400">Loading…</td></tr>
              ) : !data || data.rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-xs text-gray-400">
                    Nothing billed or received{from || to ? " in this period" : " yet"}. Invoices come from
                    Invoicing; receipts from the deposits you link on a statement.
                  </td>
                </tr>
              ) : (
                data.rows.map((r, idx) => (
                  <tr key={`${r.party.party_type}:${r.party.party_id}`} className={`border-b border-gray-50 ${idx % 2 ? "bg-gray-50/30" : "bg-white"}`}>
                    <td className={CELL}>
                      <span className="text-[9px] font-semibold uppercase tracking-wide text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded mr-1.5">
                        {PARTY_TYPE_LABEL[r.party.party_type]}
                      </span>
                      <span className="font-semibold text-gray-800">{r.party.name}</span>
                      {r.party.code && <span className="ml-1.5 font-mono text-[10px] text-gray-400">{r.party.code}</span>}
                    </td>
                    <td className={CELL_R}>{r.invoices}</td>
                    <td className={CELL_R}>{inr(r.billed, 2)}</td>
                    <td className={CELL_R}>{r.receipts}</td>
                    <td className={`${CELL_R} text-green-700`}>{inr(r.received, 2)}</td>
                    <td className={`${CELL_R} font-semibold ${r.outstanding > 0 ? "text-red-600" : "text-green-700"}`}>
                      {r.outstanding < 0 ? `${inr(-r.outstanding, 2)} advance` : inr(r.outstanding, 2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <p className="text-[10px] text-gray-400">
        Billed is every saved invoice in Invoicing. Received is the deposits linked on your statements;
        for an agency it is the money-in side of its ledger, so receipts entered there by hand count too.
      </p>
    </div>
  );
}
