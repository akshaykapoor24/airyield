"use client";

// Vendors data → Payment Module → Payments. Steps 11–13 of the vendor payment process.
//
// PER VENDOR STATEMENT: what it billed, what Operations' decisions leave payable, what was
// brought forward from earlier statements, and the final payable. Tickets are paid in full
// or not at all — the rest stays outstanding and is brought forward onto the next statement
// once approved. Every figure comes from the payment ledger
// (backend/app/services/payment_ledger.py), which each reconciliation run keeps in step.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle, Ban, CheckCircle2, Clock, Eye, FileText, Hourglass, Landmark, PauseCircle,
  Receipt, RefreshCw, Wallet, X, XCircle,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { PAYMENT_MODULE_API, VENDOR_STATEMENT, type PaymentTabSlug } from "@/lib/paymentModule";
import {
  ACTION_LABEL, DECISION_STYLE, DecisionChip, PAYMENT_MODES, ReasonDialog, errorDetail, inr,
  ticketLabel, todayIso,
} from "./shared";
import type {
  OutstandingPage, PayableSummary, PaymentItem, StatementBatch, VendorPayment,
  VendorPaymentDetail,
} from "./types";

const BRAND = "#1e3a5f";
const SELECT_CLS =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";
const INPUT_CLS =
  "w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400";

type View = "pay" | "outstanding" | "history";
// A vendor is a supplier id; uploads made before the agency was captured share "none".
const NO_VENDOR = "none";

const byNewest = (a: StatementBatch, b: StatementBatch) =>
  (b.uploaded_at || "").localeCompare(a.uploaded_at || "");

const vendorKey = (b: StatementBatch) => (b.supplier_id != null ? String(b.supplier_id) : NO_VENDOR);

function statementLabel(b: StatementBatch): string {
  const when = b.uploaded_at ? new Date(b.uploaded_at).toLocaleDateString() : "";
  return [b.source_file || b.batch_id, `${b.row_count} entries`, when].filter(Boolean).join(" · ");
}

/** What an unpaid item is worth: its approved amount once approved, else the suggestion. */
const itemAmount = (i: PaymentItem) =>
  i.decision_status === "approved" ? i.approved_amount : i.suggested_payable;

