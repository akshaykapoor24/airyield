"use client";

// What the Reconciliation and Payments tabs both draw with: money, ticket labels, the
// decision vocabulary of backend/app/services/payment_ledger.py, and the one small dialog
// that asks why (bulk decisions, voiding a payment).

import { useState } from "react";
import { X } from "lucide-react";
import type { DecisionStatus } from "./types";

export const inr = (n: number | null | undefined) =>
  n == null ? "—" : `₹${Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

export function errorDetail(err: unknown, fallback: string): string {
  const msg = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof msg === "string" ? msg : fallback;
}

export function ticketLabel(serial: string | null, prefix: string | null): string | null {
  return serial && prefix ? `${prefix} ${serial}` : serial;
}

/** Today as YYYY-MM-DD in the viewer's own timezone — what a date input wants. */
export function todayIso(): string {
  return new Date().toLocaleDateString("en-CA");
}

export const PAYMENT_MODES = ["NEFT", "RTGS", "IMPS", "UPI", "Cheque", "Cash", "Other"] as const;

export const DECISION_STYLE: Record<DecisionStatus, { cls: string; label: string }> = {
  approved: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Approved" },
  pending: { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Pending" },
  held: { cls: "bg-orange-50 text-orange-700 border-orange-200", label: "Held" },
  excluded: { cls: "bg-gray-100 text-gray-500 border-gray-200", label: "Excluded" },
};
const PAID_CLS = "bg-blue-50 text-blue-700 border-blue-200";

/** `decision_action` in words. An automatic "pending" has no action — its reason says why. */
export const ACTION_LABEL: Record<string, string> = {
  auto_clean: "Matched — approved automatically",
  auto_duplicate: "Duplicate — excluded automatically",
  pay_suggested: "Pay the payable after commission",
  pay_vendor: "Pay the vendor's net, as billed",
  pay_mo: "Pay our MO net",
  pay_custom: "Pay an agreed amount",
  hold: "Hold until resolved",
  exclude: "Exclude from payment",
};

/** The decision as a chip. An automatic decision has a dashed border: no person made it. */
export function DecisionChip({
  status, paid, source, title,
}: {
  status: DecisionStatus | null | undefined;
  paid?: boolean;
  source?: "auto" | "user" | null;
  title?: string;
}) {
  if (paid) {
    return <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border whitespace-nowrap ${PAID_CLS}`}>Paid</span>;
  }
  if (!status) return <span className="text-[10px] text-gray-300">—</span>;
  const st = DECISION_STYLE[status] ?? { cls: "bg-gray-100 text-gray-500 border-gray-200", label: status };
  return (
    <span title={title ?? (source === "auto" ? "Decided automatically" : undefined)}
      className={`px-2 py-0.5 rounded-full text-[10px] font-medium border whitespace-nowrap ${st.cls} ${source === "auto" ? "border-dashed" : ""}`}>
      {st.label}
    </span>
  );
}

/** A small dialog that collects remarks (and, for decisions, the Ops reference). */
export function ReasonDialog({
  title, description, confirmLabel, requireRemarks, showOpsReference, busy, danger,
  onCancel, onConfirm,
}: {
  title: string;
  description?: string;
  confirmLabel: string;
  requireRemarks: boolean;
  showOpsReference?: boolean;
  busy: boolean;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: (remarks: string, opsReference: string) => void;
}) {
  const [remarks, setRemarks] = useState("");
  const [opsRef, setOpsRef] = useState("");
  const blocked = busy || (requireRemarks && !remarks.trim());
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
            {description && <p className="text-xs text-gray-500 mt-1">{description}</p>}
          </div>
          <button type="button" onClick={onCancel} className="p-1 hover:bg-gray-100 rounded-lg text-gray-400">
            <X className="w-4 h-4" />
          </button>
        </div>
        <label className="block">
          <span className="text-[11px] text-gray-500">Remarks{requireRemarks ? " (required)" : " (optional)"}</span>
          <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={3}
            className="mt-1 w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
        </label>
        {showOpsReference && (
          <label className="block">
            <span className="text-[11px] text-gray-500">Operations reference (optional)</span>
            <input value={opsRef} onChange={(e) => setOpsRef(e.target.value)} placeholder="Email subject, ticket or call note"
              className="mt-1 w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400" />
          </label>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onCancel}
            className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">
            Cancel
          </button>
          <button type="button" disabled={blocked} onClick={() => onConfirm(remarks.trim(), opsRef.trim())}
            className={`px-4 py-1.5 text-xs font-semibold text-white rounded-lg disabled:opacity-50 ${danger ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"}`}>
            {busy ? "Saving…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
