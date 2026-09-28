"use client";

import { useCallback, useEffect, useState } from "react";
import { Ban, CheckCircle2, Download, FilePlus2, Mail, RotateCcw } from "lucide-react";
import api from "@/lib/api";
import { rupees } from "@/lib/money";
import { INPUT, LABEL, ModalShell, apiError } from "@/components/userMaster/shared";
import { STATUS_CHIP, downloadInvoicePdf, fmtDate, type Invoice } from "./shared";

type Action = { id: number; kind: "send" | "paid" | "cancel" } | null;

// The local calendar date, as YYYY-MM-DD. Not toISOString(): that is UTC, which in India is
// still yesterday until 05:30 — a payment recorded at 1 a.m. would be dated a day early.
const today = () => new Date().toLocaleDateString("en-CA");

function IconButton({ title, onClick, children, tone = "hover:text-violet-700 hover:bg-violet-50" }: {
  title: string; onClick: () => void; children: React.ReactNode; tone?: string;
}) {
  return (
    <button title={title} onClick={onClick} className={`p-1.5 rounded-md text-gray-400 ${tone}`}>
      {children}
    </button>
  );
}

/**
 * One workspace's invoices, newest first. Payment is recorded by hand (there is no gateway),
 * and a mistake is cancelled with a reason — never deleted, so its number stays accounted for.
 */
