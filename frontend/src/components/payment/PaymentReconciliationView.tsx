"use client";

// Vendors data → Payment Module → Reconciliation.
//
// ONE PAIR AT A TIME: a vendor upload (the consolidator's Third Party GDS statement) against
// an MO upload (our own mid-office record), because a payment is made per statement. Each
// ticket shows both sides, the variance (always vendor − MO), and the commission Commission
// income calculated on the vendor's rows — which is what turns the bill into the amount
// actually payable.
//
// Steps 6–10 of the vendor payment process happen here. The checks strip says whether both
// statements are complete and the right vendor's. Calculate income prices the vendor's
// tickets with the MO statement's class, sector and travel date filling what the vendor
// leaves blank. Every ticket carries its process flags (duplicate, not billed, in another
// vendor's MO, filled from MO) and the payment decision on it — automatic until a person
// records what Operations decided, and kept across re-runs.
//
// The pickers read the two uploads lists the statement tabs themselves use, and the MO
// picker suggests the newest MO upload for the same agency until one is chosen by hand.

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertCircle, AlertTriangle, Calculator, CheckCircle2, ChevronLeft, ChevronRight, FileX,
  GitMerge, Info, Landmark, Play, Receipt, RefreshCw, Scale, Search, Ticket as TicketIcon,
  Wallet, X,
} from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import {
  COMMISSION_TP_GDS_HREF, MO_CHECKS, MO_STATEMENT, PAYMENT_CHECKS_API, PAYMENT_MODULE_API,
  PAYMENT_RECON_API, VENDOR_CHECKS, VENDOR_STATEMENT, type PaymentTabSlug,
} from "@/lib/paymentModule";
import { ChecksBadge, ChecksPanel, type CheckResult } from "@/components/statements/StatementChecks";
import {
  ACTION_LABEL, DECISION_STYLE, DecisionChip, ReasonDialog, errorDetail, inr, ticketLabel,
} from "./shared";
import type {
  CalculateIncomeResult, CommissionDetailEntry, CommissionStatus, PaymentDetail,
  PaymentFacets, PaymentPage, PaymentRow, PaymentRunResult, PaymentStatus, StatementBatch,
  StatementRecord,
} from "./types";

const BRAND = "#1e3a5f";
const PAGE_SIZE = 50;
const SELECT_CLS =
  "py-2 px-2.5 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 text-gray-600 bg-white";
const INPUT_CLS =
  "w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400";

const STATUS_STYLE: Record<PaymentStatus, { cls: string; label: string }> = {
  matched: { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Matched" },
  minor_diff: { cls: "bg-amber-50 text-amber-700 border-amber-200", label: "Minor Diff" },
  mismatch: { cls: "bg-red-50 text-red-700 border-red-200", label: "Mismatch" },
  possible_match: { cls: "bg-blue-50 text-blue-700 border-blue-200", label: "Possible Match" },
  // Billed but not in our books is the one to stop a payment over — red, like a mismatch.
  vendor_only: { cls: "bg-red-50 text-red-700 border-red-200", label: "Vendor only" },
  mo_only: { cls: "bg-purple-50 text-purple-700 border-purple-200", label: "MO only" },
};

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "matched", label: "Matched" },
  { value: "minor_diff", label: "Minor difference" },
  { value: "mismatch", label: "Mismatch" },
  { value: "possible_match", label: "Possible match" },
  { value: "vendor_only", label: "Billed, not in MO" },
  { value: "mo_only", label: "In MO, not billed" },
];

const DECISION_OPTIONS = [
  { value: "", label: "All decisions" },
  { value: "approved", label: "Approved, unpaid" },
  { value: "pending", label: "Pending" },
  { value: "held", label: "Held" },
  { value: "excluded", label: "Excluded" },
  { value: "paid", label: "Paid" },
  { value: "none", label: "No decision (MO only)" },
];

const FLAG_OPTIONS = [
  { value: "", label: "All flags" },
  { value: "duplicate", label: "Duplicate" },
  { value: "not_billed", label: "Not billed in MO" },
  { value: "other_vendor", label: "In another vendor's MO" },
  { value: "enriched", label: "Filled from MO" },
];

const ENRICHED_LABEL: Record<string, string> = {
  booking_class: "class", sector: "sector", travel_date: "travel date",
};

const COMMISSION_STYLE: Record<CommissionStatus, { cls: string; label: string; title: string }> = {
  priced: { cls: "text-emerald-600", label: "Priced",
    title: "Every sale row of this ticket was priced by a deal." },
  partial: { cls: "text-amber-600", label: "Partly priced",
    title: "Some rows were priced; others had no deal, need data, or their arithmetic does not close." },
  unpriced: { cls: "text-gray-400", label: "Not priced",
    title: "Commission income ran, but no deal priced this ticket." },
  skipped: { cls: "text-gray-400", label: "Not a sale",
    title: "Only cancelled or void rows — there is nothing to price." },
  not_run: { cls: "text-gray-400", label: "Not run",
    title: "Income has not been calculated on this vendor statement." },
  none: { cls: "text-gray-300", label: "—", title: "No vendor rows — nothing to price." },
};

const MATCH_METHOD_LABEL: Record<string, string> = {
  ticket_number: "paired on the ticket number",
  pnr_pax: "paired on PNR and passenger name",
  other_vendor: "paired with another vendor's MO statement",
  none: "not paired",
};

// Commission income's per-row statuses, plus the two this screen adds for a row it has no
// figure for.
const COMMISSION_ROW_LABEL: Record<string, string> = {
  calculated: "Calculated", reversed: "Reversed", skipped: "Not a sale", unmatched: "No deal",
  needs_data: "Needs data", excluded: "Excluded", pending: "Pending",
  not_run: "Not run", missing: "No figure",
};

// The bulk bar's actions. Remarks are required where the ledger requires them.
const BULK_ACTIONS: { action: string; label: string; title: string; requireRemarks: boolean }[] = [
  { action: "pay_suggested", label: "Approve", title: "Approve the selected tickets at their payable after commission", requireRemarks: false },
  { action: "hold", label: "Hold", title: "Hold the selected tickets until Operations resolves them", requireRemarks: true },
  { action: "exclude", label: "Exclude", title: "Exclude the selected tickets from payment", requireRemarks: true },
  { action: "auto", label: "Revert to automatic", title: "Let the automatic rule decide again", requireRemarks: false },
];

const byNewest = (a: StatementBatch, b: StatementBatch) =>
  (b.uploaded_at || "").localeCompare(a.uploaded_at || "");

function batchLabel(b: StatementBatch): string {
  const when = b.uploaded_at ? new Date(b.uploaded_at).toLocaleDateString() : "";
  return [b.source_file || b.batch_id, b.supplier_name || "No agency",
          `${b.row_count} entries`, when].filter(Boolean).join(" · ");
}

/** The MO upload most likely to be this vendor statement's other half: the newest one for
 *  the same agency, else the newest of all. */
function suggestMo(vendor: StatementBatch | undefined, mos: StatementBatch[]): string {
  if (!mos.length) return "";
  const same = vendor?.supplier_id != null
    ? mos.filter((m) => m.supplier_id === vendor.supplier_id) : [];
  return (same[0] ?? mos[0]).batch_id;
}

/** Red when the vendor billed more than our books, amber when less. */
function varianceTone(v: number | null | undefined): string {
  if (v == null) return "text-gray-300";
  if (Math.abs(v) < 0.005) return "text-gray-500";
  return v > 0 ? "text-red-600" : "text-amber-600";
}

