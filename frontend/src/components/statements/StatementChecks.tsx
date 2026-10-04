"use client";

// Payment Module steps 2, 3 and 5 — "validate completeness by checking count of records and
// amount of records for every statement loaded", and "ensure the statement is for the vendor
// specified while loading".
//
// A badge per upload (complete / attention / incomplete / unverified) that opens the checks
// behind it: records, amount (opening + tickets − payments = closing), continuity with the
// previous statement, the control totals typed at upload, and — on vendor statements — the
// file's Customer ID against the vendor's confirmed account. The two things a person can do
// about a check live here too: enter control totals / an opening balance, and confirm an
// account. Every figure comes from GET /payment-module/checks.

import { useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, ShieldCheck, X, XCircle } from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";

export type CheckItem = {
  key: string;
  label: string;
  status: "pass" | "fail" | "warn" | "na";
  detail: string;
  needs_opening?: boolean;
  confirmable?: boolean;
  account?: string;
};

export type CheckResult = {
  batch_id: string;
  slug: string;
  verdict: "complete" | "attention" | "incomplete" | "unverified";
  checks: CheckItem[];
  figures: {
    file_rows: number | null; loaded_rows: number | null; rows_now: number;
    ticket_rows: number; ticket_net: string;
    opening: string | null; opening_source: string | null; closing: string | null;
    payments: string | null; expected_count: number | null; expected_amount: string | null;
    period_from: string | null; period_to: string | null;
    accounts: { account: string; name: string | null; rows: number }[];
  };
  supplier_name?: string | null;
  source_file?: string | null;
};

const amt = (v: string | number | null | undefined) =>
  v == null || v === "" ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