export default function InvoiceHistoryModal({ tenantId, tenantName, ownerEmail, highlightId, onClose, onChanged, onGenerate }: {
  tenantId: number;
  tenantName: string;
  ownerEmail: string | null;
  /** The invoice just generated, flagged in the list. */
  highlightId?: number;
  onClose: () => void;
  /** Something changed — the Subscriptions table's Invoice column should reload. */
  onChanged: () => void;
  onGenerate: () => void;
}) {
  const [rows, setRows] = useState<Invoice[] | null>(null);
  const [error, setError] = useState("");
  const [action, setAction] = useState<Action>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [fields, setFields] = useState({ to: "", message: "", paid_at: today(), reference: "", reason: "" });

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<Invoice[]>(`/subscriptions/${tenantId}/invoices`);
      setRows(data);
    } catch (e) {
      setError(apiError(e));
    }
  }, [tenantId]);

  useEffect(() => { load(); }, [load]);

  const open = (inv: Invoice, kind: NonNullable<Action>["kind"]) => {
    setActionError("");
    setFields({ to: inv.sent_to || inv.bill_to.email || ownerEmail || "", message: "", paid_at: today(), reference: "", reason: "" });
    setAction(action?.id === inv.id && action.kind === kind ? null : { id: inv.id, kind });
  };

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError("");
    try {
      await fn();
      setAction(null);
      await load();
      onChanged();
    } catch (e) {
      setActionError(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const download = (inv: Invoice) => downloadInvoicePdf(inv).catch((e) => setError(apiError(e)));

  return (
    <ModalShell title={`Invoices — ${tenantName}`} onClose={onClose} wide>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-[11px] text-gray-400">
            Mark an invoice paid when the money arrives. A wrong invoice is cancelled, not deleted — its number stays in the series.
          </p>
          <button onClick={onGenerate} className="inline-flex items-center gap-1 shrink-0 text-[11px] font-medium text-violet-700 hover:text-violet-900">
            <FilePlus2 className="w-3.5 h-3.5" /> New invoice
          </button>
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-600 text-xs rounded-lg px-3 py-2">{error}</div>}
        {!rows && !error && <p className="text-xs text-gray-400 py-6 text-center">Loading…</p>}
        {rows && rows.length === 0 && <p className="text-xs text-gray-400 py-6 text-center">No invoices yet.</p>}

        {rows && rows.length > 0 && (
          <div className="border border-gray-100 rounded-lg divide-y divide-gray-100">
            {rows.map((inv) => (
              <div key={inv.id} className={inv.id === highlightId ? "bg-violet-50/40" : undefined}>
                <div className="flex items-center gap-3 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-gray-900">{inv.invoice_number}</span>
                      <span className={`inline-flex px-1.5 py-0.5 rounded-full text-[10px] font-medium border ${inv.overdue ? "bg-red-50 text-red-600 border-red-200" : STATUS_CHIP[inv.status]}`}>
                        {inv.overdue ? "overdue" : inv.status === "issued" ? "unpaid" : inv.status}
                      </span>
                      {inv.id === highlightId && <span className="text-[10px] text-violet-600">just generated</span>}
                    </div>
                    <p className="text-[10px] text-gray-400 mt-0.5 truncate">
                      {fmtDate(inv.invoice_date)}
                      {inv.period_from && <> · for {fmtDate(inv.period_from)} – {fmtDate(inv.period_to)}</>}
                      {inv.due_date && inv.status === "issued" && <> · due {fmtDate(inv.due_date)}</>}
                      {inv.status === "paid" && <> · paid {fmtDate(inv.paid_at)}{inv.payment_reference && ` (${inv.payment_reference})`}</>}
                      {inv.status === "cancelled" && inv.cancel_reason && <> · {inv.cancel_reason}</>}
                      {inv.sent_at && <> · emailed to {inv.sent_to}</>}
                    </p>
                  </div>
                  <span className={`text-xs font-semibold tabular-nums ${inv.status === "cancelled" ? "text-gray-300 line-through" : "text-gray-900"}`}>
                    {rupees(inv.grand_total, 2)}
                  </span>
                  <div className="flex items-center">
                    <IconButton title="Download PDF" onClick={() => download(inv)}><Download className="w-3.5 h-3.5" /></IconButton>
                    {inv.status !== "cancelled" && (
                      <IconButton title="Email to the customer" onClick={() => open(inv, "send")}><Mail className="w-3.5 h-3.5" /></IconButton>
                    )}
                    {inv.status === "issued" && (
                      <IconButton title="Mark as paid" onClick={() => open(inv, "paid")} tone="hover:text-green-700 hover:bg-green-50">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      </IconButton>
                    )}
                    {inv.status === "paid" && (
                      <IconButton title="Mark as unpaid" onClick={() => run(() => api.patch(`/subscriptions/invoices/${inv.id}`, { status: "issued" }))}>
                        <RotateCcw className="w-3.5 h-3.5" />
                      </IconButton>
                    )}
                    {inv.status !== "cancelled" && (
                      <IconButton title="Cancel invoice" onClick={() => open(inv, "cancel")} tone="hover:text-red-600 hover:bg-red-50">
                        <Ban className="w-3.5 h-3.5" />
                      </IconButton>
                    )}
                  </div>
                </div>

                {action?.id === inv.id && (
                  <div className="px-3 pb-3">
                    <div className="rounded-lg bg-gray-50 border border-gray-100 p-3 space-y-3">
                      {action.kind === "send" && (
                        <>
                          <div>
                            <label className={LABEL}>Send to</label>
                            <input className={INPUT} value={fields.to} onChange={(e) => setFields({ ...fields, to: e.target.value })} />
                          </div>
                          <div>
                            <label className={LABEL}>Message (optional)</label>
                            <textarea className={INPUT} rows={2} value={fields.message} onChange={(e) => setFields({ ...fields, message: e.target.value })} />
                          </div>
                          <p className="text-[10px] text-gray-400">The PDF is attached. Sent from the platform&apos;s email address.</p>
                        </>
                      )}
                      {action.kind === "paid" && (
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className={LABEL}>Paid on</label>
                            <input type="date" className={INPUT} value={fields.paid_at} onChange={(e) => setFields({ ...fields, paid_at: e.target.value })} />
                          </div>
                          <div>
                            <label className={LABEL}>Payment reference</label>
                            <input className={INPUT} value={fields.reference} placeholder="UTR, cheque no., UPI id…"
                              onChange={(e) => setFields({ ...fields, reference: e.target.value })} />
                          </div>
                        </div>
                      )}
                      {action.kind === "cancel" && (
                        <div>
                          <label className={LABEL}>Reason (printed on the invoice)</label>
                          <input className={INPUT} value={fields.reason} placeholder="e.g. Raised against the wrong period"
                            onChange={(e) => setFields({ ...fields, reason: e.target.value })} />
                          <p className="mt-1 text-[10px] text-gray-400">Cancelling can&apos;t be undone. Raise a new invoice for the right amount.</p>
                        </div>
                      )}
                      {actionError && <p className="text-[11px] text-red-500">{actionError}</p>}
                      <div className="flex justify-end gap-2">
                        <button onClick={() => setAction(null)} className="px-3 py-1.5 rounded-lg text-xs text-gray-600 border border-gray-200 bg-white hover:bg-gray-50">
                          Close
                        </button>
                        <button
                          disabled={busy || (action.kind === "send" && !fields.to.trim()) || (action.kind === "cancel" && !fields.reason.trim())}
                          onClick={() => run(() =>
                            action.kind === "send"
                              ? api.post(`/subscriptions/invoices/${inv.id}/send`, { to: fields.to.trim(), message: fields.message.trim() || null })
                              : action.kind === "paid"
                                ? api.patch(`/subscriptions/invoices/${inv.id}`, { status: "paid", paid_at: fields.paid_at || null, payment_reference: fields.reference.trim() || null })
                                : api.patch(`/subscriptions/invoices/${inv.id}`, { status: "cancelled", cancel_reason: fields.reason.trim() }),
                          )}
                          className={`px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-50 ${action.kind === "cancel" ? "bg-red-600 hover:bg-red-700" : action.kind === "paid" ? "bg-green-600 hover:bg-green-700" : "bg-violet-600 hover:bg-violet-700"}`}
                        >
                          {busy ? "Working…" : action.kind === "send" ? "Send invoice" : action.kind === "paid" ? "Mark as paid" : "Cancel invoice"}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </ModalShell>
  );
}