/** Red when the vendor under-paid commission (they owe us), blue when over-paid. */
function shortfallTone(v: number | null | undefined): string {
  if (v == null) return "text-gray-300";
  if (Math.abs(v) < 0.005) return "text-gray-500";
  return v > 0 ? "text-red-600" : "text-blue-600";
}

export default function PaymentReconciliationView({
  onOpenTab,
}: {
  /** Switch the Payment Module to another tab — the empty states point at the upload tabs. */
  onOpenTab?: (slug: PaymentTabSlug) => void;
}) {
  const [vendorBatches, setVendorBatches] = useState<StatementBatch[]>([]);
  const [moBatches, setMoBatches] = useState<StatementBatch[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(true);
  // What the user PICKED. "" = nothing picked, which means "the suggestion" — see below.
  const [vendorChoice, setVendorChoice] = useState("");
  const [moChoice, setMoChoice] = useState("");

  const [status, setStatus] = useState("");
  const [airline, setAirline] = useState("");
  const [decision, setDecision] = useState("");
  const [flag, setFlag] = useState("");
  const [search, setSearch] = useState("");
  // Debounced copy, so a ticket number is one request, not thirteen.
  const [searchQ, setSearchQ] = useState("");
  const [offset, setOffset] = useState(0);

  const [page, setPage] = useState<PaymentPage | null>(null);
  const [airlines, setAirlines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [calculating, setCalculating] = useState(false);

  const [checks, setChecks] = useState<{ vendor?: CheckResult; mo?: CheckResult }>({});
  const [checksOpen, setChecksOpen] = useState<"vendor" | "mo" | null>(null);

  // Payment item ids ticked for a bulk decision — this page's only.
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [bulkAction, setBulkAction] = useState<(typeof BULK_ACTIONS)[number] | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);

  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<PaymentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // The selection actually in force. A pick that no longer exists (deleted upload) falls
  // back to the suggestion rather than querying a pair that cannot be reconciled.
  const vendorBatch = useMemo(() => (
    vendorBatches.some((b) => b.batch_id === vendorChoice)
      ? vendorChoice : vendorBatches[0]?.batch_id ?? ""
  ), [vendorBatches, vendorChoice]);
  const vendor = vendorBatches.find((b) => b.batch_id === vendorBatch);
  const moBatch = useMemo(() => (
    moBatches.some((b) => b.batch_id === moChoice) ? moChoice : suggestMo(vendor, moBatches)
  ), [moBatches, moChoice, vendor]);
  const mo = moBatches.find((b) => b.batch_id === moBatch);
  const ready = !!(vendorBatch && moBatch);

  const loadBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const [v, m] = await Promise.all([
        api.get<StatementBatch[]>(`${VENDOR_STATEMENT.apiBase}/batches`),
        api.get<StatementBatch[]>(`${MO_STATEMENT.apiBase}/batches`),
      ]);
      setVendorBatches([...(v.data ?? [])].sort(byNewest));
      setMoBatches([...(m.data ?? [])].sort(byNewest));
    } catch {
      toast.error("Failed to load the vendor and MO uploads.");
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  useEffect(() => { loadBatches(); }, [loadBatches]);

  useEffect(() => {
    const t = setTimeout(() => { setSearchQ(search.trim()); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchPage = useCallback(async () => {
    if (!ready) { setPage(null); return; }
    setLoading(true); setError(null);
    try {
      const { data } = await api.get<PaymentPage>(`${PAYMENT_RECON_API}/`, {
        params: {
          vendor_batch_id: vendorBatch, mo_batch_id: moBatch,
          status: status || undefined, airline: airline || undefined,
          decision: decision || undefined, flag: flag || undefined,
          search: searchQ || undefined, offset, limit: PAGE_SIZE,
        },
      });
      setPage(data);
    } catch (err) {
      setError(errorDetail(err, "Failed to load the reconciliation."));
      setPage(null);
    } finally {
      setLoading(false);
    }
  }, [ready, vendorBatch, moBatch, status, airline, decision, flag, searchQ, offset]);

  useEffect(() => { fetchPage(); }, [fetchPage]);
  // A new page is a new set of rows — a tick on a row no longer shown would act unseen.
  useEffect(() => { setPicked(new Set()); }, [page]);

  useEffect(() => {
    if (!ready) return;
    api.get<PaymentFacets>(`${PAYMENT_RECON_API}/facets`, {
      params: { vendor_batch_id: vendorBatch, mo_batch_id: moBatch },
    }).then((r) => setAirlines(r.data.airlines ?? [])).catch(() => setAirlines([]));
  }, [ready, vendorBatch, moBatch, page?.run?.run_id]);

  // Steps 2, 3 and 5 for the two uploads on screen — the same checks the upload tabs show.
  const fetchChecks = useCallback(async () => {
    if (!vendorBatch || !moBatch) { setChecks({}); return; }
    const one = (slug: string, batchId: string) =>
      api.get<Record<string, CheckResult>>(PAYMENT_CHECKS_API, { params: { slug, batch_id: batchId } })
        .then((r) => r.data[batchId]).catch(() => undefined);
    const [v, m] = await Promise.all([one(VENDOR_CHECKS.slug, vendorBatch), one(MO_CHECKS.slug, moBatch)]);
    setChecks({ vendor: v, mo: m });
  }, [vendorBatch, moBatch]);

  useEffect(() => { fetchChecks(); }, [fetchChecks]);

  const pickVendor = (id: string) => { setVendorChoice(id); setOffset(0); };
  const pickMo = (id: string) => { setMoChoice(id); setOffset(0); };

  const refreshAfterRun = async () => {
    if (offset !== 0) setOffset(0); else await fetchPage();
  };

  const runReconciliation = async () => {
    if (!ready) return;
    setRunning(true);
    try {
      const { data } = await api.post<PaymentRunResult>(`${PAYMENT_RECON_API}/run`, {
        vendor_batch_id: vendorBatch, mo_batch_id: moBatch,
      });
      const diffs = data.mismatch + data.minor_diff;
      toast.success(
        `Reconciled ${data.total} tickets — ${data.matched} matched, ${diffs} with differences, ` +
        `${data.vendor_only} billed but not in MO. Payable after commission ${inr(data.payable_total)}.`);
      await refreshAfterRun();
    } catch (err) {
      toast.error(errorDetail(err, "Failed to run the reconciliation."));
    } finally {
      setRunning(false);
    }
  };

  // Step 8: price every vendor ticket against the deals, with the MO's details filling the
  // vendor's blanks. Small statements come back priced and re-reconciled in one go.
  const calculateIncome = async () => {
    if (!ready) return;
    setCalculating(true);
    try {
      const { data } = await api.post<CalculateIncomeResult>(`${PAYMENT_RECON_API}/calculate-income`, {
        vendor_batch_id: vendorBatch, mo_batch_id: moBatch,
      });
      if (data.mode === "queued") {
        toast.success("Income is being calculated in the background. Re-run the reconciliation when the banner says it has finished.");
      } else {
        const priced = (data.calculated ?? 0) + (data.reversed ?? 0);
        toast.success(
          `Income calculated — ${priced} row${priced === 1 ? "" : "s"} priced, ` +
          `${data.needs_data ?? 0} need data, ${data.unmatched ?? 0} with no deal. Reconciliation refreshed.`);
      }
      await refreshAfterRun();
    } catch (err) {
      toast.error(errorDetail(err, "Failed to calculate income."));
    } finally {
      setCalculating(false);
    }
  };

  const openDetail = useCallback(async (id: number, quiet = false) => {
    setSelected(id);
    if (!quiet) { setDetail(null); setDetailLoading(true); }
    try {
      const { data } = await api.get<PaymentDetail>(`${PAYMENT_RECON_API}/rows/${id}`);
      setDetail(data);
    } catch {
      toast.error("Failed to load the ticket.");
      setSelected(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = () => { setSelected(null); setDetail(null); };

  const applyBulk = async (action: string, remarks: string, opsReference: string) => {
    setBulkBusy(true);
    try {
      const { data } = await api.post<{ updated: number; refused: { id: number; ticket: string | null; reason: string }[] }>(
        `${PAYMENT_MODULE_API}/items/bulk-decision`,
        { item_ids: [...picked], action, remarks: remarks || null, ops_reference: opsReference || null });
      if (data.refused.length) {
        toast.error(`${data.updated} updated; ${data.refused.length} refused — ${data.refused[0].reason}`);
      } else {
        toast.success(`${data.updated} ticket${data.updated === 1 ? "" : "s"} updated.`);
      }
      setBulkAction(null);
      await fetchPage();
    } catch (err) {
      toast.error(errorDetail(err, "Failed to record the decision."));
    } finally {
      setBulkBusy(false);
    }
  };

  const s = page?.summary;
  const run = page?.run ?? null;
  const commission = page?.commission;
  const flags = page?.flags ?? {};
  const decisions = page?.decisions ?? {};
  const rows = page?.rows ?? [];
  const total = page?.total ?? 0;
  const hasFilter = !!(status || airline || decision || flag || search);
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + rows.length, total);
  const pickable = rows.filter((r) => r.item_id != null && !r.paid);
  const allPicked = pickable.length > 0 && pickable.every((r) => picked.has(r.item_id!));

  const togglePick = (id: number) => setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAll = () => setPicked(allPicked ? new Set() : new Set(pickable.map((r) => r.item_id!)));
  const setFilter = (setter: (v: string) => void, v: string) => { setter(v); setOffset(0); };

  const countCards = [
    { label: "Tickets", value: s?.total ?? 0, cls: "text-slate-600 bg-slate-50", icon: TicketIcon },
    { label: "Matched", value: s?.matched ?? 0, cls: "text-emerald-600 bg-emerald-50", icon: CheckCircle2 },
    { label: "Differences", value: (s?.mismatch ?? 0) + (s?.minor_diff ?? 0), cls: "text-amber-600 bg-amber-50", icon: AlertTriangle },
    { label: "Billed, not in MO", value: s?.vendor_only ?? 0, cls: "text-red-600 bg-red-50", icon: FileX },
    { label: "In MO, not billed", value: s?.mo_only ?? 0, cls: "text-purple-600 bg-purple-50", icon: FileX },
  ];

  const flagChips = [
    { key: "duplicate", label: "Duplicates", n: flags.duplicates ?? 0, cls: "text-red-700 bg-red-50 border-red-200" },
    { key: "not_billed", label: "Not billed in MO", n: flags.not_billed ?? 0, cls: "text-amber-700 bg-amber-50 border-amber-200" },
    { key: "other_vendor", label: "In another vendor's MO", n: flags.other_vendor ?? 0, cls: "text-purple-700 bg-purple-50 border-purple-200" },
    { key: "enriched", label: "Filled from MO", n: flags.enriched ?? 0, cls: "text-sky-700 bg-sky-50 border-sky-200" },
  ];

  // ── nothing to reconcile yet ──────────────────────────────────────────────
  if (!batchesLoading && (!vendorBatches.length || !moBatches.length)) {
    const missing: { tab: PaymentTabSlug; label: string }[] = [];
    if (!vendorBatches.length) missing.push({ tab: "vendor", label: "a vendor statement" });
    if (!moBatches.length) missing.push({ tab: "mo", label: "an MO statement" });
    return (
      <div className="bg-white rounded-xl border border-gray-200 px-6 py-12 text-center space-y-3">
        <GitMerge className="w-8 h-8 text-gray-300 mx-auto" />
        <p className="text-sm text-gray-600">
          To reconcile, upload {missing.map((m) => m.label).join(" and ")} first.
        </p>
        <div className="flex items-center justify-center gap-2">
          {missing.map((m) => (
            <button key={m.tab} type="button" onClick={() => onOpenTab?.(m.tab)}
              className="px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700">
              Go to {m.tab === "vendor" ? "Vendor Statement" : "MO Statement"}
            </button>
          ))}
        </div>
        <button type="button" onClick={loadBatches}
          className="text-xs text-gray-400 hover:text-gray-600 hover:underline">Refresh</button>
      </div>
    );
  }

  const checksTarget = checksOpen ? checks[checksOpen] : undefined;

  return (
    <div className="space-y-5 pb-16">
      {/* pair */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wide text-gray-400">Vendor statement</span>
              <select value={vendorBatch} onChange={(e) => pickVendor(e.target.value)}
                disabled={batchesLoading} className={`${SELECT_CLS} w-full mt-1`}>
                {vendorBatches.map((b) => <option key={b.batch_id} value={b.batch_id}>{batchLabel(b)}</option>)}
              </select>
            </label>
            <span className="flex items-center gap-1.5 mt-1.5 text-[11px] text-gray-400">
              Checks <ChecksBadge result={checks.vendor} onOpen={() => setChecksOpen("vendor")} />
            </span>
          </div>
          <div>
            <label className="block">
              <span className="text-[10px] uppercase tracking-wide text-gray-400">MO statement</span>
              <select value={moBatch} onChange={(e) => pickMo(e.target.value)}
                disabled={batchesLoading} className={`${SELECT_CLS} w-full mt-1`}>
                {moBatches.map((b) => <option key={b.batch_id} value={b.batch_id}>{batchLabel(b)}</option>)}
              </select>
            </label>
            <span className="flex items-center gap-1.5 mt-1.5 text-[11px] text-gray-400">
              Checks <ChecksBadge result={checks.mo} onOpen={() => setChecksOpen("mo")} />
            </span>
          </div>
        </div>
        {vendor?.supplier_id != null && mo?.supplier_id != null && vendor.supplier_id !== mo.supplier_id && (
          <p className="flex items-center gap-1.5 text-[11px] text-amber-600">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            These two uploads are for different agencies ({vendor.supplier_name} and {mo.supplier_name}).
          </p>
        )}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <p className="text-xs text-gray-500">
            {run?.completed_at
              ? <>Last reconciled {new Date(run.completed_at).toLocaleString()}.</>
              : <>This pair has not been reconciled yet.</>}
          </p>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => { loadBatches(); fetchPage(); fetchChecks(); }} disabled={loading}
              className="flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-50">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
            </button>
            <button type="button" onClick={calculateIncome} disabled={calculating || running || !ready}
              title="Price every vendor ticket against your deals, using the MO statement's class, sector and travel date where the vendor prints none"
              className="flex items-center gap-1.5 px-3 py-2 border border-[#1e3a5f]/30 rounded-lg text-xs font-semibold text-[#1e3a5f] hover:bg-[#1e3a5f]/5 disabled:opacity-50">
              {calculating ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Calculator className="w-3.5 h-3.5" />}
              {calculating ? "Calculating…" : "Calculate income"}
            </button>
            <button type="button" onClick={runReconciliation} disabled={running || calculating || !ready}
              className="flex items-center gap-1.5 px-4 py-2 text-white rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-60"
              style={{ backgroundColor: BRAND }}>
              {running ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              {running ? "Reconciling…" : run ? "Re-run reconciliation" : "Run reconciliation"}
            </button>
          </div>
        </div>
      </div>

      <CommissionBanner commission={commission} run={run} onCalculate={calculateIncome} calculating={calculating} />

      {/* counts */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        {countCards.map(({ label, value, cls, icon: Icon }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-200 p-4">
            <div className={`p-2 rounded-lg ${cls} w-fit mb-2`}><Icon className="w-4 h-4" /></div>
            <p className="text-xl font-bold text-gray-900">{value.toLocaleString()}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label}</p>
          </div>
        ))}
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="p-2 rounded-lg text-[#1e3a5f] bg-[#1e3a5f]/10 w-fit mb-2"><Scale className="w-4 h-4" /></div>
          <p className={`text-xl font-bold ${varianceTone(s?.net_variance_total)}`}>{inr(s?.net_variance_total ?? null)}</p>
          <p className="text-xs text-gray-500 mt-0.5">Net variance</p>
          <p className="text-[10px] text-gray-400 mt-0.5">vendor − MO, paired tickets</p>
        </div>
      </div>

      {/* money */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
        <MoneyTile icon={Receipt} label="Vendor net (bill)" value={s?.vendor_net_total}
          sub={`MO net ${inr(s?.mo_net_total ?? null)}`} />
        <MoneyTile icon={Wallet} label="Calculated commission" value={s?.calc_commission_total}
          sub="Commission income → Third Party → GDS" />
        <MoneyTile icon={Wallet} label="Vendor commission" value={s?.vendor_commission_total}
          sub="Agent commission + incentive printed" />
        <MoneyTile icon={AlertTriangle} label="Commission shortfall" value={s?.shortfall_total}
          tone={shortfallTone(s?.shortfall_total)} sub="calculated − vendor, priced rows" />
        <MoneyTile icon={CheckCircle2} label="Payable after commission" value={s?.payable_total}
          hero sub="vendor net − shortfall" />
        <MoneyTile icon={Landmark} label="Closing balance" value={run?.vendor_closing_balance}
          sub={!run
            ? "Read from the vendor statement on the first run"
            : run.vendor_closing_balance == null
              ? "No BALANCE line on the vendor statement"
              : `Opening ${inr(run.vendor_opening_balance)}${run.vendor_opening_derived ? " (closing − period net)" : ""}`} />
      </div>

      {/* decisions (step 10) and process checks (step 6) — each one filters the grid */}
      {run && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wide text-gray-400 w-24 shrink-0">Decisions</span>
            {(["approved", "pending", "held", "excluded"] as const).map((k) => (
              <button key={k} type="button" onClick={() => setFilter(setDecision, decision === k ? "" : k)}
                className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium ${DECISION_STYLE[k].cls} ${decision === k ? "ring-2 ring-offset-1 ring-blue-300" : ""}`}>
                {DECISION_STYLE[k].label} {(decisions[k] ?? 0).toLocaleString()}
                {k === "approved" && (decisions.approved_amount ?? 0) > 0 && (
                  <span className="font-normal"> · {inr(decisions.approved_amount)}</span>
                )}
              </button>
            ))}
            <button type="button" onClick={() => setFilter(setDecision, decision === "paid" ? "" : "paid")}
              className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium bg-blue-50 text-blue-700 border-blue-200 ${decision === "paid" ? "ring-2 ring-offset-1 ring-blue-300" : ""}`}>
              Paid {(decisions.paid ?? 0).toLocaleString()}
            </button>
            {onOpenTab && (
              <button type="button" onClick={() => onOpenTab("payments")}
                className="ml-auto text-[11px] font-semibold text-blue-600 hover:underline">
                Go to Payments →
              </button>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] uppercase tracking-wide text-gray-400 w-24 shrink-0">Process checks</span>
            {flagChips.map((c) => (
              <button key={c.key} type="button" onClick={() => setFilter(setFlag, flag === c.key ? "" : c.key)}
                disabled={c.n === 0 && flag !== c.key}
                className={`px-2.5 py-1 rounded-lg border text-[11px] font-medium disabled:opacity-40 disabled:cursor-default ${c.cls} ${flag === c.key ? "ring-2 ring-offset-1 ring-blue-300" : ""}`}>
                {c.label} {c.n.toLocaleString()}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input type="text" placeholder="Ticket #, PNR, passenger or booking ID…" value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 pr-3 py-2 text-xs border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-64" />
        </div>
        <select value={status} onChange={(e) => setFilter(setStatus, e.target.value)} className={SELECT_CLS}>
          {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={decision} onChange={(e) => setFilter(setDecision, e.target.value)} className={SELECT_CLS}>
          {DECISION_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={flag} onChange={(e) => setFilter(setFlag, e.target.value)} className={SELECT_CLS}>
          {FLAG_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={airline} onChange={(e) => setFilter(setAirline, e.target.value)} className={SELECT_CLS}>
          <option value="">All airlines</option>
          {airlines.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        {hasFilter && (
          <button type="button"
            onClick={() => { setStatus(""); setAirline(""); setDecision(""); setFlag(""); setSearch(""); setOffset(0); }}
            className="p-2 hover:bg-gray-100 rounded-lg text-gray-400" title="Clear filters">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* bulk decision bar */}
      {picked.size > 0 && (
        <div className="flex items-center gap-2 flex-wrap px-4 py-2.5 rounded-xl border border-blue-200 bg-blue-50 text-xs text-blue-800">
          <span className="font-semibold">{picked.size} ticket{picked.size === 1 ? "" : "s"} selected</span>
          <span className="text-blue-300">|</span>
          {BULK_ACTIONS.map((b) => (
            <button key={b.action} type="button" title={b.title} onClick={() => setBulkAction(b)}
              className="px-2.5 py-1 rounded-lg border border-blue-200 bg-white font-medium hover:bg-blue-100">
              {b.label}
            </button>
          ))}
          <button type="button" onClick={() => setPicked(new Set())} className="ml-auto text-blue-600 hover:underline">
            Clear selection
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" /> {error}
        </div>
      )}

      {/* grid */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ background: BRAND }}>
                <th className="pl-3 pr-1 py-2.5 w-8">
                  <input type="checkbox" checked={allPicked} onChange={toggleAll} disabled={pickable.length === 0}
                    aria-label="Select every unpaid ticket on this page" className="accent-white cursor-pointer disabled:cursor-default" />
                </th>
                {GRID_COLUMNS.map((c, i) => (
                  <th key={c.label || i}
                      className={`px-3 py-2.5 text-[11px] font-semibold text-white/80 uppercase tracking-wide whitespace-nowrap ${c.right ? "text-right" : "text-left"}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading || batchesLoading ? (
                <tr><td colSpan={GRID_COLUMNS.length + 1} className="px-4 py-12 text-center text-sm text-gray-400">
                  <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…
                </td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={GRID_COLUMNS.length + 1} className="px-4 py-12 text-center text-sm text-gray-400">
                  {hasFilter ? "No tickets match these filters." : run ? "No tickets in this reconciliation." : (
                    <span>
                      Not reconciled yet. Press{" "}
                      <button type="button" onClick={runReconciliation} className="text-blue-600 hover:underline">
                        Run reconciliation
                      </button>{" "}
                      to compare these two statements ticket by ticket.
                    </span>
                  )}
                </td></tr>
              ) : rows.map((r) => {
                const st = STATUS_STYLE[r.match_status] ?? { cls: "bg-gray-100 text-gray-500 border-gray-200", label: r.match_status };
                const cs = COMMISSION_STYLE[r.commission_status] ?? COMMISSION_STYLE.none;
                const bits: string[] = [];
                if (r.vendor_rows > 1) bits.push(`${r.vendor_rows} vendor rows`);
                if (r.mo_rows > 1) bits.push(`${r.mo_rows} MO rows`);
                const canPick = r.item_id != null && !r.paid;
                return (
                  <tr key={r.id} onClick={() => openDetail(r.id)}
                      className={`border-b border-gray-100 hover:bg-gray-50/70 cursor-pointer ${canPick && picked.has(r.item_id!) ? "bg-blue-50/40" : ""}`}>
                    <td className="pl-3 pr-1 py-2.5" onClick={(e) => e.stopPropagation()}>
                      {canPick && (
                        <input type="checkbox" checked={picked.has(r.item_id!)} onChange={() => togglePick(r.item_id!)}
                          aria-label={`Select ticket ${r.ticket_number ?? r.id}`} className="cursor-pointer" />
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs font-medium text-gray-800 whitespace-nowrap">
                      {ticketLabel(r.ticket_number, r.ticket_prefix) || r.pnr || "—"}
                      {bits.length > 0 && <span className="block text-[10px] text-gray-400 font-normal">{bits.join(" · ")}</span>}
                      <FlagChips row={r} />
                    </td>
                    <td className="px-3 py-2.5 text-xs text-gray-600 max-w-[180px] truncate" title={r.pax_name ?? ""}>{r.pax_name || "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-gray-600 whitespace-nowrap">{r.airline_name || r.airline_code || "—"}</td>
                    <td className="px-3 py-2.5 text-xs text-gray-500 whitespace-nowrap">{r.issue_date || "—"}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>
                      {r.issue_count > 0 && r.match_status !== "vendor_only" && r.match_status !== "mo_only" && (
                        <span className="ml-1.5 text-[10px] text-gray-400">{r.issue_count} issue{r.issue_count === 1 ? "" : "s"}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-right text-gray-700 whitespace-nowrap">{inr(r.vendor_net)}</td>
                    <td className="px-3 py-2.5 text-xs text-right text-gray-700 whitespace-nowrap">{inr(r.mo_net)}</td>
                    <td className={`px-3 py-2.5 text-xs text-right font-medium whitespace-nowrap ${varianceTone(r.net_variance)}`}>
                      {inr(r.net_variance)}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-right text-gray-600 whitespace-nowrap">{inr(r.vendor_commission)}</td>
                    <td className="px-3 py-2.5 text-xs text-right whitespace-nowrap" title={cs.title}>
                      <span className="text-gray-700">{inr(r.calc_commission)}</span>
                      <span className={`block text-[10px] ${cs.cls}`}>{cs.label}</span>
                    </td>
                    <td className={`px-3 py-2.5 text-xs text-right font-medium whitespace-nowrap ${shortfallTone(r.commission_shortfall)}`}>
                      {inr(r.commission_shortfall)}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-right font-semibold text-gray-900 whitespace-nowrap">{inr(r.payable_after_commission)}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <DecisionChip status={r.decision_status} paid={r.paid} source={r.decision_source}
                        title={r.decision_reason ?? (r.decision_action ? ACTION_LABEL[r.decision_action] : undefined)} />
                      {r.decision_status === "approved" && !r.paid && r.approved_amount != null && (
                        <span className="block text-[10px] text-gray-500 mt-0.5">{inr(r.approved_amount)}</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right"><ChevronRight className="w-4 h-4 text-gray-300 inline" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {total > 0 && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-gray-100 text-xs text-gray-500">
            <span>Showing {pageStart}–{pageEnd} of {total.toLocaleString()}</span>
            <div className="flex items-center gap-1">
              <button type="button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
                <ChevronLeft className="w-3.5 h-3.5" /> Prev
              </button>
              <button type="button" disabled={offset + PAGE_SIZE >= total || loading} onClick={() => setOffset(offset + PAGE_SIZE)}
                className="flex items-center gap-1 px-2 py-1 border border-gray-200 rounded-md hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed">
                Next <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </div>

      {selected != null && (
        <DetailModal
          detail={detail} loading={detailLoading} vendorName={vendor?.supplier_name ?? null}
          onClose={closeDetail}
          onDecided={() => { if (selected != null) openDetail(selected, true); fetchPage(); }}
          onCorrected={() => { closeDetail(); runReconciliation(); }}
        />
      )}

      {checksOpen && checksTarget && (
        <ChecksPanel key={checksTarget.batch_id} api={PAYMENT_CHECKS_API} result={checksTarget}
          onClose={() => setChecksOpen(null)} onChanged={fetchChecks} />
      )}

      {bulkAction && (
        <ReasonDialog
          title={`${bulkAction.label} ${picked.size} ticket${picked.size === 1 ? "" : "s"}`}
          description={bulkAction.action === "auto"
            ? "Each ticket goes back to the automatic rule: clean matches approved, duplicates excluded, the rest pending."
            : bulkAction.action === "pay_suggested"
              ? "Each ticket is approved at its own payable after commission. Paid tickets are left as they are."
              : "Record what Operations decided, so the next person can see why."}
          confirmLabel={bulkAction.label} requireRemarks={bulkAction.requireRemarks}
          showOpsReference={bulkAction.action !== "auto"} busy={bulkBusy}
          danger={bulkAction.action === "exclude"}
          onCancel={() => setBulkAction(null)}
          onConfirm={(remarks, opsRef) => applyBulk(bulkAction.action, remarks, opsRef)}
        />
      )}
    </div>
  );
}

const GRID_COLUMNS: { label: string; right?: boolean }[] = [
  { label: "Ticket #" }, { label: "Passenger" }, { label: "Airline" }, { label: "Issue date" },
  { label: "Status" }, { label: "Vendor net", right: true }, { label: "MO net", right: true },
  { label: "Variance", right: true }, { label: "Vendor comm", right: true },
  { label: "Calc comm", right: true }, { label: "Shortfall", right: true },
  { label: "Payable", right: true }, { label: "Decision" }, { label: "" },
];

/** Steps 6A–6E at a glance, under the ticket number. */
function FlagChips({ row: r }: { row: PaymentRow }) {
  const chips: { label: string; cls: string; title: string }[] = [];
  if (r.is_duplicate) {
    chips.push({ label: "Duplicate", cls: "text-red-700 bg-red-50 border-red-200",
      title: "Billed before, or more than once in this statement — ignored for payout unless Operations decides otherwise." });
  }
  if (r.mo_vendor_status === "other_vendor") {
    chips.push({ label: `In ${r.mo_vendor_name ?? "another vendor"}'s MO`, cls: "text-purple-700 bg-purple-50 border-purple-200",
      title: "The mid office booked this ticket under another vendor. Open it to correct the vendor in MO." });
  } else if (r.mo_vendor_status === "corrected") {
    chips.push({ label: "MO vendor corrected", cls: "text-slate-600 bg-slate-50 border-slate-200",
      title: "Filed under this vendor by a correction." });
  }
  if (r.not_billed) {
    chips.push({ label: "Not billed", cls: "text-amber-700 bg-amber-50 border-amber-200",
      title: "The MO statement shows no booking ID for this ticket — it may never have been billed to a customer." });
  }
  if (r.enriched_fields.length) {
    const what = r.enriched_fields.map((f) => ENRICHED_LABEL[f] ?? f).join(", ");
    chips.push({ label: "From MO", cls: "text-sky-700 bg-sky-50 border-sky-200",
      title: `The vendor prints no ${what}; the MO statement's is used for income.` });
  }
  if (!chips.length) return null;
  return (
    <span className="flex flex-wrap gap-1 mt-1">
      {chips.map((c) => (
        <span key={c.label} title={c.title}
          className={`px-1.5 py-px rounded border text-[9px] font-semibold uppercase tracking-wide ${c.cls}`}>
          {c.label}
        </span>
      ))}
    </span>
  );
}

function MoneyTile({
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
      <p className={`text-xl font-bold ${hero ? "text-white" : tone || "text-gray-900"}`} title={inr(value ?? null)}>
        {inr(value ?? null)}
      </p>
      <p className={`text-xs mt-0.5 ${hero ? "text-white/80" : "text-gray-500"}`}>{label}</p>
      {sub && <p className={`text-[10px] mt-0.5 ${hero ? "text-white/60" : "text-gray-400"}`}>{sub}</p>}
    </div>
  );
}

function CommissionBanner({
  commission, run, onCalculate, calculating,
}: {
  commission: PaymentPage["commission"] | undefined;
  run: PaymentPage["run"];
  onCalculate: () => void;
  calculating: boolean;
}) {
  if (!commission) return null;
  const link = (
    <Link href={COMMISSION_TP_GDS_HREF} className="font-semibold underline underline-offset-2">
      Commission income → Third Party → GDS
    </Link>
  );
  const calc = (
    <button type="button" onClick={onCalculate} disabled={calculating}
      className="font-semibold underline underline-offset-2 disabled:opacity-50">
      Calculate income
    </button>
  );
  if (commission.status === "none") {
    return (
      <Banner tone="amber">
        Income has not been calculated on this vendor statement, so calculated commission is blank,
        the payable is the vendor&apos;s net unadjusted, and no ticket is approved automatically.
        Press {calc} — it prices every ticket against your deals, with the MO statement filling the
        class, sector and travel date the vendor leaves blank.
      </Banner>
    );
  }
  if (commission.status === "queued" || commission.status === "processing") {
    return (
      <Banner tone="blue">
        Income is being calculated on this vendor statement. Press Refresh to check, then re-run
        the reconciliation when it finishes to pick up its figures.
      </Banner>
    );
  }
  if (commission.status === "failed") {
    return (
      <Banner tone="red">
        The last income calculation on this vendor statement failed. Press {calc} to try again, or
        see {link}.
      </Banner>
    );
  }
  if (commission.stale) {
    return (
      <Banner tone="amber">
        Income was recalculated after this reconciliation. Press <b>Re-run reconciliation</b> to
        pick up the new figures.
      </Banner>
    );
  }
  if (run && run.commission_unpriced_rows > 0) {
    return (
      <Banner tone="slate">
        {run.commission_unpriced_rows} vendor row{run.commission_unpriced_rows === 1 ? " has" : "s have"} no
        priced commission (no matching deal, missing data, or added after income was calculated).
        Their payable is the vendor&apos;s net, unadjusted — see {link} for why.
      </Banner>
    );
  }
  return null;
}

function Banner({ tone, children }: { tone: "amber" | "blue" | "red" | "slate"; children: React.ReactNode }) {
  const cls = {
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    blue: "bg-blue-50 border-blue-200 text-blue-800",
    red: "bg-red-50 border-red-200 text-red-700",
    slate: "bg-slate-50 border-slate-200 text-slate-600",
  }[tone];
  const Icon = tone === "red" ? AlertCircle : tone === "amber" ? AlertTriangle : Info;
  return (
    <div className={`flex items-start gap-2 px-4 py-3 border rounded-xl text-xs ${cls}`}>
      <Icon className="w-4 h-4 shrink-0 mt-px" />
      <p className="leading-relaxed">{children}</p>
    </div>
  );
}

// ── drill-down ───────────────────────────────────────────────────────────────

function DetailModal({
  detail, loading, vendorName, onClose, onDecided, onCorrected,
}: {
  detail: PaymentDetail | null;
  loading: boolean;
  vendorName: string | null;
  onClose: () => void;
  /** A decision was saved — reload this ticket and the grid. */
  onDecided: () => void;
  /** The ticket was filed under this vendor — the pair must be reconciled again. */
  onCorrected: () => void;
}) {
  const d = detail;
  const st = d ? STATUS_STYLE[d.match_status] : null;
  const enrichment = Object.entries(d?.enrichment ?? {});

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-4xl max-h-[88vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-sm font-bold text-gray-900">
              {d ? ticketLabel(d.ticket_number, d.ticket_prefix) || d.pnr || "Ticket" : "Ticket"}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {d ? [d.pax_name, d.sector, d.airline_name, d.issue_date].filter(Boolean).join(" · ") || "—" : "—"}
              {d && <span className="text-gray-400"> · {MATCH_METHOD_LABEL[d.match_method] ?? d.match_method}</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {d && <DecisionChip status={d.decision_status} paid={d.payment_id != null} source={d.decision_source} />}
            {st && <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${st.cls}`}>{st.label}</span>}
            <button type="button" onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-400">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {loading || !d ? (
          <div className="px-5 py-12 text-center text-sm text-gray-400">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin mx-auto mb-2" />Loading…
          </div>
        ) : (
          <div className="px-5 py-4 space-y-5">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Tile label="Vendor net" value={inr(d.vendor_net)} />
              <Tile label="MO net" value={inr(d.mo_net)} />
              <Tile label="Variance (vendor − MO)" value={inr(d.net_variance)} tone={varianceTone(d.net_variance)} />
              <Tile label="Payable after commission" value={inr(d.payable_after_commission)} />
            </div>

            {d.issues.length > 0 && (
              <div className="space-y-1.5">
                {d.issues.map((i, n) => (
                  <div key={n} className={`px-3 py-2 rounded-lg border text-xs ${
                    i.severity === "critical"
                      ? "bg-red-50 border-red-200 text-red-700"
                      : "bg-amber-50 border-amber-200 text-amber-700"}`}>
                    {i.message}
                  </div>
                ))}
              </div>
            )}

            <DecisionPanel key={`${d.item_id}-${d.decision_action}-${d.decided_at}-${d.payment_id}`}
              detail={d} onSaved={onDecided} />

            <MoVendorSection key={`mo-${d.id}`} detail={d} vendorName={vendorName} onCorrected={onCorrected} />

            {(d.booking_id || d.not_billed || enrichment.length > 0) && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="rounded-xl border border-gray-100 px-3 py-2.5">
                  <p className="text-[10px] uppercase tracking-wide text-gray-400">Booking ID (MO)</p>
                  <p className={`text-xs font-semibold mt-0.5 ${d.booking_id ? "text-gray-800" : "text-amber-600"}`}>
                    {d.booking_id || (d.not_billed ? "None — may not have been billed" : "—")}
                  </p>
                </div>
                {enrichment.length > 0 && (
                  <div className="rounded-xl border border-sky-100 bg-sky-50/40 px-3 py-2.5">
                    <p className="text-[10px] uppercase tracking-wide text-sky-600">Filled from the MO statement</p>
                    <p className="text-xs text-gray-700 mt-0.5">
                      {enrichment.map(([k, v]) => `${ENRICHED_LABEL[k] ?? k}: ${v.value}`).join(" · ")}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">Used by Calculate income for deal inclusions and exclusions.</p>
                  </div>
                )}
              </div>
            )}

            <div>
              <h3 className="text-xs font-semibold text-gray-700 mb-2">Field comparison</h3>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-100">
                    {["Field", "Vendor", "MO", "Variance"].map((h, i) => (
                      <th key={h} className={`py-1.5 text-[10px] font-semibold text-gray-400 uppercase ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.fields.map((f) => {
                    // Neither statement prints this figure — "0.00" would claim nothing was charged.
                    if (f.vendor == null && f.mo == null) return null;
                    return (
                      <tr key={f.key} className="border-b border-gray-50 last:border-0">
                        <td className="py-1.5 text-xs text-gray-600">{f.label}</td>
                        <td className="py-1.5 text-xs text-right text-gray-800">{inr(f.vendor)}</td>
                        <td className="py-1.5 text-xs text-right text-gray-800">{inr(f.mo)}</td>
                        <td className={`py-1.5 text-xs text-right font-medium ${
                          f.variance == null ? "text-gray-300" : f.match ? "text-gray-500" : "text-red-600"}`}>
                          {inr(f.variance)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <CommissionBlock detail={d} />

            <RecordsBlock title="Vendor statement rows" records={d.vendor_records} />
            <RecordsBlock title="MO statement rows" records={d.mo_records} />
            {d.records_missing && (
              <p className="text-[11px] text-amber-600">
                Some rows behind this ticket have been re-processed or deleted since it was reconciled.
                Re-run the reconciliation to refresh it.
              </p>
            )}

            {d.notes.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-gray-700 mb-2">How these figures were built</h3>
                <ul className="space-y-1">
                  {d.notes.map((n, i) => (
                    <li key={i} className="text-xs text-gray-500 flex gap-2">
                      <span className="text-gray-300">•</span><span>{n}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {d.reconciled_at && (
              <p className="text-[11px] text-gray-400">Reconciled {new Date(d.reconciled_at).toLocaleString()}.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Step 10: what is decided about paying this ticket, and the form to change it. */
function DecisionPanel({ detail: d, onSaved }: { detail: PaymentDetail; onSaved: () => void }) {
  const [action, setAction] = useState<string>(d.decision_source === "user" && d.decision_action ? d.decision_action : "");
  const [amount, setAmount] = useState(
    d.decision_action === "pay_custom" && d.approved_amount != null ? String(d.approved_amount) : "");
  const [remarks, setRemarks] = useState(d.remarks ?? "");
  const [opsRef, setOpsRef] = useState(d.ops_reference ?? "");
  const [saving, setSaving] = useState(false);

  if (d.item_id == null) {
    return (
      <div className="rounded-xl border border-gray-200 px-3 py-2.5 text-xs text-gray-500">
        {d.match_status === "mo_only"
          ? "Not on the vendor's bill — there is nothing to pay or decide."
          : "No payment decision yet — re-run the reconciliation to add this ticket to the payment ledger."}
      </div>
    );
  }

  const paid = d.payment_id != null;
  const options: { value: string; label: string; amount?: number | null; disabled?: boolean }[] = [
    { value: "pay_suggested", label: "Pay the payable after commission", amount: d.suggested_payable ?? d.vendor_net },
    { value: "pay_vendor", label: "Pay the vendor's net, as billed", amount: d.vendor_net, disabled: d.vendor_net == null },
    { value: "pay_mo", label: "Pay our MO net", amount: d.mo_net, disabled: d.mo_net == null },
    { value: "pay_custom", label: "Pay an agreed amount" },
    { value: "hold", label: "Hold — carry it forward until resolved" },
    { value: "exclude", label: "Exclude — not payable" },
    { value: "auto", label: "Let the automatic rule decide" },
  ];
  const needsRemarks = action === "pay_custom" || action === "hold" || action === "exclude";

  const save = async () => {
    if (!action) return;
    if (needsRemarks && !remarks.trim()) { toast.error("Add a remark saying why."); return; }
    if (action === "pay_custom" && !amount.trim()) { toast.error("Enter the agreed amount."); return; }
    setSaving(true);
    try {
      await api.put(`${PAYMENT_MODULE_API}/items/${d.item_id}/decision`, {
        action,
        amount: action === "pay_custom" ? amount.replace(/[,\s₹]/g, "") : null,
        remarks: remarks.trim() || null,
        ops_reference: opsRef.trim() || null,
      });
      toast.success("Decision recorded.");
      onSaved();
    } catch (err) {
      toast.error(errorDetail(err, "Could not record the decision."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-xl border border-gray-200">
      <div className="px-3 py-2.5 border-b border-gray-100 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-gray-700">Payment decision</p>
          <p className="text-xs text-gray-600 mt-0.5">
            {d.decision_action ? ACTION_LABEL[d.decision_action] ?? d.decision_action : "Awaiting a decision"}
            {d.decision_status === "approved" && d.approved_amount != null && <> — <b>{inr(d.approved_amount)}</b></>}
          </p>
          {d.decision_reason && <p className="text-[11px] text-gray-500 mt-0.5">{d.decision_reason}</p>}
          {(d.remarks || d.ops_reference) && (
            <p className="text-[11px] text-gray-500 mt-0.5">
              {d.remarks && <>“{d.remarks}”</>}
              {d.ops_reference && <span className="text-gray-400"> · Ops ref {d.ops_reference}</span>}
            </p>
          )}
          {d.decided_at && d.decision_source === "user" && (
            <p className="text-[10px] text-gray-400 mt-0.5">
              Recorded by {d.decided_by_name || "a user"} on {new Date(d.decided_at).toLocaleString()}
            </p>
          )}
        </div>
        <DecisionChip status={d.decision_status} paid={paid} source={d.decision_source} />
      </div>

      {paid ? (
        <p className="px-3 py-2.5 text-xs text-blue-700 bg-blue-50/50">
          Paid {inr(d.paid_amount)}{d.paid_at && <> on {new Date(d.paid_at).toLocaleDateString()}</>} (payment #{d.payment_id}).
          Void the payment under Payments to change this decision.
        </p>
      ) : (
        <div className="px-3 py-3 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {options.map((o) => (
              <label key={o.value}
                className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-xs cursor-pointer ${
                  action === o.value ? "border-blue-300 bg-blue-50/60" : "border-gray-100 hover:bg-gray-50"} ${
                  o.disabled ? "opacity-40 cursor-not-allowed" : ""}`}>
                <input type="radio" name={`decision-${d.item_id}`} value={o.value} checked={action === o.value}
                  disabled={o.disabled} onChange={() => setAction(o.value)} />
                <span className="text-gray-700">{o.label}</span>
                {o.amount !== undefined && <span className="ml-auto font-semibold text-gray-800">{inr(o.amount)}</span>}
              </label>
            ))}
          </div>
          {action === "pay_custom" && (
            <label className="block max-w-xs">
              <span className="text-[11px] text-gray-500">Agreed amount (₹)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" className={`${INPUT_CLS} mt-1`} />
            </label>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <label className="block sm:col-span-2">
              <span className="text-[11px] text-gray-500">Remarks{needsRemarks ? " (required)" : ""}</span>
              <input value={remarks} onChange={(e) => setRemarks(e.target.value)} className={`${INPUT_CLS} mt-1`}
                placeholder="What Operations decided, and why" />
            </label>
            <label className="block">
              <span className="text-[11px] text-gray-500">Operations reference</span>
              <input value={opsRef} onChange={(e) => setOpsRef(e.target.value)} className={`${INPUT_CLS} mt-1`}
                placeholder="Email, ticket or call note" />
            </label>
          </div>
          <div className="flex justify-end">
            <button type="button" onClick={save} disabled={!action || saving}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50">
              {saving ? "Saving…" : "Record decision"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Step 6C: a ticket the mid office booked under a different vendor. */
function MoVendorSection({
  detail: d, vendorName, onCorrected,
}: {
  detail: PaymentDetail;
  vendorName: string | null;
  onCorrected: () => void;
}) {
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const info = d.mo_vendor_info ?? {};

  if (d.mo_vendor_status === "corrected") {
    return (
      <p className="text-[11px] text-gray-500">
        MO vendor corrected — the mid office had this ticket under {info.corrected_from || "another vendor"}
        {info.source_file && <> ({info.source_file})</>}; it is filed under this vendor now.
      </p>
    );
  }
  if (d.mo_vendor_status !== "other_vendor") return null;

  const correct = async () => {
    setBusy(true);
    try {
      await api.post(`${PAYMENT_MODULE_API}/mo-vendor-corrections`, {
        reconciliation_id: d.id, remarks: remarks.trim() || null,
      });
      toast.success("Filed under this vendor. Re-running the reconciliation…");
      onCorrected();
    } catch (err) {
      toast.error(errorDetail(err, "Could not correct the vendor."));
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-purple-200 bg-purple-50/50 p-3 space-y-2">
      <p className="text-xs font-semibold text-purple-800">
        In {info.supplier_name || "another vendor"}&apos;s MO statement
      </p>
      <p className="text-xs text-purple-700">
        The mid office booked this ticket under {info.supplier_name || "another vendor"}
        {info.source_file && <> ({info.source_file})</>}, but {vendorName || "this vendor"} billed it. If the bill is
        right, file the MO record under {vendorName || "this vendor"}: the reconciliation pairs it here from now on,
        and Calculate income uses its class, sector and travel date.
      </p>
      <div className="flex items-center gap-2 flex-wrap">
        <input value={remarks} onChange={(e) => setRemarks(e.target.value)} placeholder="Remarks (optional)"
          className={`${INPUT_CLS} max-w-sm bg-white`} />
        <button type="button" onClick={correct} disabled={busy}
          className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-purple-600 hover:bg-purple-700 disabled:opacity-50">
          {busy ? "Correcting…" : "Correct vendor in MO"}
        </button>
      </div>
    </div>
  );
}

function CommissionBlock({ detail }: { detail: PaymentDetail }) {
  const entries: CommissionDetailEntry[] = detail.commission_detail ?? [];
  if (!entries.length) return null;
  const cs = COMMISSION_STYLE[detail.commission_status] ?? COMMISSION_STYLE.none;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-xs font-semibold text-gray-700">Commission</h3>
        <span className={`text-[11px] ${cs.cls}`} title={cs.title}>{cs.label}</span>
      </div>
      <div className="grid grid-cols-3 gap-3 mb-3">
        <Tile label="Calculated (deal)" value={inr(detail.calc_commission)} />
        <Tile label="Vendor paid" value={inr(detail.vendor_commission)} />
        <Tile label="Shortfall" value={inr(detail.commission_shortfall)} tone={shortfallTone(detail.commission_shortfall)} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-100">
              {["Row", "Commission", "Deal", "IATA", "Incentive", "Calculated", "Vendor paid", "TDS", "Shortfall"].map((h, i) => (
                <th key={h} className={`py-1.5 pr-2 text-[10px] font-semibold text-gray-400 uppercase whitespace-nowrap ${i < 3 ? "text-left" : "text-right"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => {
              const paid = e.declared_commission == null && e.declared_incentive == null
                ? null : (e.declared_commission ?? 0) + (e.declared_incentive ?? 0);
              return (
                <tr key={e.source_row_id} className="border-b border-gray-50 last:border-0 align-top">
                  <td className="py-1.5 pr-2 text-xs text-gray-600 whitespace-nowrap">{e.ticket_status || "—"}</td>
                  <td className="py-1.5 pr-2 text-xs text-gray-700">
                    {COMMISSION_ROW_LABEL[e.status] ?? e.status}
                    {(e.note || e.reason) && (
                      <span className="block text-[10px] text-gray-400 max-w-[260px]">{e.note || e.reason}</span>
                    )}
                  </td>
                  <td className="py-1.5 pr-2 text-xs text-gray-600 whitespace-nowrap" title={e.deal_name ?? ""}>{e.deal_no || "—"}</td>
                  <td className="py-1.5 pr-2 text-xs text-right text-gray-700">{inr(e.iata)}</td>
                  <td className="py-1.5 pr-2 text-xs text-right text-gray-700">{inr(e.incentive)}</td>
                  <td className="py-1.5 pr-2 text-xs text-right text-gray-800">{inr(e.calc_commission)}</td>
                  <td className="py-1.5 pr-2 text-xs text-right text-gray-800">{inr(paid)}</td>
                  <td className="py-1.5 pr-2 text-xs text-right text-gray-500">{inr(e.declared_tds)}</td>
                  <td className={`py-1.5 text-xs text-right font-medium ${shortfallTone(e.shortfall)}`}>{inr(e.shortfall)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[10px] text-gray-400 mt-1.5">
        Shortfall is calculated minus what the vendor paid (agent commission + incentive), gross of
        TDS, on rows a deal priced. TDS on any extra commission is not recalculated — the TDS shown is
        what the vendor printed.
      </p>
    </div>
  );
}

const RECORD_COLUMNS: { key: string; label: string; money?: boolean }[] = [
  { key: "ticket_status", label: "Status" },
  { key: "booking_date", label: "Booked" },
  { key: "passenger_name", label: "Passenger" },
  { key: "sector", label: "Sector" },
  { key: "base_fare", label: "Basic", money: true },
  { key: "yq", label: "YQ", money: true },
  { key: "other_taxes", label: "Other taxes", money: true },
  { key: "commission_amount", label: "Comm", money: true },
  { key: "service_fee", label: "SF", money: true },
  { key: "net_amount", label: "Net", money: true },
];

function RecordsBlock({ title, records }: { title: string; records: StatementRecord[] }) {
  if (!records.length) return null;
  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-700 mb-2">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-100">
              {RECORD_COLUMNS.map((c) => (
                <th key={c.key} className={`py-1.5 pr-2 text-[10px] font-semibold text-gray-400 uppercase whitespace-nowrap ${c.money ? "text-right" : "text-left"}`}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.map((rec) => (
              <tr key={rec._id} className="border-b border-gray-50 last:border-0">
                {RECORD_COLUMNS.map((c) => {
                  const v = rec[c.key];
                  return (
                    <td key={c.key} className={`py-1.5 pr-2 text-xs whitespace-nowrap ${c.money ? "text-right text-gray-800" : "text-gray-600"}`}>
                      {v == null || v === "" ? "—" : c.money ? inr(Number(v)) : String(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Tile({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-gray-50 rounded-xl px-3 py-2.5">
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-sm font-bold mt-0.5 ${tone || "text-gray-900"}`}>{value}</p>
    </div>
  );
}