export const VERDICT_STYLE: Record<CheckResult["verdict"], { cls: string; label: string }> = {
  complete: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Complete" },
  attention: { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Review" },
  incomplete: { cls: "bg-red-50 text-red-700 border-red-200", label: "Issues" },
  unverified: { cls: "bg-slate-100 text-slate-500 border-slate-200", label: "Unverified" },
};

function StatusIcon({ status }: { status: CheckItem["status"] }) {
  if (status === "pass") return <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />;
  if (status === "fail") return <XCircle className="w-4 h-4 text-red-500 shrink-0" />;
  if (status === "warn") return <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />;
  return <CircleDashed className="w-4 h-4 text-slate-300 shrink-0" />;
}

function errMsg(e: unknown, fallback: string): string {
  const m = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof m === "string" ? m : fallback;
}

/** The uploads-list cell: a badge that opens the panel. */
export function ChecksBadge({ result, onOpen }: { result?: CheckResult; onOpen: () => void }) {
  if (!result) return <span className="text-xs text-slate-300">—</span>;
  const v = VERDICT_STYLE[result.verdict];
  const failing = result.checks.filter((c) => c.status === "fail" || c.status === "warn").length;
  return (
    <button type="button" onClick={onOpen} title="Open the completeness and vendor checks"
      className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border whitespace-nowrap ${v.cls}`}>
      {v.label}{failing ? ` · ${failing}` : ""}
    </button>
  );
}

/** The panel: every check with its reason, plus the two fixes a person can make. */
export function ChecksPanel({
  api: checksApi, result, onClose, onChanged,
}: {
  api: string;
  result: CheckResult;
  onClose: () => void;
  /** Called after a save — confirming an account changes other uploads' vendor check too. */
  onChanged: () => void;
}) {
  const f = result.figures;
  const [count, setCount] = useState(f.expected_count != null ? String(f.expected_count) : "");
  const [amount, setAmount] = useState(f.expected_amount ?? "");
  const [opening, setOpening] = useState(f.opening_source === "user" && f.opening ? f.opening : "");
  const [saving, setSaving] = useState(false);
  const openingFromFile = f.opening != null && f.opening_source === "file";
  const vendorCheck = result.checks.find((c) => c.key === "vendor");
  const v = VERDICT_STYLE[result.verdict];

  const save = async () => {
    setSaving(true);
    try {
      const clear: string[] = [];
      const body: Record<string, unknown> = {};
      if (count.trim()) body.expected_count = parseInt(count.replace(/[^\d]/g, ""), 10) || 0;
      else clear.push("expected_count");
      if (amount.trim()) body.expected_amount = amount.replace(/[,\s₹]/g, "");
      else clear.push("expected_amount");
      if (!openingFromFile) {
        if (opening.trim()) body.opening_balance = opening.replace(/[,\s₹]/g, "");
        else clear.push("opening_balance");
      }
      await api.put(`${checksApi}/${result.slug}/${result.batch_id}`, { ...body, clear });
      toast.success("Control figures saved.");
      onChanged();
    } catch (e) {
      toast.error(errMsg(e, "Could not save the control figures."));
    } finally {
      setSaving(false);
    }
  };

  const confirmAccount = async () => {
    setSaving(true);
    try {
      await api.post(`${checksApi}/${result.slug}/${result.batch_id}/confirm-account`,
        { account_id: vendorCheck?.account ?? null });
      toast.success("Account confirmed for this vendor.");
      onChanged();
    } catch (e) {
      toast.error(errMsg(e, "Could not confirm the account."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-slate-100 sticky top-0 bg-white">
          <div>
            <h2 className="text-sm font-bold text-slate-900">Statement checks</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {[result.source_file, result.supplier_name].filter(Boolean).join(" · ")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${v.cls}`}>{v.label}</span>
            <button type="button" onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded-lg text-slate-400">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="px-5 py-4 space-y-5">
          <ul className="space-y-2.5">
            {result.checks.map((c) => (
              <li key={c.key} className="flex gap-2.5">
                <StatusIcon status={c.status} />
                <div className="min-w-0">
                  <p className="text-xs font-semibold text-slate-700">{c.label}</p>
                  <p className="text-xs text-slate-500">{c.detail}</p>
                  {c.confirmable && (
                    <button type="button" onClick={confirmAccount} disabled={saving}
                      className="mt-1.5 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-60">
                      <ShieldCheck className="w-3.5 h-3.5" /> Confirm {c.account} as this vendor&apos;s account
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              ["Tickets", String(f.ticket_rows)],
              ["Ticket net", amt(f.ticket_net)],
              ["Opening", `${amt(f.opening)}${f.opening_source === "user" ? " (entered)" : ""}`],
              ["Closing", amt(f.closing)],
              ["Payments in period", amt(f.payments)],
              ["Rows in file", f.file_rows == null ? "—" : String(f.file_rows)],
              ["Rows saved", f.loaded_rows == null ? "—" : String(f.loaded_rows)],
              ["Period", f.period_from ? `${f.period_from} → ${f.period_to ?? ""}` : "—"],
            ].map(([label, value]) => (
              <div key={label} className="bg-slate-50 rounded-lg px-2.5 py-2">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">{label}</p>
                <p className="text-xs font-semibold text-slate-800 mt-0.5">{value}</p>
              </div>
            ))}
          </div>

          <div className="rounded-lg border border-slate-200 p-3">
            <p className="text-xs font-semibold text-slate-700">Control figures</p>
            <p className="text-[11px] text-slate-400 mt-0.5">
              What the statement should hold. Leave a box empty to clear it.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-2">
              <label className="block">
                <span className="text-[11px] text-slate-500">Expected records</span>
                <input value={count} onChange={(e) => setCount(e.target.value)} inputMode="numeric"
                  className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
              </label>
              <label className="block">
                <span className="text-[11px] text-slate-500">Expected net amount (₹)</span>
                <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal"
                  className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
              </label>
              <label className="block">
                <span className="text-[11px] text-slate-500">Opening balance (₹)</span>
                <input value={openingFromFile ? f.opening ?? "" : opening}
                  onChange={(e) => setOpening(e.target.value)} inputMode="decimal"
                  disabled={openingFromFile}
                  title={openingFromFile ? "Read from the file's OLD line" : "The file's OLD line, if it was not captured"}
                  className="mt-1 w-full border border-slate-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 disabled:bg-slate-50 disabled:text-slate-400" />
              </label>
            </div>
            <div className="flex justify-end mt-3">
              <button type="button" onClick={save} disabled={saving}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-60">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