export default function PaymentsView({
  onOpenTab,
}: {
  onOpenTab?: (slug: PaymentTabSlug) => void;
}) {
  const [batches, setBatches] = useState<StatementBatch[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(true);
  const [vendorChoice, setVendorChoice] = useState("");
  const [statementChoice, setStatementChoice] = useState("");
  const [view, setView] = useState<View>("pay");

  const [summary, setSummary] = useState<PayableSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outstanding, setOutstanding] = useState<OutstandingPage | null>(null);
  const [payments, setPayments] = useState<VendorPayment[]>([]);

  // Approved items NOT to pay this time. Everything payable is ticked by default, so the
  // common case — pay what was approved — is one click.
  const [unticked, setUnticked] = useState<Set<number>>(new Set());
  const [payOpen, setPayOpen] = useState(false);
  const [openPayment, setOpenPayment] = useState<number | null>(null);
  const [voidTarget, setVoidTarget] = useState<VendorPayment | null>(null);
  const [voiding, setVoiding] = useState(false);

  const loadBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const { data } = await api.get<StatementBatch[]>(`${VENDOR_STATEMENT.apiBase}/batches`);
      setBatches([...(data ?? [])].sort(byNewest));
    } catch {
      toast.error("Failed to load the vendor statements.");
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => { loadBatches(); }, [loadBatches]);

  // Vendors in the order of their newest statement.
  const vendors = useMemo(() => {
    const seen = new Map<string, string>();
    for (const b of batches) {
      const k = vendorKey(b);
      if (!seen.has(k)) seen.set(k, b.supplier_name || "No agency");
    }
    return [...seen.entries()].map(([key, name]) => ({ key, name }));
  }, [batches]);

  const vendor = vendors.some((v) => v.key === vendorChoice) ? vendorChoice : vendors[0]?.key ?? "";
  const statements = useMemo(() => batches.filter((b) => vendorKey(b) === vendor), [batches, vendor]);
  const statement = statements.some((b) => b.batch_id === statementChoice)
    ? statementChoice : statements[0]?.batch_id ?? "";
  const supplierId = vendor && vendor !== NO_VENDOR ? Number(vendor) : null;

  const fetchSummary = useCallback(async () => {
    if (!statement) { setSummary(null); return; }
    setSummaryLoading(true); setError(null);
    try {
      const { data } = await api.get<PayableSummary>(`${PAYMENT_MODULE_API}/payable`, {
        params: { vendor_batch_id: statement },
      });
      setSummary(data);
      setUnticked(new Set());
    } catch (err) {
      setError(errorDetail(err, "Failed to load what this statement leaves payable."));
      setSummary(null);
    } finally {
      setSummaryLoading(false);
    }
  }, [statement]);

  const fetchVendorWide = useCallback(async () => {
    if (!vendor) { setOutstanding(null); setPayments([]); return; }
    const params = supplierId != null ? { supplier_id: supplierId } : {};
    try {
      const [o, p] = await Promise.all([
        api.get<OutstandingPage>(`${PAYMENT_MODULE_API}/outstanding`, { params }),
        api.get<VendorPayment[]>(`${PAYMENT_MODULE_API}/payments`, { params }),
      ]);
      // "No agency" cannot be filtered server-side — keep only the unattributed rows.
      const own = <T extends { supplier_id: number | null }>(rows: T[]) =>
        supplierId != null ? rows : rows.filter((r) => r.supplier_id == null);
      setOutstanding({ ...o.data, items: own(o.data.items) });
      setPayments(own(p.data));
    } catch {
      toast.error("Failed to load the vendor's outstanding tickets and payments.");
    }
  }, [vendor, supplierId]);

  useEffect(() => { fetchSummary(); }, [fetchSummary]);
  useEffect(() => { fetchVendorWide(); }, [fetchVendorWide]);

  const refreshAll = () => { fetchSummary(); fetchVendorWide(); };
  const closePayment = useCallback(() => setOpenPayment(null), []);

  const payable = summary?.items ?? [];
  const ticked = payable.filter((i) => !unticked.has(i.id));
  const tickedTotal = ticked.reduce((t, i) => t + (i.approved_amount ?? 0), 0);
  const allTicked = payable.length > 0 && unticked.size === 0;

  const toggle = (id: number) => setUnticked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAll = () => setUnticked(allTicked ? new Set(payable.map((i) => i.id)) : new Set());

  const voidPayment = async (reason: string) => {
    if (!voidTarget) return;
    setVoiding(true);
    try {
      await api.post(`${PAYMENT_MODULE_API}/payments/${voidTarget.id}/void`, { reason });
      toast.success("Payment voided — its tickets are unpaid again, with their decisions kept.");
      setVoidTarget(null);
      setOpenPayment(null);
      refreshAll();
    } catch (err) {
      toast.error(errorDetail(err, "Could not void the payment."));
    } finally {
      setVoiding(false);
    }
  };

  if (!batchesLoading && !batches.length) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-12 text-center space-y-3">
        <Wallet className="w-8 h-8 text-gray-300 mx-auto" />
        <p className="text-sm text-gray-600">No vendor statements yet — upload one, reconcile it, then pay it here.</p>
        <button type="button" onClick={() => onOpenTab?.("vendor")}
          className="px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
          Go to Vendor Statement
        </button>
      </div>
    );
  }

  const s = summary;
  const counts = s?.counts ?? {};
  const reconciled = !!s && s.tickets > 0;

  return (
    <div className="space-y-5 pb-16">
      {/* vendor + statement */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_2fr] gap-3">
          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-gray-400">Vendor</span>
            <select value={vendor} onChange={(e) => { setVendorChoice(e.target.value); setStatementChoice(""); }}
              disabled={batchesLoading} className={`${SELECT_CLS} w-full mt-1`}>
              {vendors.map((v) => <option key={v.key} value={v.key}>{v.name}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-gray-400">Vendor statement</span>
            <select value={statement} onChange={(e) => setStatementChoice(e.target.value)}
              disabled={batchesLoading} className={`${SELECT_CLS} w-full mt-1`}>
              {statements.map((b) => <option key={b.batch_id} value={b.batch_id}>{statementLabel(b)}</option>)}
            </select>
          </label>
        </div>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs text-gray-500">
            {reconciled
              ? <>{s!.tickets.toLocaleString()} billed ticket{s!.tickets === 1 ? "" : "s"} on this statement.</>
              : summaryLoading ? "Loading…" : "This statement has not been reconciled yet."}
          </p>
          <button type="button" onClick={() => { loadBatches(); refreshAll(); }} disabled={summaryLoading}
            className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${summaryLoading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {s && !reconciled && !summaryLoading && (
        <div className="flex items-start gap-2 px-4 py-3 border rounded-xl text-xs bg-amber-50 border-amber-200 text-amber-800">
          <AlertCircle className="w-4 h-4 shrink-0 mt-px" />
          <p className="leading-relaxed">
            A statement&apos;s payable is built when it is reconciled against its MO statement — each billed ticket
            gets a decision there.{" "}
            <button type="button" onClick={() => onOpenTab?.("reconciliation")} className="font-semibold underline underline-offset-2">
              Go to Reconciliation
            </button>
          </p>
        </div>
      )}

      {/* step 11: payable */}
      {s && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <Tile icon={Receipt} label="Billed" value={s.billed} sub={`${s.tickets} tickets · shortfall ${inr(s.commission_shortfall)}`} />
          <Tile icon={XCircle} label="Excluded" value={s.excluded} sub={`${counts.excluded ?? 0} tickets — duplicates or removed`} />
          <Tile icon={Hourglass} label="Pending" value={s.pending} sub={`${counts.pending ?? 0} awaiting Operations`} tone="text-amber-600" />
          <Tile icon={PauseCircle} label="Held" value={s.held} sub={`${counts.held ?? 0} carried forward`} tone="text-orange-600" />
          <Tile icon={CheckCircle2} label="Approved" value={s.approved} sub={`${counts.approved ?? 0} unpaid on this statement`} tone="text-emerald-600" />
          <Tile icon={Clock} label="Brought forward" value={s.brought_forward} sub={`${counts.brought_forward ?? 0} approved on earlier statements`} />
          <Tile icon={Landmark} label="Paid" value={s.paid} sub={`${counts.paid ?? 0} tickets from this statement`} tone="text-blue-600" />
          <Tile icon={Wallet} label="Final payable" value={s.final_payable} sub="approved + brought forward" hero />
        </div>
      )}

      {/* views */}
      <div className="flex items-center gap-1 border-b border-gray-200">
        {([
          ["pay", `Pay now${payable.length ? ` (${payable.length})` : ""}`],
          ["outstanding", `Outstanding${outstanding?.items.length ? ` (${outstanding.items.length})` : ""}`],
          ["history", `Payment history${payments.length ? ` (${payments.length})` : ""}`],
        ] as [View, string][]).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setView(k)}
            className={`px-3 py-2 text-xs font-semibold border-b-2 -mb-px ${view === k
              ? "border-blue-600 text-blue-700" : "border-transparent text-gray-500 hover:text-gray-800"}`}>
            {label}
          </button>
        ))}
      </div>

      {view === "pay" && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ background: BRAND }}>
                  <th className="pl-3 pr-1 py-2.5 w-8">
                    <input type="checkbox" checked={allTicked} onChange={toggleAll} disabled={!payable.length}
                      aria-label="Select every payable ticket" className="cursor-pointer" />
                  </th>
                  {["Ticket #", "Passenger", "Airline", "From", "Decision", "Vendor net", "Approved"].map((h, i) => (
                    <th key={h} className={`px-3 py-2.5 text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap ${i >= 5 ? "text-right" : "text-left"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {summaryLoading ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-sm text-gray-400">
                    <RefreshCw className="w-5 h-5 text-blue-400 animate-spin mx-auto mb-2" />Loading…
                  </td></tr>
                ) : !payable.length ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-sm text-gray-400">
                    Nothing is approved and unpaid for this vendor yet. Approve tickets under{" "}
                    <button type="button" onClick={() => onOpenTab?.("reconciliation")} className="text-blue-600 hover:underline">Reconciliation</button>.
                  </td></tr>
                ) : payable.map((i) => {
                  const brought = i.vendor_batch_id !== statement;
                  return (
                    <tr key={i.id} onClick={() => toggle(i.id)}
                      className={`border-b border-gray-100 cursor-pointer ${unticked.has(i.id) ? "opacity-50" : "hover:bg-gray-50/70"}`}>
                      <td className="pl-3 pr-1 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={!unticked.has(i.id)} onChange={() => toggle(i.id)}
                          aria-label={`Pay ticket ${i.ticket_number ?? i.id}`} className="cursor-pointer" />
                      </td>
                      <td className="px-3 py-2.5 text-xs font-medium text-gray-800 whitespace-nowrap">
                        {ticketLabel(i.ticket_number, i.ticket_prefix) || i.ticket_key}
                        {i.booking_id && <span className="block text-[10px] text-gray-400 font-normal">Booking {i.booking_id}</span>}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[180px] truncate" title={i.pax_name ?? ""}>{i.pax_name || "—"}</td>
                      <td className="px-3 py-2.5 text-xs text-gray-600 whitespace-nowrap">{i.airline_name || "—"}</td>
                      <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                        {brought
                          ? <span className="text-orange-600" title={i.vendor_source_file ?? ""}>Brought forward · {i.vendor_source_file || "earlier statement"}</span>
                          : <span className="text-gray-500">This statement</span>}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap" title={i.remarks ?? i.decision_reason ?? ""}>
                        <DecisionChip status={i.decision_status} source={i.decision_source} />
                        <span className="block text-[10px] text-gray-400 mt-0.5">
                          {i.decision_action ? ACTION_LABEL[i.decision_action] ?? i.decision_action : ""}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-right text-gray-600 whitespace-nowrap">{inr(i.vendor_net)}</td>
                      <td className="px-3 py-2.5 text-xs text-right font-semibold text-gray-900 whitespace-nowrap">{inr(i.approved_amount)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {payable.length > 0 && (
            <div className="flex items-center justify-between gap-3 flex-wrap px-4 py-3 border-t border-gray-100">
              <p className="text-xs text-gray-500">
                {ticked.length} of {payable.length} selected · <b className="text-gray-900">{inr(tickedTotal)}</b>
                {ticked.length > 0 && tickedTotal <= 0
                  ? <span className="text-amber-600"> — refunds outweigh sales here, so there is nothing to pay. Tick sales too, or carry the credit forward.</span>
                  : <span className="text-gray-400"> — tickets are paid in full; anything left unticked stays payable.</span>}
              </p>
              <button type="button" onClick={() => setPayOpen(true)} disabled={!ticked.length || tickedTotal <= 0}
                className="flex items-center gap-1.5 px-4 py-2 text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50"
                style={{ backgroundColor: BRAND }}>
                <Landmark className="w-3.5 h-3.5" /> Record payment
              </button>
            </div>
          )}
        </div>
      )}

      {view === "outstanding" && (
        <OutstandingTable page={outstanding} currentStatement={statement} />
      )}

      {view === "history" && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  {["Paid on", "Amount", "Mode", "Reference", "Tickets", "Statement", "Status", ""].map((h, i) => (
                    <th key={h || i} className={`px-3 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap ${i === 1 || i === 4 ? "text-right" : "text-left"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!payments.length ? (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-sm text-gray-400">No payments recorded for this vendor yet.</td></tr>
                ) : payments.map((p) => (
                  <tr key={p.id} className={`border-b border-gray-100 ${p.status === "voided" ? "text-gray-400" : ""}`}>
                    <td className="px-3 py-2.5 text-xs whitespace-nowrap">{p.payment_date}</td>
                    <td className={`px-3 py-2.5 text-xs text-right font-semibold whitespace-nowrap ${p.status === "voided" ? "line-through" : "text-gray-900"}`}>{inr(p.amount)}</td>
                    <td className="px-3 py-2.5 text-xs whitespace-nowrap">{p.mode || "—"}</td>
                    <td className="px-3 py-2.5 text-xs whitespace-nowrap max-w-[160px] truncate" title={p.reference ?? ""}>{p.reference || "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-right">{p.items_count}</td>
                    <td className="px-3 py-2.5 text-xs max-w-[200px] truncate" title={p.vendor_source_file ?? ""}>{p.vendor_source_file || "—"}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {p.status === "voided"
                        ? <span className="px-2 py-0.5 rounded-full text-[10px] font-medium border bg-gray-100 text-gray-500 border-gray-200" title={p.void_reason ?? ""}>Voided</span>
                        : <span className="px-2 py-0.5 rounded-full text-[10px] font-medium border bg-emerald-50 text-emerald-700 border-emerald-200">Completed</span>}
                    </td>
                    <td className="px-3 py-2.5 text-right whitespace-nowrap">
                      <button type="button" onClick={() => setOpenPayment(p.id)} className="p-1 text-gray-400 hover:text-blue-600" title="View tickets">
                        <Eye className="w-3.5 h-3.5" />
                      </button>
                      {p.status !== "voided" && (
                        <button type="button" onClick={() => setVoidTarget(p)} className="p-1 text-gray-400 hover:text-red-600 ml-1" title="Void payment">
                          <Ban className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {payOpen && s && (
        <RecordPaymentDialog
          supplierId={s.supplier_id} supplierName={s.supplier_name} vendorBatchId={statement}
          items={ticked} total={tickedTotal}
          onClose={() => setPayOpen(false)}
          onDone={() => { setPayOpen(false); refreshAll(); }}
        />
      )}

      {openPayment != null && (
        <PaymentDetailDialog paymentId={openPayment} onClose={closePayment}
          onVoid={(p) => setVoidTarget(p)} />
      )}

      {voidTarget && (
        <ReasonDialog
          title={`Void the ${inr(voidTarget.amount)} payment of ${voidTarget.payment_date}?`}
          description={`Its ${voidTarget.items_count} ticket${voidTarget.items_count === 1 ? "" : "s"} return to unpaid, keeping their decisions. The payment stays in the history, marked void.`}
          confirmLabel="Void payment" requireRemarks busy={voiding} danger
          onCancel={() => setVoidTarget(null)} onConfirm={(reason) => voidPayment(reason)}
        />
      )}
    </div>
  );
}

function Tile({
  icon: Icon, label, value, sub, tone, hero,
}: {
  icon: typeof Receipt;
  label: string;
  value: number | null | undefined;
  sub?: string;
  tone?: string;
  hero?: boolean;
}) {
  return (
    <div className={`rounded-xl border p-4 ${hero ? "bg-[#1e3a5f] border-[#1e3a5f]" : "bg-white border-gray-200"}`}>
      <div className={`p-2 rounded-lg w-fit mb-2 ${hero ? "bg-white/15 text-white" : "bg-slate-50 text-slate-600"}`}>
        <Icon className="w-4 h-4" />
      </div>
      <p className={`text-xl font-bold ${hero ? "text-white" : tone || "text-gray-900"}`}>{inr(value ?? null)}</p>
      <p className={`text-xs mt-0.5 ${hero ? "text-white/80" : "text-gray-500"}`}>{label}</p>
      {sub && <p className={`text-[10px] mt-0.5 ${hero ? "text-white/60" : "text-gray-400"}`}>{sub}</p>}
    </div>
  );
}

/** Step 13: every unpaid ticket of this vendor still owed or in question, oldest first. */
function OutstandingTable({ page, currentStatement }: { page: OutstandingPage | null; currentStatement: string }) {
  const items = page?.items ?? [];
  const totals = page?.totals ?? {};
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        {(["approved", "pending", "held"] as const).map((k) => (
          <span key={k} className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium ${DECISION_STYLE[k].cls}`}>
            {DECISION_STYLE[k].label} {totals[k]?.count ?? 0} · {inr(totals[k]?.amount ?? 0)}
          </span>
        ))}
        <span className="text-[11px] text-gray-400">Pending and held amounts are the payable after commission, until a decision fixes them.</span>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                {["Statement", "Ticket #", "Passenger", "Decision", "Why", "Amount", "Age"].map((h, i) => (
                  <th key={h} className={`px-3 py-2.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap ${i >= 5 ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {!items.length ? (
                <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">Nothing outstanding for this vendor.</td></tr>
              ) : items.map((i) => (
                <tr key={i.id} className="border-b border-gray-100">
                  <td className="px-3 py-2.5 text-xs max-w-[200px] truncate" title={i.vendor_source_file ?? ""}>
                    <span className={i.vendor_batch_id === currentStatement ? "text-gray-800 font-medium" : "text-gray-600"}>
                      {i.vendor_source_file || i.vendor_batch_id}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs font-medium text-gray-800 whitespace-nowrap">{ticketLabel(i.ticket_number, i.ticket_prefix) || i.ticket_key}</td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[160px] truncate" title={i.pax_name ?? ""}>{i.pax_name || "—"}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap"><DecisionChip status={i.decision_status} source={i.decision_source} /></td>
                  <td className="px-3 py-2.5 text-[11px] text-gray-500 max-w-[320px]">
                    {i.remarks || i.decision_reason || (i.decision_action ? ACTION_LABEL[i.decision_action] : "—")}
                    {i.ops_reference && <span className="text-gray-400"> · Ops ref {i.ops_reference}</span>}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-right font-semibold text-gray-900 whitespace-nowrap">{inr(itemAmount(i))}</td>
                  <td className="px-3 py-2.5 text-xs text-right text-gray-500 whitespace-nowrap">
                    {i.age_days == null ? "—" : `${i.age_days} day${i.age_days === 1 ? "" : "s"}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/** Step 12: pay the ticked tickets in full and mark them paid. */
function RecordPaymentDialog({
  supplierId, supplierName, vendorBatchId, items, total, onClose, onDone,
}: {
  supplierId: number | null;
  supplierName: string | null;
  vendorBatchId: string;
  items: PaymentItem[];
  total: number;
  onClose: () => void;
  onDone: () => void;
}) {
  const [date, setDate] = useState(todayIso());
  const [mode, setMode] = useState<string>("NEFT");
  const [reference, setReference] = useState("");
  const [remarks, setRemarks] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!date) { toast.error("Enter the payment date."); return; }
    setSaving(true);
    try {
      const { data } = await api.post<VendorPayment>(`${PAYMENT_MODULE_API}/payments`, {
        supplier_id: supplierId, vendor_batch_id: vendorBatchId, item_ids: items.map((i) => i.id),
        payment_date: date, mode, reference: reference.trim() || null, remarks: remarks.trim() || null,
      });
      toast.success(`Payment of ${inr(data.amount)} recorded for ${data.items_count} ticket${data.items_count === 1 ? "" : "s"}.`);
      onDone();
    } catch (err) {
      toast.error(errorDetail(err, "Could not record the payment."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Record payment</h2>
            <p className="text-xs text-gray-500 mt-1">
              {items.length} ticket{items.length === 1 ? "" : "s"} to {supplierName || "this vendor"}, paid in full.
            </p>
          </div>
          <button type="button" onClick={onClose} className="p-1 hover:bg-gray-100 rounded-lg text-gray-400"><X className="w-4 h-4" /></button>
        </div>
        <div className="rounded-lg bg-gray-50 px-3 py-2.5">
          <p className="text-[10px] uppercase tracking-wide text-gray-400">Amount</p>
          <p className="text-lg font-bold text-gray-900">{inr(total)}</p>
          <p className="text-[10px] text-gray-400">The sum of the approved amounts — change a ticket&apos;s decision to change it.</p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="text-[11px] text-gray-500">Payment date</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={`${INPUT_CLS} mt-1`} />
          </label>
          <label className="block">
            <span className="text-[11px] text-gray-500">Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)} className={`${INPUT_CLS} mt-1 bg-white`}>
              {PAYMENT_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        </div>
        <label className="block">
          <span className="text-[11px] text-gray-500">Reference (UTR / cheque number)</span>
          <input value={reference} onChange={(e) => setReference(e.target.value)} className={`${INPUT_CLS} mt-1`} />
        </label>
        <label className="block">
          <span className="text-[11px] text-gray-500">Remarks</span>
          <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={2} className={`${INPUT_CLS} mt-1`} />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 text-xs font-medium text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50">Cancel</button>
          <button type="button" onClick={submit} disabled={saving || !items.length}
            className="px-4 py-1.5 text-xs font-semibold text-white rounded-lg hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: BRAND }}>
            {saving ? "Recording…" : `Record ${inr(total)}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function PaymentDetailDialog({
  paymentId, onClose, onVoid,
}: {
  paymentId: number;
  onClose: () => void;
  onVoid: (p: VendorPayment) => void;
}) {
  const [p, setP] = useState<VendorPaymentDetail | null>(null);

  useEffect(() => {
    let live = true;
    api.get<VendorPaymentDetail>(`${PAYMENT_MODULE_API}/payments/${paymentId}`)
      .then((r) => { if (live) setP(r.data); })
      .catch(() => { toast.error("Failed to load the payment."); onClose(); });
    return () => { live = false; };
  }, [paymentId, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-3xl max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <div>
            <h2 className="text-sm font-bold text-gray-900 flex items-center gap-2">
              <FileText className="w-4 h-4 text-gray-400" />
              {p ? `${inr(p.amount)} on ${p.payment_date}` : "Payment"}
            </h2>
            {p && (
              <p className="text-xs text-gray-500 mt-0.5">
                {[p.supplier_name, p.mode, p.reference && `Ref ${p.reference}`, p.vendor_source_file].filter(Boolean).join(" · ")}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {p && p.status !== "voided" && (
              <button type="button" onClick={() => onVoid(p)}
                className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-red-600 border border-red-200 rounded-lg hover:bg-red-50">
                <Ban className="w-3.5 h-3.5" /> Void
              </button>
            )}
            <button type="button" onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400"><X className="w-4 h-4" /></button>
          </div>
        </div>
        {!p ? (
          <div className="px-5 py-12 text-center text-sm text-gray-400">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…
          </div>
        ) : (
          <div className="px-5 py-4 space-y-3">
            {p.status === "voided" && (
              <p className="px-3 py-2 rounded-lg border border-gray-200 bg-gray-50 text-xs text-gray-600">
                Voided{p.voided_at && <> on {new Date(p.voided_at).toLocaleString()}</>} — {p.void_reason}. Its tickets are unpaid again.
              </p>
            )}
            {p.remarks && <p className="text-xs text-gray-600">“{p.remarks}”</p>}
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  {["Ticket #", "Passenger", "Statement", "Decision", "Amount"].map((h, i) => (
                    <th key={h} className={`py-1.5 pr-2 text-[10px] font-semibold text-gray-400 uppercase whitespace-nowrap ${i === 4 ? "text-right" : "text-left"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {p.items.length === 0 ? (
                  <tr><td colSpan={5} className="py-6 text-center text-xs text-gray-400">
                    {p.status === "voided" ? "The tickets were released when the payment was voided." : "No tickets."}
                  </td></tr>
                ) : p.items.map((i) => (
                  <tr key={i.id} className="border-b border-gray-50 last:border-0">
                    <td className="py-1.5 pr-2 text-xs font-medium text-gray-800 whitespace-nowrap">{ticketLabel(i.ticket_number, i.ticket_prefix) || i.ticket_key}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-600">{i.pax_name || "—"}</td>
                    <td className="py-1.5 pr-2 text-xs text-gray-500 max-w-[200px] truncate" title={i.vendor_source_file ?? ""}>{i.vendor_source_file || "—"}</td>
                    <td className="py-1.5 pr-2 text-[11px] text-gray-500">{i.decision_action ? ACTION_LABEL[i.decision_action] ?? i.decision_action : "—"}</td>
                    <td className="py-1.5 text-xs text-right font-semibold text-gray-900">{inr(i.paid_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
